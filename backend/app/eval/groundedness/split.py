"""Tách câu trả lời thành từng ý BẰNG CODE (quyết định G11: tái lập, không tốn LLM; giới hạn ở docstring `__init__`).

Quy tắc, theo thứ tự:
1. Bỏ khối "Nguồn:" cuối (do `render_answer` ghép) — dòng đúng `SOURCES_HEADER` và mọi dòng sau nó.
2. Dòng đánh số (`1.`, `2)`) hoặc gạch đầu dòng (`-`, `*`, `•`) là MỘT ý, bỏ ký hiệu đầu dòng.
3. Dòng văn xuôi tách theo câu: sau `. ! ? …` + khoảng trắng + chữ HOA. Không tách sau từ viết tắt (`vd.`, `ts.`…) hay trong số
   phiên bản/mã (`1.2.3`, `0x8004010F` — không có khoảng trắng sau dấu chấm).
4. Dòng kết thúc bằng ":" là câu dẫn dắt → bỏ.
5. Có `steps`: dòng đánh số/gạch đầu dòng của `answer` trùng một bước (so sau chuẩn hoá khoảng trắng) bị bỏ, rồi các bước nối vào
   cuối — ghép `render_answer` (đã chứa steps) và `answer_markdown` + `steps` đều cho cùng danh sách ý.
"""

import re
from collections.abc import Sequence

from app.domain.answer import SOURCES_HEADER

_LIST_ITEM = re.compile(r"^\s*(?:\d{1,3}[.)]|[-*•])\s+(?P<body>.+?)\s*$")
_BOUNDARY = re.compile(r"[.!?…]+[\"'”’)\]]*\s+")
ABBREVIATIONS = frozenset({"vd", "v.v", "tr", "ts", "ths", "gs", "pgs", "tp", "q", "p", "stt", "mr", "ms", "dr"})
MIN_CLAIM_CHARS = 2


def _norm(text: str) -> str:
    return " ".join(text.split())


def _sentences(line: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(line):
        nxt = line[m.end() : m.end() + 1]
        word = re.split(r"\s", line[start : m.start()].rstrip())[-1].lower().strip("([\"'“‘")
        token = word.rstrip(".")
        if not nxt.isupper() or token in ABBREVIATIONS:
            continue
        parts.append(line[start : m.end()].strip())
        start = m.end()
    parts.append(line[start:].strip())
    return [p for p in parts if p]


def _drop_sources(text: str) -> list[str]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == SOURCES_HEADER:
            return lines[:i]
    return lines


def split_claims(answer: str, steps: Sequence[str] | None = None) -> list[str]:
    step_texts = [_norm(s) for s in steps or () if _norm(s)]
    step_set = set(step_texts)
    claims: list[str] = []
    for line in _drop_sources(answer):
        if not line.strip() or line.rstrip().endswith(":"):
            continue
        item = _LIST_ITEM.match(line)
        if item:
            body = _norm(item.group("body"))
            if body not in step_set:
                claims.append(body)
            continue
        claims.extend(_norm(s) for s in _sentences(line.strip()))
    claims.extend(step_texts)
    return [c for c in claims if len(c) >= MIN_CLAIM_CHARS]
