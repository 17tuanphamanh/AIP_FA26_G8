"""D-97 trên Postgres 16 thật — `db/hours_mode.SqlHoursModeStore` bằng role `app_rw` (đúng quyền của backend + worker).

- Chưa có dòng → `real`; `set_mode` ghi ĐÚNG một dòng `security_events` `policy_saved` `{kind, from, to}`; `current` đọc dòng mới nhất.
- Trùng chế độ hiện hành → `SameHoursMode`, không ghi thêm. Dòng `policy_saved` loại khác (đổi chiến lược M5) không lẫn vào.
- Giá trị lạ trong DB → `real`.
DB riêng mỗi test (`fresh_database`): bảng chỉ ghi thêm, ghi vào DB chung thì test downgrade về base đỏ.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.db.hours_mode import SameHoursMode, SqlHoursModeStore
from app.db.security_events import insert_event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import APPROVER, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)


@pytest.fixture
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


async def _rows(engine: AsyncEngine) -> list[tuple[str, str, dict[str, str]]]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT event_type, user_id, detail FROM security_events WHERE detail->>'kind' = 'hours_mode' ORDER BY event_id"
        ))).all()  # fmt: skip
    return [(r.event_type, r.user_id, dict(r.detail)) for r in rows]


async def test_default_real_then_switch_and_read_back(rw: AsyncEngine) -> None:
    store = SqlHoursModeStore(rw)
    first = await store.current()
    assert (first.mode, first.changed_by, first.changed_at) == ("real", None, None)
    assert await store.mode() == "real"
    await store.set_mode("outside", changed_by=APPROVER, at=T0)
    got = await store.current()
    assert (got.mode, got.changed_by, got.changed_at) == ("outside", APPROVER, T0)
    assert await store.mode() == "outside"
    await store.set_mode("real", changed_by=APPROVER, at=T0 + timedelta(minutes=5))
    assert await store.mode() == "real"
    assert await _rows(rw) == [
        ("policy_saved", APPROVER, {"kind": "hours_mode", "from": "real", "to": "outside"}),
        ("policy_saved", APPROVER, {"kind": "hours_mode", "from": "outside", "to": "real"}),
    ]


async def test_same_mode_rejected_without_writing(rw: AsyncEngine) -> None:
    store = SqlHoursModeStore(rw)
    with pytest.raises(SameHoursMode):
        await store.set_mode("real", changed_by=APPROVER, at=T0)
    await store.set_mode("inside", changed_by=APPROVER, at=T0)
    with pytest.raises(SameHoursMode):
        await store.set_mode("inside", changed_by=APPROVER, at=T0)
    assert len(await _rows(rw)) == 1


async def test_other_policy_saved_kinds_and_unknown_values_ignored(rw: AsyncEngine) -> None:
    store = SqlHoursModeStore(rw)
    async with rw.begin() as conn:
        await insert_event(conn, "policy_saved", occurred_at=T0, user_id=APPROVER,
                           detail={"kind": "m5_strategy", "from": "hybrid", "to": "rule_only"})  # fmt: skip
    assert await store.mode() == "real"  # đổi chiến lược M5 không phải chế độ giờ
    async with rw.begin() as conn:
        await insert_event(conn, "policy_saved", occurred_at=T0, user_id=APPROVER,
                           detail={"kind": "hours_mode", "from": "real", "to": "ngoai"})  # fmt: skip
    assert await store.mode() == "real"  # giá trị lạ → giờ thật
