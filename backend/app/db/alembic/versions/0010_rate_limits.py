"""chong spam: rate_limited, index tickets(requester_id, created_at), bang rate_hits, v_leaf them requester_id

Phase 5 gói 2b (D-54 a; đặc tả `claude/dac-ta-bat-2-model.md` 4.8, 4.10 "Dữ liệu"):
- CHECK `security_events.event_type` thêm `rate_limited` (429 theo tài khoản, mỗi đợt một dòng).
- Index `tickets(requester_id, created_at)` cho bộ đếm ticket mới (đếm `parent_ticket_id IS NULL` trong 10 phút / 1 giờ).
- Bảng thứ 23 `rate_hits` — bộ đếm tin nhắn (`/messages`, `/reply`, `/confirm`). KHÔNG append-only: `app_rw` được `SELECT, INSERT, DELETE`
  (xoá dòng cũ của chính người gửi), không UPDATE; `GRANT USAGE, SELECT` trên sequence của `hit_id` (lệnh GRANT mọi sequence ở `0001`
  không phủ sequence tạo sau). Không cấp `app_monitor`: M9 đọc `rate_limited` ở `security_events`, không đọc bảng này.
- `v_leaf` thêm `requester_id` làm cột CUỐI (cho luật M9 theo người gửi; M9 không đọc thẳng `tickets` — D-30). `CREATE OR REPLACE VIEW`
  thay TOÀN BỘ option của view → phải ghi lại `WITH (security_invoker = true)` (bỏ đi thì view chạy theo quyền chủ view, rào chỉ-đọc của
  `app_monitor` mất). GRANT trên view giữ nguyên. Không sửa file `0008`: danh sách cột mới khai ở đây.

Downgrade: dừng nếu `security_events` đã có dòng `rate_limited` (khuôn `0002`: bảng append-only, không xoá được thì không siết được CHECK)
— kiểm TRƯỚC mọi thay đổi. `CREATE OR REPLACE` không bỏ được cột → xoá 3 view theo thứ tự ngược rồi tạo lại ĐÚNG như `0008` (kèm
`security_invoker` + GRANT `app_monitor`); xoá `rate_hits`, xoá index, CHECK về 15 loại cũ. SQL và danh sách giá trị viết tĩnh — migration
không đổi theo code.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENTS = "security_events"
CONSTRAINT = "ck_security_events_event_type"
OLD_TYPES = (
    "login_success", "login_failed", "account_locked", "logout", "token_refreshed",
    "refresh_reuse_detected", "session_revoked", "permission_denied", "role_changed",
    "mfa_failed", "policy_saved", "injection_detected", "privacy_secret_redacted",
    "mfa_enrolled", "mfa_reset",
)  # fmt: skip
NEW_TYPES = ("rate_limited",)

TICKETS_INDEX = "ix_tickets_requester_created_at"
HITS = "rate_hits"
HITS_INDEX = "ix_rate_hits_user_created_at"
HITS_SEQUENCE = "rate_hits_hit_id_seq"
RW_TABLES = (HITS,)  # quyền app_rw ngoài danh sách của 0001 (test_db_models gộp hai danh sách)
RW_PRIVILEGES = "SELECT, INSERT, DELETE"

# Cột `v_leaf` của 0008 + `requester_id` ở cuối.
LEAF_COLUMNS: tuple[str, ...] = (
    "ticket_id", "parent_ticket_id", "created_at", "closed_at", "final_state", "exit_code", "resolution_path",
    "intent", "redacted_request", "requester_id",
)  # fmt: skip

# Ba view đúng như 0008 (chép tĩnh) — để downgrade tạo lại; thứ tự tạo, xoá theo thứ tự ngược.
VIEWS_0008: tuple[tuple[str, str], ...] = (
    (
        "v_leaf",
        (
            "SELECT t.ticket_id, t.parent_ticket_id, t.created_at, t.closed_at, t.final_state, t.exit_code, t.resolution_path, "
            "t.intent, t.redacted_request FROM tickets t WHERE t.is_parent = false"
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
)


def _replace_check(values: Sequence[str]) -> None:
    op.drop_constraint(op.f(CONSTRAINT), EVENTS, type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), EVENTS, "event_type IN (" + ", ".join(f"'{v}'" for v in values) + ")")


def upgrade() -> None:
    _replace_check((*OLD_TYPES, *NEW_TYPES))
    op.create_index(TICKETS_INDEX, "tickets", ["requester_id", "created_at"], unique=False)
    op.create_table(
        HITS,
        sa.Column("hit_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk_rate_hits_user_id_users")),
        sa.PrimaryKeyConstraint("hit_id", name=op.f("pk_rate_hits")),
    )
    op.create_index(HITS_INDEX, HITS, ["user_id", "created_at"], unique=False)
    op.execute(f"GRANT {RW_PRIVILEGES} ON {HITS} TO app_rw")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {HITS_SEQUENCE} TO app_rw")
    columns = ", ".join(f"t.{c}" for c in LEAF_COLUMNS)
    op.execute(
        f"CREATE OR REPLACE VIEW v_leaf WITH (security_invoker = true) AS SELECT {columns} FROM tickets t WHERE t.is_parent = false"
    )


def downgrade() -> None:
    placeholders = ", ".join(f"'{v}'" for v in NEW_TYPES)
    count: int = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {EVENTS} WHERE event_type IN ({placeholders})")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Không hạ được migration 0010: {EVENTS} đã có {count} dòng {'/'.join(NEW_TYPES)}. "
            "Bảng append-only nên không xoá được — giữ DB ở 0010, hoặc dựng lại DB trống."
        )
    for name, _ in reversed(VIEWS_0008):
        op.execute(f"DROP VIEW IF EXISTS {name}")
    for name, query in VIEWS_0008:
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {query}")
    op.execute(f"GRANT SELECT ON {', '.join(name for name, _ in VIEWS_0008)} TO app_monitor")
    op.drop_index(HITS_INDEX, table_name=HITS)
    op.drop_table(HITS)  # GRANT và sequence mất theo bảng
    op.drop_index(TICKETS_INDEX, table_name="tickets")
    _replace_check(OLD_TYPES)
