"""Bọc notifier hiện có để ghi email (notify-email). Tin chat KHÔNG đổi: bản bọc gọi `inner` y như cũ, trả `result_ref` của
`inner`, rồi ghi MỘT dòng `email_outbox` trong CÙNG transaction `effects.once` (`current_tx()`).

- `EmailingNotifier` (bọc `inner` của `ChildAwareNotifier` — ticket con không bao giờ tới đây; outbox còn kiểm lại
  `parent_ticket_id`): bước lấy từ `current_effect()` — B10/B16/B18/B20 có email, B11 (câu hỏi) và bước khác không;
  `effect_key` của dòng outbox = khoá của effect (chạy lại không trùng). Ngoài `effects.once` → không email.
- `ApproverEmailNotice`: `(approval_id, approver_id, kind) → result_ref` — `approval.store.log_approver_notice` như cũ + dòng outbox.
  MỘT hàm cho B15 (`EmailingApprovals.notify_approver`, trong `effects.once("notify_approver")` → khoá effect) và worker nhắc duyệt
  (`WorkerJobs(notify_approver=…)`, ngoài effect → khoá `sha256("email", phiếu, người nhận, loại)`; `mark_reminder_once` đã bảo đảm
  chỉ một worker gửi, UNIQUE chặn lớp thứ hai).
- `email_outbox_from_settings`: None khi `Settings.email_active` sai (EMAIL_ENABLED=false hoặc EVAL_MODE=true) → nơi dựng KHÔNG bọc gì,
  không dòng outbox nào được ghi.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from app.approval.store import NoticeKind, SqlApprovals, log_approver_notice
from app.core.clock import Clock
from app.core.hashing import sha256_key
from app.db.runtime import current_effect
from app.guard.privacy import TextRedactor
from app.notify.email import ApproverNoticeKind, EmailKind, user_kind
from app.notify.outbox import SqlEmailOutbox
from app.settings import Settings


class UserNotifier(Protocol):
    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str: ...


class EmailOutboxPort(Protocol):
    async def enqueue_user(self, *, ticket_id: str, kind: EmailKind, text: str, effect_key: str) -> int | None: ...

    async def enqueue_approver(
        self, *, approval_id: str, approver_id: str, kind: ApproverNoticeKind, effect_key: str
    ) -> int | None: ...


type ApproverNotice = Callable[[str, str, NoticeKind], Awaitable[str]]


class EmailingNotifier:
    def __init__(self, inner: UserNotifier, outbox: EmailOutboxPort) -> None:
        self._inner = inner
        self._outbox = outbox

    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
        ref = await self._inner.notify_user(ticket_id, text, needs)
        call = current_effect()
        kind = None if call is None else user_kind(call.step)
        if call is not None and kind is not None:
            await self._outbox.enqueue_user(ticket_id=ticket_id, kind=kind, text=text, effect_key=call.key)
        return ref


def approver_effect_key(approval_id: str, approver_id: str, kind: NoticeKind) -> str:
    call = current_effect()
    return call.key if call is not None else sha256_key("email", approval_id, approver_id, kind)


class ApproverEmailNotice:
    def __init__(self, outbox: EmailOutboxPort, inner: ApproverNotice = log_approver_notice) -> None:
        self._outbox = outbox
        self._inner = inner

    async def __call__(self, approval_id: str, approver_id: str, kind: NoticeKind = "new") -> str:
        ref = await self._inner(approval_id, approver_id, kind)
        await self._outbox.enqueue_approver(
            approval_id=approval_id, approver_id=approver_id, kind=kind,
            effect_key=approver_effect_key(approval_id, approver_id, kind),
        )  # fmt: skip
        return ref


class EmailingApprovals(SqlApprovals):
    """`SqlApprovals` y nguyên, chỉ `notify_approver` thêm dòng outbox (qua `ApproverEmailNotice`)."""

    def __init__(self, engine: AsyncEngine, notice: ApproverEmailNotice) -> None:
        super().__init__(engine)
        self._notice = notice

    async def notify_approver(self, approval_id: str, approver_id: str, kind: NoticeKind = "new") -> str:
        return await self._notice(approval_id, approver_id, kind)


def email_outbox_from_settings(
    settings: Settings, engine: AsyncEngine, guard: TextRedactor, clock: Clock
) -> SqlEmailOutbox | None:
    """Store outbox khi email bật thật (`email_active`); None = không bọc, không ghi outbox (EMAIL_ENABLED=false / EVAL_MODE=true)."""
    if not settings.email_active:
        return None
    assert settings.email_link_base_url is not None  # Settings._email_config đã bắt khi bật
    return SqlEmailOutbox(engine, guard, clock, settings.email_link_base_url)
