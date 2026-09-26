"""security_events: them mfa_enrolled, mfa_reset

Nới CHECK `security_events.event_type` thêm `mfa_enrolled`, `mfa_reset` (P7 2.3 bản 1.5 — ghi bởi
CLI `python -m app.auth.mfa enroll|reset`). View `auth_failures` giữ nguyên: hai loại mới KHÔNG
phải lần đăng nhập thất bại.

Downgrade dừng nếu bảng đã có dòng thuộc hai loại này: `security_events` là append-only (trigger
chặn DELETE), không xoá được thì không thể siết CHECK lại. Danh sách giá trị viết tĩnh — migration
không được đổi theo models.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "security_events"
CONSTRAINT = "ck_security_events_event_type"
OLD_TYPES = (
    "login_success", "login_failed", "account_locked", "logout", "token_refreshed",
    "refresh_reuse_detected", "session_revoked", "permission_denied", "role_changed",
    "mfa_failed", "policy_saved", "injection_detected", "privacy_secret_redacted",
)  # fmt: skip
NEW_TYPES = ("mfa_enrolled", "mfa_reset")


def _check(values: Sequence[str]) -> str:
    return "event_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _replace_check(values: Sequence[str]) -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, _check(values))


def upgrade() -> None:
    _replace_check((*OLD_TYPES, *NEW_TYPES))


def downgrade() -> None:
    placeholders = ", ".join(f"'{v}'" for v in NEW_TYPES)
    count: int = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE event_type IN ({placeholders})")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Không hạ được migration 0002: {TABLE} đã có {count} dòng {'/'.join(NEW_TYPES)}. "
            "Bảng append-only nên không xoá được — giữ DB ở 0002, hoặc dựng lại DB trống."
        )
    _replace_check(OLD_TYPES)
