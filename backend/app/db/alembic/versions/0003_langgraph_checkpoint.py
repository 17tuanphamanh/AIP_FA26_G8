"""langgraph checkpoint: tao bang bang PostgresSaver.setup, grant CRUD cho app_rw

P7 mục 3: bảng checkpoint do `checkpointer.setup()` tạo, chạy dưới `app_migrate` lúc migration;
`app_rw` có CRUD. App (role app_rw) KHÔNG gọi `setup()`.

`setup()` có `CREATE INDEX CONCURRENTLY` → không chạy được trong transaction của Alembic: mở kết nối
psycopg autocommit RIÊNG bằng cùng URL (role app_migrate). Chỉ hỗ trợ chế độ online.

Khoá phiên bản schema: `KNOWN_CHECKPOINT_MIGRATIONS` = số migration của langgraph-checkpoint-postgres
lúc viết file này. Nâng thư viện mà số này đổi → test đỏ ("cần migration Alembic mới"): viết migration
mới gọi lại `setup()` (nó tự chạy phần còn thiếu theo `checkpoint_migrations`), đừng sửa file này.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import psycopg
from alembic import op
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKPOINT_TABLES = ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes")
KNOWN_CHECKPOINT_MIGRATIONS = 10  # langgraph-checkpoint-postgres 3.1.2


def upgrade() -> None:
    url = op.get_bind().engine.url.set(drivername="postgresql")
    dsn = url.render_as_string(hide_password=False)
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        PostgresSaver(conn).setup()
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(CHECKPOINT_TABLES)} TO app_rw")


def downgrade() -> None:
    for table in reversed(CHECKPOINT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
