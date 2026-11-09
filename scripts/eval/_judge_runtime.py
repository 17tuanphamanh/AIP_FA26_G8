"""Gọi LLM chấm `b02_injection_judge` NGOÀI stack, đúng đường lúc chạy thật (gói 1, D-52; `dac-ta-bat-2-model.md` mục 3).

Dùng `LLMClient` + `OpenAICompatProvider` thật của backend (cùng cách render prompt, cùng dấu phân cách ngẫu nhiên, cùng 1 lần sửa
schema, cùng retry của vai trò `fast`), chỉ khác: store trong bộ nhớ (`MemoryStore`), chuỗi dự phòng RỖNG (không âm thầm đổi
LLM chấm), trần chi riêng của lượt đo. Không sửa `backend/app/llm/*`.

Đích (`--target`):
- `deepseek`: đúng vai trò `fast` đang chạy (D-51) — provider, `extra_body`, `json_mode` từ `config/llm.yaml`; model, base_url,
  khoá đọc từ biến môi trường `FAST_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` (cùng tên trường Settings mà `llm.yaml` trỏ tới).
- tên khác: khối cùng tên trong `scripts/eval/judge_targets.yaml` (thân request ghim một lần, gói 3 dùng lại); khoá đọc từ biến
  ghi ở `api_key_env` (`LLM_JUDGE_API_KEY`). Còn ô `<điền>` → từ chối chạy.
Thời gian, `max_tokens`, `temperature`: chép từ vai trò `fast` của `config/llm.yaml` (một nguồn).

`finish_reason`, nhà cung cấp thật (OpenRouter trả `provider`), số token suy luận: lấy bằng event hook của `httpx2.AsyncClient`
tiêm qua tham số `http_client` sẵn có của provider — hook chỉ giữ 4 trường đó, KHÔNG giữ nội dung trả lời. Khoá: đọc theo tên
biến, bọc `SecretStr`, không in, không ghi file; thông báo lỗi chỉ nêu TÊN biến.
"""

import contextvars
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config"
TARGETS_FILE = Path(__file__).with_name("judge_targets.yaml")
PROMPT_ID = "b02_injection_judge"
ROLE = "fast"
PLACEHOLDER = "<điền>"
JUDGE_KEY_ENV = "LLM_JUDGE_API_KEY"  # đích OpenRouter chỉ được dùng khoá riêng này — không bao giờ gửi khoá DeepSeek đi nơi khác
DEEPSEEK = "deepseek"
DEEPSEEK_ENV = {"model": "FAST_MODEL", "base_url": "LLM_BASE_URL", "api_key": "LLM_API_KEY"}

_CAPTURE: contextvars.ContextVar[list[dict[str, Any]]] = contextvars.ContextVar("judge_capture")


class TargetError(RuntimeError):
    """Cấu hình đích sai/thiếu — thông điệp chỉ nêu tên biến/khối, không có giá trị khoá."""


@dataclass
class MemoryStore:
    """`LlmStore` trong bộ nhớ (không DB): ghi dòng `llm_calls` để trần chi của lượt đo hoạt động; không cache."""

    requires_trace: bool = False
    rows: list[Any] = field(default_factory=list)

    async def cache_get(self, key: str, *, mode: Any, now: datetime) -> dict[str, Any] | None:
        return None

    async def cache_put(self, key: str, **_: Any) -> None:
        return None

    async def record(self, span: Any, call: Any) -> None:
        self.rows.append(call)

    async def spend_total(self) -> float:
        return float(sum(r.cost_usd for r in self.rows))


@dataclass(frozen=True)
class Target:
    name: str
    model: str
    base_url: str
    api_key_env: str
    json_mode: str
    extra_body: dict[str, Any] | None
    price_in: float
    price_out: float


