"""ml-service (P4, thiết kế Phase 3 mục 4): embed, rerank, count_tokens; classify/classify_intent → 503.

Chạy: `uvicorn app.main:build --factory --port 8200` (PYTHONPATH=ml_service), **1 worker** — một bản
model; song song hoá bằng threadpool + `asyncio.Semaphore(ML_MAX_CONCURRENCY)`.

- Lifespan nạp model qua `loader` (test tiêm loader giả, không cần torch) rồi warm-up (embed 1 câu,
  rerank 1 cặp). Thiếu model → exception → service không lên. Chưa nạp xong → `/health` 503 `loading`.
- 413 (body > 256 KB, đếm byte đọc thật) → 401 (`X-Service-Token`, trừ `/health`) → 422 (body) → handler.
- Log chỉ ghi endpoint, số phần tử, số ký tự, thời lượng — KHÔNG ghi văn bản. Lỗi 422 trả về không kèm
  giá trị đầu vào (mặc định của FastAPI vọng lại `input`).
- Response thành công có header `X-Model-Version: bge-m3@<rev7>;reranker@<rev7>` (P4 mục 7).
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
from app.classify import model_missing
from app.embed import embed_sync
from app.intent import intent_missing
from app.limits import BodyLimitMiddleware
from app.loader import load_models
from app.models import Models
from app.rerank import rerank_sync
from app.schemas import (
    ClassifyIn,
    CountIn,
    CountOut,
    EmbedIn,
    EmbedOut,
    IntentIn,
    RerankIn,
    RerankOut,
)
from app.settings import MlSettings
from app.tokens import count

log = logging.getLogger("app.ml_service")

MODEL_VERSION_HEADER = "X-Model-Version"
WARM_UP_TEXT = "khởi động ml-service"

type Loader = Callable[[MlSettings], Models]


def warm_up(models: Models) -> None:
    embed_sync(models, [WARM_UP_TEXT])
    rerank_sync(models, WARM_UP_TEXT, [WARM_UP_TEXT])


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

    async def run[T](fn: Callable[..., T], *args: Any) -> T:
        async with limiter:
            return await anyio.to_thread.run_sync(fn, *args)

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
        return {
            "status": "ok",
            "models": {
                "embed": {"repo": models.embed.repo, "revision": models.embed.revision, "dim": models.dim},
                "rerank": {"repo": models.rerank.repo, "revision": models.rerank.revision},
                "injection": "missing", "intent": "missing",  # Phase 5 (P11)
            },
        }  # fmt: skip

    api = APIRouter(dependencies=[Depends(require_token)])

    @api.post("/embed")
    async def embed(body: EmbedIn, request: Request) -> EmbedOut:
        started = time.perf_counter()
        out = await run(embed_sync, loaded(request), body.texts)
        _log("embed", len(body.texts), sum(map(len, body.texts)), started, sum(out.truncated))
        return out

    @api.post("/rerank")
    async def rerank(body: RerankIn, request: Request) -> RerankOut:
        started = time.perf_counter()
        out = await run(rerank_sync, loaded(request), body.query, body.passages)
        chars = len(body.query) + sum(map(len, body.passages))
        _log("rerank", len(body.passages), chars, started, sum(out.truncated))
        return out

    @api.post("/count_tokens")
    async def count_tokens(body: CountIn, request: Request) -> CountOut:
        started = time.perf_counter()
        models = loaded(request)
        counts = await run(lambda: [count(models.tokenizer, t) for t in body.texts])
        _log("count_tokens", len(body.texts), sum(map(len, body.texts)), started, 0)
        return CountOut(counts=counts, model=models.embed.repo)

    @api.post("/classify")
    async def classify(body: ClassifyIn) -> JSONResponse:
        return model_missing()

    @api.post("/classify_intent")
    async def classify_intent(body: IntentIn) -> JSONResponse:
        return intent_missing()

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
