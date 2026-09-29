"""Writer `security_events` (P7 2.3, D-04) — chỉ INSERT (bảng append-only ở cả quyền `app_rw` lẫn
trigger); `occurred_at` lấy từ clock tiêm vào. Khớp `auth.ports.SecurityEventSink` theo cấu trúc.

`detail` KHÔNG chứa mật khẩu, token, secret, URI otpauth hay nội dung chat: `check_event`/`check_detail`
(ở `db/security_events.py` từ 3e, import lại ở đây) từ chối khoá tên nhạy cảm và giá trị trông như JWT.

Trong `effects.once` (node B2, `clarify_wait`, `confirm_wait` — 3e, kind `security_event`) writer ghi bằng
`current_tx()`: dòng `security_events` và dòng `side_effects` cùng commit — chạy lại node sau sự cố không ghi hai sự
kiện cho một lần tấn công (e15). Ngoài đó (auth, API) mỗi lần ghi là một transaction riêng như trước.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import Clock
from app.db.runtime import current_tx
from app.db.security_events import check_detail, check_event, insert_event

__all__ = ["SecurityEventWriter", "check_detail", "check_event"]


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
        check_event(event_type, dict(detail or {}))  # lỗi lập trình nổ TRƯỚC khi mở transaction
        values: dict[str, Any] = {
            "occurred_at": self._clock.now(), "user_id": user_id, "username_attempted": username_attempted,
            "ip_prefix": ip_prefix, "route": route, "ticket_id": ticket_id, "detail": detail,
        }  # fmt: skip
        conn = current_tx()
        if conn is not None:
            await insert_event(conn, event_type, **values)
            return
        async with self._engine.begin() as own:
            await insert_event(own, event_type, **values)
