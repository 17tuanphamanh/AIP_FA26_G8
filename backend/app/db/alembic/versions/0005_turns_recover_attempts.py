"""turns: them recover_attempts (gioi han phuc hoi luot do dang)

Quyết định 2b-Q6 + trả lời Q-B (người duyệt 26/09/2026): worker tăng `recover_attempts` TRƯỚC khi chạy
lại một lượt dở dang (`UPDATE … SET recover_attempts = recover_attempts + 1 … RETURNING`). Vượt 3 →
ngừng thử: lượt kẹt ở B20 → audit `finalize_failed_permanent` + đóng lượt; kẹt ở node khác → E9 qua B20.

Không đếm bằng span lỗi: process bị giết (OOM/SIGKILL) không kịp ghi span → đếm ra 0 → thử vô hạn.
Bộ đếm nằm trên `turns` (một lượt = một đơn vị phục hồi), tăng trước khi chạy nên process chết giữa
lượt vẫn được tính.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turns",
        sa.Column("recover_attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("turns", "recover_attempts")
