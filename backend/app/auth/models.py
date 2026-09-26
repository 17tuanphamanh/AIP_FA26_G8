"""Bản ghi và kết quả của auth — không biết HTTP hay SQL."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.domain.context import Role

INACTIVE_STATUSES = frozenset({"disabled", "terminated"})  # P6 mục 4 bước 5


@dataclass(frozen=True)
class UserRecord:
    """Dòng `users` (P7 2.1) — bản sao thuộc tính AD đồng bộ lúc đăng nhập. Không có mật khẩu."""

    user_id: str
    username: str
    full_name: str | None
    role: Role
    department: str | None
    manager_id: str | None
    employment_status: str
    hired_at: date | None
    is_privileged_account: bool
    token_version: int = 0
    locked_until: datetime | None = None
    mfa_secret_enc: bytes | None = None

    @property
    def active(self) -> bool:
        return self.employment_status not in INACTIVE_STATUSES


@dataclass(frozen=True)
class UserSync:
    """Thuộc tính AD ghi vào `users` khi đồng bộ; không đụng token_version, khoá, MFA."""

    user_id: str
    username: str
    full_name: str | None
    role: Role
    department: str | None
    manager_id: str | None
    employment_status: str
    hired_at: date | None
    is_privileged_account: bool
    synced_at: datetime


@dataclass(frozen=True)
class SessionRecord:
    """Dòng `sessions` (P7 2.2). Refresh token chỉ lưu SHA-256."""

    session_id: str
    user_id: str
    token_family_id: UUID
    refresh_token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    ip_prefix: str | None = None
    user_agent_hash: str | None = None

    def usable(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at


@dataclass(frozen=True)
class Principal:
    """Người đang gọi API — dựng từ access token đã kiểm với DB (tầng 1)."""

    user_id: str
    role: Role
    session_id: str
    token_version: int
    permissions: frozenset[str]

    def has(self, perm: str) -> bool:
        return perm in self.permissions


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    expires_in: int  # giây, của access token
    refresh_expires_at: datetime
