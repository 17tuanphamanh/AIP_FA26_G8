"""kb: content_sha256, chunk_count, eval_status, index duy nhat ban hien hanh

Thiết kế Phase 3 mục 5.10 + chốt Q-3b-5 (người duyệt 27/09/2026):

- `kb_documents.content_sha256` (3-Q4): sửa nội dung tài liệu mà không tăng `version` thì `make ingest` dừng —
  so sha của thân bài + front matter với dòng đã ghi. NULL cho dòng cũ (chưa có dòng nào).
- `kb_versions.chunk_count` (3-Q16): số đoạn của bản đã nạp; ghi bù DB sau khi chết giữa đổi alias và ghi DB
  đọc lại từ metadata collection.
- `kb_versions.eval_status` (3-Q15): `unevaluated` khi nạp không có bộ kiểm tra (`--allow-unevaluated`, chỉ
  dev/test) — số đo NULL; mặc định `evaluated`.
- `ux_kb_versions_current`: nhiều nhất MỘT dòng `is_current` — index duy nhất một phần dạng cột
  `(is_current) WHERE is_current` như `ux_policy_versions_current` (Q-3b-5, không dùng `((true))`).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("kb_documents", sa.Column("content_sha256", sa.CHAR(length=64), nullable=True))
    op.add_column("kb_versions", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column(
        "kb_versions",
        sa.Column("eval_status", sa.String(length=16), server_default=sa.text("'evaluated'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_kb_versions_eval_status"), "kb_versions", "eval_status IN ('evaluated', 'unevaluated')"
    )
    op.create_index(
        "ux_kb_versions_current", "kb_versions", ["is_current"], unique=True,
        postgresql_where=sa.text("is_current"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_index("ux_kb_versions_current", table_name="kb_versions")
    op.drop_constraint(op.f("ck_kb_versions_eval_status"), "kb_versions", type_="check")
    op.drop_column("kb_versions", "eval_status")
    op.drop_column("kb_versions", "chunk_count")
    op.drop_column("kb_documents", "content_sha256")
