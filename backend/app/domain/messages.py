"""Tin nhắn trong `conversation` (phase3 mục 10.2, 3-Q28 bản 1.1; chốt P9 3g) — theo khuôn B20 `{role, kind, text, ref}`.

- `kind` ∈ `answer` (B10), `question` (B11), `result` (B18), `escalation` (B20 — đã có). `needs` như tham số `notify_user`.
- `sources` CHỈ ở `answer`, mỗi nguồn ĐÚNG 3 khoá `chunk_id`, `title`, `heading_path` — không đoạn trích, không bằng chứng
  đã mở rộng (P9).
- Tin người dùng `{role: "user", text}`: `text` là bản ĐÃ CHE (P3) — node chỉ gọi `user_msg` với văn bản đã qua guard.

`conversation` giữ 20 tin cuối (reducer `append_capped(20)` ở `ticket_state.py`); `GET /api/tickets/{id}` đọc từ checkpoint.
"""

from collections.abc import Sequence
from typing import Final

from app.domain.ticket_state import ChunkRef, Msg

MSG_KINDS: Final = ("answer", "question", "result", "escalation")
SOURCE_KEYS: Final = ("chunk_id", "title", "heading_path")


def source_of(chunk: ChunkRef) -> dict[str, str]:
    return {"chunk_id": chunk.chunk_id, "title": chunk.title, "heading_path": chunk.heading_path}


def answer_msg(text: str, ref: str | None, cited: Sequence[ChunkRef]) -> Msg:
    """Câu trả lời B10; `cited` = các chunk top-5 được trích (không trùng, giữ thứ tự)."""
    seen: dict[str, dict[str, str]] = {}
    for c in cited:
        seen.setdefault(c.chunk_id, source_of(c))
    return {"role": "assistant", "kind": "answer", "text": text, "ref": ref, "needs": "confirm",
            "sources": list(seen.values())}  # fmt: skip


def question_msg(text: str, ref: str | None) -> Msg:
    return {"role": "assistant", "kind": "question", "text": text, "ref": ref, "needs": "answer"}


def user_msg(redacted_text: str) -> Msg:
    return {"role": "user", "text": redacted_text}
