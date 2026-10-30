"""RQ2 — chạy lại đọc cache trong thư mục run, 0 lời gọi mạng: (a) qua gateway + `FileLlmStore`; (c) `LogprobClient` (+ httpx giả)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.core.clock import FakeClock
from app.eval.rq2.filestore import FileLlmStore, SpendLedger
from app.eval.rq2.logprob import (
    BudgetStop,
    HttpxTransport,
    LogprobClient,
    RequestCfg,
    body_sha256,
)
from app.eval.rq2.self_report import self_report
from app.llm.client import LLMClient
from app.llm.config import Price
from pydantic import SecretStr
from tests.fakes.llm import repo_registry, scripted_runtime
from tests.fakes.scripted_llm import Reply, ScriptedLLM
from tests.unit.eval.rq2_fakes import (
    FakeTransport,
    logprob_response,
    prompt_full,
    variables,
    vote_tokens,
)

ESTIMATE_OK = {"prob_needs_human": 0.35, "factors": ["new_employee"], "rationale": "thử việc"}
PRICE = Price.model_validate({"in": 0.3, "out": 1.2})
CFG = RequestCfg("deepseek-flash", 900, {"type": "json_object"}, {"thinking": {"type": "disabled"}})
WIRE = [{"role": "system", "content": "hệ thống"}, {"role": "user", "content": "người dùng"}]


def _client(run_dir: Path, llm: ScriptedLLM) -> tuple[LLMClient, FileLlmStore]:
    store = FileLlmStore(run_dir, SpendLedger(run_dir / "spend.jsonl"))
    client = LLMClient(runtime=scripted_runtime(), registry=repo_registry(), providers={"scripted": llm}, store=store,
                       clock=FakeClock(), eval_mode=True, cache_mode="eval")  # fmt: skip
    return client, store


@pytest.mark.asyncio
async def test_a_second_run_reads_cache_zero_network(tmp_path: Path) -> None:
    llm = ScriptedLLM({"b14_risk_estimate": [Reply(ESTIMATE_OK)]})
    first, _ = _client(tmp_path, llm)
    a = await self_report(first, variables())
    second, store2 = _client(tmp_path, llm)  # lần chạy 2: store mới, cùng thư mục run
    b = await self_report(second, variables())
    assert len(llm.calls) == 1
    assert a.p_a == b.p_a == 0.35 and a.error is None
    rows = store2.calls()
    assert [r["cache_hit"] for r in rows] == [False, True]
    assert rows[0]["prompt_id"] == "b14_risk_estimate" and rows[0]["prompt_full"] is not None
    assert len(list((tmp_path / "cache_a").glob("*.json"))) == 1
    assert rows[0]["prompt_full"] == prompt_full(repo_registry().get("b14_risk_estimate"), variables())  # đúng đầu vào B14


@pytest.mark.asyncio
async def test_a_temperature_zero_and_recoverable_error(tmp_path: Path) -> None:
    llm = ScriptedLLM({"b14_risk_estimate": [Reply("không phải json"), Reply("vẫn sai")]})
    client, _ = _client(tmp_path, llm)
    got = await self_report(client, variables())
    assert got.p_a is None and got.error == "LLMSchemaError"
    assert not (tmp_path / "cache_a").exists()  # lỗi không vào cache


@pytest.mark.asyncio
async def test_c_second_run_reads_cache_zero_network(tmp_path: Path) -> None:
    t = FakeTransport(lambda body: logprob_response(vote_tokens(0.7)))
    ledger = SpendLedger(tmp_path / "spend.jsonl")
    c1 = LogprobClient(t, tmp_path / "cache_c", ledger, PRICE, 2.0)
    r1 = await c1.fetch(CFG.body(WIRE))
    c2 = LogprobClient(t, tmp_path / "cache_c", ledger, PRICE, 2.0)
    r2 = await c2.fetch(CFG.body(WIRE))
    assert len(t.bodies) == 1 and (c1.network_calls, c2.network_calls, c2.cache_hits) == (1, 0, 1)
    assert r1 == r2
    assert (tmp_path / "cache_c" / f"{body_sha256(CFG.body(WIRE))}.json").exists()
    assert ledger.total() == pytest.approx(PRICE.cost(800, 20))


def test_c_body() -> None:
    body = CFG.body(WIRE)
    assert body["logprobs"] is True and body["top_logprobs"] == 5 and body["temperature"] == 0.0
    assert body["thinking"] == {"type": "disabled"} and body["response_format"] == {"type": "json_object"}
    with pytest.raises(ValueError, match="trùng"):
        RequestCfg("m", 9, {}, {"temperature": 1}).body(WIRE)


@pytest.mark.asyncio
async def test_c_budget_stop_before_network(tmp_path: Path) -> None:
    t = FakeTransport(lambda body: logprob_response(vote_tokens(0.7)))
    client = LogprobClient(t, tmp_path / "cache_c", SpendLedger(tmp_path / "spend.jsonl"), PRICE, 1e-6)
    with pytest.raises(BudgetStop):
        await client.fetch(CFG.body(WIRE))
    assert t.bodies == [] and client.network_calls == 0


@pytest.mark.asyncio
async def test_httpx_transport_key_only_in_header(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=logprob_response(vote_tokens(0.6)))

    key = "CANARY-RQ2-" + "x" * 8  # khoá giả (canary), không phải bí mật
    transport = HttpxTransport("https://api.example.test/", SecretStr(key), timeout_s=5,
                               client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))  # fmt: skip
    client = LogprobClient(transport, tmp_path / "cache_c", SpendLedger(tmp_path / "spend.jsonl"), PRICE, 2.0)
    await client.fetch(CFG.body(WIRE))
    await transport.aclose()
    assert str(seen[0].url) == "https://api.example.test/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {key}"
    sent: dict[str, Any] = json.loads(seen[0].content)
    assert key not in json.dumps(sent) and sent["logprobs"] is True
    assert all(key not in p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.asyncio
async def test_httpx_transport_error_status_only(tmp_path: Path) -> None:
    transport = HttpxTransport("https://api.example.test", SecretStr("sk-x"), timeout_s=5, client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(400, json={"error": {"message": "bí mật phản hồi"}}))))  # fmt: skip
    from app.eval.rq2.logprob import LogprobHttpError

    with pytest.raises(LogprobHttpError) as e:
        await transport.post({"model": "m"})
    assert str(e.value) == "HTTP 400" and "bí mật" not in repr(e.value)
    await transport.aclose()
