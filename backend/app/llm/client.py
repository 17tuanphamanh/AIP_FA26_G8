"""`LLMClient.complete` — cổng DUY NHẤT cho mọi lời gọi LLM (P2 mục 2; phase3 mục 7; PLAN-3d).

Thứ tự trong một lời gọi:

1. Prompt từ registry; `role`/`schema`/`cache_policy` của node phải khớp YAML (Q-3d-5) — lệch → `PromptContractError`.
2. Vai THỰC SỰ dùng (`RuntimeLlm.role_of`: `prompt_roles` của llm.yaml, không có thì `role` file khai — Q10) quyết định
   `budget_in`, timeout, chuỗi đích, khoá cache; render + whitelist + cắt theo `budget_in` của vai đó (`llm/context.py`).
3. Chuỗi đích của vai trò; **strong và chat_strong KHÔNG fallback** (P2 mục 5). Đích chính không có dòng pricing →
   `LLMBudgetExceeded`, 0 request (3-Q26).
4. Cache (trừ prompt `bypass`) — hit thì trả luôn, chi phí 0.
5. Mỗi đích: trần chi (đích trả phí, Q-3d-14) → mỗi request trả phí giữ chỗ chi phí xấu nhất trước khi gửi (S9: song
   song, thử lại, sửa schema đều không lọt trần — `llm/spend.py`) → semaphore → provider; retry 429/5xx/timeout/mất kết nối tới
   `max_retries` (Retry-After ưu tiên, không thì backoff + jitter); hết lượt → đích fallback kế. Toàn bộ nằm trong
   `deadline_s` (Q-3d-7): lần chờ vượt thời gian còn lại → dừng, `LLMUnavailable`. Hạn cho cả lượt (phase3 9.0):
   deadline = min(`deadline_s`, còn lại của lượt − biên an toàn); hết vì hạn LƯỢT → `TurnBudgetExceeded` (không phải
   `LLMUnavailable` — node ghi E2 `turn_budget_exceeded`); lượt đã hết trước khi gửi → ném ngay, 0 request.
6. Validate schema; sai → một lần sửa trên CÙNG đích; vẫn sai → `LLMSchemaError` (không fallback).
7. Ghi cache (chỉ khi đích chính trả lời) + span `llm:<id>` và dòng `llm_calls` (kể cả cache hit, kể cả lỗi) —
   không có văn bản prompt/đầu ra, trừ `prompt_full` khi `EVAL_MODE=true` (P2 mục 11).

`ScriptExhausted`, `PromptVariableError`… không phải lỗi provider → xuyên qua vòng retry → E9.
"""

import asyncio
import json
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.core.clock import Clock
from app.core.turn_budget import TurnBudgetExceeded, window
from app.llm.cache import cache_key, cache_mode
from app.llm.config import NO_FALLBACK_ROLES, LlmRole, RoleCfg, RuntimeLlm, Target
from app.llm.context import (
    BoundaryFactory,
    Rendered,
    TokenEstimator,
    estimate_tokens,
    new_boundary,
    render,
)
from app.llm.errors import (
    LLMBudgetExceeded,
    LLMSchemaError,
    LLMUnavailable,
    PromptContractError,
)
from app.llm.ports import (
    CachePolicy,
    LlmCallRow,
    LLMMeta,
    LlmSpan,
    LlmStore,
    Role,
    Sensitivity,
    TraceParent,
    TraceSource,
    no_trace,
)
from app.llm.providers.base import (
    Provider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)
from app.llm.registry import Prompt, PromptRegistry
from app.llm.spend import SpendTracker

log = logging.getLogger(__name__)

MAX_REPAIR_ERRORS = 5  # số lỗi Pydantic nêu trong lời nhắc sửa schema
MODEL_VERSION_MAX = 64  # llm_calls.model_version VARCHAR(64) — chuỗi dài hơn làm hỏng cả dòng (mất chi phí)


