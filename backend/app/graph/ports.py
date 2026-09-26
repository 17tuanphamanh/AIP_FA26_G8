"""Cổng lưu trữ của runtime (P1) và phụ thuộc của node thật — bản SQL ở `app/db/runtime.py`,
`app/db/identity.py`, `app/audit/writer.py`, `app/audit/alerts.py`; bản in-memory cùng hợp đồng ở
`backend/tests/fakes/graph.py` để test graph không cần Postgres.
"""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.db.identity import LiveSession
from app.db.runtime import DueWait, OpenTurn, WaitKind
from app.domain.alerts import AlertDraft
from app.domain.final import FinalSummary
from app.tools.registry import ToolResult

# bản ghi dữ liệu dùng chung với store SQL
__all__ = ["DueWait", "LiveSession", "OpenTurn", "ToolResult", "WaitKind"]


class AuditSink(Protocol):
    async def record(self, row: Mapping[str, Any]) -> bool:
        """INSERT `audit_logs`; `idempotency_key` trùng → bỏ qua (ON CONFLICT DO NOTHING).

        Trả True nếu SAU lệnh ghi có dòng mang khoá đó (vừa ghi hoặc đã có) — kiểm trong CÙNG
        transaction với INSERT (cấm 4, P1 mục 5.1.1). Dòng không khoá: luôn ghi, trả True."""
        ...


class EffectStore(Protocol):
    async def run_once(
        self,
        *,
        key: str,
        ticket_id: str,
        kind: str,
        step: str,
        turn_id: str,
        call: Callable[[], Awaitable[Any]],
    ) -> str | None:
        """Khoá chưa có → ghi `side_effects`, gọi `call()` đúng một lần, lưu `result_ref`, cùng
        một transaction. Khoá đã có → trả `result_ref` cũ, KHÔNG gọi `call` (D-18)."""
        ...


@dataclass
class SpanRecord:
    span_id: str
    trace_id: str
    turn_id: str
    span_type: str  # node | llm | tool | rag
    name: str
    started_at: datetime
    parent_span_id: str | None = None
    duration_ms: int | None = None
    status: str = "ok"  # ok | error | interrupted
    attributes: dict[str, Any] = field(default_factory=dict)


class SpanSink(Protocol):
    async def write(self, span: SpanRecord) -> None: ...


class TurnStore(Protocol):
    async def start(
        self, *, turn_id: str, ticket_id: str, session_id: str | None, event_type: str, at: datetime
    ) -> None: ...

    async def end(self, turn_id: str, at: datetime) -> None: ...

    async def is_open(self, turn_id: str) -> bool: ...

    async def bump_recover_attempts(self, turn_id: str) -> int | None:
        """`recover_attempts + 1` của lượt còn mở, trả giá trị mới; lượt đã đóng → None (2b-Q6)."""
        ...

    async def stale(self, before: datetime, limit: int) -> list[OpenTurn]:
        """Lượt chưa kết thúc (`ended_at IS NULL`) bắt đầu trước `before` (P1 mục 7)."""
        ...


class DeadlineStore(Protocol):
    async def set(self, ticket_id: str, kind: str, deadline: datetime, created_turn: str) -> str:
        """Đặt hạn chờ `clarify`/`confirm` (`wait_deadlines`). Hạn cũ chưa bắn của cùng ticket +
        kind bị đánh dấu đã bắn (bị thay) — để hạn vòng hỏi trước không cắt ngang vòng sau."""
        ...

    async def due(self, now: datetime, limit: int) -> list[DueWait]:
        """Hạn đã qua, chưa bắn: `wait_deadlines` + `approvals` đang `pending` (hạn duyệt nằm ở
        `approvals.deadline` [Chốt], P7 2.5). Worker không đọc checkpoint."""
        ...

    async def mark_fired(self, due: DueWait, at: datetime) -> None: ...


class TicketLock(Protocol):
    def hold(self, ticket_id: str) -> AbstractAsyncContextManager[None]:
        """Khoá theo ticket suốt một lượt (D-19). Hết `lock_timeout` → `TicketBusy`."""
        ...


class TicketBusy(Exception):
    """Ticket đang bị lượt khác giữ khoá quá `lock_timeout` — lỗi tạm, thử lại chu kỳ sau."""


# ---- phụ thuộc của node thật ------------------------------------------------------------------


class IdentityReads(Protocol):
    """B1 (B01 mục 5): phiên còn sống (theo họ token) + khoá do dò mật khẩu (`users.locked_until`)."""

    async def active_session(self, session_id: str, now: datetime) -> LiveSession | None: ...

    async def locked_until(self, user_id: str) -> datetime | None: ...


class ToolCaller(Protocol):
    """`tools.registry.ToolRegistry` khớp theo cấu trúc: lỗi hệ thống ngoài → `ToolResult.error`,
    không raise (P5 mục 6.1)."""

    async def call(
        self, name: str, args: Mapping[str, Any], *, caller_step: str
    ) -> ToolResult: ...


class AlertSink(Protocol):
    """`audit.alerts.AlertWriter` — idempotent theo `(rule_id, subject, window_start)`."""

    async def raise_once(self, draft: AlertDraft) -> bool: ...


class TicketStore(Protocol):
    """`db/tickets.SqlTicketStore` — B20 đọc `created_at`, số lượt, ghi kết quả cuối MỘT lần."""

    async def created_at(self, ticket_id: str) -> datetime: ...

    async def count_turns(self, ticket_id: str) -> int: ...

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        """Ghi nếu `final_state IS NULL`; luôn trả dòng ĐANG CÓ (vừa ghi hoặc từ lần trước)."""
        ...


class EscalationStore(Protocol):
    """`db/escalations.SqlEscalationStore.create` — chỉ gọi qua `effects.once("escalation_create")`."""

    async def create(
        self,
        *,
        ticket_id: str,
        exit_code: str,
        reason_detail: str | None,
        handoff_note: Mapping[str, Any],
        is_deny_case: bool,
        created_at: datetime,
    ) -> str: ...
