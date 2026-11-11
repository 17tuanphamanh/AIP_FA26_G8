"""Migration 0016 (bn-a, 08/11 — dời từ 0015 sang 0016 ngày 09/11, nối sau 0015 `it_help` của lô Q1) trên Postgres 16 thật (test viết trước, DỪNG 1; TA chạy).

Hợp đồng (PLAN bn-a mục "Migration 0015", nay là 0016):
- S1 `transaction_log` append-only: `app_rw` chỉ SELECT, INSERT (REVOKE UPDATE, DELETE, TRUNCATE); trigger `transaction_log_append_only`
  (BEFORE UPDATE OR DELETE, FOR EACH ROW) + `transaction_log_no_truncate` (BEFORE TRUNCATE, FOR EACH STATEMENT) dùng `forbid_mutation()`
  như `audit_logs` — chặn cả role owner (`app_migrate`).
- S2 trigger `tickets_final_state_once` (BEFORE UPDATE OF final_state): `OLD.final_state IS NOT NULL AND NEW.final_state IS DISTINCT FROM
  OLD.final_state` → lỗi. NULL → giá trị: được (`finalize_once`); cột khác (`close_reason` L2 đóng) khi `final_state` đã có: được.
- S4 chỉ mục từng phần `ix_approvals_pending_deadline` ON approvals(deadline) WHERE status = 'pending'.
- A4 cột `users.mfa_last_step BIGINT NULL`.
- (chờ ĐP) `security_events.event_type` thêm `retention_run`.
- Lên 0016 → xuống 0015 → lên 0016: xuống trả đúng quyền cũ (`app_rw` lại có UPDATE/DELETE `transaction_log`), bỏ trigger/chỉ mục/cột.
Mỗi test một database riêng (`fresh_database`).
"""

from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from tests.integration.pg import PgUrls, alembic_config, fresh_database

PRIVS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")


def _scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _state(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rw = {p: conn.execute(text("SELECT has_table_privilege('app_rw', 'transaction_log', :p)"), {"p": p}).scalar()
              for p in PRIVS}  # fmt: skip
        tx_triggers: set[str] = set(conn.execute(text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = 'public.transaction_log'::regclass"
        )).scalars())  # fmt: skip
        ticket_triggers: set[str] = set(conn.execute(text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = 'public.tickets'::regclass"
        )).scalars())  # fmt: skip
        index = conn.execute(text(
            "SELECT pg_get_indexdef(indexrelid) FROM pg_index WHERE indexrelid = to_regclass('public.ix_approvals_pending_deadline')"
        )).scalar()  # fmt: skip
        col = conn.execute(text(
            "SELECT data_type || '/' || is_nullable FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'users' AND column_name = 'mfa_last_step'"
        )).scalar()  # fmt: skip
    return {"rw": rw, "tx_triggers": tx_triggers, "ticket_triggers": ticket_triggers, "index": index, "col": col}


def test_0016_up_down_up(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        owner = create_engine(db.role("app_migrate"))
        try:
            command.upgrade(cfg, "0016")
            assert _scalar(owner, "SELECT version_num FROM alembic_version") == "0016"
            up = _state(owner)
            assert up["rw"] == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False}
            assert up["tx_triggers"] == {"transaction_log_append_only", "transaction_log_no_truncate"}
            assert "tickets_final_state_once" in up["ticket_triggers"]
            assert up["index"] is not None and "(deadline)" in up["index"] and "WHERE" in up["index"]
            assert "'pending'" in up["index"]
            assert up["col"] == "bigint/YES"
            command.downgrade(cfg, "0015")
            down = _state(owner)
            assert down["rw"] == {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": True, "TRUNCATE": False}  # như 0001
            assert down["tx_triggers"] == set()
            assert "tickets_final_state_once" not in down["ticket_triggers"]
            assert (down["index"], down["col"]) == (None, None)
            assert _scalar(owner, "SELECT count(*) FROM pg_proc WHERE proname = 'forbid_mutation'") == 1  # của 0001 — không bị xoá
            command.upgrade(cfg, "0016")
            assert _state(owner) == up
        finally:
            owner.dispose()


def _seed(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('nv-15', 'nv.15', 'employee')"))
        conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
                          "VALUES ('t-15', 'nv-15', 'employee', 'x')"))  # fmt: skip


def test_0016_transaction_log_insert_only_for_rw_and_owner(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw, owner = create_engine(db.role("app_rw")), create_engine(db.role("app_migrate"))
        try:
            _seed(rw)
            with rw.begin() as conn:
                conn.execute(text("INSERT INTO transaction_log (ticket_id, turn_id, step_name, status) "
                                  "VALUES ('t-15', 'T1', 'renew_vpn_cert', 'begun')"))  # fmt: skip
            for engine in (rw, owner):  # rw: thiếu quyền; owner: trigger
                for sql in ("UPDATE transaction_log SET status = 'undone'", "DELETE FROM transaction_log",
                            "TRUNCATE transaction_log"):  # fmt: skip
                    with pytest.raises(DBAPIError), engine.begin() as conn:
                        conn.execute(text(sql))
            assert _scalar(rw, "SELECT count(*) FROM transaction_log WHERE status = 'begun'") == 1
        finally:
            rw.dispose()
            owner.dispose()


def test_0016_final_state_written_once(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw = create_engine(db.role("app_rw"))
        try:
            _seed(rw)
            with rw.begin() as conn:  # NULL → giá trị: đường `finalize_once`
                conn.execute(text("UPDATE tickets SET final_state = 'S_ESCALATED', exit_code = 'E5', closed_at = now() "
                                  "WHERE ticket_id = 't-15' AND final_state IS NULL"))  # fmt: skip
            with rw.begin() as conn:  # cột khác khi đã có final_state: L2 đóng escalation ghi close_reason — vẫn được
                conn.execute(text("UPDATE tickets SET close_reason = 'resolved_after_escalation' WHERE ticket_id = 't-15'"))
            with rw.begin() as conn:  # gán lại CÙNG giá trị: không đổi → được (finalize_once chạy lại không ghi gì vì WHERE IS NULL)
                conn.execute(text("UPDATE tickets SET final_state = 'S_ESCALATED' WHERE ticket_id = 't-15'"))
            for new in ("'S_RESOLVED'", "NULL"):
                with pytest.raises(DBAPIError, match="final_state"), rw.begin() as conn:
                    conn.execute(text(f"UPDATE tickets SET final_state = {new} WHERE ticket_id = 't-15'"))
            assert _scalar(rw, "SELECT final_state FROM tickets WHERE ticket_id = 't-15'") == "S_ESCALATED"
        finally:
            rw.dispose()


def test_0016_pending_deadline_index_used_by_scan(pg: PgUrls) -> None:
    """S4: truy vấn quét hạn phiếu (`status='pending' AND deadline <= :now`) CÓ THỂ dùng chỉ mục từng phần (planner chọn khi bảng
    lớn — ở đây chỉ kiểm chỉ mục khớp điều kiện bằng `enable_seqscan = off`)."""
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        owner = create_engine(db.role("app_migrate"))
        try:
            with owner.connect() as conn:
                conn.execute(text("SET enable_seqscan = off"))
                plan = "\n".join(r[0] for r in conn.execute(text(
                    "EXPLAIN SELECT approval_id FROM approvals WHERE status = 'pending' AND deadline <= now()"
                )))  # fmt: skip
            assert "ix_approvals_pending_deadline" in plan
        finally:
            owner.dispose()
