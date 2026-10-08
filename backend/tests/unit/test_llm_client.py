"""LLMClient.complete (PLAN-3d S3–S4): d1 (P2 §13 dòng 1–7), d4, d5, d6, d8, d9, d14, d17 + hợp đồng node, chặn mạng.

Không test nào gọi LLM thật. Đếm ở NƠI NHẬN (phase3 3.9): `ScriptedLLM.calls` hoặc handler của `httpx2.MockTransport`
(SDK openai 3.x dùng httpx2 — respx không chặn được, chốt DỪNG 1). Đồng hồ `FakeClock`: backoff/Retry-After tua ngay.
"""

import json
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from app.core.clock import FakeClock
from app.llm.cache import cache_key
from app.llm.config import Price, RoleCfg, RuntimeLlm, Target
from app.llm.errors import (
    LLMBudgetExceeded,
    LLMSchemaError,
    LLMUnavailable,
    PromptContractError,
    PromptVariableError,
)
from app.llm.ports import TraceParent
from app.llm.providers.base import ProviderRequest, parse_retry_after
from app.llm.providers.openai_compat import OpenAICompatProvider
from app.llm.registry import load_prompts
from app.llm.schemas import AnswerOut, InjectionJudgeOut, NeedTypeOut, QuestionOut
from app.llm.wiring import check_llm
from app.settings import Settings
from pydantic import SecretStr
from tests.fakes.llm import (
    REPO_CONFIG,
    MemoryLlmStore,
    make_gateway,
    repo_registry,
    scripted_runtime,
)
from tests.fakes.scripted_llm import (
    BadJSON,
    Http,
    Reply,
    ScriptedLLM,
    ScriptExhausted,
    Timeout,
    Unavailable,
)

PRICE = Price.model_validate({"in": 0.25, "out": 1.0})
FREE = Price.model_validate({"in": 0, "out": 0})
NEED = {"text": "làm sao gia hạn chứng chỉ VPN", "evidence_titles": ["Gia hạn chứng chỉ VPN"]}
NEED_OK = {"type": "info", "confidence": 0.9}
EVIDENCE = [{"anchor_chunk_id": "KB-VPN-003#1", "title": "Gia hạn", "heading_path": "Các bước", "text": "Mở ứng dụng.",
             "score": 0.8}]  # fmt: skip
ANSWER_VARS = {"question": "gia hạn chứng chỉ VPN thế nào", "evidence": EVIDENCE}
ANSWER_OK = {"answer_markdown": "Mở ứng dụng VPN.", "citations": ["KB-VPN-003#1"]}


def runtime(
    fast: tuple[Target, ...],
    strong: tuple[Target, ...] | None = None,
    *,
    roles: dict[str, dict[str, Any]] | None = None,
) -> RuntimeLlm:
    """Cấu hình dựng tay (bỏ qua validator của llm.yaml) — để thử cả trường hợp validator đã chặn (vd. strong fallback).
    `roles` ghi đè tham số vai trò, vd. `{"fast": {"max_retries": 100}}`."""
    base = scripted_runtime()
    over = roles or {}
    cfg: dict[str, RoleCfg] = {r: base.roles[r].model_copy(update=over.get(r, {})) for r in ("fast", "strong")}
    chains = {"fast": fast, "strong": strong if strong is not None else fast[:1]}
    return RuntimeLlm("real", cfg, chains, base.limits, base.spend, base.cache)  # type: ignore[arg-type]


def target(provider: str, price: Price | None = PRICE, model: str | None = None) -> Target:
    return Target(provider, model or f"m-{provider}", None, price)


