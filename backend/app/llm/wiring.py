"""Dựng gateway cho backend/worker.

`check_llm` chạy TRƯỚC mọi kết nối (cùng khuôn `require_ml_token`, `require_dev_fakes`): `LLM_BACKEND` thiếu/sai,
`scripted` ngoài dev/test, model thiếu giá, thời gian retry vượt trần, prompt hay preset sai → `RuntimeError`/
`ValueError`, backend và worker từ chối khởi động (3-Q26, PLAN-3d Q-3d-3, Q-3d-7, Q-3d-12, Q-3d-13).
`open_llm` dựng `LLMClient` + provider (đóng client HTTP khi thoát); `EVAL_MODE=true` → một dòng WARNING (mỗi tiến trình
dựng gateway đúng một lần — `check_llm` thì backend gọi hai lần).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import Clock
from app.llm.client import LLMClient
from app.llm.config import (
    SCRIPTED_PROVIDER,
    LlmConfig,
    RuntimeLlm,
    check_timing,
    load_llm_config,
    resolve,
)
from app.llm.context import check_evidence_budget
from app.llm.ports import TraceSource
from app.llm.providers.base import Provider
from app.llm.providers.openai_compat import OpenAICompatProvider
from app.llm.providers.scripted import (
    PresetScriptedLLM,
    SqlPresetResolver,
    load_presets,
)
from app.llm.registry import PromptRegistry, load_prompts
from app.llm.store import SqlLlmStore
from app.settings import Settings

log = logging.getLogger(__name__)

ANSWER_PROMPT = "b10_answer"  # prompt nhận `evidence` (B10) — f1


@dataclass(frozen=True)
class LlmSetup:
    config: LlmConfig
    runtime: RuntimeLlm
    registry: PromptRegistry
    presets: dict[str, dict[str, dict[str, Any]]] | None  # chỉ LLM_BACKEND=scripted


def check_llm(settings: Settings) -> LlmSetup:
    backend = settings.require_llm_backend()
    cfg = load_llm_config(settings.config_dir / "llm.yaml")
    check_timing(cfg, settings.worker_stale_turn_seconds)
    runtime = resolve(cfg, settings, backend)
    registry = load_prompts(settings.config_dir / "prompts")
    answer = registry.get(ANSWER_PROMPT)  # f1 (PLAN-3g): bằng chứng B10 phải vừa khung vào của vai trò
    check_evidence_budget(answer, cfg.roles[answer.spec.role].budget_in, settings.rag_evidence_max_tokens)
    presets = None
    if backend == "scripted":
        presets = load_presets(settings.llm_script_preset_dir or settings.config_dir / "scripted", registry)
    return LlmSetup(config=cfg, runtime=runtime, registry=registry, presets=presets)


@asynccontextmanager
async def open_llm(
    setup: LlmSetup, settings: Settings, *, engine: AsyncEngine, clock: Clock, trace: TraceSource
) -> AsyncIterator[LLMClient]:
    providers: dict[str, Provider] = {}
    if settings.eval_mode:  # Settings đã từ chối EVAL_MODE ở prod/APP_ENV thiếu (chốt DỪNG 3: dev/test/staging)
        log.warning("EVAL_MODE=true (APP_ENV=%s): llm_calls.prompt_full lưu prompt đầy đủ — chỉ dùng cho thử nghiệm",
                    settings.app_env)  # fmt: skip
    async with AsyncExitStack() as stack:
        if setup.runtime.backend == "scripted":
            assert setup.presets is not None
            providers[SCRIPTED_PROVIDER] = PresetScriptedLLM(setup.presets, SqlPresetResolver(engine))
        else:
            for name in sorted({t.provider for chain in setup.runtime.chains.values() for t in chain}):
                p = setup.config.providers[name]
                key = getattr(settings, p.api_key_setting)
                assert isinstance(key, SecretStr)  # resolve() đã từ chối khởi động nếu thiếu
                real = OpenAICompatProvider(name, base_url=getattr(settings, p.base_url_setting), api_key=key,
                                            json_mode=p.json_mode, extra_body=p.extra_body)  # fmt: skip
                stack.push_async_callback(real.aclose)
                providers[name] = real
        yield LLMClient(
            runtime=setup.runtime, registry=setup.registry, providers=providers, store=SqlLlmStore(engine),
            clock=clock, trace=trace, eval_mode=settings.eval_mode, cache_mode=settings.llm_cache_mode,
        )  # fmt: skip
