"""(c) xác suất token — MỘT lời gọi/lá, temperature 0, `logprobs`. Đường RIÊNG (httpx), không qua gateway: gateway cấm
`logprobs`/`top_logprobs` (`app/llm/config.py:43-47` `EXTRA_BODY_FORBIDDEN`) và `ProviderResponse` không mang logprobs.

- Messages: nguyên messages của phiếu `sample_idx = 0` của S1 (prompt `b14_risk_vote`, không viết prompt mới), qua đúng phép biến đổi
  của provider (`json_object` → ghi chú schema cuối system — script gọi `OpenAICompatProvider._messages`; module này nhận `wire` đã biến
  đổi). Thân request: model, messages, temperature 0, max_tokens của vai strong, response_format, `logprobs: true`, `top_logprobs`, rồi
  `extra_body` của provider gộp vào gốc (như SDK openai).
- Base URL / khoá / model: từ `Settings` qua tên trường của `config/llm.yaml` (script truyền vào). Khoá chỉ nằm trong header, không vào
  thân, cache, log hay lỗi; lỗi HTTP chỉ nêu mã.
- Cache: `<run>/cache_c/<sha256(thân request chuẩn hoá)>.json` (thân KHÔNG có khoá). Chạy lại → đọc file, 0 lời gọi mạng. Lỗi không cache.
- Trần chi: trước mỗi lời gọi mạng, `sổ chi + chi phí xấu nhất (token vào ước tính, max_tokens)` > `max_usd` → `BudgetStop`.
- Token quyết định: giá trị của khoá `needs_human` (đầu ra của prompt vote). Vị trí = token đầu tiên mà phần chữ TRƯỚC nó đã có
  `"needs_human"` + dấu `:` (+ khoảng trắng) và chính nó mở đầu giá trị `true`/`false`. Mỗi lựa chọn trong `top_logprobs` ở vị trí đó được
  xếp loại bằng cách ghép vào cùng phần chữ trước. p_c = Σexp(lp | true) / (Σexp(lp | true) + Σexp(lp | false)). Lệch huong-dan:573 ("một
  token Có/Không"): prompt vote trả JSON `needs_human` true/false — dùng lại prompt có sẵn thay vì viết prompt mới (BE duyệt 30/10).
- Không suy p_c từ nguồn khác: không có logprobs / không thấy vị trí → `None` + lý do.
"""

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import httpx
from pydantic import SecretStr

from app.eval.rq2.filestore import SpendLedger, write_atomic
from app.llm.config import Price
from app.llm.context import estimate_tokens

P_METHOD: Final = "token_logprob"  # P8:287
TEMPERATURE: Final = 0.0
TOP_LOGPROBS: Final = 5
KEY_NAME: Final = "needs_human"
_KEY_THEN_COLON = re.compile(r'"needs_human"\s*:\s*')

type CReason = Literal["no_logprobs", "no_decision_token", "no_true_false_alternative", "http_error", "budget"]


class BudgetStop(Exception):
    """Lời gọi tiếp theo có thể vượt `--max-usd` — dừng (c), không gửi."""


class LogprobHttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class Transport(Protocol):
    async def post(self, body: Mapping[str, Any]) -> dict[str, Any]: ...


class HttpxTransport:
    """POST `<base_url>/chat/completions` (như SDK openai). Khoá chỉ ở header `Authorization`."""

    def __init__(self, base_url: str, api_key: SecretStr, *, timeout_s: float, client: httpx.AsyncClient | None = None) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._timeout = timeout_s
        self._client = client or httpx.AsyncClient()

    async def post(self, body: Mapping[str, Any]) -> dict[str, Any]:
        r = await self._client.post(self._url, json=dict(body), timeout=self._timeout,
                                    headers={"Authorization": f"Bearer {self._key.get_secret_value()}"})  # fmt: skip
        if r.status_code // 100 != 2:
            raise LogprobHttpError(r.status_code)
        return dict(r.json())

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass(frozen=True)
class RequestCfg:
    model: str
    max_tokens: int
    response_format: dict[str, Any]
    extra_body: dict[str, Any] | None = None
    top_logprobs: int = TOP_LOGPROBS

    def body(self, wire: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model, "messages": [dict(m) for m in wire], "temperature": TEMPERATURE,
            "max_tokens": self.max_tokens, "response_format": self.response_format, "logprobs": True,
            "top_logprobs": self.top_logprobs,
        }  # fmt: skip
        overlap = set(self.extra_body or {}) & set(body)
        if overlap:
            raise ValueError(f"extra_body trùng khoá thân request: {sorted(overlap)}")
        return {**body, **(self.extra_body or {})}


