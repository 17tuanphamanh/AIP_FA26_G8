"""RQ2 (c) — token quyết định `needs_human`, hàm kiểm khả thi; API không trả logprobs → "(c) không khả thi", không cột p_c giả."""

from pathlib import Path
from typing import Any

import pytest
from app.eval.rq2.collect import CRun, Deps, Leaf, c_summary, collect
from app.eval.rq2.filestore import SpendLedger
from app.eval.rq2.logprob import (
    LogprobClient,
    RequestCfg,
    check_logprobs_feasible,
    decisive_p,
)
from app.eval.rq2.report import (
    C_PROBE_SHA256,
    c_feasibility_note,
    methods_present,
    per_ticket_csv,
)
from app.llm.config import Price
from tests.unit.eval.rq2_fakes import (
    BUDGET_IN,
    FakeSql,
    FakeTransport,
    cache_for,
    logprob_response,
    vote_calls,
    vote_prompt,
    vote_tokens,
)

PRICE = Price.model_validate({"in": 0.3, "out": 1.2})
VOTES = {0: True, 1: True, 2: False, 3: True, 4: False}


def test_decisive_p_normalised_over_true_false() -> None:
    d = decisive_p(logprob_response(vote_tokens(0.7)))
    assert d.position == 4 and d.reason is None
    assert d.p == pytest.approx(0.7 / (0.7 + 0.29), abs=1e-9)  # " tr" (cắt giữa chữ) không tính
    assert (d.n_true, d.n_false) == (1, 1)


def test_decisive_p_when_false_chosen_and_colon_merged() -> None:
    tokens = [('{"needs_human', {'{"needs_human': 1.0}), ('": false', {'": false': 0.6, '": true': 0.3, '": "': 0.1}),
              ("}", {"}": 1.0})]  # fmt: skip
    d = decisive_p(logprob_response(tokens))
    assert d.position == 1 and d.p == pytest.approx(0.3 / 0.9, abs=1e-9)


def test_decisive_p_key_after_factors() -> None:
    tokens = [('{"factors": [], "', {'{"factors": [], "': 1.0}), ("needs_human", {"needs_human": 1.0}), ('":', {'":': 1.0}),
              ("true", {"true": 0.9, "false": 0.1}), ("}", {"}": 1.0})]  # fmt: skip
    assert decisive_p(logprob_response(tokens)).p == pytest.approx(0.9, abs=1e-9)


@pytest.mark.parametrize(
    ("resp", "reason"),
    [
        ({"choices": [{"message": {"content": "{}"}, "logprobs": None}]}, "no_logprobs"),
        ({"choices": [{"message": {"content": "{}"}}]}, "no_logprobs"),
        ({"choices": []}, "no_logprobs"),
        (logprob_response([('{"factors": []}', {'{"factors": []}': 1.0})]), "no_decision_token"),
    ],
    ids=["logprobs_null", "khong_khoa", "khong_choices", "khong_needs_human"],
)
def test_no_decision(resp: dict[str, Any], reason: str) -> None:
    d = decisive_p(resp)
    assert d.p is None and d.reason == reason
    assert check_logprobs_feasible(resp).ok is False


def test_feasibility_evidence_has_counts_not_content() -> None:
    f = check_logprobs_feasible(logprob_response(vote_tokens(0.7)))
    assert f.ok and f.evidence["content_tokens"] == 7 and f.evidence["decision_found"] is True
    assert "needs_human" not in str(f.evidence)


def _deps(tmp_path: Path, respond: Any, calls_by_ticket: dict[str, Any]) -> tuple[Deps, FakeTransport]:
    cache: dict[str, Any] = {}
    for calls in calls_by_ticket.values():
        cache.update(cache_for(calls, VOTES))
    t = FakeTransport(respond)
    client = LogprobClient(t, tmp_path / "cache_c", SpendLedger(tmp_path / "spend.jsonl"), PRICE, 2.0)
    c = CRun(client, RequestCfg("deepseek-flash", 900, {"type": "json_object"}), wire=lambda m: m)
    return Deps(sql=FakeSql(calls_by_ticket, cache), vote_prompt=vote_prompt(), budget_in=BUDGET_IN, model_version=None,
                model="deepseek-flash", c=c), t  # fmt: skip


LEAVES = [Leaf("tk-1", "S-1", "HB01", 1, True, 0.6), Leaf("tk-2", "S-2", "HB02", 2, False, 0.6)]


@pytest.mark.asyncio
async def test_c_infeasible_no_p_c_column(tmp_path: Path) -> None:
    no_lp = {"model": "deepseek-flash", "choices": [{"message": {"content": '{"needs_human": true}'}, "logprobs": None}]}
    deps, t = _deps(tmp_path, lambda body: no_lp, {"tk-1": vote_calls(), "tk-2": vote_calls()})
    rows = await collect(deps, LEAVES)
    assert len(t.bodies) == 1  # một lời gọi kiểm khả thi, rồi dừng (c)
    assert all("p_c" not in r and "c" not in r["reasons"] for r in rows)
    s = c_summary(deps.c)
    assert s["status"] == "infeasible" and "không khả thi" in s["note"]
    assert s["feasibility"]["evidence"]["logprobs_present"] is False
    assert methods_present(rows) == ["a", "b"]
    assert "p_c" not in per_ticket_csv(rows, {"a": {}, "b": {}}, ["a", "b"]).splitlines()[0]


@pytest.mark.asyncio
async def test_c_feasible_uses_vote0_messages(tmp_path: Path) -> None:
    calls = vote_calls()
    deps, t = _deps(tmp_path, lambda body: logprob_response(vote_tokens(0.8)), {"tk-1": calls, "tk-2": vote_calls()})
    rows = await collect(deps, LEAVES)
    assert c_summary(deps.c)["status"] == "feasible"
    assert [r["p_c"] for r in rows] == [pytest.approx(0.8 / 0.99)] * 2
    zero = next(c for c in calls if "số 0." in c.messages[1]["content"])
    assert t.bodies[0]["messages"] == zero.messages  # NGUYÊN messages phiếu sample_idx 0 của S1
    assert methods_present(rows) == ["a", "b", "c"]


def test_c_feasibility_note_both_branches() -> None:
    yes = c_feasibility_note("deepseek-flash")
    assert yes.startswith("(c) khả thi: lời gọi thử 30/10 trả logprobs") and C_PROBE_SHA256 in yes
    no = c_feasibility_note("deepseek-v4-pro")
    assert "CHƯA kiểm trên model B14 (deepseek-v4-pro)" in no and "D1 31/10" in no and C_PROBE_SHA256 not in no
