"""Migration 0013 (D-60 — chiến lược M5 lúc vận hành) trên Postgres 16 thật + store SQL (`SqlStrategyStore`, `SqlTicketStore`).

- Lên 0013 → xuống 0012 → lên 0013 (BE chốt 26/10): cột `tickets.strategy`/`source` + CHECK, `escalations.close_note` + CHECK, bảng `m5_strategy_changes` (chỉ ghi thêm,
  quyền `app_rw` SELECT/INSERT, trigger), `v_leaf` thêm 2 cột CUỐI; sau downgrade đủ 4 view (`v_leaf`, `v_decisions`, `v_l2_queue`,
  `v_child_notices`) tồn tại, `security_invoker=true`, và `app_monitor` đọc được cả 4.
- Store: `append` → `current`/`history` (`strategy_from`, mới nhất trước, `truncated`), trùng → `SameStrategy`, `policy_saved` cùng
  transaction; ticket gốc ghi `strategy`/`source`, ticket con kế thừa (`INSERT … SELECT`), CHECK `source` từ chối giá trị lạ.
Mỗi test migration một database riêng (`fresh_database`)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from app.db.m5_strategy import SameStrategy, SqlStrategyStore
from app.db.tickets import NewTicket, SqlTicketStore
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration.pg import PgUrls, alembic_config, fresh_database

VIEWS = ("v_leaf", "v_decisions", "v_l2_queue", "v_child_notices")
LEAF_0012 = [
    "ticket_id", "parent_ticket_id", "created_at", "closed_at", "final_state", "exit_code", "resolution_path", "intent",
    "redacted_request", "requester_id",
]  # fmt: skip
T0 = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)


def _scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _columns(engine: Engine, name: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :v "
            "ORDER BY ordinal_position"
        ), {"v": name})  # fmt: skip
        return [r[0] for r in rows]


def _state(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT relname, reloptions FROM pg_class WHERE relkind = 'v' AND relname = ANY(:v)"), {"v": list(VIEWS)}
        ).all()  # fmt: skip
        grants = {v: conn.execute(text("SELECT has_table_privilege('app_monitor', :v, 'SELECT')"), {"v": v}).scalar()
                  for v in VIEWS if conn.execute(text("SELECT to_regclass(:v)"), {"v": f"public.{v}"}).scalar()}  # fmt: skip
        table = conn.execute(text("SELECT to_regclass('public.m5_strategy_changes')")).scalar()
        check = conn.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_tickets_source'")).scalar()
        rw = {p: conn.execute(text("SELECT has_table_privilege('app_rw', 'm5_strategy_changes', :p)"), {"p": p}).scalar()
              for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")} if table else {}  # fmt: skip
        monitor = conn.execute(text("SELECT has_table_privilege('app_monitor', 'm5_strategy_changes', 'SELECT')")).scalar() \
            if table else None  # fmt: skip
        triggers: set[str] = set(conn.execute(text(
            "SELECT trigger_name FROM information_schema.triggers WHERE event_object_table = 'm5_strategy_changes'"
        )).scalars())  # fmt: skip
    tickets = _columns(engine, "tickets")
    with engine.connect() as conn:
        note_check = conn.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_escalations_close_note_len'"
        )).scalar()  # fmt: skip
    return {
        "views": {name: opts for name, opts in rows}, "monitor_grants": grants, "table": table is not None, "check": check,
        "rw": rw, "monitor_on_table": monitor, "triggers": triggers, "v_leaf": _columns(engine, "v_leaf"),
        "ticket_cols": [c for c in tickets if c in ("strategy", "source")],
        "close_note": "close_note" in _columns(engine, "escalations"), "close_note_check": note_check is not None,
    }  # fmt: skip


UP = {
    "views": {v: ["security_invoker=true"] for v in VIEWS}, "monitor_grants": dict.fromkeys(VIEWS, True), "table": True,
    "check": "CHECK ((source = ANY (ARRAY['real'::text, 'sim'::text, 'eval'::text])))",
    "rw": {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False}, "monitor_on_table": False,
    "triggers": {"m5_strategy_changes_append_only", "m5_strategy_changes_no_truncate"},
    "v_leaf": [*LEAF_0012, "strategy", "source"], "ticket_cols": ["strategy", "source"],
    "close_note": True, "close_note_check": True,
}  # fmt: skip
DOWN = {**UP, "table": False, "check": None, "rw": {}, "monitor_on_table": None, "triggers": set(), "v_leaf": LEAF_0012,
        "ticket_cols": [], "close_note": False, "close_note_check": False}  # fmt: skip


def test_0013_up_down_up(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        owner = create_engine(db.role("app_migrate"))
        mon = create_engine(db.role("app_monitor"))
        try:
            command.upgrade(cfg, "0013")
            assert _scalar(owner, "SELECT version_num FROM alembic_version") == "0013"
            assert _state(owner) == UP
            assert _scalar(mon, "SELECT count(*) FROM v_leaf WHERE strategy IS NOT NULL OR source <> 'real'") == 0
            command.downgrade(cfg, "0012")
            assert _scalar(owner, "SELECT version_num FROM alembic_version") == "0012"
            assert _state(owner) == DOWN
            for view in VIEWS:  # 4 view tạo lại + GRANT app_monitor còn hiệu lực
                assert _scalar(mon, f"SELECT count(*) FROM {view}") == 0
            command.upgrade(cfg, "0013")
            assert _state(owner) == UP
        finally:
            owner.dispose()
            mon.dispose()


def test_0013_close_note_check(pg: PgUrls) -> None:
    """`escalations.close_note` (ĐP bổ sung 26/10): NULL và 1 / 1000 ký tự nhận; chuỗi rỗng và 1001 ký tự bị CHECK từ chối."""
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw = create_engine(db.role("app_rw"))
        try:
            with rw.begin() as conn:
                conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('nv-cn', 'nv.cn', 'employee')"))
                conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
                                  "VALUES ('t-cn', 'nv-cn', 'employee', 'x')"))  # fmt: skip

            def esc(note: str | None) -> None:
                with rw.begin() as conn:
                    conn.execute(text(
                        "INSERT INTO escalations (ticket_id, exit_code, priority, handoff_note, close_note) "
                        "VALUES ('t-cn', 'E5', 3, '{}'::jsonb, :n)"
                    ), {"n": note})  # fmt: skip

            for ok in (None, "a", "a" * 1000):
                esc(ok)
            for bad in ("", "a" * 1001):
                with pytest.raises(DBAPIError, match="ck_escalations_close_note_len"):
                    esc(bad)
        finally:
            rw.dispose()


def test_0013_append_only_and_source_check(pg: PgUrls) -> None:
    """`app_rw` không UPDATE/DELETE được; owner bị trigger chặn (kể cả TRUNCATE); CHECK `source` từ chối giá trị lạ."""
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw, owner = create_engine(db.role("app_rw")), create_engine(db.role("app_migrate"))
        try:
            with rw.begin() as conn:
                conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('mgr-d60', 'mgr.d60', 'manager')"))
                conn.execute(text("INSERT INTO m5_strategy_changes (strategy, changed_by, reason) VALUES "
                                  "('rule_only', 'mgr-d60', 'chạy dữ liệu thử')"))  # fmt: skip
            for stmt in ("UPDATE m5_strategy_changes SET reason = 'x'", "DELETE FROM m5_strategy_changes"):
                with pytest.raises(DBAPIError, match="permission denied"), rw.begin() as conn:
                    conn.execute(text(stmt))
            for stmt in ("UPDATE m5_strategy_changes SET reason = 'x'", "DELETE FROM m5_strategy_changes",
                         "TRUNCATE m5_strategy_changes"):  # fmt: skip
                with pytest.raises(DBAPIError, match="append-only table"), owner.begin() as conn:
                    conn.execute(text(stmt))
            with pytest.raises(DBAPIError, match="ck_tickets_source"), rw.begin() as conn:
                conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, source) "
                                  "VALUES ('t-src', 'mgr-d60', 'manager', 'x', 'khac')"))  # fmt: skip
        finally:
            rw.dispose()
            owner.dispose()


@pytest.mark.asyncio
async def test_strategy_store_and_ticket_snapshot_sql(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        engine = create_async_engine(db.role("app_rw"))
        try:
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('mgr-d60', 'mgr.d60', 'manager'), "
                                        "('nv-d60', 'nv.d60', 'employee')"))  # fmt: skip
            store = SqlStrategyStore(engine)
            assert await store.current() is None
            with pytest.raises(SameStrategy):  # chưa có dòng = hybrid
                await store.append("hybrid", changed_by="mgr-d60", reason="chạy dữ liệu thử", at=T0)
            for i, s in enumerate(("rule_only", "hybrid_guarded", "hybrid")):
                await store.append(s, changed_by="mgr-d60", reason=f"lý do số {i} đủ dài", at=T0 + timedelta(minutes=i))
            with pytest.raises(SameStrategy):
                await store.append("hybrid", changed_by="mgr-d60", reason="chạy dữ liệu thử", at=T0)
            current = await store.current()
            assert current is not None and (current.strategy, current.strategy_from) == ("hybrid", "hybrid_guarded")
            items, truncated = await store.history(2)
            assert ([(c.strategy_from, c.strategy) for c in items], truncated) == (
                [("hybrid_guarded", "hybrid"), ("rule_only", "hybrid_guarded")], True)
            items, truncated = await store.history(50)
            assert (items[-1].strategy_from, items[-1].strategy, truncated) == ("hybrid", "rule_only", False)
            async with engine.connect() as conn:
                events: list[Any] = list((await conn.execute(text(
                    "SELECT detail FROM security_events WHERE event_type = 'policy_saved' ORDER BY event_id"))).scalars())
            assert events == [{"kind": "m5_strategy", "from": "hybrid", "to": "rule_only"},
                              {"kind": "m5_strategy", "from": "rule_only", "to": "hybrid_guarded"},
                              {"kind": "m5_strategy", "from": "hybrid_guarded", "to": "hybrid"}]  # fmt: skip

            tickets = SqlTicketStore(engine)
            await tickets.create(NewTicket(ticket_id="t-d60", requester_id="nv-d60", requester_role="employee", requester_dept=None,
                                           session_id=None, redacted_request="x", created_at=T0, strategy="hybrid_guarded",
                                           source="sim"), turn_id="turn-d60")  # fmt: skip
            await tickets.create(NewTicket(ticket_id="t-old", requester_id="nv-d60", requester_role="employee", requester_dept=None,
                                           session_id=None, redacted_request="x", created_at=T0), turn_id="turn-old")  # fmt: skip
            await tickets.create_child("t-d60-1", parent_id="t-d60", redacted_request="ý 1", created_at=T0, intents=2,
                                       intent_type="vpn")  # fmt: skip
            assert await tickets.strategy_of("t-d60") == "hybrid_guarded"
            assert await tickets.strategy_of("t-d60-1") == "hybrid_guarded"  # con kế thừa
            assert await tickets.strategy_of("t-old") is None  # không ghi → NULL (B12 coi là hybrid)
            async with engine.connect() as conn:
                sources: dict[str, str] = {r[0]: r[1] for r in await conn.execute(text("SELECT ticket_id, source FROM tickets"))}
            assert sources == {"t-d60": "sim", "t-d60-1": "sim", "t-old": "real"}
        finally:
            await engine.dispose()
