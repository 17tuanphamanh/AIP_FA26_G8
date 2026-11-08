"""`FakeMlService` — ml-service giả ở tầng HTTP (thiết kế Phase 3 mục 4.6, Q-3a-6).

Là một `httpx.MockTransport` đặt SAU `MlClient` thật: test đi qua đúng retry, chia lô, phân loại lỗi của
client; số lời gọi đếm ở NƠI NHẬN (`calls`, quy ước 3.9). Tất định và có ngữ nghĩa, để test truy hồi phân
biệt được tài liệu đúng/sai:

- Embed: NFC + chữ thường, tách âm tiết theo chữ/số, bỏ stopword nhỏ; băm từng âm tiết và từng cặp âm
  tiết liền nhau (`blake2b` — tất định giữa các process, khác `hash()`) → 1024 chiều, đếm tần suất, chuẩn
  hoá L2. Hai câu chung nhiều từ → cosine cao.
- Rerank: |T(q) ∩ T(p)| / max(1, |T(q)|) trên tập âm tiết → đã nằm trong [0, 1]. `rerank_score=<số>` (Phase 4 s8): mọi
  đoạn trả đúng điểm đó — ép điểm truy hồi thấp như reranker thật với câu mệnh lệnh (tc09 0,047).
- Count: ceil(1,5 × số âm tiết) + 2 — chỉ dùng khi test không kiểm giới hạn token thật.
- `fail_next(endpoint, kind, times)`, `kind` ∈ {timeout, http_500, model_missing}; `truncate_all=True`.
- `slow(endpoint, seconds, times)` (3f S0, hạn cả lượt): request tốn `seconds` giây trên FakeClock của `client(clock)`;
  `seconds` ≥ timeout client gửi → tua đúng timeout rồi `ReadTimeout` (như server chậm thật). `seen` ghi (endpoint,
  timeout đọc, thời điểm nhận) ở NƠI NHẬN.
- `/classify`, `/classify_intent` mặc định 503 `model_missing` như ml-service Phase 3. `classify_p=<số>` (3e, e18):
  `/classify` trả `p_malicious` đó — để test nhánh ngưỡng L3 của B2 trước khi có model thật.
"""

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Literal

import httpx
from app.core.clock import Clock, FakeClock
from app.ml import MlClient

TOKEN = "fake-ml-service-token-" + "x" * 16
BASE_URL = "http://ml-fake:8200"
DIM = 1024
MODEL_VERSION = "bge-m3@fake000;reranker@fake000"
STOPWORDS = frozenset({
    "và", "là", "của", "có", "tôi", "bị", "thì", "mà", "này", "cho", "với", "các", "những", "một", "được", "để",
    "khi", "ở", "trong", "ra", "vào", "rồi", "đã", "đang", "sẽ", "không", "cũng", "như", "nhé", "ạ",
})  # fmt: skip
_SYLLABLE = re.compile(r"\w+")

type FaultKind = Literal["timeout", "http_500", "model_missing"]


def syllables(text: str) -> list[str]:
    norm = unicodedata.normalize("NFC", text).lower()
    return [s for s in _SYLLABLE.findall(norm) if s not in STOPWORDS]


def _bucket(feature: str) -> int:
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % DIM


def embed_text(text: str) -> list[float]:
    s = syllables(text)
    vec = [0.0] * DIM
    for feature in s + [f"{a} {b}" for a, b in pairwise(s)]:
        vec[_bucket(feature)] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def rerank_score(query: str, passage: str) -> float:
    q = set(syllables(query))
    return len(q & set(syllables(passage))) / max(1, len(q))


def count_tokens(text: str) -> int:
    return math.ceil(1.5 * len(syllables(text))) + 2


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vector đã chuẩn hoá L2


