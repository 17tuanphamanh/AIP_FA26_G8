"""Migration 0015 (lô Q12 `it_help`, ĐP 09/11) trên Postgres 16 thật (test viết trước, DỪNG 1 phần 2; chờ CI / TA chạy).

- Lên 0015: `tickets.intent`, `audit_logs.intent` nhận `it_help`; `policy_rules` giữ 4 loại; giá trị lạ vẫn bị CHECK chặn.
- Ticket ghi `intent = 'it_help'` được (B20 ghi `tickets.intent` từ state).
- Xuống 0014 khi CHƯA có dòng `it_help` → CHECK về 4 loại; lên lại 0015 → như lần đầu.
- Xuống 0014 khi ĐÃ có dòng `it_help` → `RuntimeError` (khuôn 0002; chấp nhận, PLAN mục 21: `audit_logs` append-only nên không xoá dòng để hạ).
"""

from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from tests.integration.pg import PgUrls, alembic_config, fresh_database

FIVE = "'account', 'vpn', 'software', 'access', 'it_help'"


def _defs(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname IN ('ck_tickets_intent', 'ck_audit_logs_intent', 'ck_policy_rules_intent')"
        )).all()  # fmt: skip
    return {str(r[0]): str(r[1]) for r in rows}


def _seed_user(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('nv-q12', 'nv.q12', 'employee')"))


def _insert_ticket(engine: Engine, ticket_id: str, intent: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, intent) "
                          "VALUES (:t, 'nv-q12', 'employee', 'máy in không in được', :i)"), {"t": ticket_id, "i": intent})  # fmt: skip


def _insert_audit(engine: Engine, ticket_id: str, intent: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO audit_logs (ticket_id, step, event, loop_seq, intent) "
                          "VALUES (:t, 'B3', 'intent_classified', 0, :i)"), {"t": ticket_id, "i": intent})  # fmt: skip


def _scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def test_0015_up_accepts_it_help_on_tickets_and_audit_only(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "0015")
        owner = create_engine(db.role("app_migrate"))
        try:
            assert _scalar(owner, "SELECT version_num FROM alembic_version") == "0015"
            defs = _defs(owner)
            assert FIVE in defs["ck_tickets_intent"].replace("::text", "").replace("::character varying", "")
            assert FIVE in defs["ck_audit_logs_intent"].replace("::text", "").replace("::character varying", "")
            assert "it_help" not in defs["ck_policy_rules_intent"]
            _seed_user(owner)
            _insert_ticket(owner, "t-q12", "it_help")
            _insert_audit(owner, "t-q12", "it_help")
            with pytest.raises(IntegrityError):
                _insert_ticket(owner, "t-q12-x", "printer")  # giá trị lạ vẫn bị chặn
        finally:
            owner.dispose()


def test_0015_down_up_without_it_help_rows(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        owner = create_engine(db.role("app_migrate"))
        try:
            command.upgrade(cfg, "0015")
            up = _defs(owner)
            command.downgrade(cfg, "0014")
            down = _defs(owner)
            assert all("it_help" not in d for d in down.values())
            command.upgrade(cfg, "0015")
            assert _defs(owner) == up
        finally:
            owner.dispose()


def test_0015_downgrade_fails_when_it_help_rows_exist(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "0015")
        owner = create_engine(db.role("app_migrate"))
        try:
            _seed_user(owner)
            _insert_ticket(owner, "t-q12", "it_help")
            with pytest.raises(RuntimeError, match="Không hạ được migration 0015"):
                command.downgrade(cfg, "0014")
            assert _scalar(owner, "SELECT version_num FROM alembic_version") == "0015"
        finally:
            owner.dispose()