class _TargetFailed(Exception):
    """Một đích hết lượt, hết deadline, hoặc bị trần chi chặn giữa chừng — nội bộ, không bao giờ ra khỏi client."""

    def __init__(self, reason: str, *, deadline: bool = False, spend: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.deadline = deadline
        self.spend = spend


@dataclass
class _Call:
    """Tích luỹ của một lời gọi cho span + `llm_calls`. Không giữ văn bản ngoài `prompt_full` (EVAL_MODE)."""

    span_id: str
    t0: datetime
    prompt: Prompt
    role: Role  # vai node truyền = `role` file prompt khai (hợp đồng)
    sensitivity: Sensitivity
    llm_role: LlmRole  # vai thực sự dùng (Q10: sau `prompt_roles`) — chọn cấu hình vai, chuỗi đích
    provider: str = ""
    model: str = ""
    model_version: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    usage_tokens_in: int | None = None  # token thật provider báo — hiệu chỉnh ước lượng ở mốc G (Q-3d-8)
    cost_usd: float = 0.0
    cache_hit: bool = False
    json_valid_first_try: bool | None = None
    used_fallback: bool = False
    attempts: int = 0
    failures: list[str] = field(default_factory=list)
    est_tokens_in: int = 0
    trimmed_evidence: int = 0
    trimmed_messages: int = 0
    trimmed_chars: int = 0  # Q1 điểm 2: chỉ đưa lên `LLMMeta`, không vào span/`llm_calls`
    prompt_full: str | None = None
    error: str | None = None
    turn_bound: bool = False  # deadline của lời gọi bị hạn cả lượt chặn (9.0), không phải `deadline_s` của vai trò


def _parse[T: BaseModel](schema: type[T], content: str) -> tuple[T | None, ValidationError | None]:
    try:
        return schema.model_validate_json(content), None
    except ValidationError as e:
        return None, e


def repair_note(err: ValidationError) -> str:
    """Lời nhắc sửa schema: chỉ vị trí + thông điệp Pydantic rút gọn (P2 mục 9) — không chép lại đầu ra."""
    parts = [f"{'.'.join(str(p) for p in e['loc']) or '(gốc)'}: {e['msg']}" for e in err.errors()[:MAX_REPAIR_ERRORS]]
    return "Phản hồi trước không đúng schema JSON — " + "; ".join(parts) + ". Trả lại DUY NHẤT một JSON đúng schema."


class LLMClient:
    def __init__(
        self,
        *,
        runtime: RuntimeLlm,
        registry: PromptRegistry,
        providers: Mapping[str, Provider],
        store: LlmStore,
        clock: Clock,
        trace: TraceSource = no_trace,
        eval_mode: bool = False,
        cache_mode: Literal["default", "eval", "bypass"] = "default",
        estimate: TokenEstimator = estimate_tokens,
        boundary: BoundaryFactory = new_boundary,
        rng: random.Random | None = None,
    ) -> None:
        self._rt = runtime
        self._registry = registry
        self._providers = dict(providers)
        self._store = store
        self._clock = clock
        self._trace = trace
        self._eval_mode = eval_mode
        self._cache_mode = cache_mode
        self._estimate = estimate
        self._boundary = boundary
        self._rng = rng or random.Random()
        self._sem = asyncio.Semaphore(runtime.limits.max_concurrency)  # dùng chung cả process [Chốt 14.3]
        self._spend = SpendTracker(runtime.spend, store, clock)

    async def complete[T: BaseModel](
        self,
        role: Role,
        prompt_id: str,
        variables: Mapping[str, Any],
        schema: type[T],
        *,
        sensitivity: Sensitivity = "internal",
        cache_policy: CachePolicy = "default",
        n: int = 1,
        temperature: float | None = None,
        kb_version: str | None = None,
        keep_tail: Mapping[str, int] | None = None,
    ) -> tuple[T, LLMMeta]:
        if n != 1:
            raise ValueError("n > 1 chưa hỗ trợ ở Phase 3 (hỏi nhiều lần: B14, Phase 6)")
        prompt = self._registry.get(prompt_id)
        spec = prompt.spec
        if keep_tail and not set(keep_tail) <= set(spec.trim_vars):  # Q1 điểm 2: chỉ biến được phép cắt mới có phần đuôi giữ nguyên
            raise PromptContractError(f"{prompt_id}: keep_tail {sorted(keep_tail)} ngoài trim_vars {list(spec.trim_vars)}")
        if role != spec.role or schema is not prompt.schema or cache_policy not in ("default", "bypass"):
            raise PromptContractError(
                f"{prompt_id}: node truyền role={role!r}, schema={schema.__name__}, cache_policy={cache_policy!r}; "
                f"YAML: role={spec.role!r}, schema={spec.schema_name}"
            )
        parent = self._trace()
        if parent is None and self._store.requires_trace:
            raise RuntimeError(f"{prompt_id}: gọi LLM ngoài lượt graph — không có span cha để ghi llm_calls (Q-3d-2)")
        call = _Call(uuid4().hex, self._clock.now(), prompt, role, sensitivity, self._rt.role_of(prompt))
        try:
            obj = await self._run(call, prompt, variables, schema, cache_policy, temperature, kb_version, parent, keep_tail)
        except BaseException as e:
            call.error = type(e).__name__
            raise
        finally:
            await self._record(call, parent)
        return obj, self._meta(call)

    # ---- một lời gọi ------------------------------------------------------------------------------------

    async def _run[T: BaseModel](
        self, call: _Call, prompt: Prompt, variables: Mapping[str, Any], schema: type[T],
        cache_policy: CachePolicy, temperature: float | None, kb_version: str | None, parent: TraceParent | None,
        keep_tail: Mapping[str, int] | None = None,
    ) -> T:  # fmt: skip
        rcfg = self._rt.roles[call.llm_role]
        chain = list(self._rt.chains[call.llm_role])
        if call.llm_role in NO_FALLBACK_ROLES:
            chain = chain[:1]  # P2 mục 5: strong KHÔNG fallback — kể cả sang provider khác (chat_strong cũng vậy)
        primary = chain[0]
        call.provider, call.model, call.model_version = primary.provider, primary.model, primary.model_version
        rendered = render(prompt, variables, budget_in=rcfg.budget_in, estimate=self._estimate,
                          boundary=self._boundary, keep_tail=keep_tail)  # fmt: skip
        call.est_tokens_in = rendered.est_tokens
        call.trimmed_evidence, call.trimmed_messages = rendered.trimmed_evidence, rendered.trimmed_messages
        call.trimmed_chars = rendered.trimmed_chars
        if self._eval_mode:
            call.prompt_full = json.dumps(rendered.messages, ensure_ascii=False)
        if primary.price is None:  # 3-Q26: không chi tiền cho thứ không đo được
            raise LLMBudgetExceeded(f"{prompt.id}: model {primary.model!r} không có dòng pricing — không gửi request")
        chain = [t for t in chain if t.price is not None]
        temp = rcfg.temperature if temperature is None else temperature
        json_schema = schema.model_json_schema()
        mode = cache_mode(prompt.spec.cache, cache_policy, self._cache_mode)
        key = None
        if mode is not None:
            key = cache_key(
                provider=primary.provider, model=primary.model, model_version=primary.model_version,
                prompt_id=prompt.id, prompt_version=prompt.version, messages=rendered.messages,
                json_schema=json_schema, temperature=temp, n=1, kb_version=kb_version, mode=mode,
            )  # fmt: skip
            hit = await self._store.cache_get(key, mode=mode, now=self._clock.now())
            if hit is not None:
                try:
                    obj = schema.model_validate(hit)
                except ValidationError:
                    log.warning("%s: bỏ qua bản cache sai schema", prompt.id)
                else:
                    call.cache_hit, call.json_valid_first_try = True, True
                    return obj
        now = self._clock.now()
        role_left = (call.t0 + timedelta(seconds=rcfg.deadline_s) - now).total_seconds()
        limit_s, call.turn_bound = window(role_left, self._clock, what=f"llm:{prompt.id}")  # 9.0: hết → ném, 0 request
        deadline = now + timedelta(seconds=limit_s)
        obj, answered = await self._call_chain(call, chain, prompt, rendered, schema, json_schema, rcfg, temp,
                                               deadline, variables, parent)  # fmt: skip
        if key is not None and mode is not None and answered is primary:
            now = self._clock.now()
            expires = None if mode == "eval" else now + timedelta(hours=self._rt.cache.ttl_hours_runtime)
            await self._store.cache_put(key, mode=mode, prompt_id=prompt.id, prompt_version=prompt.version,
                                        model=primary.model, response=obj.model_dump(mode="json"), now=now,
                                        expires_at=expires)  # fmt: skip
        return obj

    async def _call_chain[T: BaseModel](
        self, call: _Call, chain: list[Target], prompt: Prompt, rendered: Rendered, schema: type[T],
        json_schema: dict[str, Any], rcfg: RoleCfg, temperature: float, deadline: datetime,
        variables: Mapping[str, Any], parent: TraceParent | None,
    ) -> tuple[T, Target]:  # fmt: skip
        over_budget = unknown_spend = failed = 0
        deadline_hit = False
        for index, target in enumerate(chain):
            assert target.price is not None
            if target.price.paid:
                status = await self._spend.check()
                if status != "ok":
                    call.failures.append(f"{target.provider}:spend_{status}")
                    over_budget += status == "over"
                    unknown_spend += status == "unknown"
                    continue
            call.provider, call.model, call.model_version = target.provider, target.model, target.model_version
            call.used_fallback = index > 0
            try:
                obj = await self._call_target(call, target, prompt, rendered, schema, json_schema, rcfg,
                                              temperature, deadline, variables, parent)  # fmt: skip
            except _TargetFailed as f:
                if f.spend:  # giữ chỗ bị từ chối giữa chừng (lần thử lại, lần sửa schema, lời gọi song song)
                    over_budget += 1
                    continue
                failed += 1
                if f.deadline:
                    deadline_hit = True
                    break
                continue
            return obj, target
        if deadline_hit and call.turn_bound:  # 9.0: hết vì hạn cả lượt → E2 turn_budget_exceeded, không LLMUnavailable
            raise TurnBudgetExceeded(f"llm:{prompt.id}: hết hạn lượt ({', '.join(call.failures)})") from None
        if over_budget and not unknown_spend and not failed:
            raise LLMBudgetExceeded(f"{prompt.id}: đã chạm trần chi tiêu, không còn đích giá 0") from None
        raise LLMUnavailable(f"{prompt.id}: hết retry/fallback/deadline ({', '.join(call.failures)})") from None

    async def _call_target[T: BaseModel](
        self, call: _Call, target: Target, prompt: Prompt, rendered: Rendered, schema: type[T],
        json_schema: dict[str, Any], rcfg: RoleCfg, temperature: float, deadline: datetime,
        variables: Mapping[str, Any], parent: TraceParent | None,
    ) -> T:  # fmt: skip
        def request(messages: list[dict[str, str]], attempt: int, timeout_s: float) -> ProviderRequest:
            return ProviderRequest(
                prompt_id=prompt.id, model=target.model, messages=messages, json_schema=json_schema,
                schema_name=prompt.spec.schema_name, max_tokens=rcfg.max_tokens, temperature=temperature,
                timeout_s=timeout_s, attempt=attempt, variables=variables, trace=parent,
            )  # fmt: skip

        resp = await self._with_retry(call, target, rcfg, deadline, request, rendered.messages)
        obj, err = _parse(schema, resp.content)
        if obj is not None:
            call.json_valid_first_try = True
            return obj
        call.json_valid_first_try = False
        assert err is not None
        repair = [*rendered.messages, {"role": "assistant", "content": resp.content},
                  {"role": "user", "content": repair_note(err)}]  # fmt: skip
        resp = await self._with_retry(call, target, rcfg, deadline, request, repair)
        obj, _ = _parse(schema, resp.content)
        if obj is None:
            raise LLMSchemaError(f"{prompt.id}: sai schema {prompt.spec.schema_name} sau 1 lần sửa") from None
        return obj

    async def _with_retry(
        self, call: _Call, target: Target, rcfg: RoleCfg, deadline: datetime,
        request: Any, messages: list[dict[str, str]],
    ) -> ProviderResponse:  # fmt: skip
        provider = self._providers[target.provider]
        limits = self._rt.limits
        attempt = 0
        while True:
            remaining = (deadline - self._clock.now()).total_seconds()
            if remaining <= 0:
                call.failures.append("deadline")
                raise _TargetFailed("deadline", deadline=True)
            req: ProviderRequest = request(messages, attempt, min(rcfg.timeout_s, remaining))
            held = self._reserve(target, rcfg, req)
            if held is None:
                call.failures.append(f"{target.provider}:spend_over")
                raise _TargetFailed("spend_over", spend=True)
            call.attempts += 1
            try:
                async with self._sem:
                    resp = await asyncio.wait_for(provider.chat(req), timeout=req.timeout_s)
            except TimeoutError:
                err = ProviderError("timeout")
            except ProviderError as e:
                err = e
            else:
                self._account(call, target, req, resp)
                return resp
            finally:
                self._spend.release(held)
            call.failures.append(f"{target.provider}:{err.label}")
            retryable = err.kind in ("timeout", "connect") or err.status in limits.retry_on
            if not retryable or attempt >= rcfg.max_retries:
                raise _TargetFailed(err.label)
            if err.retry_after is not None:  # server nói chờ bao lâu thì chờ đúng bấy nhiêu (P2 mục 9)
                wait = err.retry_after
            else:
                wait = limits.backoff_base_s * 2**attempt + self._rng.uniform(0, limits.jitter_max_s)
            if wait >= (deadline - self._clock.now()).total_seconds():
                call.failures.append("deadline")
                raise _TargetFailed("deadline", deadline=True)  # không ngủ quá deadline (Q-3d-7)
            await self._clock.sleep(wait)
            attempt += 1

    def _reserve(self, target: Target, rcfg: RoleCfg, req: ProviderRequest) -> float | None:
        """Giữ chỗ chi phí xấu nhất của MỘT request (S9): 0 với đích giá 0; None = trần không còn chỗ, không gửi."""
        if target.price is None or not target.price.paid:
            return 0.0
        worst = target.price.cost(sum(self._estimate(m["content"]) for m in req.messages), rcfg.max_tokens)
        return worst if self._spend.reserve(worst) else None

    def _account(self, call: _Call, target: Target, req: ProviderRequest, resp: ProviderResponse) -> None:
        tokens_in = resp.tokens_in
        if tokens_in is None:
            tokens_in = sum(self._estimate(m["content"]) for m in req.messages)
        else:
            call.usage_tokens_in = (call.usage_tokens_in or 0) + tokens_in
        tokens_out = resp.tokens_out if resp.tokens_out is not None else self._estimate(resp.content)
        cost = target.price.cost(tokens_in, tokens_out) if target.price is not None else 0.0
        call.tokens_in += tokens_in
        call.tokens_out += tokens_out
        call.cost_usd += cost
        call.model_version = (resp.model_version or target.model_version or "")[:MODEL_VERSION_MAX] or None
        self._spend.add(cost)

    # ---- trace --------------------------------------------------------------------------------------------

    def _latency_ms(self, call: _Call) -> int:
        return max(0, int((self._clock.now() - call.t0).total_seconds() * 1000))

    def _meta(self, call: _Call) -> LLMMeta:
        return LLMMeta(
            span_id=call.span_id, provider=call.provider, model=call.model, model_version=call.model_version,
            prompt_id=call.prompt.id, prompt_version=call.prompt.version, prompt_hash=call.prompt.sha256,
            tokens_in=call.tokens_in, tokens_out=call.tokens_out, cost_usd=call.cost_usd,
            latency_ms=self._latency_ms(call), cache_hit=call.cache_hit,
            json_valid_first_try=bool(call.json_valid_first_try), used_fallback=call.used_fallback,
            trimmed_evidence=call.trimmed_evidence, trimmed_messages=call.trimmed_messages, trimmed_chars=call.trimmed_chars,
        )  # fmt: skip

    async def _record(self, call: _Call, parent: TraceParent | None) -> None:
        latency = self._latency_ms(call)
        span = LlmSpan(
            span_id=call.span_id, trace_id=parent.trace_id if parent else "", turn_id=parent.turn_id if parent else None,
            name=f"llm:{call.prompt.id}", started_at=call.t0, parent_span_id=parent.parent_span_id if parent else None,
            duration_ms=latency, status="error" if call.error else "ok",
            attributes={
                "prompt_id": call.prompt.id, "prompt_version": call.prompt.version, "role": call.role,
                "llm_role": call.llm_role,
                "sensitivity": call.sensitivity, "attempts": call.attempts, "failures": list(call.failures),
                "est_tokens_in": call.est_tokens_in, "usage_tokens_in": call.usage_tokens_in,
                "trimmed_evidence": call.trimmed_evidence, "trimmed_messages": call.trimmed_messages,
                "cache_hit": call.cache_hit, "used_fallback": call.used_fallback, "error": call.error,
            },
        )  # fmt: skip
        row = LlmCallRow(
            span_id=call.span_id, provider=call.provider, model=call.model, model_version=call.model_version,
            prompt_id=call.prompt.id, prompt_version=call.prompt.version, prompt_hash=call.prompt.sha256,
            prompt_full=call.prompt_full, tokens_in=call.tokens_in, tokens_out=call.tokens_out,
            cost_usd=call.cost_usd, latency_ms=latency, cache_hit=call.cache_hit,
            json_valid_first_try=call.json_valid_first_try, used_fallback=call.used_fallback, error=call.error,
        )  # fmt: skip
        try:
            await self._store.record(span, row)
        except Exception as e:  # noqa: BLE001 — trace hỏng không được làm hỏng ticket (như graph/tracing.traced)
            log.warning("không ghi được span/llm_calls của %s: %s", call.prompt.id, type(e).__name__)
        else:
            self._spend.recorded(call.cost_usd)  # dòng đã vào DB: lần đọc tổng sau thấy nó (spend.py)
