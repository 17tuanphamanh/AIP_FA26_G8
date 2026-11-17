"""`MlClient` — cổng DUY NHẤT từ backend tới ml-service (thiết kế Phase 3 mục 4.5, 3-Q7).

- Retry dùng lại `tools/retry.call_with_retry` (TOOL_RETRY = 2, backoff 1 s, 2 s) — không có vòng retry thứ
  hai. Lỗi tạm thời: timeout, mất kết nối, 5xx/429. `httpx.TransportError` khác (vd. `RemoteProtocolError`
  khi ml-service bị OOMKilled giữa request) cũng coi là mất kết nối, có retry (Q-3a-3) — `call_with_retry`
  tự nó không bắt loại này.
- 503 `{"error": "model_missing"}` → trả ngay `error="model_missing"`, KHÔNG retry (không tốn 3 s mỗi ticket
  khi nhóm chưa có model).
- Phase 5 (T23a, P4 — Q-5-9): `/classify` 422 `{"error": "too_many_windows"}` (văn bản > 48 cửa sổ, ml-service không chấm một
  phần) → trả ngay `error="too_many_windows"`, KHÔNG retry — lỗi lớp 3 như `model_missing`, B2 xuống L4 (không E9).
- Phase 5 gói 1 (D-52, phase5 §6.5 #10, ĐT 4.6): 500 `{"error": "classify_failed"}` của `/classify`, `/classify_intent` (lỗi suy
  luận đã bắt ở ml-service) → trả ngay `error="classify_failed"`, KHÔNG BAO GIỜ thử lại. `/classify` hết thời gian chờ → trả ngay
  `error="timeout"`, KHÔNG thử lại (`to_thread` ở ml-service không huỷ được: mỗi lần thử lại chiếm hàng chờ thêm ~2 s và kéo
  ticket khác timeout theo); mất kết nối và 5xx khác vẫn thử lại như cũ.
- 401/413/422 khác/404, response sai schema, một văn bản vượt giới hạn byte → raise `MlContractError`. Thông điệp
  chỉ có endpoint + mã HTTP, không kèm body (body có thể chứa văn bản người dùng).
- Tự chia lô theo số phần tử (khớp `ml_service/app/schemas.py`) VÀ theo byte (dưới giới hạn 256 KB của
  ml-service): lô lỗi đầu tiên → dừng, trả lỗi; `attempts` cộng dồn qua các lô (Q-3a-12).
- Span `ml:<endpoint>`: một dòng log (như `ToolRegistry._span`) — không ghi văn bản.
- Hạn cho cả lượt (phase3 9.0): timeout mỗi lần thử = `cap_timeout(TIMEOUT_S[endpoint])`; hết → `TurnBudgetExceeded`
  (KHÔNG thành `MlResult.error` — B2/B3 không được "rơi xuống LLM" khi chính lượt đã hết giờ).
- D-101 (máy demo 17/11: 3 ticket đồng thời → cả 3 E2 `rag_system_error` sau 50 s, ~1 phút mới hồi): ml-service chạy rerank MỘT việc
  một lúc (5–15 s/lần trên CPU máy demo); timeout 18 s + thử lại 2 lần xếp thêm việc vào cuối hàng trong khi ml-service vẫn làm nốt
  việc đã bỏ → hàng chờ phình. Nay: (1) mỗi lời gọi gửi `X-Client-Timeout` (giây chờ của lần thử) — ml-service bỏ việc đã chờ quá số
  đó thay vì chạy; (2) `/rerank` chờ MỘT lần tới 40 s (trong `RAG_DEADLINE_S` 50 s), hết giờ / 5xx KHÔNG thử lại (thử lại sau 18 s gần
  như luôn vượt hạn 50 s, chỉ thêm tải) — mất kết nối vẫn thử lại; (3) mọi endpoint: timeout KẾT NỐI ≤ `CONNECT_TIMEOUT_S` (mạng
  docker nội bộ) — trần xấu nhất `/rerank` = 2·5 + 3 + 40 = 53 s < `WORKER_STALE_TURN_SECONDS`/2.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.core.clock import Clock, SystemClock
from app.core.turn_budget import cap_timeout
from app.ml.models import ClassifyOut, CountOut, EmbedOut, IntentOut, RerankOut
from app.ml.ports import MlContractError, MlError, MlResult
from app.tools.retry import call_with_retry

log = logging.getLogger(__name__)

# Số phần tử tối đa mỗi request — PHẢI khớp ml_service/app/schemas.py (test đọc file đó bằng AST).
EMBED_MAX_ITEMS = 64
RERANK_MAX_PASSAGES = 32
COUNT_MAX_ITEMS = 256
# ml-service chặn body > 256 KB (413); chừa phần đầu JSON và câu truy vấn.
MAX_REQUEST_BYTES = 200 * 1024
# Giây mỗi lần gọi (thiết kế 3a mục 4.5). rerank=18: trần cho phép của Q-3a-16 (PLAN-3c mục 6.2 điểm 3,
# 3·T+3 < WORKER_STALE_TURN_SECONDS/2=60 → T ≤ 18) — KHÔNG phải 2×p95 đo thật (tier ② trung vị p95 10,4 s
# trên CPU dev, lớn nhất đo được 12,4 s, vẫn dưới 18 s nên timeout trên máy chậm sẽ là E2 an toàn, không
# phải false-negative). Xem PROGRESS S9 (Q-3a-16) và nợ kỹ thuật đo lại trên máy staging GPU (N2).
# D-101: rerank 18 → 40 (một lần, không thử lại khi hết giờ — xem docstring).
TIMEOUT_S = {"embed": 5.0, "rerank": 40.0, "count_tokens": 5.0, "classify": 2.0, "classify_intent": 2.0}
CONNECT_TIMEOUT_S = 5.0  # D-101: kết nối tới ml-service (mạng docker nội bộ) — không chờ cả 40 s của rerank chỉ để kết nối
MODEL_VERSION_HEADER = "X-Model-Version"
CLIENT_TIMEOUT_HEADER = "X-Client-Timeout"  # D-101: ml-service bỏ việc đã chờ quá số giây này
CLASSIFY_ENDPOINTS = frozenset({"classify", "classify_intent"})  # gói 1: 500 `classify_failed` là lỗi lớp 3, không thử lại
NO_TIMEOUT_RETRY = frozenset({"classify", "rerank"})  # gói 1 (ĐT 4.6): timeout không thử lại; D-101: thêm rerank
NO_SLOW_RETRY = frozenset({"rerank"})  # D-101: 5xx cũng không thử lại (một lần chờ dài là đủ; chỉ mất kết nối mới thử lại)

_SYSTEM_CLOCK = SystemClock()


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def batches(items: list[str], max_items: int, budget: int) -> list[list[str]]:
    """Chia `items` thành lô ≤ `max_items` phần tử và ≤ `budget` byte JSON, giữ thứ tự."""
    if not items:
        raise MlContractError("gọi ml-service với danh sách rỗng")
    out: list[list[str]] = []
    current: list[str] = []
    size = 0
    for i, item in enumerate(items):
        n = len(_dumps(item)) + 1  # + dấu phẩy
        if n > budget:
            raise MlContractError(
                f"văn bản thứ {i} dài {n} byte JSON — vượt {budget} byte của một request ml-service; "
                "phải chia nhỏ trước khi gọi"
            )
        if current and (len(current) == max_items or size + n > budget):
            out.append(current)
            current, size = [], 0
        current.append(item)
        size += n
    out.append(current)
    return out


def _error_code(response: httpx.Response) -> object:
    """`body["error"]` của ml-service (`model_missing`, `too_many_windows`); body khác → None."""
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("error") if isinstance(body, dict) else None


class _TimeoutNoRetry(Exception):
    """`/classify`, `/rerank` hết thời gian chờ (D-101: `/rerank` cả 5xx) — thoát `call_with_retry` ngay (nó chỉ bắt lỗi httpx), không
    thử lại."""


def _is_l3_error(endpoint: str, response: httpx.Response) -> bool:
    """Lỗi trả như GIÁ TRỊ, không retry: 503 `model_missing` (mọi endpoint phân loại), 500 `classify_failed` (gói 1, hai endpoint
    phân loại) và 422 `too_many_windows` CHỈ của `/classify` (T23a P4) — 422 khác vẫn là lỗi hợp đồng, 500 khác vẫn thử lại."""
    if response.status_code == 503:
        return _error_code(response) == "model_missing"
    if response.status_code == 500:
        return endpoint in CLASSIFY_ENDPOINTS and _error_code(response) == "classify_failed"
    return endpoint == "classify" and response.status_code == 422 and _error_code(response) == "too_many_windows"


class MlClient:
    def __init__(
        self, http: httpx.AsyncClient, token: str, *, clock: Clock = _SYSTEM_CLOCK,
        retries: int | None = None,
    ) -> None:  # fmt: skip
        self._http = http  # base_url = ML_SERVICE_URL; người dựng tự đóng
        self._headers = {"X-Service-Token": token, "Content-Type": "application/json"}
        self._clock = clock
        self._retries = retries  # None → TOOL_RETRY của policy.json

    async def embed(self, texts: list[str]) -> MlResult[EmbedOut]:
        bodies = [{"texts": b} for b in batches(texts, EMBED_MAX_ITEMS, MAX_REQUEST_BYTES)]

        def merge(parts: list[EmbedOut]) -> EmbedOut:
            return EmbedOut(
                vectors=[v for p in parts for v in p.vectors], dim=parts[0].dim, model=parts[0].model,
                truncated=[t for p in parts for t in p.truncated],
                token_counts=[n for p in parts for n in p.token_counts],
            )  # fmt: skip

        return await self._collect("embed", bodies, EmbedOut, merge, len(texts))

    async def rerank(self, query: str, passages: list[str]) -> MlResult[RerankOut]:
        budget = MAX_REQUEST_BYTES - len(_dumps(query))
        if budget <= 0:
            raise MlContractError("câu truy vấn vượt giới hạn byte của một request ml-service")
        bodies = [
            {"query": query, "passages": b}
            for b in batches(passages, RERANK_MAX_PASSAGES, budget)
        ]  # fmt: skip

        def merge(parts: list[RerankOut]) -> RerankOut:
            return RerankOut(
                scores=[s for p in parts for s in p.scores],
                truncated=[t for p in parts for t in p.truncated],
                query_truncated=any(p.query_truncated for p in parts), model=parts[0].model,
            )  # fmt: skip

        return await self._collect("rerank", bodies, RerankOut, merge, len(passages))

    async def count_tokens(self, texts: list[str]) -> MlResult[CountOut]:
        bodies = [{"texts": b} for b in batches(texts, COUNT_MAX_ITEMS, MAX_REQUEST_BYTES)]

        def merge(parts: list[CountOut]) -> CountOut:
            return CountOut(counts=[c for p in parts for c in p.counts], model=parts[0].model)

        return await self._collect("count_tokens", bodies, CountOut, merge, len(texts))

    async def classify(self, text: str) -> MlResult[ClassifyOut]:
        batches([text], 1, MAX_REQUEST_BYTES)  # một văn bản quá lớn → MlContractError
        return await self._collect("classify", [{"text": text}], ClassifyOut, lambda p: p[0], 1)

    async def classify_intent(self, text: str) -> MlResult[IntentOut]:
        batches([text], 1, MAX_REQUEST_BYTES)
        return await self._collect("classify_intent", [{"text": text}], IntentOut, lambda p: p[0], 1)

    async def _collect[M: BaseModel](
        self, endpoint: str, bodies: list[dict[str, Any]], model: type[M],
        merge: Callable[[list[M]], M], items: int,
    ) -> MlResult[M]:  # fmt: skip
        started = time.perf_counter()
        parts: list[M] = []
        attempts = 0
        version: str | None = None
        result: MlResult[M] | None = None
        for body in bodies:
            one = await self._post(endpoint, _dumps(body), model)
            attempts += one.attempts
            version = version or one.model_version
            if one.data is None:
                result = MlResult(None, one.error, attempts, version)
                break
            parts.append(one.data)
        if result is None:
            result = MlResult(merge(parts), None, attempts, version)
        log.info(
            "ml:%s items=%d batches=%d attempts=%d error=%s model_version=%s ms=%.0f",
            endpoint, items, len(bodies), attempts, result.error, version,
            (time.perf_counter() - started) * 1000,
        )  # fmt: skip
        return result

    async def _post[M: BaseModel](self, endpoint: str, payload: bytes, model: type[M]) -> MlResult[M]:
        kind: MlError = "connect"  # loại lỗi của lần gọi gần nhất

        async def once() -> httpx.Response:
            nonlocal kind
            try:
                timeout = cap_timeout(TIMEOUT_S[endpoint], self._clock, what=f"ml:{endpoint}")  # 9.0
                headers = {**self._headers, CLIENT_TIMEOUT_HEADER: f"{timeout:.3f}"}  # D-101
                response = await self._http.post(
                    f"/{endpoint}", content=payload, headers=headers,
                    timeout=httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT_S)),
                )  # fmt: skip
            except httpx.TimeoutException as e:
                kind = "timeout"
                # chỉ timeout khi ĐÃ gửi (ml-service có thể đang chấm, `to_thread` không huỷ) mới không thử lại; chưa kết nối
                # được / chờ pool thì request chưa tới ml-service → thử lại như mất kết nối (ĐT 4.6)
                if endpoint in NO_TIMEOUT_RETRY and not isinstance(e, httpx.ConnectTimeout | httpx.PoolTimeout):
                    raise _TimeoutNoRetry from None
                raise
            except httpx.ConnectError:
                kind = "connect"
                raise
            except httpx.TransportError as e:  # Q-3a-3: đứt giữa chừng = mất kết nối, có retry
                kind = "connect"
                raise httpx.ConnectError(f"{type(e).__name__}: {e}") from e
            if _is_l3_error(endpoint, response):
                return response  # không raise → call_with_retry trả ngay, không retry
            if response.status_code >= 500 or response.status_code == 429:
                kind = "http_5xx"
                if endpoint in NO_SLOW_RETRY:  # D-101: không thử lại rerank sau 5xx
                    raise _TimeoutNoRetry
            response.raise_for_status()
            return response

        try:
            response, error, attempts = await call_with_retry(
                once, retries=self._retries, clock=self._clock, what=f"ml:{endpoint}"
            )
        except _TimeoutNoRetry:
            # timeout bị cắt theo hạn lượt mà lượt đã hết → TurnBudgetExceeded (giữ bất biến 9.0: không rơi xuống LLM khi chính
            # lượt hết giờ — trước gói 1 việc này do `check_sleep` của lần thử lại làm)
            cap_timeout(TIMEOUT_S[endpoint], self._clock, what=f"ml:{endpoint}")
            return MlResult(None, kind, 1)
        except httpx.HTTPStatusError as e:  # 4xx khác 404/429: call_with_retry raise lại, không retry
            raise MlContractError(f"ml-service /{endpoint}: HTTP {e.response.status_code}") from e
        if error is not None:
            return MlResult(None, kind, attempts)
        if response is None:  # 404: call_with_retry coi là "không tồn tại" — với ml-service là sai URL
            raise MlContractError(f"ml-service /{endpoint}: HTTP 404 (kiểm ML_SERVICE_URL)")
        version = response.headers.get(MODEL_VERSION_HEADER)
        if response.status_code == 503:
            return MlResult(None, "model_missing", attempts, version)
        if response.status_code == 500:  # chỉ tới đây khi `_is_l3_error` (classify_failed)
            return MlResult(None, "classify_failed", attempts, version)
        if response.status_code == 422:  # chỉ tới đây khi `_is_l3_error` (too_many_windows của /classify)
            return MlResult(None, "too_many_windows", attempts, version)
        try:
            data = model.model_validate(response.json())
        except (ValueError, ValidationError) as e:
            raise MlContractError(f"ml-service /{endpoint}: response sai schema") from e
        return MlResult(data, None, attempts, version)
