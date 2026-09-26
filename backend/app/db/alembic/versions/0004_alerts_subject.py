"""alerts: them cot subject, khoa chong trung (rule_id, subject, window_start)

Quyết định Q1 (người duyệt 26/09/2026): khoá chống trùng cũ `(rule_id, window_start)` gộp cảnh báo
của hai người bị khoá cùng lúc thành một dòng — bỏ sót sự cố an ninh (False Negative). Thêm
`subject` (user_id với luật theo người, ticket_id với luật theo ticket, '' với luật tổng hợp — truyền
tường minh, cột KHÔNG có DEFAULT) và đổi khoá thành `(rule_id, subject, window_start)`. P7 (mục 2.12,
bản 1.6) và P9 mục 6 do người duy trì đặc tả cập nhật.

Downgrade dừng nếu đã có hai dòng cùng `(rule_id, window_start)` khác `subject`: khoá cũ không chứa
nổi chúng, và xoá cảnh báo để hạ migration là mất dấu vết an ninh.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "alerts"
OLD_KEY = "uq_alerts_rule_id_window_start"
NEW_KEY = "uq_alerts_rule_id_subject_window_start"


def upgrade() -> None:
    # DEFAULT '' chỉ để điền dòng cũ lúc thêm cột, rồi bỏ ngay: INSERT thiếu `subject` phải LỖI — quên
    # subject là gộp cảnh báo (False Negative). Luật tổng hợp truyền `SYSTEM_SUBJECT` ('') tường minh.
    op.add_column(
        TABLE,
        sa.Column("subject", sa.String(length=64), server_default=sa.text("''"), nullable=False),
    )
    op.alter_column(TABLE, "subject", server_default=None)
    op.drop_constraint(op.f(OLD_KEY), TABLE, type_="unique")
    op.create_unique_constraint(op.f(NEW_KEY), TABLE, ["rule_id", "subject", "window_start"])


def downgrade() -> None:
    clashes: int = op.get_bind().execute(
        sa.text(
            f"SELECT count(*) FROM (SELECT 1 FROM {TABLE} GROUP BY rule_id, window_start "
            "HAVING count(*) > 1) AS d"
        )
    ).scalar_one()
    if clashes:
        raise RuntimeError(
            f"Không hạ được migration 0004: {TABLE} có {clashes} cặp (rule_id, window_start) trùng "
            "khác subject — khoá cũ không chứa nổi. Giữ DB ở 0004, hoặc dựng lại DB trống."
        )
    op.drop_constraint(op.f(NEW_KEY), TABLE, type_="unique")
    op.create_unique_constraint(op.f(OLD_KEY), TABLE, ["rule_id", "window_start"])
    op.drop_column(TABLE, "subject")
