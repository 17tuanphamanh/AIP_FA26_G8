"""D-67 P2 — SQL của `monitor.queries.strategies` trên Postgres 16 thật (engine `app_monitor`, qua `v_leaf`) với dữ liệu dựng sẵn.

Kỳ vọng tính TAY từ dữ liệu dưới (không suy từ code): 4 lá `hybrid_guarded` nguồn real đã kết thúc trong cửa sổ; bị loại: lá đang chạy,
lá ngoài cửa sổ, lá `strategy` NULL, lá `llm_only`, ticket CHA (`v_leaf` bỏ), lá `hybrid` nguồn sim (chỉ vào khi `source=sim`).
`rule_only` 0 lá → null mọi khoá.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.monitor.queries.strategies import STRATEGY_METRICS, strategy_comparison
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

STRATEGIES = ["rule_only", "hybrid", "hybrid_guarded"]
T0 = datetime(2030, 1, 3, 9, 0, tzinfo=UTC)
FRM, TO = datetime(2030, 1, 3, tzinfo=UTC), datetime(2030, 1, 4, tzinfo=UTC)
L1_A = seed.SEED_APPROVERS[0]
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


@pytest_asyncio.fixture
async def mon(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_monitor"))
    yield engine
    await engine.dispose()


async def _mark(conn: AsyncConnection, ticket: str, strategy: str | None, source: str = "real") -> str:
    await conn.execute(text("UPDATE tickets SET strategy = :s, source = :src WHERE ticket_id = :t"),
                       {"s": strategy, "src": source, "t": ticket})  # fmt: skip
    return ticket


async def _route(conn: AsyncConnection, ticket: str, route: str, at: datetime, event: str = "risk_decided") -> None:
    await seed.audit_row(conn, ticket, step="B13/B14", event=event, created_at=at, detail={"route": route})


async def _node_span(conn: AsyncConnection, ticket: str, at: datetime, ms: int, status: str = "ok") -> None:
    turn = await seed.turn(conn, ticket, started_at=at)
    await seed.span(conn, turn, name="node:b12_assess", started_at=at, duration_ms=ms, status=status)


async def _seed(rw: AsyncEngine) -> None:
    async with rw.begin() as conn:
        # L1 tự xử lý: AUTO, xác nhận, span 1000 + 500 (+ 1 span interrupted bị loại), 2 lời gọi LLM 0,02 + 0,01 USD
        l1 = await _mark(conn, await seed.leaf_ticket(conn, created_at=T0, final_state="S_RESOLVED", resolution_path="auto",
                                                      intent="vpn"), "hybrid_guarded")  # fmt: skip
        await _route(conn, l1, "AUTO", T0)
        await seed.audit_row(conn, l1, step="B19", event="user_confirmed", created_at=T0 + 9 * S)
        await _node_span(conn, l1, T0, 1000)
        await _node_span(conn, l1, T0, 500)
        await _node_span(conn, l1, T0, 9999, status="interrupted")
        await seed.llm_call_for(conn, l1, created_at=T0, cost_usd=0.02)
        await seed.llm_call_for(conn, l1, created_at=T0, cost_usd=0.01)
        # L2 duyệt nhanh: HITL, phiếu approved sau 120 s, B16 view 3 s (< 5), không phản hồi 48 h, span 3000, 1 ghi đè
        l2 = await _mark(conn, await seed.leaf_ticket(conn, created_at=T0, final_state="S_RESOLVED", resolution_path="approved",
                                                      intent="vpn"), "hybrid_guarded")  # fmt: skip
        await _route(conn, l2, "HITL", T0)
        await seed.approval(conn, l2, approver_id=L1_A, created_at=T0, status="approved", decided_by=L1_A,
                            decided_at=T0 + 120 * S)  # fmt: skip
        await seed.audit_row(conn, l2, step="B16", event="approved", created_at=T0 + 120 * S, approval_result="approved",
                             detail={"view_duration": 3.0, "decided_without_view": False, "decided_as": "primary"})  # fmt: skip
        await seed.audit_row(conn, l2, step="B19", event="auto_closed_no_response_48h", created_at=T0 + 200 * S)
        await _node_span(conn, l2, T0, 3000)
        await seed.override(conn, l2, created_at=T0 + 300 * S)
        # L3 từ chối: HITL, phiếu rejected sau 60 s, B16 view 30 s; không span, không B19
        l3 = await _mark(conn, await seed.leaf_ticket(conn, created_at=T0, final_state="S_REJECTED", resolution_path="rejected",
                                                      intent="account"), "hybrid_guarded")  # fmt: skip
        await _route(conn, l3, "HITL", T0)
        await seed.approval(conn, l3, approver_id=L1_A, created_at=T0, status="rejected", decided_by=L1_A, decided_at=T0 + 60 * S,
                            note="không thuộc diện")  # fmt: skip
        await seed.audit_row(conn, l3, step="B16", event="rejected", created_at=T0 + 60 * S, approval_result="rejected",
                             detail={"view_duration": 30.0, "decided_without_view": False, "decided_as": "primary"})  # fmt: skip
        # L4: B13/B14 cũ AUTO rồi mới ESCALATE_L2 (lấy dòng MỚI NHẤT); E5 recheck_failed; B17 hoàn tác; báo chưa ổn; intent NULL
        l4 = await _mark(conn, await seed.leaf_ticket(conn, created_at=T0, final_state="S_ESCALATED", exit_code="E5",
                                                      resolution_path="escalated"), "hybrid_guarded")  # fmt: skip
        await _route(conn, l4, "AUTO", T0)
        await _route(conn, l4, "ESCALATE_L2", T0 + S, event="llm_layer_disabled")
        await seed.escalation(conn, l4, exit_code="E5", created_at=T0 + 2 * S, reason_detail="recheck_failed")
        await seed.audit_row(conn, l4, step="B17", event="executed", created_at=T0 + 3 * S, rollback_status="undone")
        await seed.audit_row(conn, l4, step="B19", event="user_reported_unresolved", created_at=T0 + 4 * S)
        # bị loại khỏi `hybrid_guarded` real
        await _mark(conn, await seed.leaf_ticket(conn, created_at=T0, intent="vpn"), "hybrid_guarded")  # đang chạy
        await _mark(conn, await seed.leaf_ticket(conn, created_at=T0 - timedelta(days=2), final_state="S_RESOLVED",
                                                 intent="vpn"), "hybrid_guarded")  # fmt: skip  — ngoài cửa sổ
        await _mark(conn, await seed.leaf_ticket(conn, created_at=T0, final_state="S_RESOLVED", intent="vpn"), None)  # trước D-67
        await _mark(conn, await seed.leaf_ticket(conn, created_at=T0, final_state="S_RESOLVED", intent="vpn"), "llm_only")
        parent, (child,) = await seed.parent_with_children(conn, 1, created_at=T0, parent_final_state="S_RESOLVED",
                                                           final_state="S_RESOLVED", intent="software")  # fmt: skip
        await _mark(conn, parent, "hybrid_guarded")  # cha: v_leaf bỏ
        await _mark(conn, child, "hybrid", "sim")  # con kế thừa; chỉ vào khi source=sim
        await _route(conn, child, "AUTO", T0)


def _values(got: Any) -> dict[str, dict[str, Any]]:
    return {spec.key: values for spec, values in got.metrics}


async def test_strategy_comparison_counts_real(rw: AsyncEngine, mon: AsyncEngine) -> None:
    await _seed(rw)
    async with mon.connect() as conn:
        got = await strategy_comparison(conn, FRM, TO, source="real", strategies=STRATEGIES)
    v = _values(got)
    assert list(v) == [m.key for m in STRATEGY_METRICS]
    for values in v.values():
        assert list(values) == STRATEGIES and values["rule_only"] is None and values["hybrid"] is None
    g = {k: values["hybrid_guarded"] for k, values in v.items()}
    assert g["tickets"] == {"value": 4}
    assert (g["auto_rate"], g["hitl_rate"], g["l2_rate"]) == ({"num": 1, "den": 4}, {"num": 2, "den": 4}, {"num": 1, "den": 4})
    assert (g["confirmed_rate"], g["no_response_rate"], g["unresolved_rate"]) == (
        {"num": 1, "den": 3}, {"num": 1, "den": 3}, {"num": 1, "den": 3})
    assert (g["l1_reject_rate"], g["quick_approve_rate"]) == ({"num": 1, "den": 2}, {"num": 1, "den": 2})
    assert g["system_time_p50"] == {"value": pytest.approx(2.25), "n": 2}  # (1,5 + 3,0) / 2
    assert g["system_time_p90"] == {"value": pytest.approx(2.85), "n": 2}  # 1,5 + 0,9 × 1,5
    assert g["human_wait_p50"] == {"value": pytest.approx(1.5), "n": 2}  # (120 + 60) / 2 s = 1,5 phút
    assert g["human_minutes_per_100"] == {"value": pytest.approx(13.75), "n": 4}  # 100 × 33 s / 60 / 4
    assert (g["e5_recheck_failed"], g["overrides"], g["rollbacks"]) == ({"value": 1}, {"value": 1}, {"value": 1})
    assert g["llm_cost_per_ticket"] == {"value": pytest.approx(0.0075), "n": 4}
    assert got.intent_mix == {"rule_only": {}, "hybrid": {}, "hybrid_guarded": {"account": 1, "none": 1, "vpn": 2}}
    assert got.unavailable == ()


async def test_strategy_comparison_sim_only_child_inherited(mon: AsyncEngine) -> None:
    """Dữ liệu của test trên (cùng DB module): `source=sim` chỉ thấy lá con `hybrid` (cha bỏ qua `v_leaf`)."""
    async with mon.connect() as conn:
        got = await strategy_comparison(conn, FRM, TO, source="sim", strategies=STRATEGIES)
    v = _values(got)
    assert v["tickets"] == {"rule_only": None, "hybrid": {"value": 1}, "hybrid_guarded": None}
    assert v["auto_rate"]["hybrid"] == {"num": 1, "den": 1}
    assert v["system_time_p50"]["hybrid"] == {"value": None, "n": 0}  # không span → loại, n = 0
    assert v["human_wait_p50"]["hybrid"] == {"value": None, "n": 0}
    assert got.intent_mix["hybrid"] == {"software": 1}
