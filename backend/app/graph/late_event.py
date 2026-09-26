"""Guard sự kiện muộn [Chốt 8.3] + `wake_parent` (D-17) — P1 mục 6.1.

API (thao tác của người) và worker (timeout) đều đi qua `deliver_event` → timeout và thao tác người
không bao giờ chạy hai đường code khác nhau [Chốt]. Dưới khoá ticket: ticket không còn ở đúng trạng
thái chờ (hoặc không dừng ở node chờ) → audit `late_event` + `LateEvent` (HTTP 409), trạng thái không
đổi. `detail.source` = `user` | `worker` để M9 không đếm lẫn timeout trùng của worker với thao tác trễ
của người (người duyệt 26/09/2026).
"""

from collections.abc import Mapping
from typing import Any, Final, Literal

from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL
from app.graph.runner import Runner, RunResult

# Node chờ → (trạng thái lúc chờ, bước ghi audit, loại sự kiện hợp lệ) — P1 mục 6.
WAITS: Final[Mapping[str, tuple[str, str, frozenset[str]]]] = {
    "clarify_wait": (S_CLARIFYING, "B11", frozenset({"user_reply", "timeout"})),
    "approval_wait": (S_PENDING_APPROVAL, "B16", frozenset({"approved", "rejected", "timeout"})),
    "confirm_wait": (S_CONFIRMING, "B19", frozenset({"confirmed", "unresolved", "timeout"})),
    "parent_reply_wait": (S_CONFIRMING, "B5", frozenset({"reply", "timeout"})),
}
_STEP_OF_STATUS: Final = {S_CLARIFYING: "B11", S_PENDING_APPROVAL: "B16", S_CONFIRMING: "B19"}

type Source = Literal["user", "worker"]


class LateEvent(Exception):
    """Sự kiện đến khi ticket không ở trạng thái chờ tương ứng (TC27)."""

    http_status = 409
    message = "Yêu cầu đã chuyển sang bước khác"

    def __init__(self, ticket_id: str, expected: str, actual: str | None) -> None:
        self.ticket_id, self.expected, self.actual = ticket_id, expected, actual
        super().__init__(f"{ticket_id}: chờ {expected}, đang {actual}")


class TicketNotFound(LookupError):
    pass


class InvalidEvent(ValueError):
    """Loại sự kiện không hợp lệ cho node chờ (API → 422)."""


async def deliver_event(
    runner: Runner,
    ticket_id: str,
    expected_status: str,
    event: Mapping[str, Any],
    *,
    source: Source = "user",
    session_id: str | None = None,
) -> RunResult:
    async with runner.hold(ticket_id):
        snap = await runner.snapshot(ticket_id)
        if not snap.values:
            raise TicketNotFound(ticket_id)
        status = snap.values.get("status")
        waiting = snap.next[0] if snap.next else None
        spec = WAITS.get(waiting) if waiting else None
        if status != expected_status or spec is None or spec[0] != expected_status:
            await runner.audit.record({
                "ticket_id": ticket_id, "turn_id": None, "loop_seq": 0, "idempotency_key": None,
                # Bước của trạng thái chờ mà sự kiện NHẮM tới (không phải nơi ticket đang đứng).
                "step": _STEP_OF_STATUS.get(expected_status, "B20"),
                "event": "late_event", "from_status": status, "to_status": status,
                "created_at": runner.clock.now(),
                "detail": {
                    "expected_status": expected_status, "actual_status": status,
                    "event_kind": str(event.get("kind")), "source": source,
                },
            })  # fmt: skip
            raise LateEvent(ticket_id, expected_status, status)
        if event.get("kind") not in spec[2]:
            raise InvalidEvent(f"{waiting} không nhận sự kiện {event.get('kind')!r}")
        result = await runner.resume_locked(ticket_id, event, session_id=session_id)
    await runner.after_turn(result)  # SAU khi nhả khoá: con kết thúc → đánh thức cha (2b-Q7)
    return result


async def wake_parent(runner: Runner, parent_id: str) -> RunResult | None:
    """Chỉ là tín hiệu (D-17) — xem `Runner.wake_parent`."""
    return await runner.wake_parent(parent_id)