def _has_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return PLACEHOLDER in value
    if isinstance(value, Mapping):
        return any(_has_placeholder(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_has_placeholder(v) for v in value)
    return False


def load_target(name: str, env: Mapping[str, str], *, targets_file: Path = TARGETS_FILE) -> Target:
    from app.llm.config import load_llm_config

    cfg = load_llm_config(CONFIG / "llm.yaml")
    if name == DEEPSEEK:
        role = cfg.roles[ROLE]
        provider = cfg.providers[role.provider]
        missing = [v for k, v in DEEPSEEK_ENV.items() if not env.get(v)]
        if missing:
            raise TargetError(f"thiếu biến môi trường {missing} cho đích deepseek (vai trò fast đang chạy)")
        model = env[DEEPSEEK_ENV["model"]]
        price = cfg.pricing.get(model)
        if price is None:
            raise TargetError("model của FAST_MODEL chưa có dòng pricing trong config/llm.yaml")
        return Target(DEEPSEEK, model, env[DEEPSEEK_ENV["base_url"]], DEEPSEEK_ENV["api_key"], provider.json_mode,
                      provider.extra_body, price.in_, price.out)  # fmt: skip
    raw = yaml.safe_load(targets_file.read_text(encoding="utf-8")) or {}
    block = (raw.get("targets") or {}).get(name)
    if not isinstance(block, Mapping):
        raise TargetError(f"không có đích {name!r} trong {targets_file.name}")
    if _has_placeholder(block):
        raise TargetError(f"đích {name!r} trong {targets_file.name} còn ô {PLACEHOLDER} — điền trước khi chạy")
    from app.llm.config import ProviderCfg

    try:
        # cùng luật `extra_body` của gateway: không được trùng tham số gateway điều khiển (temperature, max_tokens…)
        ProviderCfg(kind="openai_compat", base_url_setting="-", api_key_setting="-",
                    json_mode=block.get("json_mode", "json_object"), extra_body=block.get("extra_body"))  # fmt: skip
        if block.get("api_key_env") != JUDGE_KEY_ENV or not str(block.get("base_url", "")).startswith("https://"):
            raise TargetError(f"đích {name!r}: api_key_env phải là {JUDGE_KEY_ENV} và base_url phải https://")
        price = block["price"]
        return Target(name, str(block["model"]), str(block["base_url"]), str(block["api_key_env"]),
                      str(block.get("json_mode", "json_object")), dict(block.get("extra_body") or {}) or None,
                      float(price["in"]), float(price["out"]))  # fmt: skip
    except (KeyError, TypeError, ValueError) as exc:  # ValidationError của pydantic là ValueError
        raise TargetError(f"đích {name!r} trong {targets_file.name} thiếu/sai trường ({type(exc).__name__})") from None


async def _capture(response: Any) -> None:
    """Event hook `httpx2`: giữ `finish_reason`, `provider`, `model`, token suy luận — KHÔNG giữ nội dung."""
    sink = _CAPTURE.get(None)
    if sink is None:
        return
    info: dict[str, Any] = {"status": response.status_code}
    try:
        await response.aread()
        body = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        body = None
    if isinstance(body, dict):
        choices = body.get("choices") or [{}]
        first = choices[0] if isinstance(choices[0], dict) else {}
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
        info.update(finish_reason=first.get("finish_reason"), provider=body.get("provider"), model=body.get("model"),
                    reasoning_tokens=details.get("reasoning_tokens"))  # fmt: skip
    sink.append(info)


@dataclass
class Judge:
    """Một đích LLM chấm đã dựng: `await judge.one(text)` → dòng kết quả (không có chữ đầu vào hay chữ LLM)."""

    target: Target
    client: Any
    closers: list[Callable[[], Any]]

    async def one(self, text: str) -> dict[str, Any]:
        from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
        from app.llm.schemas import InjectionJudgeOut

        sink: list[dict[str, Any]] = []
        token = _CAPTURE.set(sink)
        started = time.perf_counter()
        row: dict[str, Any] = {"model": self.target.model, "is_attack": None, "category": None,
                               "json_valid_first_try": None, "repaired": None, "error": None}  # fmt: skip
        try:
            out, meta = await self.client.complete(ROLE, PROMPT_ID, {"text": text}, InjectionJudgeOut, cache_policy="bypass")
            row.update(is_attack=out.is_attack, category=out.category, json_valid_first_try=meta.json_valid_first_try,
                       repaired=not meta.json_valid_first_try, cost_usd=meta.cost_usd)  # fmt: skip
        except (LLMUnavailable, LLMBudgetExceeded, LLMSchemaError) as exc:
            row["error"] = type(exc).__name__
        finally:
            _CAPTURE.reset(token)
        row["latency_ms"] = round((time.perf_counter() - started) * 1000)
        last = next((c for c in reversed(sink) if c.get("status") == 200), sink[-1] if sink else {})
        row.update(finish_reason=last.get("finish_reason"), provider=last.get("provider"),
                   reasoning_tokens=last.get("reasoning_tokens"), http_attempts=len(sink))  # fmt: skip
        return row

    async def aclose(self) -> None:
        for close in reversed(self.closers):
            await close()


def build_judge(target: Target, env: Mapping[str, str], *, max_usd: float) -> Judge:
    """Dựng `LLMClient` thật cho MỘT đích, không dự phòng. Thiếu khoá → `TargetError` nêu tên biến."""
    import httpx2
    from app.core.clock import SystemClock
    from app.llm.client import LLMClient
    from app.llm.config import Price, RuntimeLlm, SpendCfg, load_llm_config
    from app.llm.config import Target as LlmTarget
    from app.llm.providers.openai_compat import OpenAICompatProvider
    from app.llm.registry import load_prompts
    from pydantic import SecretStr

    key = env.get(target.api_key_env)
    if not key:
        raise TargetError(f"thiếu biến môi trường {target.api_key_env} (khoá của đích {target.name})")
    cfg = load_llm_config(CONFIG / "llm.yaml")
    price = Price.model_validate({"in": target.price_in, "out": target.price_out})
    chain = (LlmTarget(target.name, target.model, None, price),)
    runtime = RuntimeLlm(backend="real", roles=cfg.roles, chains={"fast": chain, "strong": chain}, limits=cfg.limits,
                         spend=SpendCfg(cap_usd=max_usd, warn_ratio=0.8), cache=cfg.cache)  # fmt: skip
    http = httpx2.AsyncClient(event_hooks={"response": [_capture]})
    provider = OpenAICompatProvider(target.name, base_url=target.base_url, api_key=SecretStr(key), json_mode=target.json_mode,
                                    extra_body=target.extra_body, http_client=http)  # fmt: skip
    client = LLMClient(runtime=runtime, registry=load_prompts(CONFIG / "prompts"), providers={target.name: provider},
                       store=MemoryStore(), clock=SystemClock(), cache_mode="bypass")  # fmt: skip
    return Judge(target, client, [http.aclose, provider.aclose])


def environ() -> Mapping[str, str]:
    return os.environ
