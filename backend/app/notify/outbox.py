"""`email_outbox` (migration 0012) — ghi hàng đợi email và các câu của worker gửi / API quản trị.

Ghi (`enqueue_user`, `enqueue_approver`):
- Trong transaction của `effects.once` (`current_tx()`) → dòng outbox và dòng `side_effects` cùng commit; process chết/rollback thì
  cùng mất (chạy lại làm như chưa làm). Không có transaction đó (worker nhắc duyệt) → transaction ngắn riêng.
- Bọc SAVEPOINT: ghi outbox lỗi (DB, guard…) → rollback về savepoint, log TÊN LỚP, trả None — tin chat/phiếu duyệt KHÔNG đổi, không
  E9 vì email.
- `effect_key` UNIQUE + `ON CONFLICT DO NOTHING`: lần ghi thứ hai cùng khoá không thêm dòng (và không ghi lại sự kiện bảo mật).
- Thân email chạy lại privacy guard (`TextRedactor.redact_text`) TRƯỚC khi ghi: có bí mật → `skipped` (`SecretInBody`), thân lưu bản
  đã che + một `security_events(privacy_secret_redacted)` cùng transaction. Người nhận không có `users.email` → `skipped`
  (`NoRecipientEmail`). Ticket con (`parent_ticket_id` có giá trị) → không có dòng nào (D-31: con không nhắn người dùng).
- KHÔNG lưu địa chỉ: worker nối `users.email` lúc gửi. Không log thân, không log địa chỉ.

Gửi (`claim`, `mark_*`): `claim` chọn tối đa N dòng `pending` đã tới lượt `FOR UPDATE SKIP LOCKED`, dời `next_attempt_at` thêm một
hạn giữ chỗ rồi commit NGAY (transaction ngắn — không giữ khoá trong lúc nói chuyện với SMTP); worker khác không lấy lại dòng đang gửi.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import Table, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.clock import Clock
from app.db.models import Approval, EmailOutbox, Ticket, User
from app.db.runtime import current_tx
from app.db.security_events import insert_event
from app.guard.privacy import TextRedactor
from app.notify.email import (
    APPROVER_KIND,
    ApproverNoticeKind,
    EmailKind,
    approver_link,
    approver_text,
    subject,
    user_link,
    with_link,
)

log = logging.getLogger(__name__)

_OUTBOX: Table = EmailOutbox.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
_USERS: Table = User.__table__  # type: ignore[assignment]
_APPROVALS: Table = Approval.__table__  # type: ignore[assignment]

SKIP_NO_EMAIL: Final = "NoRecipientEmail"
SKIP_SECRET: Final = "SecretInBody"
SECRET_EVENT: Final = "privacy_secret_redacted"

# `FOR UPDATE SKIP LOCKED` + dời hạn giữ chỗ trong MỘT câu; nối `users` lấy địa chỉ hiện hành (FK bảo đảm có dòng).
_CLAIM = text(
    "WITH due AS (SELECT id FROM email_outbox WHERE status = 'pending' AND next_attempt_at <= :now "
    "             ORDER BY next_attempt_at, id LIMIT :limit FOR UPDATE SKIP LOCKED) "
    "UPDATE email_outbox o SET next_attempt_at = :lease FROM due, users u "
    "WHERE o.id = due.id AND u.user_id = o.recipient_user_id "
    "RETURNING o.id, o.kind, o.subject, o.body, o.attempts, u.email"
)


@dataclass(frozen=True)
class ClaimedEmail:
    id: int
    kind: str
    subject: str
    body: str
    attempts: int
    address: str | None  # `users.email` lúc lấy — None → skipped


@dataclass(frozen=True)
class OutboxRow:
    """Dòng cho `GET /api/admin/email-outbox` — KHÔNG có `subject`/`body`; địa chỉ chỉ dạng che (do API che)."""

    id: int
    created_at: datetime
    sent_at: datetime | None
    kind: str
    status: str
    attempts: int
    last_error_class: str | None
    address: str | None


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


class SqlEmailOutbox:
    def __init__(self, engine: AsyncEngine, guard: TextRedactor, clock: Clock, link_base_url: str) -> None:
        self._engine = engine
        self._guard = guard
        self._clock = clock
        self._base = link_base_url.rstrip("/")

    # ---- ghi (trong effects.once) ----

    async def _guarded[T](self, what: str, fn: Callable[[AsyncConnection], Awaitable[T]]) -> T | None:
        """Chạy `fn` trong SAVEPOINT của transaction effect (hoặc transaction riêng). Lỗi → None + log tên lớp, không lan ra."""
        try:
            conn = current_tx()
            if conn is not None:
                async with conn.begin_nested():
                    return await fn(conn)
            async with self._engine.begin() as own:
                return await fn(own)
        except Exception as exc:  # noqa: BLE001 — email không được làm hỏng tin chat / phiếu duyệt
            log.warning("ghi email_outbox (%s) lỗi: %s — bỏ qua email, tin chat không đổi", what, type(exc).__name__)
            return None

    async def enqueue_user(self, *, ticket_id: str, kind: EmailKind, text: str, effect_key: str) -> int | None:
        """Email cho người gửi ticket. None = không có dòng (ticket con / không thấy ticket / lỗi ghi)."""

        async def run(conn: AsyncConnection) -> int | None:
            row = (await conn.execute(
                select(_TICKETS.c.parent_ticket_id, _TICKETS.c.requester_id, _USERS.c.email)
                .select_from(_TICKETS.outerjoin(_USERS, _USERS.c.user_id == _TICKETS.c.requester_id))
                .where(_TICKETS.c.ticket_id == ticket_id)
            )).first()  # fmt: skip
            if row is None or row.parent_ticket_id is not None:  # D-31: ticket con không nhắn (kể cả qua email)
                return None
            body = with_link(text, user_link(self._base, ticket_id))
            return await self._insert(
                conn, ticket_id=ticket_id, recipient=row.requester_id, kind=kind, body=body,
                has_address=row.email is not None, effect_key=effect_key,
            )  # fmt: skip

        return await self._guarded(kind, run)

    async def enqueue_approver(
        self, *, approval_id: str, approver_id: str, kind: ApproverNoticeKind, effect_key: str
    ) -> int | None:
        """Email cho người duyệt / dự phòng (B15 `new`, worker `reminder_1`/`reminder_2`)."""
        email_kind = APPROVER_KIND[kind]

        async def run(conn: AsyncConnection) -> int | None:
            approval = (await conn.execute(
                select(_APPROVALS.c.ticket_id, _APPROVALS.c.deadline).where(_APPROVALS.c.approval_id == int(approval_id))
            )).first()  # fmt: skip
            user = (await conn.execute(select(_USERS.c.email).where(_USERS.c.user_id == approver_id))).first()
            if approval is None or user is None:
                return None
            body = with_link(
                approver_text(email_kind, approval.ticket_id, approval.deadline), approver_link(self._base, approval_id)
            )
            return await self._insert(
                conn, ticket_id=approval.ticket_id, recipient=approver_id, kind=email_kind, body=body,
                has_address=user.email is not None, effect_key=effect_key,
            )  # fmt: skip

        return await self._guarded(email_kind, run)

    async def _insert(
        self, conn: AsyncConnection, *, ticket_id: str | None, recipient: str, kind: EmailKind, body: str,
        has_address: bool, effect_key: str,
    ) -> int:  # fmt: skip
        checked = self._guard.redact_text(body)
        now = self._clock.now()  # Clock của app (worker so `next_attempt_at` với cùng đồng hồ)
        status, reason = "pending", None
        if checked.secrets_found:
            status, reason = "skipped", SKIP_SECRET
        elif not has_address:
            status, reason = "skipped", SKIP_NO_EMAIL
        done = await conn.execute(
            pg_insert(_OUTBOX)
            .values(ticket_id=ticket_id, recipient_user_id=recipient, kind=kind, subject=subject(kind, ticket_id),
                    body=checked.text, status=status, last_error_class=reason, effect_key=effect_key, created_at=now,
                    next_attempt_at=now)
            .on_conflict_do_nothing(index_elements=["effect_key"])
            .returning(_OUTBOX.c.id)
        )  # fmt: skip
        new = done.scalar_one_or_none()
        if new is None:  # chạy lại cùng khoá: dòng cũ, không ghi lại sự kiện
            old = await conn.execute(select(_OUTBOX.c.id).where(_OUTBOX.c.effect_key == effect_key))
            return int(old.scalar_one())
        if reason == SKIP_SECRET:
            await insert_event(
                conn, SECRET_EVENT, occurred_at=now, user_id=recipient, ticket_id=ticket_id,
                detail={"source": "email_outbox", "email_kind": kind, "secrets_found": checked.secrets_found},
            )  # fmt: skip
        return int(new)

    # ---- worker gửi ----

    async def claim(self, now: datetime, limit: int, lease: timedelta) -> list[ClaimedEmail]:
        async with self._engine.begin() as conn:
            rows = await conn.execute(_CLAIM, {"now": now, "limit": limit, "lease": now + lease})
            return [ClaimedEmail(int(r.id), r.kind, r.subject, r.body, int(r.attempts), r.email) for r in rows]

    async def _update(self, email_id: int, **values: Any) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_OUTBOX).where(_OUTBOX.c.id == email_id, _OUTBOX.c.status == "pending").values(**values)
            )

    async def mark_sent(self, email_id: int, at: datetime) -> None:
        await self._update(email_id, status="sent", sent_at=at)

    async def mark_skipped(self, email_id: int, reason: str) -> None:
        await self._update(email_id, status="skipped", last_error_class=reason)

    async def mark_retry(self, email_id: int, *, attempts: int, error_class: str, next_at: datetime) -> None:
        await self._update(email_id, attempts=attempts, last_error_class=error_class[:64], next_attempt_at=next_at)

    async def mark_failed(self, email_id: int, *, attempts: int, error_class: str) -> None:
        await self._update(email_id, status="failed", attempts=attempts, last_error_class=error_class[:64])


async def recent_outbox(engine: AsyncEngine, limit: int, status: str | None = None) -> list[OutboxRow]:
    """API quản trị (chỉ đọc): dòng mới nhất trước — không đọc `subject`/`body`."""
    q = (
        select(_OUTBOX.c.id, _OUTBOX.c.created_at, _OUTBOX.c.sent_at, _OUTBOX.c.kind, _OUTBOX.c.status,
               _OUTBOX.c.attempts, _OUTBOX.c.last_error_class, _USERS.c.email)
        .select_from(_OUTBOX.join(_USERS, _USERS.c.user_id == _OUTBOX.c.recipient_user_id))
        .order_by(_OUTBOX.c.created_at.desc(), _OUTBOX.c.id.desc())
        .limit(limit)
    )  # fmt: skip
    if status is not None:
        q = q.where(_OUTBOX.c.status == status)
    async with engine.connect() as conn:
        rows = await conn.execute(q)
        return [OutboxRow(
            id=int(r.id), created_at=r.created_at.astimezone(UTC), sent_at=_utc(r.sent_at), kind=r.kind,
            status=r.status, attempts=int(r.attempts), last_error_class=r.last_error_class, address=r.email,
        ) for r in rows]  # fmt: skip
