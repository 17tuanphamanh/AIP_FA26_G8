"""transaction_log chi ghi them, khoa final_state, chi muc phieu cho, chong dung lai totp, su kien retention_run

Lô Q7 (hợp đồng bn-a 08/11, ĐP chốt; số dời 0015 → 0016 ngày 09/11 vì 0015 thuộc lô Q1 `it_help`). Test viết trước:
`unit/test_migration_0016_static.py`, `integration/test_migration_0016.py`, `integration/test_txlog_pg.py` (S1),
`integration/test_retention_pg.py` (`retention_run`), `unit/test_auth_totp_replay.py` + `unit/auth_store_contract.py` (A4).

- S1 `transaction_log` append-only — bằng chứng "có thể đã ghi" (`begun`) của B17 không sửa/xoá được: REVOKE UPDATE, DELETE, TRUNCATE khỏi
  `app_rw` + trigger `forbid_mutation()` (của 0001) như `audit_logs` — chặn cả owner. Code chỉ INSERT (`executor/txlog.SqlTxLog._insert`).
- S2 trigger `tickets_final_state_once`: `final_state` đã có giá trị thì không đổi sang giá trị khác/NULL. NULL → giá trị (`finalize_once`) và
  cột khác (`close_reason` khi L2 đóng) vẫn ghi được.
- S4 chỉ mục từng phần `ix_approvals_pending_deadline` cho câu quét hạn phiếu của worker.
- A4 `users.mfa_last_step BIGINT NULL`: bước TOTP cuối đã nhận — mã cùng bước/bước cũ hơn bị từ chối (`otp_replayed`).
- `security_events.event_type` thêm `retention_run` (job hạn giữ ghi một dòng mỗi lần chạy; ĐP chốt Q5 của bn-a).

Downgrade: trả quyền cũ của 0001 (`app_rw` lại có UPDATE, DELETE trên `transaction_log`), bỏ trigger/hàm/chỉ mục/cột. Dừng nếu đã có dòng
`retention_run` (`security_events` append-only, không xoá được để siết CHECK lại — khuôn 0002/0010). Danh sách giá trị viết tĩnh.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TXLOG = "transaction_log"
EVENTS = "security_events"
EVENTS_CHECK = "ck_security_events_event_type"
OLD_EVENT_TYPES = (
    "login_success", "login_failed", "account_locked", "logout", "token_refreshed",
    "refresh_reuse_detected", "session_revoked", "permission_denied", "role_changed",
    "mfa_failed", "policy_saved", "injection_detected", "privacy_secret_redacted",
    "mfa_enrolled", "mfa_reset", "rate_limited",
)  # fmt: skip
NEW_EVENT_TYPES = ("retention_run",)


def _replace_events_check(values: Sequence[str]) -> None:
    op.drop_constraint(op.f(EVENTS_CHECK), EVENTS, type_="check")
    op.create_check_constraint(op.f(EVENTS_CHECK), EVENTS, "event_type IN (" + ", ".join(f"'{v}'" for v in values) + ")")


def upgrade() -> None:
    # S1 — như 0001 làm với audit_logs/security_events
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON transaction_log FROM app_rw")
    op.execute(
        "CREATE TRIGGER transaction_log_append_only BEFORE UPDATE OR DELETE ON transaction_log "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER transaction_log_no_truncate BEFORE TRUNCATE ON transaction_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"
    )
    # S2
    op.execute(
        "CREATE FUNCTION forbid_final_state_change() RETURNS trigger AS $$ "
        "BEGIN "
        "IF OLD.final_state IS NOT NULL AND NEW.final_state IS DISTINCT FROM OLD.final_state THEN "
        "RAISE EXCEPTION 'tickets.final_state đã chốt (%), không đổi được', OLD.final_state; "
        "END IF; "
        "RETURN NEW; "
        "END $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER tickets_final_state_once BEFORE UPDATE OF final_state ON tickets "
        "FOR EACH ROW EXECUTE FUNCTION forbid_final_state_change()"
    )
    # S4
    op.create_index(
        "ix_approvals_pending_deadline", "approvals", ["deadline"], postgresql_where=sa.text("status = 'pending'")
    )
    # A4
    op.add_column("users", sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
    # sự kiện retention_run
    _replace_events_check((*OLD_EVENT_TYPES, *NEW_EVENT_TYPES))


def downgrade() -> None:
    placeholders = ", ".join(f"'{v}'" for v in NEW_EVENT_TYPES)
    count: int = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {EVENTS} WHERE event_type IN ({placeholders})")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Không hạ được migration 0016: {EVENTS} đã có {count} dòng {'/'.join(NEW_EVENT_TYPES)}. "
            "Bảng append-only nên không xoá được — giữ DB ở 0016, hoặc dựng lại DB trống."
        )
    _replace_events_check(OLD_EVENT_TYPES)
    op.drop_column("users", "mfa_last_step")
    op.drop_index("ix_approvals_pending_deadline", table_name="approvals")
    op.execute("DROP TRIGGER IF EXISTS tickets_final_state_once ON tickets")
    op.execute("DROP FUNCTION IF EXISTS forbid_final_state_change()")
    op.execute("DROP TRIGGER IF EXISTS transaction_log_no_truncate ON transaction_log")
    op.execute("DROP TRIGGER IF EXISTS transaction_log_append_only ON transaction_log")
    op.execute("GRANT UPDATE, DELETE ON transaction_log TO app_rw")  # trả quyền của 0001 (TRUNCATE chưa từng cấp)