def body_sha256(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class LogprobClient:
    transport: Transport
    cache_dir: Path
    ledger: SpendLedger
    price: Price
    max_usd: float
    network_calls: int = 0
    cache_hits: int = 0
    _seen: set[str] = field(default_factory=set)

    def _path(self, body: Mapping[str, Any]) -> Path:
        return self.cache_dir / f"{body_sha256(body)}.json"

    async def fetch(self, body: Mapping[str, Any]) -> dict[str, Any]:
        path = self._path(body)
        if path.exists():
            self.cache_hits += 1
            return dict(json.loads(path.read_text(encoding="utf-8")))
        est_in = sum(estimate_tokens(str(m["content"])) for m in body["messages"])
        if self.ledger.total() + self.price.cost(est_in, int(body["max_tokens"])) > self.max_usd:
            raise BudgetStop
        self.network_calls += 1
        resp = await self.transport.post(body)
        usage = resp.get("usage") or {}
        t_in, t_out = usage.get("prompt_tokens"), usage.get("completion_tokens")
        cost = self.price.cost(int(t_in), int(t_out)) if t_in is not None and t_out is not None else \
            self.price.cost(est_in, int(body["max_tokens"]))  # fmt: skip
        self.ledger.add("c", cost)
        write_atomic(path, json.dumps(resp, ensure_ascii=False, sort_keys=True))
        return resp


def _content(resp: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    choices = resp.get("choices") or []
    if not choices:
        return None
    lp = choices[0].get("logprobs")
    if not isinstance(lp, Mapping):
        return None
    content = lp.get("content")
    return list(content) if isinstance(content, list) and content else None


def _value_class(prefix: str, token: str) -> Literal["true", "false", "other", "pending"]:
    """Lớp của giá trị `needs_human` khi ghép `token` sau `prefix`; `pending` = token chưa mở đầu giá trị (khoảng trắng, dấu `:`…)."""
    text = prefix + token
    m = _KEY_THEN_COLON.search(text)
    if m is None:
        return "pending"
    rest = text[m.end() :]
    if not rest:
        return "pending"
    if rest.startswith("true"):
        return "true"
    if rest.startswith("false"):
        return "false"
    return "other"  # gồm token cắt giữa chữ (vd "tr") — không xếp loại


@dataclass(frozen=True)
class Decision:
    p: float | None
    reason: CReason | None
    position: int | None = None
    n_true: int = 0
    n_false: int = 0


def decisive_p(resp: Mapping[str, Any]) -> Decision:
    content = _content(resp)
    if content is None:
        return Decision(None, "no_logprobs")
    prefix = ""
    for i, tok in enumerate(content):
        token = str(tok.get("token", ""))
        if _value_class(prefix, "") == "pending" and _value_class(prefix, token) in ("true", "false"):
            alts: dict[str, float] = {str(a["token"]): float(a["logprob"]) for a in tok.get("top_logprobs") or []}
            alts.setdefault(token, float(tok["logprob"]))
            mass = {"true": 0.0, "false": 0.0}
            count = {"true": 0, "false": 0}
            for alt, lp in alts.items():
                cls = _value_class(prefix, alt)
                if cls in mass:
                    mass[cls] += math.exp(lp)
                    count[cls] += 1
            total = mass["true"] + mass["false"]
            if total <= 0:
                return Decision(None, "no_true_false_alternative", i)
            return Decision(mass["true"] / total, None, i, count["true"], count["false"])
        prefix += token
    return Decision(None, "no_decision_token")


@dataclass(frozen=True)
class Feasibility:
    ok: bool
    evidence: dict[str, Any]


def check_logprobs_feasible(resp: Mapping[str, Any]) -> Feasibility:
    """Kiểm MỘT phản hồi: `choices[0].logprobs.content` có dữ liệu, có `top_logprobs`, tìm được token quyết định. Bằng chứng chỉ có số
    đếm, tên model provider trả, lý do — không có nội dung trả lời."""
    choices = resp.get("choices") or []
    lp = choices[0].get("logprobs") if choices else None
    content = _content(resp)
    d = decisive_p(resp)
    with_top = sum(1 for t in content or [] if t.get("top_logprobs"))
    evidence = {
        "model": resp.get("model"), "n_choices": len(choices), "logprobs_present": lp is not None,
        "content_tokens": len(content or []), "tokens_with_top_logprobs": with_top, "decision_position": d.position,
        "decision_reason": d.reason, "decision_found": d.p is not None,
    }  # fmt: skip
    return Feasibility(content is not None and with_top > 0 and d.p is not None, evidence)
