"""chiến lược M5 lúc vận hành (D-67): tickets.strategy/source, bảng m5_strategy_changes, v_leaf thêm 2 cột

- `tickets.strategy` text NULL: chiến lược M5 CHỤP lúc tạo ticket (ticket cũ để NULL; B12 coi NULL là `hybrid`). Không CHECK giá trị:
  tập giá trị hợp lệ nằm ở `risk/strategy.py` (RUNTIME_SELECTABLE / STRATEGIES), migration không chép lại.
- `tickets.source` text NOT NULL DEFAULT 'real', CHECK IN ('real','sim','eval'): `sim` chỉ khi header X-Sim-Run + APP_ENV dev/test;
  `eval` khi EVAL_MODE.
- Bảng thứ 25 `m5_strategy_changes(id, strategy, changed_by, reason, changed_at)` CHỈ GHI THÊM (khuôn `audit_logs` của 0001): trigger
  chặn UPDATE/DELETE (từng dòng) và TRUNCATE (câu lệnh) bằng `forbid_mutation()`; `app_rw` = SELECT, INSERT (+ USAGE, SELECT trên
  sequence của `id` — lệnh GRANT mọi sequence ở `0001` không phủ sequence tạo sau). Không cấp `app_monitor`. Chiến lược hiện hành
  = dòng có `id` lớn nhất; chưa có dòng nào → `hybrid` (ở code, migration không seed).
- `escalations.close_note` text NULL + CHECK (NULL hoặc 1–1000 ký tự) — ĐP bổ sung 26/10 21:15: chỉ thêm cột, việc ghi/đọc thuộc P4.
- `v_leaf` thêm `strategy`, `source` làm cột CUỐI (cho `GET /api/dashboard/strategies`). `CREATE OR REPLACE VIEW` thay TOÀN BỘ option
  của view → ghi lại `WITH (security_invoker = true)`; GRANT trên view giữ nguyên.

Downgrade: `CREATE OR REPLACE` không bỏ được cột → `DROP VIEW v_leaf CASCADE` (kéo theo v_decisions, v_l2_queue, v_child_notices)
rồi tạo lại ĐÚNG như 0012 (SQL chép tĩnh) + GRANT `app_monitor`; xoá bảng `m5_strategy_changes` (trigger, GRANT, sequence mất theo
bảng), CHECK và hai cột của `tickets`, CHECK và cột `escalations.close_note`. SQL và danh sách giá trị viết tĩnh — migration không đổi theo code.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHANGES = "m5_strategy_changes"
CHANGES_SEQUENCE = "m5_strategy_changes_id_seq"
RW_TABLES = (CHANGES,)  # quyền app_rw ngoài danh sách của 0001/0010/0012 (test_db_models gộp các danh sách)
RW_PRIVILEGES = "SELECT, INSERT"
SOURCE_CHECK = "ck_tickets_source"
SOURCES = ("real", "sim", "eval")
CLOSE_NOTE_CHECK = "ck_escalations_close_note_len"
CLOSE_NOTE_RULE = "close_note IS NULL OR char_length(close_note) BETWEEN 1 AND 1000"
MONITOR_ROLE = "app_monitor"

# Cột `v_leaf` của 0010 + `strategy`, `source` ở cuối.
LEAF_COLUMNS_0012: tuple[str, ...] = (
    "ticket_id", "parent_ticket_id", "created_at", "closed_at", "final_state", "exit_code", "resolution_path",
    "intent", "redacted_request", "requester_id",
)  # fmt: skip
LEAF_COLUMNS: tuple[str, ...] = (*LEAF_COLUMNS_0012, "strategy", "source")

# 4 view đúng như 0012 (chép tĩnh) — để downgrade tạo lại; thứ tự tạo (view sau dựa vào view trước), xoá theo thứ tự ngược.
VIEWS_0012: tuple[tuple[str, str], ...] = (
    (
        "v_leaf",
        (
            "SELECT t.ticket_id, t.parent_ticket_id, t.created_at, t.closed_at, t.final_state, t.exit_code, t.resolution_path, "
            "t.intent, t.redacted_request, t.requester_id FROM tickets t WHERE t.is_parent = false"
        ),
    ),
    (
        "v_decisions",
        (
            "SELECT a.log_id, a.ticket_id, a.created_at, a.decided_by, a.policy_decision, a.risk_level, a.matched_rule_id, "
            "a.calibrated_prob FROM audit_logs a JOIN v_leaf t ON t.ticket_id = a.ticket_id WHERE a.step = 'B13/B14'"
        ),
    ),
    (
        "v_l2_queue",
        (
            "SELECT e.escalation_id, e.ticket_id, e.exit_code, e.reason_detail, e.created_at, p.rank FROM escalations e "
            "JOIN exit_code_priority p ON p.exit_code = e.exit_code JOIN v_leaf t ON t.ticket_id = e.ticket_id "
            "WHERE e.closed_at IS NULL ORDER BY p.rank, e.created_at"
        ),
    ),
    (
        "v_child_notices",
        (
            "SELECT n.notice_id, n.parent_ticket_id, n.child_ticket_id, n.created_at, n.delivered_round, n.delivered_at "
            "FROM child_notices n JOIN v_leaf c ON c.ticket_id = n.child_ticket_id"
        ),
    ),
)


def upgrade() -> None:
    op.add_column("tickets", sa.Column("strategy", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("source", sa.Text(), server_default=sa.text("'real'"), nullable=False))
    op.create_check_constraint(
        op.f(SOURCE_CHECK), "tickets", "source IN (" + ", ".join(f"'{v}'" for v in SOURCES) + ")"
    )
    op.add_column("escalations", sa.Column("close_note", sa.Text(), nullable=True))
    op.create_check_constraint(op.f(CLOSE_NOTE_CHECK), "escalations", CLOSE_NOTE_RULE)
    op.create_table(
        CHANGES,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.user_id"], name=op.f("fk_m5_strategy_changes_changed_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_m5_strategy_changes")),
    )
    op.execute(
        f"CREATE TRIGGER {CHANGES}_append_only BEFORE UPDATE OR DELETE ON {CHANGES} "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {CHANGES}_no_truncate BEFORE TRUNCATE ON {CHANGES} "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"
    )
    op.execute(f"GRANT {RW_PRIVILEGES} ON {CHANGES} TO app_rw")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {CHANGES_SEQUENCE} TO app_rw")
    columns = ", ".join(f"t.{c}" for c in LEAF_COLUMNS)
    op.execute(
        f"CREATE OR REPLACE VIEW v_leaf WITH (security_invoker = true) AS SELECT {columns} FROM tickets t WHERE t.is_parent = false"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_leaf CASCADE")  # kéo theo v_decisions, v_l2_queue, v_child_notices
    for name, query in VIEWS_0012:
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {query}")
    op.execute(f"GRANT SELECT ON {', '.join(name for name, _ in VIEWS_0012)} TO {MONITOR_ROLE}")
    op.drop_table(CHANGES)  # trigger, GRANT, sequence mất theo bảng
    op.drop_constraint(op.f(SOURCE_CHECK), "tickets", type_="check")
    op.drop_column("tickets", "source")
    op.drop_column("tickets", "strategy")
    op.drop_constraint(op.f(CLOSE_NOTE_CHECK), "escalations", type_="check")
    op.drop_column("escalations", "close_note")
