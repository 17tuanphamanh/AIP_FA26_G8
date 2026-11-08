"""`notify_user` biết ticket con (Phase 5 T20b P5 — phase5 5.2.1; P1 §8.1; D-31): con KHÔNG nhắn người dùng, chỉ để lại notice.

Luôn được gọi qua `effects.once` (test AST `SIDE_EFFECT_FUNCS`). Ticket con (`tickets.parent_ticket_id` có giá trị) → một dòng
`child_notices(parent, child, source_step, kind, needs, body, effect_key)` → trả `notice:<id>`; ticket thường/cha → giao cho `inner` như
cũ (`fakes.LoggingNotifier` ở runtime — tin nằm trong `conversation` của checkpoint). `source_step` + `effect_key` lấy từ
`db.runtime.current_effect()` (do `effects.once` đặt); `kind` theo bước: B10 → `answer`, B11 → `question`, B16 → `rejection`, B18 →
`result`, B20 → `escalation`, B15 → `result` (Q3 M4 — tin chờ duyệt); bước khác (hoặc gọi ngoài `effects.once`) → `ValueError` (E9 — thấy được, không gửi thẳng).
Logic các nhánh B10/B11/B16/B18/B20 KHÔNG đổi; tin của con vẫn vào `conversation` checkpoint con (nội bộ).
"""

from collections.abc import Mapping
from typing import Final, Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.notices import SqlNoticeStore
from app.db.runtime import current_effect

NOTICE_KIND_BY_STEP: Final[Mapping[str, str]] = {
    "B10": "answer", "B11": "question", "B16": "rejection", "B18": "result", "B20": "escalation",
    # Q3 M4 (ĐP 09/11): tin "chờ duyệt" của B15 (needs=none). `child_notices.kind` có CHECK 5 giá trị (P7 2.9) — không có loại riêng nên
    # dùng `result` (tin trạng thái do hệ thống báo). FE gắn nhãn khối "Đã xử lý" cho `result` — chờ ĐP chốt có thêm loại mới không.
    "B15": "result",
}  # fmt: skip


class UserNotifier(Protocol):
    """Cùng chữ ký `graph.fakes.Notifier` (không import tầng graph)."""

    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str: ...


class NoticeStore(Protocol):
    """Bản SQL `db.notices.SqlNoticeStore` (ghi trong transaction của `effects.once` — `current_tx()`); bản giả ở
    `tests/fakes/graph.py`."""

    async def parent_of(self, ticket_id: str) -> str | None:
        """`tickets.parent_ticket_id` của ticket; None = ticket thường/cha."""
        ...

    async def insert(
        self, *, parent_id: str, child_id: str, source_step: str, kind: str, needs: str, body: str, effect_key: str
    ) -> int:
        """INSERT `child_notices` → `notice_id` (`effect_key` UNIQUE — lần thứ hai trả id cũ)."""
        ...


def notice_kind(step: str) -> str:
    """`child_notices.kind` theo bước gọi `notify_user`; bước khác → `ValueError`."""
    kind = NOTICE_KIND_BY_STEP.get(step)
    if kind is None:
        raise ValueError(f"notify_user của ticket con ở bước lạ {step!r} — không có loại notice")
    return kind


class ChildAwareNotifier:
    def __init__(self, store: NoticeStore, inner: UserNotifier) -> None:
        self._store = store
        self._inner = inner

    @classmethod
    def on_engine(cls, engine: AsyncEngine, inner: UserNotifier) -> "ChildAwareNotifier":
        """Runtime (`graph/wiring.py`): store SQL trên engine chính."""
        return cls(SqlNoticeStore(engine), inner)

    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
        parent_id = await self._store.parent_of(ticket_id)
        if parent_id is None:  # ticket thường / cha: như cũ
            return await self._inner.notify_user(ticket_id, text, needs)
        call = current_effect()
        if call is None:  # D-31: con chỉ để lại notice, và chỉ qua effects.once (khoá idempotent của dòng notice)
            raise ValueError(f"notify_user của ticket con {ticket_id} ngoài effects.once")
        notice_id = await self._store.insert(
            parent_id=parent_id, child_id=ticket_id, source_step=call.step, kind=notice_kind(call.step), needs=needs,
            body=text, effect_key=call.key,
        )  # fmt: skip
        return f"notice:{notice_id}"
