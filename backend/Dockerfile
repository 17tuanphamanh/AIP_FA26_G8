# Image `backend` — dùng CHUNG cho backend (uvicorn) và worker (python -m app.worker),
# chỉ khác lệnh khởi động (01 mục 1.3, cổng T01 mục 5). Build context: gốc repo.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv/backend \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Phụ thuộc theo uv.lock, không nhóm dev và không nhóm ml (model nặng nằm ở ml-service).
COPY pyproject.toml uv.lock ./
# Cache mount: backend và mock dùng chung gói đã tải; mạng chậm không phải tải lại.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY config ./config
COPY backend/app ./backend/app

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:build", "--factory", "--host", "0.0.0.0", "--port", "8000"]
