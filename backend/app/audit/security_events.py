"""Writer `security_events` (P7 2.3, D-04) — chỉ INSERT (bảng append-only ở cả quyền `app_rw` lẫn
trigger); `occurred_at` lấy từ clock tiêm vào. Khớp `auth.ports.SecurityEventSink` theo cấu trúc.

`detail` KHÔNG chứa mật khẩu, token, secret, URI otpauth hay nội dung chat: khoá mang tên nhạy cảm
bị từ chối ngay (lỗi lập trình), và giá trị trông như JWT cũng vậy.
"""

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Table, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import Clock
from app.db.models import SECURITY_EVENT_TYPES, SecurityEvent

# So theo từng phần của tên khoá tách bởi "_" (khỏi bắt nhầm "security" chứa "uri").
_SENSITIVE_PARTS = frozenset(
    {"password", "passwd", "pwd", "token", "secret", "otp", "otpauth", "cookie", "authorization",
     "uri", "key", "jwt", "refresh", "csrf"}
)  # fmt: skip
_TABLE: Table = SecurityEvent.__table__  # type: ignore[assignment]
_JWT_LIKE = re.compile(r"eyJ[\w-]+\.[\w-]+\.")


def check_detail(table: str, detail: Mapping[str, Any]) -> None:
    """`detail` JSONB không được mang bí mật: khoá tên nhạy cảm hoặc giá trị trông như JWT → lỗi
    lập trình. Dùng cho `security_events` và `alerts`."""
    for key, value in detail.items():
        if _SENSITIVE_PARTS & set(key.lower().split("_")):
            raise ValueError(f"{table}.detail không được có khoá nhạy cảm {key!r}")
        if isinstance(value, str) and _JWT_LIKE.search(value):
            raise ValueError(f"{table}.detail[{key!r}] trông như token")


def check_event(event_type: str, detail: Mapping[str, Any]) -> None:
    """Chặn sự kiện lạ và `detail` có dấu hiệu chứa bí mật — dùng chung cho writer và bản giả test."""
    if event_type not in SECURITY_EVENT_TYPES:
        raise ValueError(f"security_events: event_type lạ {event_type!r}")
    check_detail("security_events", detail)


class SecurityEventWriter:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def record(
        self,
        event_type: str,
        *,
        user_id: str | None = None,
        username_attempted: str | None = None,
        ip_prefix: str | None = None,
        route: str | None = None,
        ticket_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        payload = dict(detail or {})
        check_event(event_type, payload)
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_TABLE).values(
                    occurred_at=self._clock.now(),
                    event_type=event_type,
                    user_id=user_id,
                    username_attempted=username_attempted,
                    ip_prefix=ip_prefix,
                    route=route,
                    ticket_id=ticket_id,
                    detail=payload,
                )
            )
