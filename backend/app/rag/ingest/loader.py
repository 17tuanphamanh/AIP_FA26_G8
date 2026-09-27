"""Duyệt thư mục KB, kiểm front matter + luật bố cục/thân bài, gom MỌI lỗi (thiết kế Phase 3 mục 5.3;
PLAN-3b mục 4.2, luật bổ sung Q-3b-13).

Bố cục `<kb_dir>/<request_type>/<doc_id>.md`. Bỏ qua: file ở gốc (`README.md`, `kb-facts.md`…), thư mục `eval/`,
file không đuôi `.md`, mục ẩn. Không dừng ở lỗi đầu tiên: người soát sửa một lượt.
"""

import re
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from app.core.clock import Clock
from app.core.textnorm import normalize
from app.db.models import KB_REQUEST_TYPES
from app.rag.ingest import frontmatter
from app.rag.ingest.config import KB_TZ
from app.rag.models import DOC_ID_PATTERN, Doc, FrontMatter, IngestIssue

EVAL_DIR = "eval"
PREFIX_OF = {"vpn": "VPN", "account": "ACC", "software": "SW", "access": "ACS", "general": "GEN"}  # Q-3b-13
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_H1 = re.compile(r"^# ")
_H2 = re.compile(r"^## ")
_H3 = re.compile(r"^### ")
_H4_PLUS = re.compile(r"^#{4,}\s")


def fence_mask(lines: list[str]) -> list[bool]:
    """True cho dòng nằm trong code fence (gồm cả hai dòng mở/đóng) — heading trong fence không tính."""
    mask: list[bool] = []
    fence: str | None = None
    for line in lines:
        m = _FENCE_OPEN.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
            mask.append(fence is not None)
        else:
            mask.append(True)
            mark = m.group(1) if m else ""
            if mark and line.strip() == mark and mark[0] == fence[0] and len(mark) >= len(fence):  # dòng đóng
                fence = None
    return mask


def _md_files(kb_dir: Path, issues: list[IngestIssue]) -> Iterator[tuple[Path, str]]:
    root = kb_dir.name
    for entry in sorted(kb_dir.iterdir()):
        if entry.name.startswith(".") or not entry.is_dir() or entry.name == EVAL_DIR:
            continue
        if entry.name not in KB_REQUEST_TYPES:
            allowed = ", ".join(KB_REQUEST_TYPES)
            issues.append(IngestIssue(f"{root}/{entry.name}", None, f"thư mục không phải request_type ({allowed})"))
            continue
        for path in sorted(entry.rglob("*.md")):
            rel = path.relative_to(kb_dir)
            if any(part.startswith(".") for part in rel.parts) or not path.is_file():
                continue
            rel_path = f"{root}/{rel.as_posix()}"
            if path.parent != entry:
                issues.append(IngestIssue(rel_path, None, "tài liệu phải ở kb/<request_type>/<doc_id>.md"))
                continue
            yield path, rel_path


def _body_issues(body: str, start: int, rel_path: str) -> list[IngestIssue]:
    lines = body.split("\n")
    in_fence = fence_mask(lines)
    issues: list[IngestIssue] = []
    seen_h2 = False
    for i, line in enumerate(lines):
        if in_fence[i]:
            continue
        where = start + i
        if _H1.match(line):
            issues.append(IngestIssue(rel_path, where, "không dùng heading # (H1) — tiêu đề lấy từ title"))
        elif _H4_PLUS.match(line):
            issues.append(IngestIssue(rel_path, where, "chỉ dùng ## và ###"))
        elif _H3.match(line) and not seen_h2:
            issues.append(IngestIssue(rel_path, where, "### phải nằm dưới một ##"))
        elif _H2.match(line):
            seen_h2 = True
    if not seen_h2:
        issues.append(IngestIssue(rel_path, start, "thân bài phải có ít nhất một heading ##"))
    return issues


def load_kb(kb_dir: Path, clock: Clock) -> tuple[list[Doc], list[IngestIssue]]:
    """Mọi tài liệu hợp lệ + mọi lỗi. Có lỗi thì pipeline in hết và thoát 1 (bước 1)."""
    issues: list[IngestIssue] = []
    if not kb_dir.is_dir():
        return [], [IngestIssue(kb_dir.name or str(kb_dir), None, "không phải thư mục KB")]
    today = clock.now().astimezone(KB_TZ).date()
    docs: list[Doc] = []
    key_lines: dict[str, dict[str, int]] = {}
    for path, rel_path in _md_files(kb_dir, issues):
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(IngestIssue(rel_path, None, "file không phải UTF-8"))
            continue
        parsed = frontmatter.parse(raw, rel_path)
        issues.extend(parsed.issues)
        body = normalize(parsed.body)
        if parsed.body_start_line > 1:  # tách được front matter → kiểm thân bài kể cả khi front matter sai
            issues.extend(_body_issues(body, parsed.body_start_line, rel_path))
        fm = parsed.fm
        if fm is None:
            continue
        key_lines[rel_path] = parsed.key_lines
        issues.extend(_rule_issues(fm, path, rel_path, parsed.key_lines, today))
        docs.append(Doc(fm, path, rel_path, body, parsed.body_start_line))

    by_id: dict[str, list[Doc]] = defaultdict(list)
    for d in docs:
        by_id[d.fm.doc_id].append(d)
    for doc_id, same in by_id.items():
        if len(same) > 1:
            others = ", ".join(d.rel_path for d in same)
            for d in same:
                at = key_lines[d.rel_path].get("doc_id", 1)
                issues.append(IngestIssue(d.rel_path, at, f"doc_id {doc_id} trùng ({others})", "doc_id"))
    for d in docs:
        sup = d.fm.supersedes
        if sup is not None and sup != d.fm.doc_id and re.match(DOC_ID_PATTERN, sup) and sup not in by_id:
            at = key_lines[d.rel_path].get("supersedes", 1)
            issues.append(IngestIssue(d.rel_path, at, f"{sup} không có trong KB", "supersedes"))
    return docs, sorted(issues, key=_sort_key)


def _rule_issues(fm: FrontMatter, path: Path, rel_path: str, lines: dict[str, int], today: date) -> list[IngestIssue]:
    """Luật loader theo từng file (PLAN-3b 4.2 luật 2, 4, 5, 6 — phần không cần biết các file khác)."""
    out: list[IngestIssue] = []

    def bad(key: str, message: str) -> None:
        out.append(IngestIssue(rel_path, lines.get(key, 1), message, key))

    if path.stem != fm.doc_id:
        bad("doc_id", f"tên file phải bằng doc_id ({fm.doc_id}.md)")
    if path.parent.name != fm.request_type:
        bad("request_type", f"phải bằng thư mục chứa ({path.parent.name})")
    prefix = PREFIX_OF[fm.request_type]
    if fm.doc_id.split("-")[1] != prefix:
        bad("doc_id", f"tiền tố phải là KB-{prefix}- cho request_type {fm.request_type}")
    if fm.updated_at > today:
        bad("updated_at", f"ngày ở tương lai (hôm nay {today.isoformat()}, giờ VN)")
    if fm.supersedes is not None:
        if not re.match(DOC_ID_PATTERN, fm.supersedes):
            bad("supersedes", f"sai định dạng (mẫu {DOC_ID_PATTERN})")
        elif fm.supersedes == fm.doc_id:
            bad("supersedes", "không được trỏ về chính nó")
    return out


def _sort_key(issue: IngestIssue) -> tuple[str, int, str]:
    return issue.rel_path, issue.line or 0, issue.message
