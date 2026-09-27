"""Tách + kiểm front matter một file KB (thiết kế Phase 3 mục 5.3; PLAN-3b mục 4.2).

File bắt đầu bằng dòng `---`, YAML tới dòng `---` kế tiếp, còn lại là thân bài. Lỗi Pydantic được dịch sang tiếng
Việt và gắn số dòng FILE của khoá (thiếu khoá → dòng 1) — người soát sửa một lượt.
"""

import re
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import ValidationError

from app.rag.models import FrontMatter, IngestIssue

_KEY_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")
_FENCE = "---"


@dataclass(frozen=True)
class Parsed:
    fm: FrontMatter | None  # None khi có lỗi
    issues: list[IngestIssue]
    body: str  # thân bài THÔ (chưa normalize)
    body_start_line: int
    key_lines: dict[str, int]  # khoá front matter → số dòng file (lỗi của loader trỏ đúng dòng)


def _length_bounds(field: str) -> tuple[Any, Any]:
    lo = hi = None
    for m in FrontMatter.model_fields[field].metadata:
        lo = getattr(m, "min_length", lo)
        hi = getattr(m, "max_length", hi)
    return lo, hi


def _message(err: Any) -> str:
    kind, ctx = err["type"], err.get("ctx") or {}
    field = str(err["loc"][0]) if err["loc"] else ""
    if kind == "missing":
        return "thiếu trường"
    if kind == "extra_forbidden":
        return "trường không được phép"
    if kind == "greater_than_equal":
        return f"phải ≥ {ctx['ge']}"
    if kind == "string_pattern_mismatch":
        return f"sai định dạng (mẫu {ctx['pattern']})"
    if kind in ("string_too_short", "string_too_long"):
        lo, hi = _length_bounds(field)
        return f"độ dài phải {lo}–{hi} ký tự"
    if kind in ("int_parsing", "int_type", "int_from_float"):
        return "phải là số nguyên"
    if kind in ("bool_parsing", "bool_type"):
        return "phải là true/false"
    if kind in ("date_parsing", "date_type", "date_from_datetime_parsing", "date_from_datetime_inexact"):
        return "phải là ngày YYYY-MM-DD"
    if kind == "value_error":
        return str(ctx.get("error", err["msg"]))
    return str(err["msg"])


def parse(text: str, rel_path: str) -> Parsed:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines[0].strip() != _FENCE:
        return Parsed(None, [IngestIssue(rel_path, 1, "file phải bắt đầu bằng dòng --- (front matter)")], "", 1, {})
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == _FENCE), None)
    if close is None:
        return Parsed(None, [IngestIssue(rel_path, 1, "front matter không có dòng --- đóng")], "", 1, {})
    yaml_lines = lines[1:close]
    body = "\n".join(lines[close + 1 :])
    body_start = close + 2  # dòng file (1-based) ngay sau dòng --- đóng
    key_line: dict[str, int] = {}
    for i, line in enumerate(yaml_lines, start=2):
        m = _KEY_LINE.match(line)
        if m:
            key_line.setdefault(m.group(1), i)

    def failed(issues: list[IngestIssue]) -> Parsed:
        return Parsed(None, issues, body, body_start, key_line)

    try:
        raw = yaml.safe_load("\n".join(yaml_lines))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        problem = getattr(e, "problem", None) or str(e)
        return failed([IngestIssue(rel_path, mark.line + 2 if mark else 1, f"YAML front matter sai: {problem}")])
    if not isinstance(raw, dict):
        return failed([IngestIssue(rel_path, 1, "front matter phải là bảng khoá: giá trị")])
    try:
        fm = FrontMatter.model_validate(raw)
    except ValidationError as e:
        issues = []
        for err in e.errors():
            field = str(err["loc"][0]) if err["loc"] else None
            issues.append(IngestIssue(rel_path, key_line.get(field, 1) if field else 1, _message(err), field))
        return failed(issues)
    return Parsed(fm, [], body, body_start, key_line)
