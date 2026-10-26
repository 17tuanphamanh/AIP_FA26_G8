"""M9 F12 (#45) — migration 0011 trên Postgres 16 thật: `app_monitor` đọc `child_notices` CHỈ qua 6 cột được GRANT (không
`body`, không `effect_key`…), view `v_child_notices` (`security_invoker`, cột tường minh, chỉ notice của con là lá — D-30),
INSERT bị từ chối, downgrade/upgrade về đúng quyền của 0009."""

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
    path = REPO / "backend" / "app" / "db" / "alembic" / "versions" / "0011_monitor_child_notices.py"
    spec = importlib.util.spec_from_file_location("m9_0011_monitor_child_notices", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load_migration()
VIEW = "v_child_notices"
HIDDEN = ("body", "effect_key", "kind", "needs", "source_step")
T0 = datetime(2030, 6, 1, 8, 0, tzinfo=UTC)


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


@pytest.mark.asyncio
async def test_app_monitor_cannot_read_body(mon: AsyncEngine) -> None:
    """Cột nội dung (`body`) và cột không cần (`effect_key`, …) KHÔNG được GRANT; cả bảng không được GRANT (`SELECT *` lỗi)."""
    for column in HIDDEN:
        priv = await _rows(mon, "SELECT has_column_privilege('app_monitor', 'child_notices', :c, 'SELECT')", c=column)
        assert priv[0][0] is False, column
    with pytest.raises(DBAPIError, match="permission denied"):
        await _rows(mon, "SELECT body FROM child_notices")
    with pytest.raises(DBAPIError, match="permission denied"):
        await _rows(mon, "SELECT * FROM child_notices")
    assert (await _rows(mon, "SELECT has_table_privilege('app_monitor', 'child_notices', 'SELECT')"))[0][0] is False


@pytest.mark.asyncio
async def test_app_monitor_reads_granted_columns(mon: AsyncEngine) -> None:
    for column in M.NOTICE_COLUMNS:
        priv = await _rows(mon, "SELECT has_column_privilege('app_monitor', 'child_notices', :c, 'SELECT')", c=column)
        assert priv[0][0] is True, column
    assert await _rows(mon, f"SELECT {', '.join(M.NOTICE_COLUMNS)} FROM child_notices LIMIT 0") == []  # đọc được, không lỗi
    with pytest.raises(DBAPIError, match="permission denied"):
        async with mon.begin() as conn:
            await conn.execute(text(
                "INSERT INTO child_notices (parent_ticket_id, child_ticket_id, source_step, kind, needs, body, effect_key) "
                "VALUES ('x', 'y', 'B20', 'result', 'none', 'x', repeat('0', 64))"
            ))  # fmt: skip


@pytest.mark.asyncio
async def test_view_columns_and_d30(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Cột view == `NOTICE_COLUMNS` (đúng thứ tự); `security_invoker=true`; notice mà `child_ticket_id` là ticket CHA (dữ
    liệu xấu cố ý) không vào view; notice của con là lá vào view."""
    cols = await _rows(
        mon, "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :v "
        "ORDER BY ordinal_position", v=VIEW,
    )  # fmt: skip
    assert [r[0] for r in cols] == list(M.NOTICE_COLUMNS)
    opts = await _rows(mon, "SELECT reloptions FROM pg_class WHERE relkind = 'v' AND relname = :v", v=VIEW)
    assert opts == [(["security_invoker=true"],)]
    async with rw.begin() as conn:
        parent, (child,) = await seed.parent_with_children(conn, 1, created_at=T0)
        keep = await seed.child_notice(conn, parent, child, created_at=T0, delivered_round=1, delivered_at=T0 + timedelta(seconds=9))
        await seed.child_notice(conn, parent, parent, created_at=T0)  # con trỏ vào cha → loại (D-30)
    rows = await _rows(
        mon, f"SELECT notice_id, child_ticket_id, delivered_round FROM {VIEW} WHERE parent_ticket_id = :p", p=parent
    )
    assert [tuple(r) for r in rows] == [(keep, child, 1)]


def _state(engine: Any) -> tuple[bool, bool, bool]:
    """(view `v_child_notices` có, app_monitor có SELECT cột `delivered_at`, view `v_leaf` của 0008 còn)."""
    with engine.connect() as conn:
        views = set(conn.execute(text("SELECT viewname FROM pg_views WHERE schemaname = 'public'")).scalars())
        priv = conn.execute(
            text("SELECT has_column_privilege('app_monitor', 'child_notices', 'delivered_at', 'SELECT')")
        ).scalar()
    return VIEW in views, bool(priv), "v_leaf" in views


def test_migration_0011_up_down_up(pg: PgUrls) -> None:
    with fresh_database(pg) as fresh:
        cfg = alembic_config(fresh)
        owner = create_engine(fresh.role("app_migrate"))
        try:
            command.upgrade(cfg, "head")
            assert _state(owner) == (True, True, True)
            command.downgrade(cfg, "0009")
            assert _state(owner) == (False, False, True)  # quyền cột về như 0009; view 0008 không bị xoá nhầm
            command.upgrade(cfg, "head")
            assert _state(owner) == (True, True, True)
        finally:
            owner.dispose()