class FakeMlService:
    def __init__(
        self, *, truncate_all: bool = False, classify_p: float | None = None,
        intent_probs: dict[str, float] | None = None, rerank_score: float | None = None, truncate_embed: bool = False,
    ) -> None:  # fmt: skip
        self.truncate_all = truncate_all
        self.truncate_embed = truncate_embed  # R2: CHỈ `/embed` báo cắt (câu truy vấn); rerank không báo gì
        self.rerank_score = rerank_score
        self.classify_p = classify_p
        self.intent_probs = intent_probs  # 3f: `/classify_intent` trả xác suất này (model "đã có") thay vì model_missing
        self.calls: Counter[str] = Counter()
        self._faults: dict[str, list[FaultKind]] = {}
        self._slow: dict[str, list[float]] = {}
        self._clock: FakeClock | None = None
        self.seen: list[tuple[str, float | None, datetime | None]] = []
        self.transport = httpx.MockTransport(self._handle)

    def slow(self, endpoint: str, seconds: float, times: int = 1) -> "FakeMlService":
        self._slow.setdefault(endpoint, []).extend([seconds] * times)
        return self

    def fail_next(self, endpoint: str, kind: FaultKind, times: int = 1) -> "FakeMlService":
        self._faults.setdefault(endpoint, []).extend([kind] * times)
        return self

    def client(self, clock: Clock | None = None) -> MlClient:
        http = httpx.AsyncClient(transport=self.transport, base_url=BASE_URL)
        clock = clock or FakeClock()
        if isinstance(clock, FakeClock):
            self._clock = clock
        return MlClient(http, TOKEN, clock=clock)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.strip("/")
        self.calls[endpoint] += 1
        timeout = (request.extensions.get("timeout") or {}).get("read")
        self.seen.append((endpoint, timeout, self._clock.now() if self._clock else None))
        if request.headers.get("X-Service-Token") != TOKEN:
            return httpx.Response(401, json={"detail": "invalid_service_token"})
        slow = self._slow.get(endpoint)
        if slow and self._clock is not None:
            seconds = slow.pop(0)
            if timeout is not None and seconds >= timeout:
                self._clock.advance(timedelta(seconds=timeout))
                raise httpx.ReadTimeout("ml-service giả: chậm quá timeout", request=request)
            self._clock.advance(timedelta(seconds=seconds))
        faults = self._faults.get(endpoint)
        if faults:
            kind = faults.pop(0)
            if kind == "timeout":
                raise httpx.ReadTimeout("ml-service giả: hết giờ", request=request)
            if kind == "http_500":
                return httpx.Response(500, json={"detail": "loi_gia"})
            return httpx.Response(503, json={"error": "model_missing"})
        body = json.loads(request.content)
        headers = {"X-Model-Version": MODEL_VERSION}
        if endpoint == "embed":
            texts = body["texts"]
            counts = [count_tokens(t) for t in texts]
            out = {
                "vectors": [embed_text(t) for t in texts], "dim": DIM, "model": "BAAI/bge-m3",
                "truncated": [self.truncate_all or self.truncate_embed or n > 512 for n in counts], "token_counts": counts,
            }  # fmt: skip
        elif endpoint == "rerank":
            passages = body["passages"]
            out = {
                "scores": [rerank_score(body["query"], p) if self.rerank_score is None else self.rerank_score
                           for p in passages],
                "truncated": [self.truncate_all] * len(passages),
                "query_truncated": self.truncate_all, "model": "BAAI/bge-reranker-v2-m3",
            }  # fmt: skip
        elif endpoint == "count_tokens":
            out = {"counts": [count_tokens(t) for t in body["texts"]], "model": "BAAI/bge-m3"}
        elif endpoint == "classify" and self.classify_p is not None:
            out = {"p_malicious": self.classify_p, "windows": 1, "model": "injection-clf-gia", "version": "0"}
        elif endpoint == "classify_intent" and self.intent_probs is not None:
            half = dict.fromkeys(self.intent_probs, 0.5)
            out = {"probs": self.intent_probs, "tau_hi": half, "tau_lo": half, "truncated": False,
                   "model": "intent-clf-gia", "version": "0"}  # fmt: skip
        elif endpoint in ("classify", "classify_intent"):
            return httpx.Response(503, json={"error": "model_missing"})
        else:
            return httpx.Response(404, json={"detail": "not_found"})
        return httpx.Response(200, json=out, headers=headers)
