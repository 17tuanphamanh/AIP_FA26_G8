"""monitor: 2 chi muc cua M9 (A4) - audit_logs theo exit_code, approvals theo ticket_id

Chọn theo số đo S3b (#11, Q-M9-A4-7, Tuấn Anh duyệt 13/10/2026; 10.000 ticket lá, role `app_monitor`):
- `ix_audit_logs_exit_created_at` — `audit_logs (created_at) WHERE exit_code IS NOT NULL`: cho `TICKET_EXIT_SQL`
  (`monitor/queries/rules_data.py`) của luật 2/4/6/16, chạy mỗi 60 giây, lọc `exit_code = :code AND created_at >= :since`
  và KHÔNG lọc `step` → ba chỉ mục sẵn có của `audit_logs` không dùng được (Seq Scan cả bảng). Chỉ mục MỘT PHẦN: chỉ dòng
  có `exit_code` vào chỉ mục — `audit_logs` chỉ ghi thêm, ghi theo từng bước của mọi ticket, nên phần lớn dòng ghi vào
  không phải cập nhật chỉ mục. Planner dùng được với tham số bind vì `exit_code = $1` (toán tử strict) suy ra
  `exit_code IS NOT NULL`. Số đo: 6,9→0,6 / 5,6→0,2 ms (E0/E7, 24 h), 8,1→2,7 ms (E9/E6, 192 h); 72 kB. Phương án đầy
  đủ `(exit_code, created_at)` nhanh ngang nhưng lớn ~12 lần → không chọn.
- `ix_approvals_ticket` — `approvals (ticket_id)`: phục vụ `NOT EXISTS (… approvals a WHERE a.ticket_id = t.ticket_id)`
  của `automation_rate` (`monitor/queries/business.py`): 500,6→30,4 ms; 64 kB. Chỉ mục sẵn có `ux_approvals_one_pending`
  là một phần (`status = 'pending'`) → không dùng được. Các lượt own (`EXISTS approvals … approver_id`) dùng được chỉ mục
  này khi tắt seqscan, nhưng plan tự nhiên ở S3b chưa chọn nó (kiểm ở `test_monitor_perf_pg.py`, lớp 1).

Không chọn (ghi ở PR): `alerts (created_at DESC, alert_id DESC)` 0,7→0,1 ms, dưới mức nhiễu — xem lại khi bảng lớn;
`llm_calls (span_id)` planner không dùng.

Không `CREATE INDEX CONCURRENTLY` (Q-M9-A4-8): Alembic chạy migration trong transaction; bảng của đồ án nhỏ, khoá SHARE
ngắn; `make up` chạy migration trước khi dựng backend/worker. Hai chỉ mục khai trùng trong `models.py`
(`test_models_match_migration` so `compare_metadata`).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_EXIT_INDEX = "ix_audit_logs_exit_created_at"
APPROVALS_TICKET_INDEX = "ix_approvals_ticket"


def upgrade() -> None:
    op.create_index(
        AUDIT_EXIT_INDEX,
        "audit_logs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("exit_code IS NOT NULL"),
    )
    op.create_index(APPROVALS_TICKET_INDEX, "approvals", ["ticket_id"], unique=False)


def downgrade() -> None:
    op.drop_index(APPROVALS_TICKET_INDEX, table_name="approvals")
    op.drop_index(AUDIT_EXIT_INDEX, table_name="audit_logs")
