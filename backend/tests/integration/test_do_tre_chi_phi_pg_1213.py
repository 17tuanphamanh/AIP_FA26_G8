"""CLI-7 S3 (13/11): `scripts/report/do_tre_chi_phi.sql` chạy được trên Postgres 16 thật và ra đúng số tính tay.

psql-meta (`\\echo`), `BEGIN READ ONLY`/`ROLLBACK` bỏ qua; biến psql `:'frm'`/`:'to'` thay bằng tham số bind. Cửa sổ tháng 5/2030.
"""

import re
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

SQL = Path(__file__).resolve().parents[3] / "scripts" / "report" / "do_tre_chi_phi.sql"
FRM = datetime(2030, 5, 1, tzinfo=UTC)
TO = FRM + timedelta(days=1)
AT = FRM + timedelta(hours=1)
S = timedelta(seconds=1)


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


def _statements() -> list[str]:
    body = "\n".join(line for line in SQL.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith(("--", "\\")))  # fmt: skip
    out = []
    for stmt in body.split(";"):
        stmt = stmt.strip()
        if not stmt or stmt.upper() in ("BEGIN READ ONLY", "ROLLBACK"):
            continue
        out.append(re.sub(r":'(frm|to)'::timestamptz", r"CAST(:\1 AS timestamptz)", stmt))
    return out


async def _turn(conn: AsyncConnection, ticket: str, seconds: float, *, event: str = "submit", cost: float | None = None,
                cache: bool = False) -> None:  # fmt: skip
    turn_id = seed.new_id("u")
    await conn.execute(text(
        "INSERT INTO turns (turn_id, ticket_id, event_type, started_at, ended_at) VALUES (:u, :t, :e, :s, :end)"
    ), {"u": turn_id, "t": ticket, "e": event, "s": AT, "end": AT + seconds * S})  # fmt: skip
    if cost is not None:
        span = await seed.span(conn, turn_id, name="llm:b03_classify", started_at=AT, duration_ms=100, span_type="llm")
        await seed.llm_call(conn, span, created_at=AT, cost_usd=cost, cache_hit=cache)


@pytest.mark.asyncio
async def test_so_tinh_tay(rw: AsyncEngine) -> None:
    async with rw.begin() as conn:
        a = await seed.leaf_ticket(conn, created_at=AT)  # thật: 4 s, 0,002 + 0,001 (trúng cache)
        await _turn(conn, a, 4, cost=0.002)
        span_turn = seed.new_id("u")
        await conn.execute(text("INSERT INTO turns (turn_id, ticket_id, event_type, started_at, ended_at) "
                                "VALUES (:u, :t, 'resume', :s, :s)"), {"u": span_turn, "t": a, "s": AT})  # fmt: skip
        sp = await seed.span(conn, span_turn, name="llm:b10", started_at=AT, duration_ms=1, span_type="llm")
        await seed.llm_call(conn, sp, created_at=AT, cost_usd=0.001, cache_hit=True)
        b, kids = await seed.parent_with_children(conn, 2, created_at=AT)  # thật, nhiều ý: cha 10 s 0,003; con 2 s 0,004
        await _turn(conn, b, 10, cost=0.003)
        await _turn(conn, kids[0], 2, cost=0.004)
        c = await seed.leaf_ticket(conn, created_at=AT)  # sim: 1 s, 0,010
        await conn.execute(text("UPDATE tickets SET source = 'sim' WHERE ticket_id = :t"), {"t": c})
        await _turn(conn, c, 1, cost=0.010)
        out = await seed.leaf_ticket(conn, created_at=TO + S)  # ngoài cửa sổ
        await _turn(conn, out, 99, cost=1.0)

    results: list[list[Any]] = []
    async with rw.connect() as conn:
        for stmt in _statements():
            results.append([tuple(r) for r in (await conn.execute(text(stmt), {"frm": FRM, "to": TO})).all()])
    assert len(results) == 4
    counts, submit, by_type, cost = results
    assert counts == [("real", 2, 1), ("sim", 1, 0)]
    assert submit == [("real", 2, Decimal("7.00"), Decimal("9.70"), Decimal("10.00")),
                      ("sim", 1, Decimal("1.00"), Decimal("1.00"), Decimal("1.00"))]  # fmt: skip
    assert ("real", "resume", 1, Decimal("0.00"), Decimal("0.00")) in by_type
    assert [r[:3] for r in by_type if r[1] == "submit"] == [("real", "submit", 3), ("sim", "submit", 1)]
    real, sim = cost
    assert real[:2] == ("real", 2)
    assert (real[2], real[3]) == (Decimal("0.010000"), Decimal("0.005000"))  # A 0,003 + B (0,003 + 0,004)
    assert (real[6], real[7]) == (4, 1)
    assert sim[:3] == ("sim", 1, Decimal("0.010000"))
