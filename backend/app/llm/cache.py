"""Cache LLM (P2 mục 8 [Chốt 17.5], P7 2.4; PLAN-3d Q-3d-5, Q-3d-9).

- **Chế độ:** prompt `cache: bypass` (YAML — nguồn duy nhất) không bao giờ cache, ở MỌI `LLM_CACHE_MODE` kể cả eval;
  node chỉ được làm chặt hơn (`cache_policy="bypass"`). `LLM_CACHE_MODE=bypass` → không đọc, không ghi.
  `eval` → dòng `mode='eval'`, không hết hạn; còn lại → `mode='runtime'`, TTL `cache.ttl_hours_runtime`.
- **Khoá:** sha256 của provider | model | model_version (giá trị GHIM trong llm.yaml — bản thật chỉ biết sau khi gọi) |
  prompt_id | prompt_version | rendered_messages | json_schema | temperature | n | kb_version | **mode** (thêm so với
  P2 vì `cache_key` là PK duy nhất của `llm_cache` mà có hai chế độ).
"""

import hashlib
import json
from typing import Any, Literal

from app.llm.ports import CacheMode, CachePolicy


def cache_mode(
    prompt_cache: Literal["default", "bypass"],
    caller_policy: CachePolicy,
    settings_mode: Literal["default", "eval", "bypass"],
) -> CacheMode | None:
    if prompt_cache == "bypass" or caller_policy == "bypass" or settings_mode == "bypass":
        return None
    return "eval" if settings_mode == "eval" else "runtime"


def cache_key(
    *,
    provider: str,
    model: str,
    model_version: str | None,
    prompt_id: str,
    prompt_version: str,
    messages: list[dict[str, str]],
    json_schema: dict[str, Any],
    temperature: float,
    n: int,
    kb_version: str | None,
    mode: CacheMode,
) -> str:
    parts = [provider, model, model_version or "", prompt_id, prompt_version, messages, json_schema, temperature, n,
             kb_version or "", mode]  # fmt: skip
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
