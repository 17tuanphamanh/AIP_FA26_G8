"""P3 tuần 8 — `SqlApprovals.policy_matches(ticket_id, before)` trên Postgres 16 thật (khuôn `test_override_pg`).

- Dòng `step='B13/B14'` MỚI NHẤT theo `log_id` có `created_at <= before` → `detail->'all_matched'` (list, đúng thứ tự) + cột
  `matched_rule_id`. Mọi event của bước B13/B14 (cả `llm_layer_disabled`).
- Dòng ghi SAU lúc tạo phiếu (`created_at > before`) bị bỏ; dòng của ticket khác / bước khác không lẫn vào.
- `detail` không có `all_matched` → `all_matched` None (route bỏ khoá); không có dòng → None.

Mã luật GIẢ (R81…R83). Database riêng cho module (`fresh_database`); ticket id ngẫu nhiên mỗi test. PG chờ Mac.
"""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.approval.store import PolicyMatchRow, SqlApprovals
from app.db.tickets import NewTicket, SqlTicketStore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import REQUESTER, SESSION, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
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


async def _ticket(rw: AsyncEngine) -> str:
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=T0),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    return ticket


async def _audit(
    rw: AsyncEngine, ticket: str, step: str = "B13/B14", event: str = "risk_decided", *, detail: dict[str, Any] | None = None,
    matched_rule_id: str | None = None, created_at: datetime = T0,
) -> None:  # fmt: skip
    async with rw.begin() as conn:
        await conn.execute(text(
            "INSERT INTO audit_logs (ticket_id, step, event, loop_seq, matched_rule_id, created_at, detail) "
            "VALUES (:t, :s, :e, 0, :r, :c, CAST(:d AS jsonb))"
        ), {"t": ticket, "s": step, "e": event, "r": matched_rule_id, "c": created_at, "d": json.dumps(detail or {})})  # fmt: skip


async def test_pg_latest_row_by_log_id_not_after_before(rw: AsyncEngine) -> None:
    ticket, other = await _ticket(rw), await _ticket(rw)
    await _audit(rw, ticket, detail={"all_matched": ["R81"]}, matched_rule_id="R81", created_at=T0 + timedelta(minutes=1))
    # ghi SAU (log_id lớn hơn), created_at sớm hơn → vẫn là mới nhất
    await _audit(rw, ticket, detail={"all_matched": ["R82", "R81", "R83"]}, matched_rule_id="R83", created_at=T0)
    # đánh giá lại SAU lúc tạo phiếu → không phải căn cứ của phiếu
    await _audit(rw, ticket, detail={"all_matched": ["R83"]}, matched_rule_id="R83", created_at=T0 + timedelta(minutes=9))
    await _audit(rw, ticket, "B17", "exec_failed", detail={"all_matched": ["R81"]}, matched_rule_id="R81")  # bước khác
    await _audit(rw, other, detail={"all_matched": ["R81"]}, matched_rule_id="R81")  # ticket khác
    got = await SqlApprovals(rw).policy_matches(ticket, T0 + timedelta(minutes=5))
    assert got == PolicyMatchRow(all_matched=["R82", "R81", "R83"], matched_rule_id="R83")


async def test_pg_llm_layer_disabled_row_counts(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    await _audit(rw, ticket, event="llm_layer_disabled", detail={"all_matched": ["R81"]}, matched_rule_id=None)
    got = await SqlApprovals(rw).policy_matches(ticket, T0)
    assert got == PolicyMatchRow(all_matched=["R81"], matched_rule_id=None)


async def test_pg_empty_list_and_missing_key(rw: AsyncEngine) -> None:
    empty, missing = await _ticket(rw), await _ticket(rw)
    await _audit(rw, empty, detail={"all_matched": []})
    await _audit(rw, missing, detail={"strategy": "full_auto", "route": "AUTO"})
    approvals = SqlApprovals(rw)
    assert await approvals.policy_matches(empty, T0) == PolicyMatchRow(all_matched=[], matched_rule_id=None)
    assert await approvals.policy_matches(missing, T0) == PolicyMatchRow(all_matched=None, matched_rule_id=None)


async def test_pg_no_row_is_none(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    await _audit(rw, ticket, "B15", "queued")
    await _audit(rw, ticket, created_at=T0 + timedelta(minutes=1), detail={"all_matched": ["R81"]})
    assert await SqlApprovals(rw).policy_matches(ticket, T0) is None
