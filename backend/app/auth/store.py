"""AuthStore trên Postgres (role app_rw): bảng `users`, `sessions`, view `auth_failures` (P7 2.1–2.3).

Mọi mốc thời gian ghi từ clock của service (không dùng `now()` của DB) để FakeClock tua được.
Mọi datetime TRẢ VỀ được chuẩn hoá thành `tzinfo=timezone.utc`: psycopg trả tzinfo theo TimeZone của
phiên Postgres (ví dụ `ZoneInfo("Etc/UTC")`), cùng thời điểm nhưng khác đối tượng — thư viện như
`email.utils.format_datetime` (cookie của Starlette) chỉ nhận đúng `timezone.utc`.
Bản in-memory cho unit test: `tests/fakes/auth.py`; hai bản chạy chung bộ test hợp đồng.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, Table, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.models import SessionRecord, UserRecord, UserSync
from app.db.models import Session, User

_users: Table = User.__table__  # type: ignore[assignment]
_sessions: Table = Session.__table__  # type: ignore[assignment]


def _utc(value: datetime | None) -> datetime | None:
    """Cùng thời điểm, tzinfo đúng là `timezone.utc`. DB naive (không thể với TIMESTAMPTZ) → lỗi."""
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("datetime từ DB không có múi giờ — cột phải là TIMESTAMPTZ")
    return value.astimezone(UTC)


def _utc_required(value: datetime) -> datetime:
    result = _utc(value)
    assert result is not None
    return result


def _user(row: Row[Any]) -> UserRecord:
    m = row._mapping
    return UserRecord(
        user_id=m["user_id"],
        username=m["username"],
        full_name=m["full_name"],
        role=m["role"],
        department=m["department"],
        manager_id=m["manager_id"],
        employment_status=m["employment_status"],
        hired_at=m["hired_at"],
        is_privileged_account=m["is_privileged_account"],
        token_version=m["token_version"],
        locked_until=_utc(m["locked_until"]),
        mfa_secret_enc=bytes(m["mfa_secret_enc"]) if m["mfa_secret_enc"] is not None else None,
    )


def _session(row: Row[Any]) -> SessionRecord:
    m = row._mapping
    return SessionRecord(
        session_id=m["session_id"],
        user_id=m["user_id"],
        token_family_id=m["token_family_id"],
        refresh_token_hash=m["refresh_token_hash"],
        created_at=_utc_required(m["created_at"]),
        expires_at=_utc_required(m["expires_at"]),
        revoked_at=_utc(m["revoked_at"]),
        revoke_reason=m["revoke_reason"],
        ip_prefix=m["ip_prefix"],
        user_agent_hash=m["user_agent_hash"],
    )


def _session_values(s: SessionRecord) -> dict[str, Any]:
    return {
        "session_id": s.session_id,
        "user_id": s.user_id,
        "token_family_id": s.token_family_id,
        "refresh_token_hash": s.refresh_token_hash,
        "created_at": s.created_at,
        "last_seen_at": s.created_at,
        "expires_at": s.expires_at,
        "revoked_at": s.revoked_at,
        "revoke_reason": s.revoke_reason,
        "ip_prefix": s.ip_prefix,
        "user_agent_hash": s.user_agent_hash,
    }


_COUNT_BY_USERNAME = text(
    "SELECT count(*) FROM auth_failures WHERE username_attempted = :u AND occurred_at > :since"
)
_COUNT_BY_IP = text("SELECT count(*) FROM auth_failures WHERE ip_prefix = :ip AND occurred_at > :since")


class SqlAuthStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ---- users ----

    async def get_user(self, user_id: str) -> UserRecord | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(_users).where(_users.c.user_id == user_id))).first()
        return _user(row) if row else None

    async def get_user_by_username(self, username: str) -> UserRecord | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(_users).where(_users.c.username == username))).first()
        return _user(row) if row else None

    async def upsert_user(self, sync: UserSync) -> tuple[UserRecord, str | None]:
        values = {
            "user_id": sync.user_id,
            "username": sync.username,
            "full_name": sync.full_name,
            "role": sync.role,
            "department": sync.department,
            "manager_id": sync.manager_id,
            "employment_status": sync.employment_status,
            "hired_at": sync.hired_at,
            "is_privileged_account": sync.is_privileged_account,
            "last_synced_at": sync.synced_at,
        }
        async with self._engine.begin() as conn:
            previous = (
                await conn.execute(
                    select(_users.c.role).where(_users.c.user_id == sync.user_id).with_for_update()
                )
            ).scalar_one_or_none()
            ins = insert(_users).values(**values, created_at=sync.synced_at)
            upsert = ins.on_conflict_do_update(
                index_elements=[_users.c.user_id],
                set_={k: ins.excluded[k] for k in values if k != "user_id"},
            ).returning(*_users.c)
            row = (await conn.execute(upsert)).one()
        return _user(row), previous

    async def bump_token_version(self, user_id: str) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(_users)
                .where(_users.c.user_id == user_id)
                .values(token_version=_users.c.token_version + 1)
                .returning(_users.c.token_version)
            )
            return int(result.scalar_one())

    async def set_locked_until(self, user_id: str, until: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_users).where(_users.c.user_id == user_id).values(locked_until=until)
            )

    async def set_mfa_secret(self, user_id: str, secret_enc: bytes) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_users).where(_users.c.user_id == user_id).values(mfa_secret_enc=secret_enc)
            )

    # ---- auth_failures ----

    async def count_failures(self, username: str, since: datetime) -> int:
        async with self._engine.connect() as conn:
            return int((await conn.execute(_COUNT_BY_USERNAME, {"u": username, "since": since})).scalar_one())

    async def count_ip_failures(self, ip_prefix: str, since: datetime) -> int:
        async with self._engine.connect() as conn:
            return int((await conn.execute(_COUNT_BY_IP, {"ip": ip_prefix, "since": since})).scalar_one())

    # ---- sessions ----

    async def create_session(self, session: SessionRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(insert(_sessions).values(**_session_values(session)))

    async def get_session(self, session_id: str) -> SessionRecord | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(select(_sessions).where(_sessions.c.session_id == session_id))
            ).first()
        return _session(row) if row else None

    async def get_session_by_refresh_hash(self, refresh_hash: str) -> SessionRecord | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_sessions).where(_sessions.c.refresh_token_hash == refresh_hash)
                )
            ).first()
        return _session(row) if row else None

    async def rotate_session(self, old_session_id: str, new: SessionRecord, now: datetime) -> bool:
        async with self._engine.begin() as conn:
            # UPDATE có điều kiện là điểm nguyên tử: hai request cùng token → chỉ một cái khớp.
            result = await conn.execute(
                update(_sessions)
                .where(_sessions.c.session_id == old_session_id, _sessions.c.revoked_at.is_(None))
                .values(revoked_at=now, revoke_reason="rotated", last_seen_at=now)
            )
            if result.rowcount != 1:
                return False
            await conn.execute(insert(_sessions).values(**_session_values(new)))
        return True

    async def revoke_session(self, session_id: str, reason: str, now: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_sessions)
                .where(_sessions.c.session_id == session_id, _sessions.c.revoked_at.is_(None))
                .values(revoked_at=now, revoke_reason=reason)
            )

    async def revoke_family(self, family_id: UUID, reason: str, now: datetime) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(_sessions)
                .where(_sessions.c.token_family_id == family_id, _sessions.c.revoked_at.is_(None))
                .values(revoked_at=now, revoke_reason=reason)
            )
            return int(result.rowcount)

    async def revoke_user_sessions(self, user_id: str, reason: str, now: datetime) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(_sessions)
                .where(_sessions.c.user_id == user_id, _sessions.c.revoked_at.is_(None))
                .values(revoked_at=now, revoke_reason=reason)
            )
            return int(result.rowcount)

    async def login_started_at(self, session_id: str) -> datetime | None:
        family = (
            select(_sessions.c.token_family_id)
            .where(_sessions.c.session_id == session_id)
            .scalar_subquery()
        )
        async with self._engine.connect() as conn:
            value = (
                await conn.execute(
                    select(func.min(_sessions.c.created_at)).where(
                        _sessions.c.token_family_id == family
                    )
                )
            ).scalar_one_or_none()
        return _utc(value)
