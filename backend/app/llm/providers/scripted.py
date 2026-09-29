"""ScriptedLLM — provider giả nằm SAU toàn bộ gateway (phase3 mục 7.5; 3-Q26; PLAN-3d Q-3d-1, Q-3d-12).

Render, whitelist, cache, retry, sửa schema, trace của gateway đều chạy thật; chỉ lời gọi provider được thay. Chỉ nạp
khi `APP_ENV` ∈ {dev, test} (`Settings.require_llm_backend`). Nằm trong `app/` (không ở `tests/`) vì stack dev
(`LLM_BACKEND=scripted`) cần nó trong image; `backend/tests/fakes/scripted_llm.py` re-export.

- **Test:** `ScriptedLLM(scripts)` — mỗi `prompt_id` một hàng đợi `Step` hoặc một hàm `biến → Step`. Hết kịch bản
  → `ScriptExhausted` (không bao giờ tự trả mặc định). `calls` ghi mọi lần gọi (đếm ở nơi nhận, 3.9).
- **Stack dev:** `PresetScriptedLLM` — preset tĩnh `config/scripted/<preset>.yaml` (mỗi `prompt_id` một phản hồi,
  đã kiểm schema lúc khởi động), chọn theo thẻ `[fake:<preset>]` trong `tickets.redacted_request` của lượt đang chạy
  (tra `turn_id → ticket` — suy từ DB như 2b-4, không nhớ theo process). Không thẻ → `default`. Thẻ lạ / preset thiếu
  prompt → `ScriptExhausted` (E9, thấy được).
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import yaml
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import Clock
from app.db.models import Ticket, Turn
from app.llm.context import estimate_tokens
from app.llm.errors import ScriptExhausted
from app.llm.ports import TraceParent
from app.llm.providers.base import ProviderError, ProviderRequest, ProviderResponse
from app.llm.registry import PromptRegistry

NAME = "scripted"
DEFAULT_PRESET = "default"
FAKE_TAG = re.compile(r"\[fake:([a-z0-9_]+)\]")  # cùng cú pháp graph/fakes.FAKE_TAG (test đối chiếu)


# ---- Bước kịch bản (7.5) -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    json: dict[str, Any] | str  # dict → JSON; str → nội dung thô (có thể sai)


@dataclass(frozen=True)
class BadJSON:
    raw: str


@dataclass(frozen=True)
class Http:
    status: int
    retry_after: float | None = None


@dataclass(frozen=True)
class Timeout:
    """Provider không trả lời trong `timeout_s`. Có `clock` → tua đồng hồ đúng `timeout_s` (FakeClock) để test deadline."""


@dataclass(frozen=True)
class Unavailable:
    """Mất kết nối."""


type Step = Reply | BadJSON | Http | Timeout | Unavailable
type Script = list[Step] | Callable[[Mapping[str, Any]], Step]


@dataclass(frozen=True)
class CallRecord:
    prompt_id: str
    model: str
    rendered_messages: list[dict[str, str]]
    variables: Mapping[str, Any]
    attempt: int
    timeout_s: float | None = None  # timeout gateway truyền cho request (test hạn cả lượt 9.0 đọc ở nơi nhận)
    at: datetime | None = None  # đồng hồ provider lúc nhận (chỉ khi dựng với `clock`)


def _content(step: Reply | BadJSON) -> str:
    if isinstance(step, BadJSON):
        return step.raw
    return step.json if isinstance(step.json, str) else json.dumps(step.json, ensure_ascii=False)


def _respond(req: ProviderRequest, content: str) -> ProviderResponse:
    tokens_in = sum(estimate_tokens(m["content"]) for m in req.messages)
    return ProviderResponse(content, tokens_in, estimate_tokens(content), NAME)


async def play(step: Step, req: ProviderRequest, clock: Clock | None) -> ProviderResponse:
    if isinstance(step, Reply | BadJSON):
        return _respond(req, _content(step))
    if isinstance(step, Http):
        raise ProviderError("http", status=step.status, retry_after=step.retry_after)
    if isinstance(step, Timeout):
        if clock is not None:
            await clock.sleep(req.timeout_s)
        raise ProviderError("timeout")
    raise ProviderError("connect")


class ScriptedLLM:
    """Provider kịch bản cho test (7.5)."""

    def __init__(self, scripts: Mapping[str, Script] | None = None, *, clock: Clock | None = None,
                 name: str = NAME) -> None:  # fmt: skip
        self.name = name
        self._scripts: dict[str, Script] = {
            pid: (s if callable(s) else list(s)) for pid, s in (scripts or {}).items()
        }
        self._clock = clock
        self.calls: list[CallRecord] = []

    def calls_for(self, prompt_id: str) -> list[CallRecord]:
        return [c for c in self.calls if c.prompt_id == prompt_id]

    async def chat(self, req: ProviderRequest) -> ProviderResponse:
        at = self._clock.now() if self._clock is not None else None
        self.calls.append(
            CallRecord(req.prompt_id, req.model, req.messages, req.variables, req.attempt, req.timeout_s, at)
        )
        script = self._scripts.get(req.prompt_id)
        if script is None:
            raise ScriptExhausted(f"ScriptedLLM: không có kịch bản cho {req.prompt_id!r}")
        if callable(script):
            step = script(req.variables)
        elif script:
            step = script.pop(0)
        else:
            raise ScriptExhausted(f"ScriptedLLM: hết kịch bản cho {req.prompt_id!r}")
        return await play(step, req, self._clock)


# ---- Preset stack dev (Q-3d-12) ----------------------------------------------------------------------------

type Presets = Mapping[str, Mapping[str, dict[str, Any]]]  # preset → prompt_id → phản hồi


def load_presets(directory: Path, registry: PromptRegistry) -> dict[str, dict[str, dict[str, Any]]]:
    """Mọi `<preset>.yaml`; mỗi phản hồi phải hợp lệ với schema của prompt — sai → không khởi động."""
    presets: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError(f"{path.name}: preset phải là mapping prompt_id → phản hồi")
        for prompt_id, reply in data.items():
            prompt = registry.get(str(prompt_id))  # prompt lạ → PromptContractError
            try:
                prompt.schema.model_validate(reply)
            except ValueError as e:
                raise ValueError(f"{path.name}: phản hồi {prompt_id} sai schema {prompt.spec.schema_name}: {e}") from e
        presets[path.stem] = {str(k): v for k, v in data.items()}
    if DEFAULT_PRESET not in presets:
        raise ValueError(f"thiếu preset {DEFAULT_PRESET!r} trong {directory}")
    return presets


class PresetResolver(Protocol):
    async def tag_for(self, trace: TraceParent | None) -> str | None: ...


_TURNS: Table = Turn.__table__  # type: ignore[assignment]
_TICKETS: Table = Ticket.__table__  # type: ignore[assignment]
_RESOLVER_CACHE_MAX = 1024


class SqlPresetResolver:
    """`turn_id → tickets.redacted_request` → thẻ `[fake:<preset>]` (backend và worker thấy như nhau)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._cache: dict[str, str | None] = {}

    async def tag_for(self, trace: TraceParent | None) -> str | None:
        if trace is None:
            return None
        if trace.turn_id not in self._cache:
            async with self._engine.connect() as conn:
                row = await conn.execute(
                    select(_TICKETS.c.redacted_request)
                    .select_from(_TURNS.join(_TICKETS, _TURNS.c.ticket_id == _TICKETS.c.ticket_id))
                    .where(_TURNS.c.turn_id == trace.turn_id)
                )
                found = FAKE_TAG.search(row.scalar_one_or_none() or "")
            if len(self._cache) >= _RESOLVER_CACHE_MAX:
                self._cache.clear()
            self._cache[trace.turn_id] = found.group(1) if found else None
        return self._cache[trace.turn_id]


class PresetScriptedLLM:
    def __init__(self, presets: Presets, resolver: PresetResolver) -> None:
        self.name = NAME
        self._presets = presets
        self._resolver = resolver

    async def chat(self, req: ProviderRequest) -> ProviderResponse:
        name = await self._resolver.tag_for(req.trace) or DEFAULT_PRESET
        preset = self._presets.get(name)
        if preset is None:
            raise ScriptExhausted(f"preset ScriptedLLM {name!r} không có (thẻ [fake:{name}])")
        reply = preset.get(req.prompt_id)
        if reply is None:
            raise ScriptExhausted(f"preset {name!r} không có phản hồi cho {req.prompt_id!r}")
        return _respond(req, json.dumps(reply, ensure_ascii=False))
