# Image `ml-service` — embed, rerank, đếm token (P4, thiết kế Phase 3 mục 4), cổng 8200. Build context: gốc repo.
# Một project uv (3-Q19): nhóm `ml` (sentence-transformers, torch CPU — index pytorch-cpu cho linux, xem
# pyproject). KHÔNG copy models/: model tải trên máy bằng `make models`, mount read-only vào /models.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv/ml_service \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HOME=/tmp/hf \
    MODELS_DIR=/models

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group ml --no-install-project

COPY ml_service/models.lock.json ./ml_service/models.lock.json
COPY ml_service/app ./ml_service/app

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8200
# 1 worker: một bản model; song song hoá bằng threadpool (P4 mục 3).
CMD ["uvicorn", "app.main:build", "--factory", "--host", "0.0.0.0", "--port", "8200", "--workers", "1"]
