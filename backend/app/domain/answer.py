"""B10 — hậu kiểm trích dẫn và render câu trả lời bằng CODE (phase3 mục 10.3; B10 §2 [10c]; chốt Q-3g-1, Q-3g-2 3g).

`check_citations` (thuần, thứ tự cố định):
1. `cannot_answer=true` → `"no_grounding"` (E3 — LLM tự nhận không đủ căn cứ; Q-3d-6, Q-3g-1).
2. Không trích dẫn nào, hoặc có trích dẫn ∉ `anchors` → `"invalid_citation"` (E3). `anchors` do B10 dựng = `chunk_id`
   top-5 ∩ anchor của khối bằng chứng thật sự gửi LLM — KHÔNG phải chunk liền kề (D-24: chunk liền kề chỉ là ngữ cảnh).
   Ca rỗng không tới được qua LLM (validator `AnswerOut` → `LLMSchemaError` → E2) — kiểm ở đây cho đủ (Q-3g-2).
3. Còn lại → `"ok"`.

`render_answer` theo mẫu (không LLM): phần trả lời; nếu có `steps` → danh sách đánh số; cuối cùng "Nguồn:" liệt kê
`title › heading_path` của các chunk được trích (không trùng, theo thứ tự trích).
"""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from typing import Literal

from app.domain.ticket_state import ChunkRef

type CitationVerdict = Literal["ok", "no_grounding", "invalid_citation"]

SOURCES_HEADER = "Nguồn:"
PATH_SEP = " › "


def check_citations(citations: Sequence[str], *, cannot_answer: bool, anchors: AbstractSet[str]) -> CitationVerdict:
    if cannot_answer:
        return "no_grounding"
    if not citations or not set(citations) <= anchors:
        return "invalid_citation"
    return "ok"


def render_answer(answer_markdown: str, steps: Sequence[str] | None, cited: Sequence[ChunkRef]) -> str:
    parts: list[str] = []
    if answer_markdown.strip():
        parts.append(answer_markdown.strip())
    numbered = [s.strip() for s in steps or () if s.strip()]
    if numbered:
        parts.append("\n".join(f"{i}. {s}" for i, s in enumerate(numbered, 1)))
    sources = list(dict.fromkeys(f"{c.title}{PATH_SEP}{c.heading_path}" for c in cited))
    if sources:
        parts.append(SOURCES_HEADER + "\n" + "\n".join(f"- {s}" for s in sources))
    return "\n\n".join(parts)
