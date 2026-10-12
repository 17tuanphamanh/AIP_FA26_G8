"""M9 A1 — migration 0008 trên Postgres 16 thật: 3 view chỉ lá (D-30), `security_invoker`, GRANT `app_monitor` (đọc
được, INSERT bị từ chối), cột tường minh, `v_decisions` chỉ step `B13/B14`, downgrade/upgrade về đúng quyền 0007."""

import importlib.util
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import REPO, PgUrls, alembic_config, fresh_database


def _load_migration() -> ModuleType:
    """Danh sách cột của view nằm MỘT chỗ — trong migration (tên file bắt đầu bằng số → nạp theo đường dẫn)."""
    path = REPO / "backend" / "app" / "db" / "alembic" / "versions" / "0008_monitor_views.py"
    spec = importlib.util.spec_from_file_location("m9_0008_monitor_views", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load_migration()
VIEWS = ("v_leaf", "v_decisions", "v_l2_queue")
T0 = datetime(2030, 3, 1, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def mon(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_monitor"))
    yield engine
    await engine.dispose()


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def _columns(engine: AsyncEngine, view: str) -> list[str]:
    rows = await _rows(
        engine,
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :v "
        "ORDER BY ordinal_position",
        v=view,
    )
    return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_v_leaf_excludes_parent(rw: AsyncEngine, mon: AsyncEngine) -> None:
    async with rw.begin() as conn:
        parent, children = await seed.parent_with_children(
            conn, 2, created_at=T0, parent_exit_code="E1", parent_final_state="S_ESCALATED",
            exit_code="E1", final_state="S_ESCALATED",
        )  # fmt: skip
    ids = [parent, *children]
    rows = await _rows(mon, "SELECT ticket_id FROM v_leaf WHERE ticket_id = ANY(:ids)", ids=ids)
    assert sorted(r[0] for r in rows) == sorted(children)


@pytest.mark.asyncio
async def test_view_columns_explicit(mon: AsyncEngine) -> None:
    assert await _columns(mon, "v_leaf") == list(M.LEAF_COLUMNS)
    assert await _columns(mon, "v_decisions") == list(M.DECISION_COLUMNS)
    assert await _columns(mon, "v_l2_queue") == [*M.L2_QUEUE_COLUMNS, "rank"]


@pytest.mark.asyncio
async def test_v_decisions_only_point4_of_leaves(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = T0 + timedelta(hours=1)
    async with rw.begin() as conn:
        parent, (child,) = await seed.parent_with_children(conn, 1, created_at=at)
        keep = await seed.audit_point4(conn, child, created_at=at, policy_decision="deny", matched_rule_id="R01")
        await seed.audit_point4(conn, parent, created_at=at, policy_decision="deny")  # cha → loại
        # B17 kiểm lại (quyết định trong detail) và step B12 riêng: không phải điểm log 4 thật → không vào view
        await seed.audit_row(
            conn, child, step="B17", event="recheck_failed", created_at=at, detail={"policy_decision": "deny"},
            decided_by="rule", policy_decision="deny",
        )  # fmt: skip
        await seed.audit_point4(conn, child, created_at=at, step="B12", policy_decision="allow")
    rows = await _rows(
        mon, "SELECT log_id, ticket_id, policy_decision, risk_level, matched_rule_id FROM v_decisions "
        "WHERE ticket_id = ANY(:ids)", ids=[parent, child],
    )  # fmt: skip
    assert [tuple(r) for r in rows] == [(keep, child, "deny", "high", "R01")]


@pytest.mark.asyncio
async def test_v_l2_queue_open_leaf_ordered(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = T0 + timedelta(hours=2)
    async with rw.begin() as conn:
        parent, (child,) = await seed.parent_with_children(conn, 1, created_at=at)
        e1 = await seed.escalation(conn, child, exit_code="E1", created_at=at, reason_detail="out_of_scope")
        e7 = await seed.escalation(
            conn, child, exit_code="E7", created_at=at + timedelta(minutes=5), reason_detail="exec_interrupted"
        )
        await seed.escalation(conn, child, exit_code="E0", created_at=at, closed_at=at + timedelta(hours=1))
        await seed.escalation(conn, parent, exit_code="E7", created_at=at)  # cha → loại
    rows = await _rows(
        mon, "SELECT escalation_id, exit_code, reason_detail, rank FROM v_l2_queue WHERE ticket_id = ANY(:ids)",
        ids=[parent, child],
    )  # fmt: skip
    # E7 (rank 1) trước E1 (rank 6) dù tạo sau; dòng đã đóng và dòng của cha không có
    assert [tuple(r) for r in rows] == [(e7, "E7", "exec_interrupted", 1), (e1, "E1", "out_of_scope", 6)]


@pytest.mark.asyncio
async def test_views_are_security_invoker(mon: AsyncEngine) -> None:
    rows = await _rows(
        mon, "SELECT relname, reloptions FROM pg_class WHERE relkind = 'v' AND relname = ANY(:v)", v=list(VIEWS)
    )
    assert {name: opts for name, opts in rows} == {view: ["security_invoker=true"] for view in VIEWS}


@pytest.mark.asyncio
async def test_app_monitor_selects_three_views(mon: AsyncEngine) -> None:
    for view in VIEWS:
        assert (await _rows(mon, f"SELECT count(*) FROM {view}"))[0][0] >= 0


@pytest.mark.asyncio
async def test_app_monitor_insert_view_denied(mon: AsyncEngine) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with mon.begin() as conn:
            await conn.execute(text(
                "INSERT INTO v_leaf (ticket_id, created_at, redacted_request) VALUES ('m9-x', now(), 'x')"
            ))  # fmt: skip


def test_security_invoker_uses_reader_rights(db: PgUrls) -> None:
    """Thiếu quyền của NGƯỜI ĐỌC trên bảng nguồn → view báo lỗi (không mượn quyền chủ view `app_migrate`)."""
    owner = create_engine(db.role("app_migrate"))
    monitor = create_engine(db.role("app_monitor"))
    try:
        with owner.begin() as conn:
            conn.execute(text("REVOKE SELECT ON exit_code_priority FROM app_monitor"))
        with pytest.raises(DBAPIError, match="permission denied"), monitor.connect() as conn:
            conn.execute(text("SELECT count(*) FROM v_l2_queue"))
    finally:
        with owner.begin() as conn:
            conn.execute(text("GRANT SELECT ON exit_code_priority TO app_monitor"))
        owner.dispose()
        monitor.dispose()


def _state(engine: Any) -> tuple[set[str], bool, bool]:
    """(view M9 đang có, app_monitor có SELECT `exit_code_priority`, view `auth_failures` của 0001 còn)."""
    with engine.connect() as conn:
        views = set(conn.execute(text("SELECT viewname FROM pg_views WHERE schemaname = 'public'")).scalars())
        priv = conn.execute(text("SELECT has_table_privilege('app_monitor', 'exit_code_priority', 'SELECT')")).scalar()
    return views & set(VIEWS), bool(priv), "auth_failures" in views


def test_migration_up_down_up(pg: PgUrls) -> None:
    with fresh_database(pg) as fresh:
        cfg = alembic_config(fresh)
        owner = create_engine(fresh.role("app_migrate"))
        try:
            command.upgrade(cfg, "head")
            assert _state(owner) == (set(VIEWS), True, True)
            command.downgrade(cfg, "0007")
            # quyền về đúng như 0007; view `auth_failures` (0001) không bị xoá nhầm
            assert _state(owner) == (set(), False, True)
            command.upgrade(cfg, "head")
            assert _state(owner) == (set(VIEWS), True, True)
        finally:
            owner.dispose()
