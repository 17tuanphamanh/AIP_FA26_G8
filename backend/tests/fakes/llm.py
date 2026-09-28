"""Gateway LLM cho test (PLAN-3d): `MemoryLlmStore` (cache, span + llm_calls, tổng chi — cùng hợp đồng
`app/llm/store.SqlLlmStore`) và `make_gateway` dựng `LLMClient` THẬT với ScriptedLLM làm provider (7.3: không thay cả
client bằng đồ giả). Cấu hình mặc định = `config/llm.yaml` + `config/prompts/` của repo, backend `scripted`.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.core.clock import FakeClock
from app.llm.client import LLMClient
from app.llm.config import RuntimeLlm, load_llm_config, resolve
from app.llm.context import BoundaryFactory, new_boundary
from app.llm.ports import CacheMode, LlmCallRow, LlmSpan, TraceSource, no_trace
from app.llm.providers.base import Provider
from app.llm.providers.scripted import Script, ScriptedLLM
from app.llm.registry import PromptRegistry, load_prompts
from app.settings import Settings

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"


@dataclass
class CacheRow:
    mode: CacheMode
    prompt_id: str
    prompt_version: str
    model: str
    response: dict[str, Any]
    created_at: datetime
    expires_at: datetime | None


@dataclass
class MemoryLlmStore:
    requires_trace: bool = False
    base_spend: float = 0.0  # chi tiêu "đã có từ trước" (giả lập SUM của các dòng cũ)
    fail_spend: bool = False  # spend_total ném lỗi (DB chết)
    fail_record: bool = False
    cache: dict[str, CacheRow] = field(default_factory=dict)
    spans: list[LlmSpan] = field(default_factory=list)
    rows: list[LlmCallRow] = field(default_factory=list)
    spend_reads: int = 0

    async def cache_get(self, key: str, *, mode: CacheMode, now: datetime) -> dict[str, Any] | None:
        row = self.cache.get(key)
        if row is None or row.mode != mode or (row.expires_at is not None and row.expires_at <= now):
            return None
        return dict(row.response)

    async def cache_put(
        self, key: str, *, mode: CacheMode, prompt_id: str, prompt_version: str, model: str,
        response: dict[str, Any], now: datetime, expires_at: datetime | None,
    ) -> None:  # fmt: skip
        self.cache[key] = CacheRow(mode, prompt_id, prompt_version, model, dict(response), now, expires_at)

    async def record(self, span: LlmSpan, call: LlmCallRow) -> None:
        if self.fail_record:
            raise ConnectionError("DB chết")
        self.spans.append(span)
        self.rows.append(call)

    async def spend_total(self) -> float:
        self.spend_reads += 1
        if self.fail_spend:
            raise ConnectionError("DB chết")
        return self.base_spend + sum(r.cost_usd for r in self.rows)


@lru_cache
def repo_registry() -> PromptRegistry:
    return load_prompts(REPO_CONFIG / "prompts")


def scripted_runtime() -> RuntimeLlm:
    return resolve(load_llm_config(REPO_CONFIG / "llm.yaml"), Settings(_env_file=None), "scripted")  # type: ignore[call-arg]


@dataclass
class Gateway:
    client: LLMClient
    llm: ScriptedLLM
    store: MemoryLlmStore
    clock: FakeClock


def make_gateway(
    scripts: dict[str, Script] | None = None,
    *,
    runtime: RuntimeLlm | None = None,
    providers: dict[str, Provider] | None = None,
    store: MemoryLlmStore | None = None,
    clock: FakeClock | None = None,
    registry: PromptRegistry | None = None,
    trace: TraceSource = no_trace,
    eval_mode: bool = False,
    cache_mode: Literal["default", "eval", "bypass"] = "default",
    boundary: BoundaryFactory = new_boundary,
    rng: random.Random | None = None,
) -> Gateway:
    clock = clock or FakeClock()
    llm = ScriptedLLM(scripts or {}, clock=clock)
    store = store or MemoryLlmStore()
    client = LLMClient(
        runtime=runtime or scripted_runtime(), registry=registry or repo_registry(),
        providers=providers if providers is not None else {"scripted": llm}, store=store, clock=clock,
        trace=trace, eval_mode=eval_mode, cache_mode=cache_mode, boundary=boundary, rng=rng or random.Random(0),
    )  # fmt: skip
    return Gateway(client, llm, store, clock)
