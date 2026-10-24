"""notify-email: users.email (dong bo tu AD) + bang email_outbox (hang doi email, worker gui qua SMTP)

- `users.email` VARCHAR(254) NULL: `auth/store.upsert_user` chép trường `email` của AD (đã kiểm dạng); AD không có → NULL. `app_rw`
  đã có CRUD cả bảng `users` từ `0001` (quyền mức bảng phủ cột mới). `users` không thuộc `MONITOR_TABLES` → `app_monitor` không
  thấy cột này.
- Bảng thứ 24 `email_outbox`: một dòng mỗi email (`effect_key` UNIQUE — chạy lại effect không thêm dòng). KHÔNG lưu địa chỉ người
  nhận (worker nối `users.email` lúc gửi). `status` pending|sent|failed|skipped, `kind` 7 loại (tĩnh ở đây, model khớp — test đối chiếu).
  `next_attempt_at`: lịch thử lại (backoff) + hạn giữ chỗ của lượt gửi; chỉ mục một phần trên dòng `pending`.
- Quyền (khuôn `0010`): `app_rw` = `SELECT, INSERT, UPDATE` — KHÔNG DELETE (lịch sử gửi giữ lại); `GRANT USAGE, SELECT` trên sequence
  của `id` (lệnh GRANT mọi sequence ở `0001` không phủ sequence tạo sau). Không cấp `app_monitor` (body là nội dung tin). Không
  trigger append-only: worker phải đổi `status`/`attempts`.

Downgrade: xoá `email_outbox` (GRANT, sequence, chỉ mục mất theo bảng) rồi xoá cột `users.email` (đồng bộ lại được ở lần đăng nhập
sau khi nâng lại). SQL và danh sách giá trị viết tĩnh — migration không đổi theo code.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OUTBOX = "email_outbox"
OUTBOX_SEQUENCE = "email_outbox_id_seq"
RW_TABLES = (OUTBOX,)  # quyền app_rw ngoài danh sách của 0001/0010 (test_db_models gộp các danh sách)
RW_PRIVILEGES = "SELECT, INSERT, UPDATE"
STATUSES = ("pending", "sent", "failed", "skipped")
KINDS = (
    "answer", "rejection", "result", "escalation", "approval_new", "approval_reminder_1", "approval_reminder_2",
)  # fmt: skip
DUE_INDEX = "ix_email_outbox_due"
CREATED_INDEX = "ix_email_outbox_created_at"


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.create_table(
        OUTBOX,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticket_id", sa.String(length=64), nullable=True),
        sa.Column("recipient_user_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=8), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_class", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effect_key", sa.String(length=128), nullable=False),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_email_outbox_status")),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f("ck_email_outbox_kind")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_email_outbox_attempts_nonneg")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.ticket_id"], name=op.f("fk_email_outbox_ticket_id_tickets")),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.user_id"], name=op.f("fk_email_outbox_recipient_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
        sa.UniqueConstraint("effect_key", name=op.f("uq_email_outbox_effect_key")),
    )
    op.create_index(DUE_INDEX, OUTBOX, ["next_attempt_at"], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_index(CREATED_INDEX, OUTBOX, ["created_at"], unique=False)
    op.execute(f"GRANT {RW_PRIVILEGES} ON {OUTBOX} TO app_rw")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {OUTBOX_SEQUENCE} TO app_rw")


def downgrade() -> None:
    op.drop_index(CREATED_INDEX, table_name=OUTBOX)
    op.drop_index(DUE_INDEX, table_name=OUTBOX)
    op.drop_table(OUTBOX)  # GRANT và sequence mất theo bảng
    op.drop_column("users", "email")
