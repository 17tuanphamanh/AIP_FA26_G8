"""ẩn ticket khỏi "Gần đây": bảng thứ 26 ticket_hidden

P3 menu ⋯ "Xóa" (người kiểm thử yêu cầu) = ẨN ticket khỏi danh sách "Gần đây" của CHÍNH người đó — không xoá dữ liệu nghiệp vụ nào.
Ngoại lệ §4 `docs/spec/CLAUDE.md` (bảng ngoài P7): TA/ĐP duyệt 08/11.
- Bảng `ticket_hidden(user_id, ticket_id, hidden_at)`: PK (user_id, ticket_id) — cũng là chỉ mục cho `NOT EXISTS` của `list_own`; FK
  `user_id` → `users`, `ticket_id` → `tickets`; `hidden_at` timestamptz NOT NULL DEFAULT now() (app ghi giờ từ Clock).
- `app_rw` = SELECT, INSERT (ẩn lại = `ON CONFLICT DO NOTHING`, không cần UPDATE; chưa có "bỏ ẩn" → không DELETE — thêm sau bằng migration
  mới). Không cấp `app_monitor`, không trigger, không sequence. KHÔNG đổi bảng `tickets`.

Downgrade: xoá bảng (GRANT mất theo bảng).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HIDDEN = "ticket_hidden"
RW_TABLES = (HIDDEN,)  # quyền app_rw ngoài danh sách của 0001/0010/0012/0013 (test_db_models gộp các danh sách)
RW_PRIVILEGES = "SELECT, INSERT"


def upgrade() -> None:
    op.create_table(
        HIDDEN,
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.String(length=64), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_ticket_hidden_user_id_users")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.ticket_id"], name=op.f("fk_ticket_hidden_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("user_id", "ticket_id", name=op.f("pk_ticket_hidden")),
    )
    op.execute(f"GRANT {RW_PRIVILEGES} ON {HIDDEN} TO app_rw")


def downgrade() -> None:
    op.drop_table(HIDDEN)  # GRANT mất theo bảng
