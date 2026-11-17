"""ml-service (P4, thiết kế Phase 3 mục 4): embed, rerank, count_tokens; classify (khi GUARD_MODEL_DIR đặt — ML-GAN,
không thì 503); classify_intent (khi INTENT_MODEL_DIR đặt — gói 2, D-53, không thì 503).

Chạy: `uvicorn app.main:build --factory --port 8200` (PYTHONPATH=ml_service), **1 worker** — một bản
model; song song hoá bằng threadpool + `asyncio.Semaphore(ML_MAX_CONCURRENCY)`.

- Lifespan nạp model qua `loader` (test tiêm loader giả, không cần torch) rồi warm-up (embed 1 câu,
  rerank 1 cặp, classify 1 câu nếu có model chặn tấn công, classify_intent 1 câu nếu có model intent). Thiếu model →
  exception → service không lên. Chưa nạp xong → `/health` 503 `loading`. `/health` ghi version 2 model của nhóm đã nạp.
- 413 (body > 256 KB, đếm byte đọc thật) → 401 (`X-Service-Token`, trừ `/health`) → 422 (body) → handler.
- Log chỉ ghi endpoint, số phần tử, số ký tự, thời lượng — KHÔNG ghi văn bản. Lỗi 422 trả về không kèm
  giá trị đầu vào (mặc định của FastAPI vọng lại `input`).
- Response thành công có header `X-Model-Version: bge-m3@<rev7>;reranker@<rev7>` (P4 mục 7).
- D-101 (máy demo 17/11 — 3 ticket đồng thời → cả 3 E2 sau 50 s, ~1 phút mới hồi): (1) request mang `X-Client-Timeout` (giây
  backend chịu chờ) mà tới lượt đã chờ quá số đó → BỎ, không chạy model (`to_thread` không huỷ được việc đang chạy, nhưng việc
  CHƯA chạy thì bỏ được — trước đây hàng chờ phình vì làm nốt mọi request backend đã bỏ và cả các lần thử lại); trả 503
  `abandoned` (backend đã đi). Thiếu / sai header → chạy như cũ. (2) `/embed` + `/count_tokens` có hàng chờ riêng
  (`ML_EMBED_CONCURRENCY`) — không xếp sau rerank.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth import require_token
from app.classify import classify_failed, model_missing, too_many_windows
from app.embed import embed_sync
from app.guard import MAX_WINDOWS, TooManyWindows, classify_sync
from app.intent import classify_intent_sync, intent_missing
from app.limits import BodyLimitMiddleware
from app.loader import load_models
from app.models import GUARD_LABEL, INTENT_LABEL, Models
from app.rerank import rerank_sync
from app.schemas import (
    ClassifyIn,
    ClassifyOut,
    CountIn,
    CountOut,
    EmbedIn,
    EmbedOut,
    IntentIn,
    IntentOut,
    RerankIn,
    RerankOut,
)
from app.settings import MlSettings
from app.tokens import count

log = logging.getLogger("app.ml_service")

MODEL_VERSION_HEADER = "X-Model-Version"
CLIENT_TIMEOUT_HEADER = "X-Client-Timeout"  # D-101: giây backend chịu chờ cho lần gọi này
MAX_CLIENT_TIMEOUT_S = 120.0
WARM_UP_TEXT = "khởi động ml-service"


class Abandoned(Exception):
    """D-101: request đã chờ trong hàng quá `X-Client-Timeout` — backend đã bỏ, không chạy model."""

    def __init__(self, endpoint: str, waited: float) -> None:
        super().__init__(endpoint)
        self.endpoint = endpoint
        self.waited = waited


def client_timeout(request: Request) -> float | None:
    """Giá trị header hợp lệ (0 < x ≤ 120) hoặc None (thiếu / sai → không bỏ, chạy như cũ)."""
    raw = request.headers.get(CLIENT_TIMEOUT_HEADER)
    try:
        value = float(raw) if raw is not None else None
    except ValueError:
        return None
    return value if value is not None and 0 < value <= MAX_CLIENT_TIMEOUT_S else None

type Loader = Callable[[MlSettings], Models]


def warm_up(models: Models) -> None:
    embed_sync(models, [WARM_UP_TEXT])
    rerank_sync(models, WARM_UP_TEXT, [WARM_UP_TEXT])
    if models.guard is not None:
        classify_sync(models.guard, WARM_UP_TEXT)
    if models.intent is not None:
        classify_intent_sync(models.intent, WARM_UP_TEXT)


def create_app(settings: MlSettings | None = None, loader: Loader = load_models) -> FastAPI:
    settings = settings or MlSettings()  # type: ignore[call-arg]  # token bắt buộc lấy từ env

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        started = time.perf_counter()
        models = await anyio.to_thread.run_sync(loader, settings)
        await anyio.to_thread.run_sync(warm_up, models)
        app.state.models = models
        app.state.ready = True
        log.info("đã nạp model %s trong %.1f s", models.version, time.perf_counter() - started)
        yield
        app.state.ready = False

    app = FastAPI(title="servicedesk-ml", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.token = settings.ml_service_token.get_secret_value().encode()
    app.state.ready = False
    app.state.models = None
    limiter = asyncio.Semaphore(settings.ml_max_concurrency)
    # Phase 5 gói 1 (D-52, ĐT 4.6): hàng chờ RIÊNG cho /classify và /classify_intent — classify không chờ rerank (10–15 s) rồi
    # hết hạn 2 s của backend
    classify_limiter = asyncio.Semaphore(settings.ml_classify_concurrency)
    embed_limiter = asyncio.Semaphore(settings.ml_embed_concurrency)  # D-101: /embed + /count_tokens không chờ rerank

    async def queued[T](
        gate: asyncio.Semaphore, request: Request, endpoint: str, fn: Callable[..., T], *args: Any
    ) -> T:
        """D-101: chờ hàng, tới lượt mà đã quá `X-Client-Timeout` → `Abandoned` (không chạy model)."""
        arrived, budget = time.perf_counter(), client_timeout(request)
        async with gate:
            waited = time.perf_counter() - arrived
            if budget is not None and waited >= budget:
                raise Abandoned(endpoint, waited)
            return await anyio.to_thread.run_sync(fn, *args)

    async def run[T](fn: Callable[..., T], *args: Any) -> T:
        async with limiter:
            return await anyio.to_thread.run_sync(fn, *args)

    async def run_classify[T](fn: Callable[..., T], *args: Any) -> T:
        async with classify_limiter:
            return await anyio.to_thread.run_sync(fn, *args)

    @app.exception_handler(Abandoned)
    async def abandoned(_: Request, exc: Abandoned) -> JSONResponse:
        log.info("%s bỏ: đã chờ %.1f s > X-Client-Timeout — backend đã đi, không chạy model", exc.endpoint, exc.waited)
        return JSONResponse({"error": "abandoned"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = [{"loc": e.get("loc"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse({"error": "invalid_request", "detail": detail}, status_code=422)

    @app.middleware("http")
    async def model_version(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        models: Models | None = request.app.state.models
        if models is not None and response.status_code < 400:
            response.headers[MODEL_VERSION_HEADER] = models.version
        return response

    def loaded(request: Request) -> Models:
        models: Models | None = request.app.state.models
        if models is None:  # lifespan chưa xong — uvicorn chưa nhận request, chỉ để chắc
            raise RuntimeError("model chưa nạp")
        return models

    @app.get("/health", response_model=None)
    async def health(request: Request) -> dict[str, Any] | JSONResponse:
        models: Models | None = request.app.state.models
        if not request.app.state.ready or models is None:
            return JSONResponse({"status": "loading"}, status_code=503)
        guard, intent = models.guard, models.intent
        return {
            "status": "ok",
            "models": {
                "embed": {"repo": models.embed.repo, "revision": models.embed.revision, "dim": models.dim},
                "rerank": {"repo": models.rerank.repo, "revision": models.rerank.revision},
                "injection": {"model": GUARD_LABEL, "version": guard.version} if guard else "missing",
                "intent": {"model": INTENT_LABEL, "version": intent.version} if intent else "missing",
            },
        }  # fmt: skip

    api = APIRouter(dependencies=[Depends(require_token)])

    @api.post("/embed")
    async def embed(body: EmbedIn, request: Request) -> EmbedOut:
        started = time.perf_counter()
        out = await queued(embed_limiter, request, "embed", embed_sync, loaded(request), body.texts)
        _log("embed", len(body.texts), sum(map(len, body.texts)), started, sum(out.truncated))
        return out

    @api.post("/rerank")
    async def rerank(body: RerankIn, request: Request) -> RerankOut:
        started = time.perf_counter()
        out = await queued(limiter, request, "rerank", rerank_sync, loaded(request), body.query, body.passages)
        chars = len(body.query) + sum(map(len, body.passages))
        _log("rerank", len(body.passages), chars, started, sum(out.truncated))
        return out

    @api.post("/count_tokens")
    async def count_tokens(body: CountIn, request: Request) -> CountOut:
        started = time.perf_counter()
        models = loaded(request)
        counts = await queued(embed_limiter, request, "count_tokens", lambda: [count(models.tokenizer, t) for t in body.texts])
        _log("count_tokens", len(body.texts), sum(map(len, body.texts)), started, 0)
        return CountOut(counts=counts, model=models.embed.repo)

    @api.post("/classify", response_model=None)
    async def classify(body: ClassifyIn, request: Request) -> ClassifyOut | JSONResponse:
        guard = loaded(request).guard
        if guard is None:
            return model_missing()
        started = time.perf_counter()
        try:
            out = await run_classify(classify_sync, guard, body.text)
        except TooManyWindows as e:  # không chấm một phần (chốt 7b PLAN-ml-gan)
            log.info("classify chars=%d windows=%d > %d → 422", len(body.text), e.count, MAX_WINDOWS)
            return too_many_windows(e.count)
        except Exception as e:  # noqa: BLE001 — gói 1 #10: lỗi suy luận → 500 mã chung; log TÊN lớp lỗi, không thông điệp/chữ
            log.error("classify chars=%d lỗi suy luận %s → 500 classify_failed", len(body.text), type(e).__name__)
            return classify_failed()
        log.info(
            "classify chars=%d windows=%d ms=%.0f",
            len(body.text), out.windows, (time.perf_counter() - started) * 1000,
        )  # fmt: skip
        return out

    @api.post("/classify_intent", response_model=None)
    async def classify_intent(body: IntentIn, request: Request) -> IntentOut | JSONResponse:
        intent = loaded(request).intent
        if intent is None:
            return intent_missing()
        started = time.perf_counter()
        try:  # gói 2: cùng hàng chờ và cách bọc lỗi như /classify (Q-B2R-11)
            out = await run_classify(classify_intent_sync, intent, body.text)
        except Exception as e:  # noqa: BLE001 — lỗi suy luận / điểm NaN → 500 mã chung; log TÊN lớp lỗi, không thông điệp/chữ
            log.error("classify_intent chars=%d lỗi suy luận %s → 500 classify_failed", len(body.text), type(e).__name__)
            return classify_failed()
        log.info(
            "classify_intent chars=%d truncated=%d ms=%.0f",
            len(body.text), int(out.truncated), (time.perf_counter() - started) * 1000,
        )  # fmt: skip
        return out

    app.include_router(api)
    app.add_middleware(BodyLimitMiddleware)  # thêm sau cùng = lớp ngoài cùng: 413 trước mọi thứ
    return app


def _log(endpoint: str, items: int, chars: int, started: float, truncated: int) -> None:
    # KHÔNG ghi văn bản (P4 mục 4): chỉ số phần tử, độ dài, thời lượng, số phần tử bị cắt.
    log.info(
        "%s items=%d chars=%d truncated=%d ms=%.0f",
        endpoint, items, chars, truncated, (time.perf_counter() - started) * 1000,
    )  # fmt: skip


def build() -> FastAPI:
    """Entrypoint cho uvicorn: `uvicorn app.main:build --factory`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
