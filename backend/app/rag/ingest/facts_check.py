"""Kiểm số liệu tài liệu KB với `kb/kb-facts.md` (thiết kế Phase 3 mục 5.4; PLAN-3b mục 4.3).

`kb-facts.md` có ĐÚNG MỘT khối ```yaml. Mỗi fact: `regex` chạy trên thân bài (đã NFC) của tài liệu có
`request_type ∈ applies_to` (cả enabled lẫn disabled); mọi nhóm bắt được mà không thuộc `allowed` là lỗi, báo đúng
DÒNG FILE. Regex không khớp chỗ nào → tài liệu không nhắc số đó → không lỗi. Fact không có nhóm bắt là lỗi cấu hình
(Q-3b-13) — nó không bao giờ kiểm được gì.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.db.models import KB_REQUEST_TYPES
from app.rag.models import Doc, IngestIssue

FACTS_FILE = "kb-facts.md"
_OPEN = "```yaml"
_CLOSE = "```"


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    applies_to: list[str] = Field(min_length=1)
    regex: str
    allowed: list[str] = Field(min_length=1)
    note: str | None = None

    @field_validator("applies_to")
    @classmethod
    def _types(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in KB_REQUEST_TYPES]
        if bad:
            raise ValueError(f"request_type lạ {bad} (cho phép: {', '.join(KB_REQUEST_TYPES)})")
        return v


class FactsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: list[Fact]


@dataclass(frozen=True)
class CompiledFact:
    fact: Fact
    pattern: re.Pattern[str]


def _item_lines(yaml_text: str, first_line: int) -> list[int]:
    """Dòng file của từng mục trong `facts:` (để lỗi trỏ đúng fact); không dựng được → []."""
    try:
        root = yaml.compose(yaml_text)
    except yaml.YAMLError:
        return []
    if not isinstance(root, yaml.MappingNode):
        return []
    for key, value in root.value:
        if getattr(key, "value", None) == "facts" and isinstance(value, yaml.SequenceNode):
            return [first_line + item.start_mark.line for item in value.value]
    return []


def load_facts(kb_dir: Path) -> tuple[list[CompiledFact], list[IngestIssue]]:
    rel = f"{kb_dir.name}/{FACTS_FILE}"
    path = kb_dir / FACTS_FILE
    if not path.is_file():
        return [], [IngestIssue(rel, None, f"thiếu file {FACTS_FILE}")]
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    opens = [i for i, line in enumerate(lines) if line.strip() == _OPEN]
    if len(opens) != 1:
        where = opens[1] + 1 if len(opens) > 1 else None
        return [], [IngestIssue(rel, where, f"phải có đúng một khối ```yaml (đang có {len(opens)})")]
    start = opens[0] + 1  # chỉ số dòng đầu của YAML (0-based) = dòng file start + 1
    end = next((i for i in range(start, len(lines)) if lines[i].strip() == _CLOSE), None)
    if end is None:
        return [], [IngestIssue(rel, opens[0] + 1, "khối ```yaml không có dòng ``` đóng")]
    yaml_text = "\n".join(lines[start:end])
    first_line = start + 1  # dòng file của dòng YAML đầu tiên
    try:
        raw: Any = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        return [], [IngestIssue(rel, first_line + mark.line if mark else first_line, f"YAML sai: {e}")]
    item_line = _item_lines(yaml_text, first_line)

    def line_of(index: Any) -> int:
        return item_line[index] if isinstance(index, int) and index < len(item_line) else first_line

    try:
        parsed = FactsFile.model_validate(raw)
    except ValidationError as e:
        return [], [
            IngestIssue(rel, line_of(err["loc"][1] if len(err["loc"]) > 1 else None), err["msg"],
                        ".".join(str(p) for p in err["loc"]))
            for err in e.errors()
        ]  # fmt: skip
    issues: list[IngestIssue] = []
    compiled: list[CompiledFact] = []
    seen: set[str] = set()
    for i, fact in enumerate(parsed.facts):
        if fact.id in seen:
            issues.append(IngestIssue(rel, line_of(i), f"id {fact.id} trùng", "id"))
        seen.add(fact.id)
        try:
            pattern = re.compile(fact.regex)
        except re.error as e:
            issues.append(IngestIssue(rel, line_of(i), f"{fact.id}: regex không biên dịch được: {e}", "regex"))
            continue
        if pattern.groups < 1:
            issues.append(IngestIssue(rel, line_of(i), f"{fact.id}: regex phải có ít nhất một nhóm bắt", "regex"))
            continue
        compiled.append(CompiledFact(fact, pattern))
    return (compiled, []) if not issues else ([], issues)


def check_docs(docs: Iterable[Doc], facts: list[CompiledFact]) -> list[IngestIssue]:
    issues: list[IngestIssue] = []
    for doc in docs:
        for cf in facts:
            if doc.fm.request_type not in cf.fact.applies_to:
                continue
            for m in cf.pattern.finditer(doc.body):
                for g in range(1, cf.pattern.groups + 1):
                    value = m.group(g)
                    if value is None or value in cf.fact.allowed:
                        continue
                    line = doc.body_start_line + doc.body.count("\n", 0, m.start(g))
                    allowed = ", ".join(cf.fact.allowed)
                    issues.append(IngestIssue(
                        doc.rel_path, line, f'"{value}" không khớp kb-facts {cf.fact.id} (cho phép: {allowed})'
                    ))  # fmt: skip
    return sorted(issues, key=lambda i: (i.rel_path, i.line or 0, i.message))


def check_facts(kb_dir: Path, docs: Iterable[Doc]) -> list[IngestIssue]:
    """Bước 2: đọc kb-facts rồi kiểm mọi tài liệu; mọi lỗi gom hết."""
    facts, issues = load_facts(kb_dir)
    return issues if issues else check_docs(docs, facts)
