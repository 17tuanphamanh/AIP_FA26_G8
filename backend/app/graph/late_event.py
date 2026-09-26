"""Guard sự kiện muộn [Chốt 8.3] + `wake_parent` (D-17) — P1 mục 6.1.

API (thao tác của người) và worker (timeout) đều đi qua `deliver_event` → timeout và thao tác người
không bao giờ chạy hai đường code khác nhau [Chốt]. Dưới khoá ticket: ticket không còn ở đúng trạng
thái chờ (hoặc không dừng ở node chờ) → audit `late_event` + `LateEvent` (HTTP 409), trạng thái không
đổi. `detail.source` = `user` | `worker` để M9 không đếm lẫn timeout trùng của worker với thao tác trễ
của người (người duyệt 26/09/2026).

`start_event` (API, 2b-3 Q1): lấy khoá + kiểm guard NGAY trong request (409/422 trả đồng bộ), rồi GIAO
khoá cho task nền chạy lượt resume và trả 202 — request không treo suốt lượt (huong-dan 14.3), mà sự
kiện thứ hai vẫn phải chờ khoá rồi gặp guard → 409. Khoá có đúng một chủ tại mọi thời điểm: chưa giao
(guard từ chối, lỗi, request bị huỷ) thì request nhả; đã giao thì task nền nhả trong `finally` — kể cả
khi task bị huỷ trước khi kịp chạy (`on_cancel`).

Mọi đường 409 ghi ĐÚNG MỘT dòng `late_event`: guard ghi ở đây; route duyệt từ chối trước khi tới guard
(phiếu quá hạn / đã quyết) thì gọi `record_late` thay vì guard — không bao giờ cả hai.
"""

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Final, Literal

from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_NEW, S_PENDING_APPROVAL
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


async def record_late(
    runner: Runner,
    ticket_id: str,
    *,
    expected_status: str,
    actual_status: str | None,
    event_kind: str,
    source: Source,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Dòng audit `late_event` (step = bước của trạng thái chờ mà sự kiện NHẮM tới, không khoá
    idempotent — mỗi lần bấm trễ là một sự kiện)."""
    await runner.audit.record({
        "ticket_id": ticket_id, "turn_id": None, "loop_seq": 0, "idempotency_key": None,
        "step": _STEP_OF_STATUS.get(expected_status, "B20"),
        "event": "late_event", "from_status": actual_status, "to_status": actual_status,
        "created_at": runner.clock.now(),
        "detail": {
            "expected_status": expected_status, "actual_status": actual_status,
            "event_kind": event_kind, "source": source, **(extra or {}),
        },
    })  # fmt: skip


async def _guard(
    runner: Runner,
    ticket_id: str,
    expected_status: str,
    event: Mapping[str, Any],
    *,
    source: Source,
    missing_is_late: bool,
    late_extra: Mapping[str, Any] | None,
) -> None:
    """Gọi khi ĐANG giữ khoá ticket. Không đúng trạng thái chờ → `late_event` + `LateEvent`."""
    snap = await runner.snapshot(ticket_id)
    if not snap.values and not missing_is_late:
        raise TicketNotFound(ticket_id)
    # API đã thấy dòng `tickets`: chưa có checkpoint = graph chưa chạy lượt đầu (vẫn S_NEW).
    status = snap.values.get("status", S_NEW) if snap.values else S_NEW
    waiting = snap.next[0] if snap.next else None
    spec = WAITS.get(waiting) if waiting else None
    if status != expected_status or spec is None or spec[0] != expected_status:
        await record_late(
            runner, ticket_id, expected_status=expected_status, actual_status=status,
            event_kind=str(event.get("kind")), source=source, extra=late_extra,
        )  # fmt: skip
        raise LateEvent(ticket_id, expected_status, status)
    if event.get("kind") not in spec[2]:
        raise InvalidEvent(f"{waiting} không nhận sự kiện {event.get('kind')!r}")


async def deliver_event(
    runner: Runner,
    ticket_id: str,
    expected_status: str,
    event: Mapping[str, Any],
    *,
    source: Source = "user",
    session_id: str | None = None,
) -> RunResult:
    """Giao sự kiện và chờ trọn lượt (worker, test)."""
    async with runner.hold(ticket_id):
        await _guard(runner, ticket_id, expected_status, event, source=source,
                     missing_is_late=False, late_extra=None)  # fmt: skip
        result = await runner.resume_locked(ticket_id, event, session_id=session_id)
    await runner.after_turn(result)  # SAU khi nhả khoá: con kết thúc → đánh thức cha (2b-Q7)
    return result


type Spawn = Callable[..., Any]  # (coro, *, name, on_cancel) → task


class _Handoff:
    """Khoá ticket đã lấy, nhả đúng MỘT lần — bởi request (chưa giao) hoặc task nền (đã giao)."""

    def __init__(self, cm: AbstractAsyncContextManager[None]) -> None:
        self._cm = cm
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._cm.__aexit__(None, None, None)  # khoá chỉ cần nhả, không cần biết lỗi


async def start_event(
    runner: Runner,
    ticket_id: str,
    expected_status: str,
    event: Mapping[str, Any],
    *,
    spawn: Spawn,
    source: Source = "user",
    session_id: str | None = None,
    late_extra: Mapping[str, Any] | None = None,
) -> None:
    """API: guard đồng bộ (LateEvent/InvalidEvent/TicketBusy ném ra cho route), lượt resume chạy nền.

    Trả về khi task nền đã NHẬN khoá — sự kiện đến sau phải chờ lượt này xong rồi mới gặp guard."""
    cm = runner.hold(ticket_id)
    await cm.__aenter__()  # TicketBusy → route trả 503
    handoff = _Handoff(cm)
    handed = False
    try:
        await _guard(runner, ticket_id, expected_status, event, source=source,
                     missing_is_late=True, late_extra=late_extra)  # fmt: skip

        async def run() -> None:
            try:
                result = await runner.resume_locked(ticket_id, event, session_id=session_id)
            finally:
                await handoff.release()
            await runner.after_turn(result)  # SAU khi nhả khoá (2b-Q7)

        spawn(run(), name=f"event:{ticket_id}", on_cancel=handoff.release)
        handed = True
    finally:
        if not handed:  # guard từ chối, lỗi, hay request bị huỷ giữa chừng → request tự nhả
            await handoff.release()


async def wake_parent(runner: Runner, parent_id: str) -> RunResult | None:
    """Chỉ là tín hiệu (D-17) — xem `Runner.wake_parent`."""
    return await runner.wake_parent(parent_id)


__all__ = [
    "InvalidEvent", "LateEvent", "Spawn", "TicketNotFound", "deliver_event", "record_late",
    "start_event", "wake_parent",
]  # fmt: skip
