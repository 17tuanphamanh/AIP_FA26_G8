"""B10 — hậu kiểm trích dẫn và render câu trả lời bằng CODE (phase3 mục 10.3; B10 §2 [10c]; chốt Q-3g-1, Q-3g-2 3g).

`check_citations` (thuần, thứ tự cố định):
1. `cannot_answer=true` → `"no_grounding"` (E3 — LLM tự nhận không đủ căn cứ; Q-3d-6, Q-3g-1).
2. Không trích dẫn nào, hoặc có trích dẫn ∉ `anchors` → `"invalid_citation"` (E3). `anchors` do B10 dựng = `chunk_id`
   top-5 ∩ anchor của khối bằng chứng thật sự gửi LLM — KHÔNG phải chunk liền kề (D-24: chunk liền kề chỉ là ngữ cảnh).
   Ca rỗng không tới được qua LLM (validator `AnswerOut` → `LLMSchemaError` → E2) — kiểm ở đây cho đủ (Q-3g-2).
3. Còn lại → `"ok"`.

`render_answer` theo mẫu (không LLM): câu mở đầu theo fact nếu có (Q2 M1); phần trả lời; nếu có `steps` → danh sách đánh số
rồi câu kết cố định `messages.ANSWER_CLOSING` (Q2 M2); cuối cùng "Nguồn:" liệt kê `title › heading_path` của các chunk được trích
(không trùng, theo thứ tự trích).

`cap_steps` (Q2 M2): bỏ bước rỗng, giữ tối đa `MAX_ANSWER_STEPS` bước đầu (prompt `b10_answer` v3 xếp bước khả năng cao nhất
lên đầu); trả kèm cờ đã cắt (B10 ghi audit `steps_truncated`).
"""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from typing import Literal

from app.domain.messages import ANSWER_CLOSING
from app.domain.ticket_state import ChunkRef

type CitationVerdict = Literal["ok", "no_grounding", "invalid_citation"]

SOURCES_HEADER = "Nguồn:"
PATH_SEP = " › "
MAX_ANSWER_STEPS = 3  # Q2 M2 (ĐP 09/11): câu trả lời B10 tối đa 3 bước


def cap_steps(steps: Sequence[str] | None) -> tuple[list[str], bool]:
    kept = [s for s in steps or () if s.strip()]
    return kept[:MAX_ANSWER_STEPS], len(kept) > MAX_ANSWER_STEPS


def check_citations(citations: Sequence[str], *, cannot_answer: bool, anchors: AbstractSet[str]) -> CitationVerdict:
    if cannot_answer:
        return "no_grounding"
    if not citations or not set(citations) <= anchors:
        return "invalid_citation"
    return "ok"


def render_answer(
    answer_markdown: str, steps: Sequence[str] | None, cited: Sequence[ChunkRef], *, intro: str | None = None
) -> str:
    """`intro` (Q2 M1): câu mở đầu do CODE ghép từ fact (`messages.symptom_intro`) — đứng trước phần trả lời của LLM."""
    parts: list[str] = []
    if intro:
        parts.append(intro)
    if answer_markdown.strip():
        parts.append(answer_markdown.strip())
    numbered = [s.strip() for s in steps or () if s.strip()]
    if numbered:
        parts.append("\n".join(f"{i}. {s}" for i, s in enumerate(numbered, 1)))
        parts.append(ANSWER_CLOSING)
    sources = list(dict.fromkeys(f"{c.title}{PATH_SEP}{c.heading_path}" for c in cited))
    if sources:
        parts.append(SOURCES_HEADER + "\n" + "\n".join(f"- {s}" for s in sources))
    return "\n\n".join(parts)
