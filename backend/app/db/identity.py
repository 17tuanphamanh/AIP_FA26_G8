"""Đọc `sessions`, `users` cho B1 (B01 mục 5: `sessions.get_active`, `users.locked_until`). Khớp
`graph.ports.IdentityReads` theo cấu trúc — graph không import auth (01 mục 4.2).

**Phiên = họ token** [Suy luận, 2b-1]: mỗi lần refresh tạo dòng `sessions` mới cùng `token_family_id`
và thu hồi dòng cũ với `revoke_reason='rotated'` (P6 mục 4). Ticket giữ `session_id` lúc tạo; nếu B1
chỉ xét đúng dòng đó thì một lần refresh bình thường cũng làm ticket bị chặn `invalid_credentials`.
Nên: phiên còn hiệu lực ⇔ họ token còn ít nhất một dòng chưa thu hồi, chưa hết hạn. Logout, admin
revoke, logout-all, phát hiện dùng lại, user bị vô hiệu hoá đều thu hồi dòng đang sống của họ → hết.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Table, and_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Session, User

_SESSIONS: Table = Session.__table__  # type: ignore[assignment]
_USERS: Table = User.__table__  # type: ignore[assignment]


@dataclass(frozen=True)
class LiveSession:
    session_id: str  # phiên trên ticket (có thể đã xoay vòng)
    user_id: str


class SqlIdentityReads:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def active_session(self, session_id: str, now: datetime) -> LiveSession | None:
        origin = _SESSIONS.alias("origin")
        live = _SESSIONS.alias("live")
        query = (
            select(origin.c.session_id, origin.c.user_id)
            .join(live, live.c.token_family_id == origin.c.token_family_id)
            .where(
                and_(
                    origin.c.session_id == session_id,
                    live.c.revoked_at.is_(None),
                    live.c.expires_at > now,
                )
            )
            .limit(1)
        )
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).first()
        return LiveSession(row.session_id, row.user_id) if row is not None else None

    async def locked_until(self, user_id: str) -> datetime | None:
        async with self._engine.connect() as conn:
            value = (
                await conn.execute(select(_USERS.c.locked_until).where(_USERS.c.user_id == user_id))
            ).scalar()
        return value.astimezone(UTC) if value is not None else None
