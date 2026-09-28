"""side_effects: them kind security_event

Nới CHECK `side_effects.kind` thêm `security_event` (thiết kế Phase 3 mục 8.2, 8.5): node B2 (`_block`),
`clarify_wait`, `confirm_wait` ghi `security_events(injection_detected)` QUA `effects.once` — chạy lại node sau sự cố
không ghi hai sự kiện an ninh cho một lần tấn công. Bảng `security_events` không đổi (`injection_detected` đã có).

Downgrade dừng nếu đã có dòng `security_event`: xoá chúng thì chạy lại node sẽ ghi sự kiện lần hai (mất idempotent).
Danh sách giá trị viết tĩnh — migration không được đổi theo models.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "side_effects"
CONSTRAINT = "ck_side_effects_kind"
OLD_KINDS = (
    "notify_user", "notify_approver", "deadline_set", "approval_create", "child_create", "child_submit",
    "escalation_create", "child_event",
)  # fmt: skip
NEW_KINDS = ("security_event",)


def _check(values: Sequence[str]) -> str:
    return "kind IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _replace_check(values: Sequence[str]) -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, _check(values))


def upgrade() -> None:
    _replace_check((*OLD_KINDS, *NEW_KINDS))


def downgrade() -> None:
    placeholders = ", ".join(f"'{v}'" for v in NEW_KINDS)
    count: int = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE kind IN ({placeholders})")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Không hạ được migration 0007: {TABLE} đã có {count} dòng {'/'.join(NEW_KINDS)}. "
            "Xoá đi thì chạy lại node sẽ ghi sự kiện an ninh lần hai — giữ DB ở 0007, hoặc dựng lại DB trống."
        )
    _replace_check(OLD_KINDS)
