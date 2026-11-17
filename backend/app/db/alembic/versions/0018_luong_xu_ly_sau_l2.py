"""luong xu ly sau khi chuyen IT: nhan ca, chuyen cap 3, loi nhan cho nguoi dung

D-99 (17/11/2026, Tuấn Anh chốt phần 1–5, L3 = Trưởng bộ phận IT): bảng `escalations` thêm cột cho vòng nghiệp vụ nhận ca → xử lý /
chuyển cấp 3 → đóng có lời nhắn. Chỉ thêm cột NULL được (hoặc có mặc định) — dòng cũ hợp lệ ngay, không cần chép dữ liệu.

- `assigned_at` timestamptz NULL: lúc người xử lý bấm "Nhận ca" (`assigned_to` có từ 0001, nay mới được ghi). CHECK hai cột cùng NULL
  hoặc cùng có giá trị.
- `tier` smallint NOT NULL DEFAULT 2, CHECK IN (2, 3): cấp đang giữ ca. 3 = đã chuyển lên Trưởng bộ phận IT (`raise_target`
  `it_manager`: an ninh, ngoại lệ chính sách) hoặc bộ phận chuyên trách / nhà cung cấp (`vendor`: phần cứng, bản quyền) — ca cấp 3 hiện ở
  hàng đợi của Trưởng IT.
- `raised_at`, `raised_by` (FK users), `raise_target` CHECK IN ('it_manager', 'vendor'), `raise_note` text (ĐÃ che, 1–1000 ký tự):
  CHECK cả bốn cột có giá trị ⇔ `tier = 3`.
- `user_message` text NULL, CHECK 1–500 ký tự: lời nhắn cho NGƯỜI DÙNG khi đóng ca (đã che + qua cổng tin trả lời) — tách khỏi
  `close_note` (ghi chú nội bộ cho IT).

Không đổi quyền: `app_rw` đã có SELECT/INSERT/UPDATE trên `escalations` từ 0001 (quyền theo bảng, không theo cột). View `v_l2_queue`
(0008/0013) liệt kê cột tĩnh nên không đổi.

Downgrade: bỏ CHECK rồi bỏ cột (ngược thứ tự thêm). SQL và danh sách giá trị viết tĩnh — migration không đổi theo code.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "escalations"
RAISE_TARGETS = ("it_manager", "vendor")
# (tên CHECK không tiền tố — `op.f` thêm `ck_escalations_` theo quy ước đặt tên của metadata, như 0013)
CHECKS: tuple[tuple[str, str], ...] = (
    ("ck_escalations_tier", "tier IN (2, 3)"),
    ("ck_escalations_assigned_pair", "(assigned_to IS NULL) = (assigned_at IS NULL)"),
    (
        "ck_escalations_raise_target",
        "raise_target IS NULL OR raise_target IN ('it_manager', 'vendor')",
    ),
    (
        "ck_escalations_raise_note_len",
        "raise_note IS NULL OR char_length(raise_note) BETWEEN 1 AND 1000",
    ),
    (
        "ck_escalations_raised_iff_tier3",
        "(tier = 3) = (raised_at IS NOT NULL AND raised_by IS NOT NULL AND raise_target IS NOT NULL AND raise_note IS NOT NULL)",
    ),
    (
        "ck_escalations_user_message_len",
        "user_message IS NULL OR char_length(user_message) BETWEEN 1 AND 500",
    ),
)
RAISED_BY_FK = "fk_escalations_raised_by_users"


def upgrade() -> None:
    op.add_column(
        TABLE, sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        TABLE,
        sa.Column(
            "tier", sa.SmallInteger(), nullable=False, server_default=sa.text("2")
        ),
    )
    op.add_column(
        TABLE, sa.Column("raised_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(TABLE, sa.Column("raised_by", sa.String(length=64), nullable=True))
    op.add_column(TABLE, sa.Column("raise_target", sa.String(length=16), nullable=True))
    op.add_column(TABLE, sa.Column("raise_note", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("user_message", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f(RAISED_BY_FK), TABLE, "users", ["raised_by"], ["user_id"]
    )
    for name, rule in CHECKS:
        op.create_check_constraint(op.f(name), TABLE, rule)


def downgrade() -> None:
    for name, _ in reversed(CHECKS):
        op.drop_constraint(op.f(name), TABLE, type_="check")
    op.drop_constraint(op.f(RAISED_BY_FK), TABLE, type_="foreignkey")
    for column in (
        "user_message",
        "raise_note",
        "raise_target",
        "raised_by",
        "raised_at",
        "tier",
        "assigned_at",
    ):
        op.drop_column(TABLE, column)
