"""RQ2 (b) — p_b đọc lại từ phiếu S1 GIẢ (llm_cache giả), 0 lời gọi LLM; đối chiếu raw_prob điểm log 4."""

import pytest
from app.eval.rq2.collect import Deps, Leaf, collect
from app.eval.rq2.votes import p_from_votes, vote_key
from app.llm.cache import cache_key
from app.llm.schemas import RiskVoteOut
from tests.fakes.llm import make_gateway
from tests.fakes.scripted_llm import Reply
from tests.unit.eval.rq2_fakes import (
    BUDGET_IN,
    FakeSql,
    cache_for,
    vote_calls,
    vote_prompt,
)

VOTES = {0: True, 1: False, 2: True, 3: True, 4: False}  # 3/5


def test_vote_key_is_gateway_cache_key() -> None:
    c = vote_calls()[0]
    expected = cache_key(provider="cloud_a", model="deepseek-flash", model_version=None, prompt_id="b14_risk_vote", prompt_version="1",
                         messages=c.messages, json_schema=RiskVoteOut.model_json_schema(), temperature=0.7, n=1, kb_version=None,
                         mode="eval")  # fmt: skip
    assert vote_key(c, model_version=None) == expected


def test_p_b_from_votes() -> None:
    calls = vote_calls()
    r = p_from_votes(calls, cache_for(calls, VOTES), 0.6, model_version=None)
    assert (r.p_b, r.source, r.reason) == (0.6, "votes", None)
    assert r.votes is not None and sum(r.votes) == 3


def test_audit_mismatch_rejected() -> None:
    calls = vote_calls()
    r = p_from_votes(calls, cache_for(calls, VOTES), 0.8, model_version=None)
    assert (r.p_b, r.reason) == (None, "audit_mismatch")


def test_missing_vote_cache() -> None:
    calls = vote_calls()
    cache = cache_for(calls, VOTES)
    cache.pop(next(iter(cache)))
    assert p_from_votes(calls, cache, 0.6, model_version=None).reason == "vote_cache_missing"
    fallback = p_from_votes(calls, cache, 0.6, model_version=None, allow_audit=True)
    assert (fallback.p_b, fallback.source) == (0.6, "audit_raw_prob")


def test_model_version_changes_key() -> None:
    calls = vote_calls()
    assert p_from_votes(calls, cache_for(calls, VOTES), 0.6, model_version="v9").reason == "vote_cache_missing"
    assert p_from_votes(calls, cache_for(calls, VOTES, model_version="v9"), 0.6, model_version="v9").p_b == 0.6


@pytest.mark.asyncio
async def test_b_from_fake_s1_zero_llm_calls() -> None:
    """(b) không gọi LLM: gateway có mặt cho (a) nhưng KHÔNG có lời gọi `b14_risk_vote` nào; không có gateway thì p_b vẫn ra."""
    calls = vote_calls()
    sql = FakeSql({"tk-1": calls}, cache_for(calls, VOTES))
    leaf = Leaf("tk-1", "S-1", "HB01", 3, True, 0.6)
    rows = await collect(Deps(sql=sql, vote_prompt=vote_prompt(), budget_in=BUDGET_IN, model_version=None), [leaf])
    assert rows[0]["p_b"] == 0.6 and rows[0]["reasons"]["a"] == "not_run" and "p_c" not in rows[0]

    gw = make_gateway({"b14_risk_estimate": [Reply({"prob_needs_human": 0.3, "factors": [], "rationale": "x"})]},
                      eval_mode=True, cache_mode="eval")  # fmt: skip
    deps = Deps(sql=sql, vote_prompt=vote_prompt(), budget_in=BUDGET_IN, model_version=None, model="deepseek-flash", llm=gw.client)
    rows = await collect(deps, [leaf])
    assert rows[0]["p_b"] == 0.6 and rows[0]["p_a"] == 0.3
    assert gw.llm.calls_for("b14_risk_vote") == []
    assert len(gw.llm.calls_for("b14_risk_estimate")) == 1


@pytest.mark.asyncio
async def test_a_skipped_on_model_mismatch() -> None:
    calls = vote_calls()
    sql = FakeSql({"tk-1": calls}, cache_for(calls, VOTES))
    gw = make_gateway({}, eval_mode=True, cache_mode="eval")
    deps = Deps(sql=sql, vote_prompt=vote_prompt(), budget_in=BUDGET_IN, model_version=None, model="model-khac", llm=gw.client)
    rows = await collect(deps, [Leaf("tk-1", "S-1", "HB01", 3, True, 0.6)])
    assert rows[0]["reasons"]["a"] == "model_mismatch" and rows[0]["p_a"] is None
    assert gw.llm.calls == []
