"""Hợp đồng của gateway (P2 mục 4) + cổng phụ thuộc: store (cache, trace, chi tiêu) và nguồn trace.

`llm` không import `graph` (hợp đồng import-linter 8): lượt/span cha đến qua `TraceSource` do graph tiêm
(`graph/tracing.trace_parent`, PLAN-3d Q-3d-2). Bản SQL của `LlmStore` ở `llm/store.py`, bản in-memory ở
`backend/tests/fakes/llm.py`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

type Role = Literal["fast", "strong"]
type Sensitivity = Literal["public", "internal", "sensitive"]
type CachePolicy = Literal["default", "bypass"]  # node chỉ được làm cache CHẶT hơn YAML (Q-3d-5)
type CacheMode = Literal["runtime", "eval"]  # cột llm_cache.mode (P7 2.4)


class LLMMeta(BaseModel):
    """P2 mục 4 + phần Phase 3 (prompt_hash, số khối bị cắt). Không chứa văn bản prompt hay đầu ra."""

    span_id: str
    provider: str
    model: str
    model_version: str | None
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    cache_hit: bool
    json_valid_first_try: bool
    used_fallback: bool
    trimmed_evidence: int = 0
    trimmed_messages: int = 0
    # Q1 điểm 2 (ĐP chốt 09/11): số ký tự bị cắt đuôi khỏi biến `trim_vars` (`Rendered.trimmed_chars`) — node ghi cờ bool vào audit
    # (B3 `request_trimmed`); KHÔNG vào span/`llm_calls` (không đổi cột DB)
    trimmed_chars: int = 0
    logprobs: list[Any] | None = None  # chỉ khi provider trả (RQ2) — chưa dùng ở Phase 3


class LlmPort(Protocol):
    """Node gọi qua `deps.llm` (phase3 mục 7). Lỗi node phải bắt: `LLMSchemaError`, `LLMUnavailable`,
    `LLMBudgetExceeded` (`core/errors.py`); lỗi khác là bug → E9."""

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
        keep_tail: Mapping[str, int] | None = None,  # Q1 điểm 2: biến ∈ `trim_vars` → giữ nguyên k ký tự cuối khi phải cắt
    ) -> tuple[T, LLMMeta]: ...


@dataclass(frozen=True)
class TraceParent:
    """Lượt graph đang chạy + span node cha — `spans.turn_id` NOT NULL FK, `llm_calls.span_id` FK (P7)."""

    turn_id: str
    trace_id: str
    parent_span_id: str | None


type TraceSource = Callable[[], TraceParent | None]


def no_trace() -> TraceParent | None:
    return None


@dataclass
class LlmSpan:
    """Một dòng `spans` (span_type `llm`, tên `llm:<prompt_id>`). `attributes` KHÔNG chứa văn bản prompt/đầu ra."""

    span_id: str
    trace_id: str
    turn_id: str | None  # None chỉ hợp lệ với store in-memory (probe/test)
    name: str
    started_at: datetime
    parent_span_id: str | None
    duration_ms: int
    status: str  # ok | error
    span_type: str = "llm"
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LlmCallRow:
    """Một dòng `llm_calls` (P2 mục 11). `prompt_full` chỉ khi EVAL_MODE=true; `error` chỉ là tên lớp lỗi."""

    span_id: str
    provider: str
    model: str
    model_version: str | None
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    prompt_full: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    cache_hit: bool
    json_valid_first_try: bool | None
    used_fallback: bool
    error: str | None


class LlmStore(Protocol):
    # True: không có lượt graph (TraceParent None) thì không ghi được — gateway từ chối gọi (Q-3d-2)
    requires_trace: bool

    async def cache_get(self, key: str, *, mode: CacheMode, now: datetime) -> dict[str, Any] | None: ...

    async def cache_put(
        self,
        key: str,
        *,
        mode: CacheMode,
        prompt_id: str,
        prompt_version: str,
        model: str,
        response: dict[str, Any],
        now: datetime,
        expires_at: datetime | None,
    ) -> None: ...

    async def record(self, span: LlmSpan, call: LlmCallRow) -> None:
        """Ghi span + dòng `llm_calls` trong MỘT transaction (FK span_id)."""
        ...

    async def spend_total(self) -> float:
        """SUM(llm_calls.cost_usd) — trần chi tiêu (P2 mục 5)."""
        ...
