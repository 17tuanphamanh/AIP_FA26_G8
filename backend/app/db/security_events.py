"""`security_events` ở tầng DB (P7 2.3, D-04): kiểm `detail` + câu INSERT dùng chung.

Nằm ở `db` (không ở `audit`) vì `db/tickets.create` phải INSERT sự kiện `privacy_secret_redacted` CÙNG transaction với
`tickets` + `turns` (phase3 mục 8.3) mà 01 §4.2 không cho `db → audit`. `audit/security_events.SecurityEventWriter` và
bản giả test dùng lại đúng các hàm này.

`detail` KHÔNG chứa mật khẩu, token, secret, URI otpauth hay nội dung chat: khoá mang tên nhạy cảm bị từ chối ngay
(lỗi lập trình), và giá trị trông như JWT cũng vậy.
"""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Table, insert
from sqlalchemy.ext.asyncio import AsyncConnection

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
    """Chặn sự kiện lạ và `detail` có dấu hiệu chứa bí mật — dùng chung cho writer, `tickets.create` và bản giả test."""
    if event_type not in SECURITY_EVENT_TYPES:
        raise ValueError(f"security_events: event_type lạ {event_type!r}")
    check_detail("security_events", detail)


async def insert_event(
    conn: AsyncConnection,
    event_type: str,
    *,
    occurred_at: datetime,
    user_id: str | None = None,
    username_attempted: str | None = None,
    ip_prefix: str | None = None,
    route: str | None = None,
    ticket_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    payload = dict(detail or {})
    check_event(event_type, payload)
    await conn.execute(
        insert(_TABLE).values(
            occurred_at=occurred_at, event_type=event_type, user_id=user_id,
            username_attempted=username_attempted, ip_prefix=ip_prefix, route=route,
            ticket_id=ticket_id, detail=payload,
        )
    )  # fmt: skip
