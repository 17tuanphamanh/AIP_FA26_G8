"""Migration 0014 (P3 menu ⋯ "Xóa" = ẩn khỏi "Gần đây") trên Postgres 16 thật.

- Lên 0014 → xuống 0013 → lên 0014: bảng `ticket_hidden(user_id, ticket_id, hidden_at)`, PK (user_id, ticket_id), FK → `tickets`,
  `users`; `app_rw` = SELECT, INSERT (không UPDATE/DELETE/TRUNCATE); `app_monitor` không đọc; bảng `tickets` không đổi cột nào.
- Ràng buộc: ticket không có → FK từ chối; trùng (user, ticket) → PK từ chối, `ON CONFLICT DO NOTHING` chạy được bằng quyền `app_rw`.
Mỗi test một database riêng (`fresh_database`)."""

from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from tests.integration.pg import PgUrls, alembic_config, fresh_database

TABLE = "ticket_hidden"


def _state(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        table = conn.execute(text(f"SELECT to_regclass('public.{TABLE}')")).scalar()
        cols = [tuple(r) for r in conn.execute(text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"), {"t": TABLE})]  # fmt: skip
        pk: list[str] = list(conn.execute(text(
            "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = to_regclass(:t) AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)"
        ), {"t": f"public.{TABLE}"}).scalars()) if table else []  # fmt: skip
        fks = {(r[0], r[1]) for r in conn.execute(text(
            "SELECT kcu.column_name, ccu.table_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name "
            "WHERE tc.table_name = :t AND tc.constraint_type = 'FOREIGN KEY'"), {"t": TABLE})}  # fmt: skip
        rw = {p: conn.execute(text("SELECT has_table_privilege('app_rw', :t, :p)"), {"t": TABLE, "p": p}).scalar()
              for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")} if table else {}  # fmt: skip
        monitor = conn.execute(text("SELECT has_table_privilege('app_monitor', :t, 'SELECT')"), {"t": TABLE}).scalar() \
            if table else None  # fmt: skip
        triggers: set[str] = set(conn.execute(text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid = to_regclass(:t)"), {"t": f"public.{TABLE}"}
        ).scalars()) if table else set()  # fmt: skip
        tickets = [tuple(r) for r in conn.execute(text(
            "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'tickets' ORDER BY ordinal_position"))]  # fmt: skip
    return {"table": table is not None, "cols": cols, "pk": pk, "fks": fks, "rw": rw, "monitor": monitor, "triggers": triggers,
            "tickets": tickets}  # fmt: skip


def test_0014_up_down_up_and_tickets_unchanged(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        owner = create_engine(db.role("app_migrate"))
        try:
            command.upgrade(cfg, "0013")
            at_0013 = _state(owner)
            assert not at_0013["table"]
            command.upgrade(cfg, "0014")
            with owner.connect() as conn:
                assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0014"
            up = _state(owner)
            assert up == {
                "table": True,
                "cols": [("user_id", "character varying", "NO"), ("ticket_id", "character varying", "NO"),
                         ("hidden_at", "timestamp with time zone", "NO")],
                "pk": ["user_id", "ticket_id"],
                "fks": {("user_id", "users"), ("ticket_id", "tickets")},
                "rw": {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False},
                "monitor": False,
                "triggers": set(),
                "tickets": at_0013["tickets"],  # không đổi bảng tickets
            }  # fmt: skip
            command.downgrade(cfg, "0013")
            assert _state(owner) == at_0013
            command.upgrade(cfg, "0014")
            assert _state(owner) == up
        finally:
            owner.dispose()


def test_0014_constraints_with_app_rw(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw = create_engine(db.role("app_rw"))
        try:
            with rw.begin() as conn:
                conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('nv-h', 'nv.h', 'employee')"))
                conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
                                  "VALUES ('t-h', 'nv-h', 'employee', 'x')"))  # fmt: skip
                conn.execute(text(f"INSERT INTO {TABLE} (user_id, ticket_id) VALUES ('nv-h', 't-h')"))
                conn.execute(text(f"INSERT INTO {TABLE} (user_id, ticket_id) VALUES ('nv-h', 't-h') ON CONFLICT DO NOTHING"))
                assert conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar() == 1
                assert conn.execute(text(f"SELECT hidden_at IS NOT NULL FROM {TABLE}")).scalar() is True  # mặc định now()
            with pytest.raises(DBAPIError, match="pk_ticket_hidden"), rw.begin() as conn:
                conn.execute(text(f"INSERT INTO {TABLE} (user_id, ticket_id) VALUES ('nv-h', 't-h')"))
            with pytest.raises(DBAPIError, match="fk_ticket_hidden_ticket_id_tickets"), rw.begin() as conn:
                conn.execute(text(f"INSERT INTO {TABLE} (user_id, ticket_id) VALUES ('nv-h', 't-khong-co')"))
            with pytest.raises(DBAPIError, match="fk_ticket_hidden_user_id_users"), rw.begin() as conn:
                conn.execute(text(f"INSERT INTO {TABLE} (user_id, ticket_id) VALUES ('u-khong-co', 't-h')"))
            for stmt in (f"UPDATE {TABLE} SET hidden_at = now()", f"DELETE FROM {TABLE}"):
                with pytest.raises(DBAPIError, match="permission denied"), rw.begin() as conn:
                    conn.execute(text(stmt))
        finally:
            rw.dispose()
