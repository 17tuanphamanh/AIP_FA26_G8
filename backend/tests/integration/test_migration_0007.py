"""Migration 0007 (thiết kế Phase 3 mục 8.2): CHECK `side_effects.kind` nhận `security_event`; hạ về 0006 khi chưa
có dòng loại đó; có dòng thì hạ bị từ chối (xoá đi là mất idempotent). Mỗi test một database riêng."""

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from tests.integration.pg import PgUrls, alembic_config, fresh_database


def _ticket_and_effect(rw: Engine, kind: str, key: str) -> None:
    with rw.begin() as conn:
        conn.execute(text(
            "INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, created_at) "
            "VALUES (:t, 'nv-mig', 'employee', 'x', now()) ON CONFLICT DO NOTHING"), {"t": "tk-mig"})  # fmt: skip
        conn.execute(text(
            "INSERT INTO side_effects (effect_key, ticket_id, kind, step, turn_id) VALUES (:k, 'tk-mig', :kind, 'B2', 'T1')"
        ), {"k": key, "kind": kind})  # fmt: skip


def _user(rw: Engine) -> None:
    with rw.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (user_id, username, role, token_version) VALUES ('nv-mig', 'nv.mig', 'employee', 0) "
            "ON CONFLICT DO NOTHING"))  # fmt: skip


def test_0007_security_event_kind_and_down_up(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "0006")
        rw = create_engine(db.role("app_rw"))
        try:
            _user(rw)
            with pytest.raises(IntegrityError, match="ck_side_effects_kind"):
                _ticket_and_effect(rw, "security_event", "a" * 64)
            command.upgrade(cfg, "head")
            _ticket_and_effect(rw, "notify_user", "b" * 64)
            command.downgrade(cfg, "0006")  # chưa có dòng security_event → hạ được
            command.upgrade(cfg, "head")
            _ticket_and_effect(rw, "security_event", "c" * 64)
            with pytest.raises(IntegrityError, match="ck_side_effects_kind"):
                _ticket_and_effect(rw, "khong_co", "d" * 64)
            with pytest.raises(RuntimeError, match="Không hạ được migration 0007"):
                command.downgrade(cfg, "0006")
        finally:
            rw.dispose()
