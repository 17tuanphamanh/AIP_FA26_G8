"""Port của auth (01 mục 4.1). auth chỉ phụ thuộc domain, core, db (01 mục 4.2) — adapter AD
(`tools/adapters/ad_read.AdIdentityProvider`), writer `audit/security_events.SecurityEventWriter` và
`audit/alerts.AlertWriter` khớp các Protocol này theo cấu trúc, `main.create_app` nối lại. Test tiêm
bản giả.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.auth.models import SessionRecord, UserRecord, UserSync
from app.domain.alerts import AlertDraft
from app.domain.context import AdAttributes


class AdUser(AdAttributes, Protocol):
    """Người dùng như AD trả về (`tools.models.AdUser` khớp theo cấu trúc)."""

    @property
    def username(self) -> str: ...
    @property
    def full_name(self) -> str: ...


class IdentityUnavailable(Exception):
    """AD không trả lời được (timeout, 5xx, breaker mở) — KHÔNG phải sai mật khẩu. Đăng nhập → 503,
    không đếm vào `login_failed` (B01 mục 5)."""


class IdentityProvider(Protocol):
    async def authenticate(self, username: str, password: str) -> AdUser | None:
        """None = sai tên đăng nhập hoặc mật khẩu. Lỗi hệ thống → `IdentityUnavailable`."""
        ...

    async def get_user(self, user_id: str) -> AdUser | None:
        """None = không có trong AD. Lỗi hệ thống → `IdentityUnavailable`."""
        ...


class SecurityEventSink(Protocol):
    """Ghi `security_events` (P7 2.3) — chỉ INSERT, `occurred_at` do sink lấy từ clock.
    `detail` KHÔNG chứa mật khẩu, token, secret hay nội dung chat."""

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
    ) -> None: ...


class AlertSink(Protocol):
    """Ghi `alerts` idempotent theo `(rule_id, subject, window_start)` (`audit/alerts.AlertWriter`).
    True = dòng mới; False = đã có."""

    async def raise_once(self, draft: AlertDraft) -> bool: ...


class AuthStore(Protocol):
    """Bảng `users`, `sessions` và view `auth_failures`. Bản SQL: `auth/store.py`; bản in-memory cho
    unit test: `tests/fakes/auth.py` — cả hai chạy cùng một bộ test hợp đồng."""

    # ---- users ----
    async def get_user(self, user_id: str) -> UserRecord | None: ...
    async def get_user_by_username(self, username: str) -> UserRecord | None: ...

    async def upsert_user(self, sync: UserSync) -> tuple[UserRecord, str | None]:
        """Ghi thuộc tính AD; trả (bản ghi mới, role cũ — None nếu dòng mới tạo)."""
        ...

    async def bump_token_version(self, user_id: str) -> int: ...
    async def set_locked_until(self, user_id: str, until: datetime) -> None: ...
    async def set_mfa_secret(self, user_id: str, secret_enc: bytes) -> None: ...

    # ---- auth_failures ----
    async def count_failures(self, username: str, since: datetime) -> int:
        """Số dòng `auth_failures` của username (kể cả user không tồn tại) sau `since`."""
        ...

    async def count_ip_failures(self, ip_prefix: str, since: datetime) -> int: ...

    # ---- sessions ----
    async def create_session(self, session: SessionRecord) -> None: ...
    async def get_session(self, session_id: str) -> SessionRecord | None: ...
    async def get_session_by_refresh_hash(self, refresh_hash: str) -> SessionRecord | None: ...

    async def rotate_session(self, old_session_id: str, new: SessionRecord, now: datetime) -> bool:
        """Nguyên tử: thu hồi phiên cũ (`rotated`) NẾU còn sống rồi tạo phiên mới. False = phiên cũ
        đã bị thu hồi trước đó (request khác đã xoay) → không tạo gì."""
        ...

    async def revoke_session(self, session_id: str, reason: str, now: datetime) -> None: ...
    async def revoke_family(self, family_id: UUID, reason: str, now: datetime) -> int: ...
    async def revoke_user_sessions(self, user_id: str, reason: str, now: datetime) -> int: ...

    async def login_started_at(self, session_id: str) -> datetime | None:
        """Thời điểm đăng nhập = `min(created_at)` của họ token chứa phiên này."""
        ...
