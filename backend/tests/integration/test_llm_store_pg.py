"""LLM gateway trên Postgres 16 thật (PLAN-3d d16): `SqlLlmStore` (span + `llm_calls` một transaction, cache runtime/
eval, tổng chi), `SqlPresetResolver` (`turn_id → tickets.redacted_request`), gateway trong một lượt graph thật
(`trace_parent` → FK `spans`/`turns`), `check_llm` + `open_llm` với `LLM_BACKEND=scripted`. Role `app_rw` như backend.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.clock import FakeClock
from app.db.runtime import SqlSpanSink, SqlTurnStore
from app.graph.context import RunContext, bind_run
from app.graph.tracing import trace_parent, traced
from app.llm.client import LLMClient
from app.llm.ports import LlmCallRow, LlmSpan, TraceParent
from app.llm.providers.scripted import SqlPresetResolver
from app.llm.schemas import InjectionJudgeOut, NeedTypeOut
from app.llm.store import SqlLlmStore
from app.llm.wiring import check_llm, open_llm
from app.settings import Settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.graph import MemoryAudit, MemoryEffects
from tests.fakes.llm import repo_registry, scripted_runtime
from tests.fakes.scripted_llm import Reply, ScriptedLLM
from tests.integration.graph_pg import REQUESTER, scalar, seed_users
from tests.integration.pg import PgUrls

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)
CANARY = "CANARY-3d-khong-duoc-luu"


@pytest_asyncio.fixture
async def arw(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


async def _turn(engine: AsyncEngine, request: str = "yêu cầu thử") -> tuple[str, str]:
    ticket_id, turn_id = f"llm-{uuid4().hex[:12]}", f"turn-{uuid4().hex[:12]}"
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
                 "VALUES (:t, :u, 'employee', :r)"),
            {"t": ticket_id, "u": REQUESTER, "r": request},
        )  # fmt: skip
    await SqlTurnStore(engine).start(turn_id=turn_id, ticket_id=ticket_id, session_id=None, event_type="submit",
                                     at=NOW)  # fmt: skip
    return ticket_id, turn_id


def _span(turn_id: str | None, span_id: str | None = None) -> LlmSpan:
    return LlmSpan(span_id=span_id or uuid4().hex, trace_id="b" * 32, turn_id=turn_id, name="llm:b10_need_type",
                   started_at=NOW, parent_span_id="node-span", duration_ms=12, status="ok",
                   attributes={"attempts": 1})  # fmt: skip


def _row(span_id: str, **over: Any) -> LlmCallRow:
    base: dict[str, Any] = {
        "span_id": span_id, "provider": "scripted", "model": "scripted", "model_version": None,
        "prompt_id": "b10_need_type", "prompt_version": "1", "prompt_hash": "c" * 64, "prompt_full": None,
        "tokens_in": 10, "tokens_out": 2, "cost_usd": 0.25, "latency_ms": 12, "cache_hit": False,
        "json_valid_first_try": True, "used_fallback": False, "error": None,
    }  # fmt: skip
    return LlmCallRow(**{**base, **over})


# ---- SqlLlmStore ------------------------------------------------------------------------------------


async def test_d16_record_span_and_call_in_one_transaction(arw: AsyncEngine) -> None:
    _, turn_id = await _turn(arw)
    span = _span(turn_id)
    await SqlLlmStore(arw).record(span, _row(span.span_id))
    got = await scalar(arw, "SELECT s.span_type || '|' || s.name || '|' || s.turn_id || '|' || c.prompt_id "
                            "FROM llm_calls c JOIN spans s USING (span_id) WHERE c.span_id = :s", s=span.span_id)
    assert got == f"llm|llm:b10_need_type|{turn_id}|b10_need_type"


async def test_d16_record_is_atomic(arw: AsyncEngine) -> None:
    _, turn_id = await _turn(arw)
    span = _span(turn_id)
    with pytest.raises(DBAPIError):  # prompt_id VARCHAR(64) tràn → dòng llm_calls lỗi SAU khi span đã INSERT
        await SqlLlmStore(arw).record(span, _row(span.span_id, prompt_id="x" * 65))
    assert await scalar(arw, "SELECT count(*) FROM spans WHERE span_id = :s", s=span.span_id) == 0


async def test_d16_record_without_turn_refused(arw: AsyncEngine) -> None:
    span = _span(None)
    with pytest.raises(RuntimeError, match="turn_id"):
        await SqlLlmStore(arw).record(span, _row(span.span_id))


async def test_d16_cache_runtime_expiry_eval_forever_and_mode_isolation(arw: AsyncEngine) -> None:
    store, key_rt, key_ev = SqlLlmStore(arw), uuid4().hex + uuid4().hex, uuid4().hex + uuid4().hex
    common: dict[str, Any] = {"prompt_id": "b10_need_type", "prompt_version": "1", "model": "scripted"}
    await store.cache_put(key_rt, mode="runtime", response={"type": "info", "confidence": 0.5}, now=NOW,
                          expires_at=NOW + timedelta(hours=24), **common)  # fmt: skip
    await store.cache_put(key_ev, mode="eval", response={"type": "action", "confidence": 0.7}, now=NOW,
                          expires_at=None, **common)  # fmt: skip
    assert await store.cache_get(key_rt, mode="runtime", now=NOW) == {"type": "info", "confidence": 0.5}
    assert await store.cache_get(key_rt, mode="runtime", now=NOW + timedelta(hours=25)) is None  # hết TTL
    assert await store.cache_get(key_rt, mode="eval", now=NOW) is None  # khác chế độ
    assert await store.cache_get(key_ev, mode="eval", now=NOW + timedelta(days=3650)) == {"type": "action",
                                                                                          "confidence": 0.7}
    await store.cache_put(key_rt, mode="runtime", response={"type": "action", "confidence": 0.9},
                          now=NOW + timedelta(hours=30), expires_at=NOW + timedelta(hours=54), **common)  # fmt: skip
    assert await store.cache_get(key_rt, mode="runtime", now=NOW + timedelta(hours=31)) == {"type": "action",
                                                                                             "confidence": 0.9}


async def test_d16_spend_total_sums_cost(arw: AsyncEngine) -> None:
    store = SqlLlmStore(arw)
    before = await store.spend_total()
    _, turn_id = await _turn(arw)
    for cost in (0.5, 0.25):
        span = _span(turn_id)
        await store.record(span, _row(span.span_id, cost_usd=cost))
    assert await store.spend_total() == pytest.approx(before + 0.75)


# ---- SqlPresetResolver -----------------------------------------------------------------------------------


async def test_d16_preset_resolver_reads_tag_of_turn_ticket(arw: AsyncEngine) -> None:
    _, tagged = await _turn(arw, "[fake:vpn_demo] VPN lỗi chứng chỉ")
    _, plain = await _turn(arw, "VPN lỗi chứng chỉ")
    resolver = SqlPresetResolver(arw)
    assert await resolver.tag_for(TraceParent(tagged, "t", None)) == "vpn_demo"
    assert await resolver.tag_for(TraceParent(plain, "t", None)) is None
    assert await resolver.tag_for(TraceParent("turn-khong-co", "t", None)) is None
    assert await resolver.tag_for(None) is None


# ---- gateway trong một lượt graph thật ---------------------------------------------------------------------


async def test_d16_gateway_in_graph_turn_links_llm_span_to_node_span(arw: AsyncEngine) -> None:
    _, turn_id = await _turn(arw)
    client = LLMClient(  # store SQL thật, provider ScriptedLLM
        runtime=scripted_runtime(), registry=repo_registry(), store=SqlLlmStore(arw), clock=FakeClock(),
        providers={"scripted": ScriptedLLM({"b10_need_type": [Reply({"type": "info", "confidence": 0.5})]})},
        trace=trace_parent,
    )  # fmt: skip
    run = RunContext(turn_id=turn_id, trace_id="d" * 32, audit=MemoryAudit(), effects=MemoryEffects(),
                     spans=SqlSpanSink(arw), clock=FakeClock())  # fmt: skip

    async def node(state: Any) -> dict[str, Any]:
        await client.complete("fast", "b10_need_type", {"text": CANARY, "evidence_titles": []}, NeedTypeOut)
        return {}

    with bind_run(run):
        await traced("b10_route", node)({})
    row = await scalar(arw, "SELECT s.parent_span_id FROM llm_calls c JOIN spans s USING (span_id) "
                            "WHERE s.turn_id = :t AND s.span_type = 'llm'", t=turn_id)  # fmt: skip
    node_span = await scalar(arw, "SELECT span_id FROM spans WHERE turn_id = :t AND name = 'node:b10_route'",
                             t=turn_id)  # fmt: skip
    assert node_span is not None and row == node_span
    leaked = await scalar(arw, "SELECT count(*) FROM llm_calls c JOIN spans s USING (span_id) WHERE s.turn_id = :t "
                               "AND (c.prompt_full IS NOT NULL OR s.attributes::text LIKE :c)",
                          t=turn_id, c=f"%{CANARY}%")  # fmt: skip
    assert leaked == 0  # EVAL_MODE=false: không văn bản prompt trong llm_calls/spans


async def test_d16_check_llm_and_open_llm_scripted_default_preset(arw: AsyncEngine) -> None:
    _, turn_id = await _turn(arw, "quên mật khẩu email")
    settings = Settings(_env_file=None, app_env="test", llm_backend="scripted")  # type: ignore[call-arg]
    setup = check_llm(settings)
    run = RunContext(turn_id=turn_id, trace_id="e" * 32, audit=MemoryAudit(), effects=MemoryEffects(),
                     spans=SqlSpanSink(arw), clock=FakeClock())  # fmt: skip
    async with open_llm(setup, settings, engine=arw, clock=FakeClock(), trace=trace_parent) as client:
        with bind_run(run):
            out, meta = await client.complete("fast", "b02_injection_judge", {"text": "quên mật khẩu email"},
                                              InjectionJudgeOut)  # fmt: skip
    assert out.is_attack is False and meta.model == "scripted"  # preset `default` (không thẻ)
    assert await scalar(arw, "SELECT count(*) FROM llm_calls c JOIN spans s USING (span_id) WHERE s.turn_id = :t",
                        t=turn_id) == 1  # fmt: skip
