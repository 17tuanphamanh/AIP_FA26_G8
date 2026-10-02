"""monitor: 3 view chi doc cua M9 + GRANT app_monitor

View của M9 (P9 §4; kế hoạch M9 4.3, D-30): mọi chỉ số/luật đếm ticket qua `v_leaf` (`is_parent = false`).
- `v_decisions`: quyết định M5 = điểm log 4 = dòng `audit_logs` step `B13/B14` (`graph/nodes/b12_assess.py`). Bản B17
  kiểm lại (step `B17`, quyết định nằm trong `detail`) không đếm. Có `log_id` để "hòa `created_at` → dòng mới hơn".
- `v_l2_queue`: escalation còn mở của lá, xếp theo `exit_code_priority.rank`.

`security_invoker = true`: view chạy theo quyền của NGƯỜI ĐỌC, không theo chủ view (`app_migrate`) → rào chỉ-đọc của
`app_monitor` áp tới tận bảng. View chỉ được đọc 9 bảng `MONITOR_TABLES` của 0001 + `exit_code_priority` (GRANT ở
đây, REVOKE khi downgrade). Cần bảng khác → GRANT theo cột, không GRANT cả bảng. Chỉ mục
`tickets(created_at) WHERE is_parent = false` đã có từ 0001 (`ix_tickets_leaf`) → không thêm.

Cột liệt kê tường minh (không `SELECT *`), chỉ cột M9 dùng — danh sách ở `*_COLUMNS` dưới đây là chỗ duy nhất. Đổi/xoá
cột nguồn hoặc cần cột mới → migration sau DROP rồi CREATE lại view. SQL viết tĩnh: migration không đổi theo code.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Cột của `tickets` mà M9 đọc: cửa sổ (`created_at`), mẫu số (`final_state`), chỉ số 5.1 (`exit_code`,
# `resolution_path`, `intent`, `redacted_request` cho ca E3), luật 2/4/6/16 (`exit_code`), drift (`intent`), chỉ số
# nhiều ý 5.2 (`parent_ticket_id`, `closed_at`).
LEAF_COLUMNS: tuple[str, ...] = (
    "ticket_id", "parent_ticket_id", "created_at", "closed_at", "final_state", "exit_code", "resolution_path",
    "intent", "redacted_request",
)  # fmt: skip
# Điểm log 4 (P9 §4) + khóa chính `log_id`.
DECISION_COLUMNS: tuple[str, ...] = (
    "log_id", "ticket_id", "created_at", "decided_by", "policy_decision", "risk_level", "matched_rule_id",
    "calibrated_prob",
)  # fmt: skip
# Hàng đợi L2 (P9 §5: "có `reason_detail`") + `rank` của `exit_code_priority`.
L2_QUEUE_COLUMNS: tuple[str, ...] = ("escalation_id", "ticket_id", "exit_code", "reason_detail", "created_at")
MONITOR_EXTRA_TABLE = "exit_code_priority"


def _cols(alias: str, columns: tuple[str, ...]) -> str:
    return ", ".join(f"{alias}.{c}" for c in columns)


# Thứ tự tạo (view sau dựa vào view trước); downgrade xoá theo thứ tự ngược.
VIEWS: tuple[tuple[str, str], ...] = (
    ("v_leaf", f"SELECT {_cols('t', LEAF_COLUMNS)} FROM tickets t WHERE t.is_parent = false"),
    (
        "v_decisions",
        (
            f"SELECT {_cols('a', DECISION_COLUMNS)} FROM audit_logs a JOIN v_leaf t ON t.ticket_id = a.ticket_id "
            "WHERE a.step = 'B13/B14'"
        ),
    ),
    (
        "v_l2_queue",
        (
            f"SELECT {_cols('e', L2_QUEUE_COLUMNS)}, p.rank FROM escalations e "
            "JOIN exit_code_priority p ON p.exit_code = e.exit_code JOIN v_leaf t ON t.ticket_id = e.ticket_id "
            "WHERE e.closed_at IS NULL ORDER BY p.rank, e.created_at"
        ),
    ),
)


def upgrade() -> None:
    for name, query in VIEWS:
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {query}")
    op.execute(f"GRANT SELECT ON {', '.join(name for name, _ in VIEWS)} TO app_monitor")
    op.execute(f"GRANT SELECT ON {MONITOR_EXTRA_TABLE} TO app_monitor")


def downgrade() -> None:
    # GRANT trên view mất theo view; GRANT trên bảng phải REVOKE để quyền về đúng như 0007.
    op.execute(f"REVOKE SELECT ON {MONITOR_EXTRA_TABLE} FROM app_monitor")
    for name, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {name}")
