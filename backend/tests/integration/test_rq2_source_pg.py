"""RQ2 trên Postgres 16 thật: câu SQL chỉ đọc của `app.eval.rq2.source` (`fetch_vote_calls`, `fetch_cache`) trên dòng do CHÍNH
`SqlLlmStore` ghi (span + `llm_calls` + `llm_cache` mode eval), nối `llm_calls → spans → turns → ticket`. Không gọi LLM.

Câu SQL chạy như `Shell.sql`: transaction READ ONLY, kết quả JSON dạng chữ → `json.loads`.
"""

import importlib
import json
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest
import pytest_asyncio
from app.db.runtime import SqlTurnStore
from app.llm.ports import LlmCallRow, LlmSpan
from app.llm.store import SqlLlmStore
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import REQUESTER, seed_users
from tests.integration.pg import PgUrls

with mock.patch.dict(os.environ, {"EVAL_MODE": "true"}):  # app.eval chỉ import được khi EVAL_MODE=true (P8 §8)
    importlib.import_module("app.eval")

from app.eval.rq2.source import fetch_cache, fetch_vote_calls, rebuild
from app.eval.rq2.votes import p_from_votes, vote_key
from tests.unit.eval.rq2_fakes import (
    BUDGET_IN,
    cache_for,
    vote_calls,
    vote_prompt,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
VOTES = {0: True, 1: False, 2: True, 3: False, 4: False}  # 2/5


@pytest_asyncio.fixture
async def arw(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def ro_sql(rw: Engine) -> Iterator[Any]:
    def sql(query: str) -> Any:
        with rw.connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            value = conn.execute(text(f"SELECT (({query}))::text")).scalar()
            conn.rollback()
        return json.loads(value or "null")

    yield sql


async def _ticket_with_votes(engine: AsyncEngine, *, trimmed: int = 0, extra_other_prompt: bool = True) -> str:
    ticket_id, turn_id = f"rq2-{uuid4().hex[:12]}", f"turn-{uuid4().hex[:12]}"
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
                                "VALUES (:t, :u, 'employee', 'yêu cầu thử')"), {"t": ticket_id, "u": REQUESTER})  # fmt: skip
    await SqlTurnStore(engine).start(turn_id=turn_id, ticket_id=ticket_id, session_id=None, event_type="submit", at=NOW)
    store = SqlLlmStore(engine)
    calls = vote_calls()
    for c in calls:
        span = LlmSpan(span_id=uuid4().hex, trace_id="b" * 32, turn_id=turn_id, name="llm:b14_risk_vote", started_at=NOW,
                       parent_span_id=None, duration_ms=5, status="ok", attributes={"trimmed_evidence": trimmed})  # fmt: skip
        row = LlmCallRow(span_id=span.span_id, provider=c.provider, model=c.model, model_version=None, prompt_id="b14_risk_vote",
                         prompt_version=c.prompt_version, prompt_hash="c" * 64, prompt_full=c.prompt_full, tokens_in=10,
                         tokens_out=2, cost_usd=0.0, latency_ms=5, cache_hit=False, json_valid_first_try=True,
                         used_fallback=False, error=None)  # fmt: skip
        await store.record(span, row)
    for key, resp in cache_for(calls, VOTES).items():
        await store.cache_put(key, mode="eval", prompt_id="b14_risk_vote", prompt_version="1", model="deepseek-flash",
                              response=resp, now=NOW, expires_at=None)  # fmt: skip
    if extra_other_prompt:  # dòng prompt khác cùng lượt — không được lọt vào kết quả
        span = LlmSpan(span_id=uuid4().hex, trace_id="b" * 32, turn_id=turn_id, name="llm:b10_need_type", started_at=NOW,
                       parent_span_id=None, duration_ms=5, status="ok", attributes={})  # fmt: skip
        await store.record(span, LlmCallRow(span_id=span.span_id, provider="cloud_a", model="deepseek-flash", model_version=None,
                                            prompt_id="b10_need_type", prompt_version="1", prompt_hash="c" * 64, prompt_full="[]",
                                            tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1, cache_hit=False,
                                            json_valid_first_try=True, used_fallback=False, error=None))  # fmt: skip
    return ticket_id


async def test_rq2_pg_fetch_votes_and_cache_end_to_end(arw: AsyncEngine, ro_sql: Any) -> None:
    ticket_id = await _ticket_with_votes(arw)
    calls = fetch_vote_calls(ro_sql, ticket_id)
    assert len(calls) == 5 and all(c.trimmed_evidence == 0 and c.error is None for c in calls)
    assert calls == sorted(calls, key=lambda c: c.call_id)
    assert [c.prompt_full for c in calls] == [c.prompt_full for c in vote_calls()]  # prompt_full đọc ra đúng từng byte
    got = rebuild(ticket_id, calls, vote_prompt(), budget_in=BUDGET_IN)
    assert got.model == "deepseek-flash"
    cache = fetch_cache(ro_sql, [vote_key(c, model_version=None) for c in calls])
    assert len(cache) == 5
    r = p_from_votes(calls, cache, 0.4, model_version=None)
    assert (r.p_b, r.source) == (0.4, "votes")


async def test_rq2_pg_trimmed_from_span_attributes(arw: AsyncEngine, ro_sql: Any) -> None:
    ticket_id = await _ticket_with_votes(arw, trimmed=1, extra_other_prompt=False)
    assert {c.trimmed_evidence for c in fetch_vote_calls(ro_sql, ticket_id)} == {1}


async def test_rq2_pg_unknown_ticket_and_keys(ro_sql: Any, arw: AsyncEngine) -> None:
    assert fetch_vote_calls(ro_sql, "khong-co-ticket") == []
    assert fetch_cache(ro_sql, ["0" * 64]) == {}