class Server:
    """Máy chủ giả sau `httpx2.MockTransport`: trả lần lượt (phần tử cuối lặp lại), ghi mọi request nhận được."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def ok(content: dict[str, Any] | str, *, tokens: tuple[int, int] = (100, 10)) -> httpx2.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx2.Response(200, json={
        "id": "x", "object": "chat.completion", "created": 0, "model": "m-cloud_a-2026",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1], "total_tokens": sum(tokens)},
    })  # fmt: skip


def openai_provider(server: Server, name: str = "cloud_a", base_url: str = "http://llm.test/v1",
                    json_mode: str = "json_schema") -> OpenAICompatProvider:  # fmt: skip
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(server.handler))
    return OpenAICompatProvider(name, base_url=base_url, api_key=SecretStr("k-test"), json_mode=json_mode,
                                http_client=client)  # fmt: skip


def scripted(name: str, *steps: Any) -> ScriptedLLM:
    """ScriptedLLM tên `name`, mọi prompt dùng chung hàng đợi `steps` (phần tử cuối lặp lại)."""
    queue = list(steps)

    def step(_: Any) -> Any:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    ids = ("b02_injection_judge", "b03_classify", "b10_need_type", "b10_answer", "b11_clarify_question",
           "b11_extract_slots")  # fmt: skip
    return ScriptedLLM(dict.fromkeys(ids, step), name=name)


# ---- khói: đầu-cuối ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_scripted_end_to_end() -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]})
    out, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert out == NeedTypeOut(type="info", confidence=0.9)
    assert (meta.provider, meta.model, meta.prompt_id, meta.prompt_version) == ("scripted", "scripted",
                                                                                "b10_need_type", "1")
    assert meta.json_valid_first_try and not meta.cache_hit and meta.cost_usd == 0
    assert meta.prompt_hash == repo_registry().get("b10_need_type").sha256
    assert len(gw.llm.calls) == 1 and len(gw.store.rows) == 1 and len(gw.store.spans) == 1
    assert gw.store.spans[0].name == "llm:b10_need_type" and gw.store.rows[0].span_id == meta.span_id


@pytest.mark.asyncio
async def test_smoke_openai_compat_through_gateway() -> None:
    server = Server(ok({"type": "action", "confidence": 0.8}, tokens=(120, 10)))
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": openai_provider(server)})
    out, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    (body,) = server.bodies()
    assert out.type == "action"
    assert body["model"] == "m-cloud_a" and body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "NeedTypeOut"
    assert (body["max_tokens"], body["temperature"]) == (400, 0)
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert (meta.tokens_in, meta.tokens_out, meta.model_version) == (120, 10, "m-cloud_a-2026")
    assert meta.cost_usd == pytest.approx((120 * 0.25 + 10 * 1.0) / 1e6)


@pytest.mark.asyncio
async def test_openai_compat_json_object_mode() -> None:
    server = Server(ok(NEED_OK))
    gw = make_gateway(runtime=runtime((target("cloud_a"),)),
                      providers={"cloud_a": openai_provider(server, json_mode="json_object")})  # fmt: skip
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert server.bodies()[0]["response_format"] == {"type": "json_object"}


# ---- LLM-JSON: json_object không mang schema → schema nằm trong system message (DeepSeek: chỉ json_object, prompt phải
# có chữ "json") -----------------------------------------------------------------------------------------------------

SCHEMA = NeedTypeOut.model_json_schema()
SCHEMA_TEXT = json.dumps(SCHEMA, ensure_ascii=False)


def provider_req(messages: list[dict[str, str]]) -> ProviderRequest:
    return ProviderRequest(
        prompt_id="b10_need_type", model="m-cloud_a", messages=messages, json_schema=SCHEMA,
        schema_name="NeedTypeOut", max_tokens=400, temperature=0, timeout_s=8.0, attempt=0, variables={}, trace=None,
    )  # fmt: skip


@pytest.mark.asyncio
async def test_json_object_appends_schema_to_system_message() -> None:
    server = Server(ok(NEED_OK))
    messages = [{"role": "system", "content": "Phân loại nhu cầu."}, {"role": "user", "content": "gia hạn VPN"}]
    before = json.loads(json.dumps(messages))
    req = provider_req(messages)
    await openai_provider(server, json_mode="json_object").chat(req)
    sent = server.bodies()[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert sent[0]["content"].startswith("Phân loại nhu cầu.")  # đoạn thêm nằm ở CUỐI system message
    assert sent[0]["content"].endswith(SCHEMA_TEXT) and "json" in sent[0]["content"]
    assert sent[1] == before[1]
    assert req.messages is messages and messages == before  # không sửa tại chỗ


@pytest.mark.asyncio
async def test_json_object_without_system_message_inserts_one_first() -> None:
    server = Server(ok(NEED_OK))
    messages = [{"role": "user", "content": "gia hạn VPN"}]
    await openai_provider(server, json_mode="json_object").chat(provider_req(messages))
    sent = server.bodies()[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert SCHEMA_TEXT in sent[0]["content"] and "json" in sent[0]["content"]
    assert sent[1] == {"role": "user", "content": "gia hạn VPN"} and messages == [sent[1]]


@pytest.mark.asyncio
async def test_json_schema_mode_sends_messages_unchanged() -> None:
    server = Server(ok(NEED_OK))
    messages = [{"role": "system", "content": "Phân loại nhu cầu."}, {"role": "user", "content": "gia hạn VPN"}]
    await openai_provider(server).chat(provider_req(messages))
    (body,) = server.bodies()
    assert body["messages"] == messages
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA


@pytest.mark.asyncio
async def test_json_object_through_gateway_carries_schema() -> None:
    server = Server(ok(NEED_OK))
    gw = make_gateway(runtime=runtime((target("cloud_a"),)),
                      providers={"cloud_a": openai_provider(server, json_mode="json_object")})  # fmt: skip
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    system = server.bodies()[0]["messages"][0]
    assert system["role"] == "system" and SCHEMA_TEXT in system["content"]


def test_smoke_check_llm_scripted_loads_presets() -> None:
    setup = check_llm(Settings(_env_file=None, app_env="test", llm_backend="scripted"))  # type: ignore[call-arg]
    assert setup.presets is not None and "default" in setup.presets
    assert set(setup.presets["default"]) == {p.id for p in setup.registry}  # default đủ 6 prompt


# ---- d1 (P2 §13) -------------------------------------------------------------------------------------


KEY_PARTS: dict[str, Any] = {
    "provider": "cloud_a", "model": "m1", "model_version": None, "prompt_id": "b10_answer", "prompt_version": "1",
    "messages": [{"role": "user", "content": "x"}], "json_schema": {"type": "object"}, "temperature": 0.0, "n": 1,
    "kb_version": None, "mode": "runtime",
}  # fmt: skip
KEY_CHANGES: dict[str, Any] = {
    "provider": "cloud_b", "model": "m2", "model_version": "2026-01", "prompt_id": "b10_need_type",
    "prompt_version": "2", "messages": [{"role": "user", "content": "y"}], "json_schema": {"type": "array"},
    "temperature": 0.5, "n": 2, "kb_version": "a" * 64, "mode": "eval",
}  # fmt: skip


@pytest.mark.parametrize("part", sorted(KEY_CHANGES))
def test_d1a_every_key_component_changes_key(part: str) -> None:
    assert set(KEY_CHANGES) == set(KEY_PARTS)  # đủ 11 thành phần (P2 §8 + mode, Q-3d-9)
    assert cache_key(**KEY_PARTS) != cache_key(**{**KEY_PARTS, part: KEY_CHANGES[part]})
    assert cache_key(**KEY_PARTS) == cache_key(**dict(KEY_PARTS))


@pytest.mark.asyncio
async def test_d1b_b14_whitelist_rejects_user_text() -> None:
    registry = load_prompts(REPO_CONFIG.parent / "backend" / "tests" / "fixtures" / "llm" / "prompts")
    gw = make_gateway({"b14_risk_estimate": [Reply({"text": "x"})]}, registry=registry)
    ok_vars: dict[str, Any] = {"intended_action": {}, "requester_context": {}, "diagnostics": {}, "retrieved": []}
    for leak in ("redacted_request", "conversation"):
        with pytest.raises(PromptVariableError, match=leak):
            await gw.client.complete("strong", "b14_risk_estimate", {**ok_vars, leak: "câu người dùng"}, QuestionOut)
    assert gw.llm.calls == []  # chặn ngay khi render, trước provider


@pytest.mark.asyncio
async def test_d1c_429_twice_then_200_respects_retry_after() -> None:
    too_many = httpx2.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "chậm lại"}})
    server = Server(too_many, too_many, ok(NEED_OK))
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": openai_provider(server)})
    out, _ = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert out.type == "info"
    assert len(server.requests) == 3
    assert gw.clock.sleeps == [2.0, 2.0]  # đúng Retry-After, không backoff/jitter


@pytest.mark.asyncio
async def test_d1d_bad_json_repaired_once() -> None:
    gw = make_gateway({"b10_need_type": [BadJSON("đây không phải JSON"), Reply(NEED_OK)]})
    out, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert out.type == "info" and meta.json_valid_first_try is False
    first, second = gw.llm.calls
    assert len(second.rendered_messages) == len(first.rendered_messages) + 2
    assert second.rendered_messages[-2] == {"role": "assistant", "content": "đây không phải JSON"}
    assert "không đúng schema" in second.rendered_messages[-1]["content"]
    assert gw.store.rows[0].json_valid_first_try is False


@pytest.mark.asyncio
async def test_d1d_still_bad_after_repair_is_schema_error_without_fallback() -> None:
    a = scripted("cloud_a", Reply({"type": "maybe", "confidence": 2}))
    b = scripted("cloud_b", Reply(NEED_OK))
    gw = make_gateway(runtime=runtime((target("cloud_a"), target("cloud_b"))), providers={"cloud_a": a, "cloud_b": b})
    with pytest.raises(LLMSchemaError, match="sau 1 lần sửa"):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert len(a.calls) == 2 and b.calls == []  # sai schema không phải lỗi hạ tầng → không fallback
    assert gw.store.rows[0].error == "LLMSchemaError"


@pytest.mark.asyncio
async def test_d1e_strong_no_fallback_even_if_configured() -> None:
    a = scripted("cloud_a", Http(503))
    b = scripted("cloud_b", Reply(ANSWER_OK))
    local = scripted("local", Reply(ANSWER_OK))
    rt = runtime((target("cloud_a"),), strong=(target("cloud_a"), target("local", FREE), target("cloud_b")))
    gw = make_gateway(runtime=rt, providers={"cloud_a": a, "cloud_b": b, "local": local})
    with pytest.raises(LLMUnavailable):
        await gw.client.complete("strong", "b10_answer", ANSWER_VARS, AnswerOut)
    assert len(a.calls) == 2  # strong: max_retries=1 → 2 lần thử
    assert b.calls == [] and local.calls == []  # P2 §5: KHÔNG local, KHÔNG provider khác
    assert gw.store.rows[0].used_fallback is False


@pytest.mark.asyncio
async def test_d1f_spend_cap_blocks_paid_but_cache_and_free_still_run() -> None:
    a = scripted("cloud_a", Reply(ANSWER_OK))
    local = scripted("local", Reply(NEED_OK))
    store = MemoryLlmStore()
    rt = runtime((target("cloud_a"), target("local", FREE)), strong=(target("cloud_a"),))
    gw = make_gateway(runtime=rt, providers={"cloud_a": a, "local": local}, store=store)
    await gw.client.complete("strong", "b10_answer", ANSWER_VARS, AnswerOut)  # dưới trần → gọi, ghi cache
    assert len(a.calls) == 1
    store.base_spend = 38.0  # chạm cap_usd
    gw.clock.advance(timedelta(seconds=61))  # qua refresh_s → đọc lại tổng
    _, meta = await gw.client.complete("strong", "b10_answer", ANSWER_VARS, AnswerOut)
    assert meta.cache_hit and len(a.calls) == 1  # cache hit vẫn chạy, chi phí 0
    with pytest.raises(LLMBudgetExceeded, match="trần chi tiêu"):
        await gw.client.complete("strong", "b10_answer", {**ANSWER_VARS, "question": "câu khác"}, AnswerOut)
    _, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert (meta.provider, meta.used_fallback) == ("local", True)  # đích giá 0 vẫn chạy
    assert len(a.calls) == 1 and len(local.calls) == 1


@pytest.mark.asyncio
async def test_d1g_fast_fallback_chain_in_order() -> None:
    a = scripted("cloud_a", Http(503))
    local = scripted("local", Unavailable())
    b = scripted("cloud_b", Reply(NEED_OK))
    rt = runtime((target("cloud_a"), target("local", FREE), target("cloud_b")))
    gw = make_gateway(runtime=rt, providers={"cloud_a": a, "local": local, "cloud_b": b})
    _, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert (len(a.calls), len(local.calls), len(b.calls)) == (4, 4, 1)  # fast: 1 + 3 lần thử lại mỗi đích
    assert (meta.provider, meta.used_fallback) == ("cloud_b", True)
    row = gw.store.rows[0]
    assert (row.provider, row.used_fallback) == ("cloud_b", True)
    assert gw.store.spans[0].attributes["failures"][:2] == ["cloud_a:http:503", "cloud_a:http:503"]


@pytest.mark.asyncio
async def test_d1_non_retryable_status_goes_straight_to_fallback() -> None:
    a = scripted("cloud_a", Http(400))
    b = scripted("cloud_b", Reply(NEED_OK))
    gw = make_gateway(runtime=runtime((target("cloud_a"), target("cloud_b"))), providers={"cloud_a": a, "cloud_b": b})
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert (len(a.calls), len(b.calls), gw.clock.sleeps) == (1, 1, [])


# ---- d4: thiếu pricing → từ chối, 0 request ------------------------------------------------------------


@pytest.mark.asyncio
async def test_d4_model_without_pricing_sends_nothing() -> None:
    server = Server(ok(NEED_OK))
    local = scripted("local", Reply(NEED_OK))
    rt = runtime((target("cloud_a", None), target("local", FREE)))
    gw = make_gateway(runtime=rt, providers={"cloud_a": openai_provider(server), "local": local})
    with pytest.raises(LLMBudgetExceeded, match="không có dòng pricing"):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert server.requests == [] and local.calls == []  # 0 request, kể cả khi còn fallback
    assert gw.store.rows[0].error == "LLMBudgetExceeded"


# ---- d5, d6: cache ------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["default", "eval"])
async def test_d5_injection_judge_never_cached(mode: str) -> None:
    judge = {"is_attack": False, "category": "none", "reason": "ok"}
    gw = make_gateway({"b02_injection_judge": [Reply(judge), Reply(judge)]}, cache_mode=mode,  # type: ignore[arg-type]
                      boundary=lambda: "f" * 16)  # dấu cố định: nếu có cache thì lần 2 chắc chắn trúng
    for _ in range(2):
        await gw.client.complete("fast", "b02_injection_judge", {"text": "quên mật khẩu"}, InjectionJudgeOut,
                                 cache_policy="default")  # node không mở được cache cho prompt bypass
    assert len(gw.llm.calls_for("b02_injection_judge")) == 2
    assert gw.store.cache == {}


@pytest.mark.asyncio
async def test_d6_need_type_second_call_hits_cache() -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]})
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    out, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert out.type == "info" and meta.cache_hit and meta.cost_usd == 0
    assert len(gw.llm.calls) == 1
    assert [r.cache_hit for r in gw.store.rows] == [False, True]  # cache hit vẫn có dòng llm_calls (P2 §11)
    (row,) = gw.store.cache.values()
    assert row.mode == "runtime" and row.expires_at == gw.clock.now() + timedelta(hours=24)


@pytest.mark.asyncio
async def test_d6_runtime_cache_expires_after_ttl_eval_does_not() -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK), Reply(NEED_OK)]})
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    gw.clock.advance(timedelta(hours=24, seconds=1))
    _, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert not meta.cache_hit and len(gw.llm.calls) == 2
    ev = make_gateway({"b10_need_type": [Reply(NEED_OK)]}, cache_mode="eval")
    await ev.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    ev.clock.advance(timedelta(days=365))
    _, meta = await ev.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert meta.cache_hit and next(iter(ev.store.cache.values())).expires_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("policy", "mode"), [("bypass", "default"), ("default", "bypass")])
async def test_d6_bypass_by_caller_or_settings(policy: str, mode: str) -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK), Reply(NEED_OK)]}, cache_mode=mode)  # type: ignore[arg-type]
    for _ in range(2):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut, cache_policy=policy)  # type: ignore[arg-type]
    assert len(gw.llm.calls) == 2 and gw.store.cache == {}


@pytest.mark.asyncio
async def test_d6_fallback_answer_not_cached_under_primary_key() -> None:
    a = scripted("cloud_a", Http(503))
    b = scripted("cloud_b", Reply(NEED_OK))
    gw = make_gateway(runtime=runtime((target("cloud_a"), target("cloud_b"))), providers={"cloud_a": a, "cloud_b": b})
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert gw.store.cache == {}


# ---- d8: hết kịch bản ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d8_script_exhausted_is_not_llm_unavailable() -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]})
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut, cache_policy="bypass")
    with pytest.raises(ScriptExhausted, match="hết kịch bản"):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut, cache_policy="bypass")
    with pytest.raises(ScriptExhausted, match="không có kịch bản"):
        await gw.client.complete("fast", "b11_clarify_question",
                                 {"missing": ["device_id"], "diagnostics_summary": "", "intent": "vpn"}, QuestionOut)
    assert len(gw.llm.calls) == 3  # không retry ScriptExhausted
    assert [r.error for r in gw.store.rows] == [None, "ScriptExhausted", "ScriptExhausted"]


# ---- d9: trace — 1 span + 1 dòng mỗi lời gọi, không văn bản prompt -----------------------------------------


CANARY = "CANARY-7f3a-mat-khau-Abc123"


@pytest.mark.asyncio
async def test_d9_one_span_one_row_per_call_no_prompt_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    parent = TraceParent("turn-1", "trace-1", "span-node")
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK), Http(400), BadJSON(CANARY), BadJSON(CANARY)]},
                      trace=lambda: parent)  # fmt: skip
    variables = {**NEED, "text": f"xin gia hạn, mật khẩu {CANARY}"}
    await gw.client.complete("fast", "b10_need_type", variables, NeedTypeOut)  # ok
    await gw.client.complete("fast", "b10_need_type", variables, NeedTypeOut)  # cache hit
    other = {**variables, "evidence_titles": ["khác"]}
    errors = []
    for exc in (LLMUnavailable, LLMSchemaError):
        with pytest.raises(exc) as e:
            await gw.client.complete("fast", "b10_need_type", other, NeedTypeOut, cache_policy="bypass")
        errors.append(str(e.value))
    assert len(gw.store.spans) == len(gw.store.rows) == 4
    assert [s.name for s in gw.store.spans] == ["llm:b10_need_type"] * 4
    assert [r.span_id for r in gw.store.rows] == [s.span_id for s in gw.store.spans]
    for s in gw.store.spans:
        assert (s.turn_id, s.trace_id, s.parent_span_id, s.span_type) == ("turn-1", "trace-1", "span-node", "llm")
    assert [r.error for r in gw.store.rows] == [None, None, "LLMUnavailable", "LLMSchemaError"]
    assert all(r.prompt_full is None for r in gw.store.rows)  # EVAL_MODE=false
    blob = repr(gw.store.rows) + repr(gw.store.spans) + caplog.text + " ".join(errors)
    assert CANARY not in blob and "mật khẩu" not in blob


@pytest.mark.asyncio
async def test_d9_eval_mode_keeps_full_prompt() -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]}, eval_mode=True)
    await gw.client.complete("fast", "b10_need_type", {**NEED, "text": CANARY}, NeedTypeOut)
    full = gw.store.rows[0].prompt_full
    assert full is not None and CANARY in full and json.loads(full)[0]["role"] == "system"


@pytest.mark.asyncio
async def test_d9_sql_like_store_refuses_call_outside_graph_turn() -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]}, store=MemoryLlmStore(requires_trace=True))
    with pytest.raises(RuntimeError, match="ngoài lượt graph"):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert gw.llm.calls == [] and gw.store.rows == []


@pytest.mark.asyncio
async def test_d9_trace_write_failure_does_not_fail_call(caplog: pytest.LogCaptureFixture) -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]}, store=MemoryLlmStore(fail_record=True))
    out, _ = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert out.type == "info" and "ConnectionError" in caplog.text


# ---- d14: deadline — retry dừng khi hết hạn (mỗi vai trò) ----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "prompt_id", "variables", "schema"), [
    ("fast", "b10_need_type", NEED, NeedTypeOut),
    ("strong", "b10_answer", ANSWER_VARS, AnswerOut),
])  # fmt: skip
async def test_d14_retry_stops_at_deadline(role: str, prompt_id: str, variables: dict[str, Any],
                                           schema: Any) -> None:  # fmt: skip
    deadline_s = scripted_runtime().roles[role].deadline_s  # type: ignore[index]
    clock = FakeClock()
    llm = ScriptedLLM({prompt_id: lambda _: Timeout()}, clock=clock)  # Timeout() tua đồng hồ đúng timeout_s
    gw = make_gateway(runtime=runtime((target("scripted"),), strong=(target("scripted"),),
                                      roles={role: {"max_retries": 100}}),
                      providers={"scripted": llm}, clock=clock)  # max_retries 100: chỉ deadline dừng được retry
    start = clock.now()
    with pytest.raises(LLMUnavailable, match="deadline"):
        await gw.client.complete(role, prompt_id, variables, schema)  # type: ignore[arg-type]
    elapsed = (gw.clock.now() - start).total_seconds()
    assert elapsed <= deadline_s
    assert 1 < len(llm.calls) < 101
    assert gw.store.spans[0].attributes["failures"][-1] == "deadline"


@pytest.mark.asyncio
async def test_d14_retry_after_beyond_deadline_does_not_sleep() -> None:
    llm = ScriptedLLM({"b10_need_type": [Http(429, retry_after=3600)]})
    gw = make_gateway(runtime=runtime((target("scripted"),)), providers={"scripted": llm})
    with pytest.raises(LLMUnavailable):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert gw.clock.sleeps == [] and len(llm.calls) == 1


@pytest.mark.parametrize(("value", "expected"), [
    ("2", 2.0), ("0.5", 0.5), ("0", 0.0), ("-1", None), ("abc", None), ("", None), (None, None),
    ("Thu, 01 Jan 2026 00:00:10 GMT", 10.0), ("Wed, 31 Dec 2025 23:59:50 GMT", None),
])  # fmt: skip
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value, now=datetime(2026, 1, 1, tzinfo=UTC)) == expected


# ---- d17: trần chi tiêu ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d17_spend_read_failure_blocks_paid_targets_only() -> None:
    a = scripted("cloud_a", Reply(NEED_OK))
    local = scripted("local", Reply(NEED_OK))
    store = MemoryLlmStore(fail_spend=True)
    rt = runtime((target("cloud_a"), target("local", FREE)), strong=(target("cloud_a"),))
    gw = make_gateway(runtime=rt, providers={"cloud_a": a, "local": local}, store=store)
    _, meta = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert (meta.provider, len(a.calls), len(local.calls)) == ("local", 0, 1)
    with pytest.raises(LLMUnavailable, match="spend_unknown"):  # không phải "hết tiền": không biết đã chi bao nhiêu
        await gw.client.complete("strong", "b10_answer", ANSWER_VARS, AnswerOut)
    assert a.calls == []


@pytest.mark.asyncio
async def test_d17_cost_added_immediately_without_waiting_refresh() -> None:
    server = Server(ok(ANSWER_OK, tokens=(1000, 1000)))
    store = MemoryLlmStore(base_spend=38.0 - 0.001)
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": openai_provider(server)},
                      store=store)  # fmt: skip
    _, meta = await gw.client.complete("strong", "b10_answer", ANSWER_VARS, AnswerOut)
    assert meta.cost_usd == pytest.approx(0.00125)  # 1000·0,25/1e6 + 1000·1,0/1e6 → vượt trần
    reads = store.spend_reads
    with pytest.raises(LLMBudgetExceeded):
        await gw.client.complete("strong", "b10_answer", {**ANSWER_VARS, "question": "khác"}, AnswerOut)
    assert store.spend_reads == reads and len(server.requests) == 1  # chặn bằng số cộng dồn, không đọc lại DB


# ---- hợp đồng node (Q-3d-5, Q-3d-10), Q-3d-6 qua gateway -------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "schema", "policy"), [
    ("strong", NeedTypeOut, "default"),  # role lệch YAML
    ("fast", AnswerOut, "default"),  # schema lệch YAML
    ("fast", NeedTypeOut, "eval_forever"),  # node không được tự chọn chế độ cache
])  # fmt: skip
async def test_contract_mismatch_is_bug(role: str, schema: Any, policy: str) -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]})
    with pytest.raises(PromptContractError):
        await gw.client.complete(role, "b10_need_type", NEED, schema, cache_policy=policy)  # type: ignore[arg-type]
    assert gw.llm.calls == [] and gw.store.rows == []


@pytest.mark.asyncio
async def test_n_greater_than_one_not_supported_in_phase3() -> None:
    gw = make_gateway({"b10_need_type": [Reply(NEED_OK)]})
    with pytest.raises(ValueError, match="n > 1"):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut, n=2)
    assert gw.llm.calls == []


@pytest.mark.asyncio
async def test_q3d6_cannot_answer_passes_gateway_without_schema_error() -> None:
    reply = {"answer_markdown": "", "citations": [], "cannot_answer": True}
    gw = make_gateway({"b10_answer": [Reply(reply)]})
    out, meta = await gw.client.complete("strong", "b10_answer", ANSWER_VARS, AnswerOut)
    assert out.cannot_answer and out.citations == [] and meta.json_valid_first_try  # B10 → E3, không E2


# ---- chặn mạng + nhãn lỗi chỉ có host (chốt DỪNG 1) --------------------------------------------------------


@pytest.mark.asyncio
async def test_real_provider_without_fake_transport_cannot_reach_network() -> None:
    provider = OpenAICompatProvider("cloud_a", base_url="http://llm.test/v1", api_key=SecretStr("k"))
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": provider})
    with pytest.raises(RuntimeError, match="test không được ra mạng: POST tới llm.test") as e:
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert type(e.value).__name__ == "NetworkBlocked"  # không bị gateway đổi thành LLMUnavailable
    assert gw.store.rows[0].error == "NetworkBlocked"
    await provider.aclose()


@pytest.mark.asyncio
async def test_connection_error_label_has_host_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    server = Server(httpx2.ConnectError("từ chối kết nối"))
    base_url = "http://nguoi:pw-bi-mat@llm.test:8443/v1?api-key=khoa-bi-mat"
    gw = make_gateway(runtime=runtime((target("cloud_a"),)),
                      providers={"cloud_a": openai_provider(server, base_url=base_url)})  # fmt: skip
    with pytest.raises(LLMUnavailable) as e:
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert "cloud_a:connect@llm.test" in str(e.value) and len(server.requests) == 4
    blob = str(e.value) + repr(gw.store.spans) + repr(gw.store.rows) + caplog.text
    for secret in ("pw-bi-mat", "khoa-bi-mat", "8443", "/v1", "k-test"):
        assert secret not in blob
    assert e.value.__cause__ is None and e.value.__suppress_context__  # không kéo lỗi SDK theo


@pytest.mark.asyncio
async def test_jitter_backoff_when_no_retry_after() -> None:
    gw = make_gateway({"b10_need_type": [Http(503), Http(503), Reply(NEED_OK)]}, rng=random.Random(1))
    await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    first, second = gw.clock.sleeps
    assert 1.0 <= first <= 1.25 and 2.0 <= second <= 2.25  # base·2^(k-1) + jitter [0, 0,25]
