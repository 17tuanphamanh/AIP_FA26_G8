# Image `mock` — giả lập hệ thống ngoài (P5), cổng 8100. Build context: gốc repo.
# Cùng lớp phụ thuộc với backend (uv.lock) để Docker dùng lại cache.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv/mock_services \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY pyproject.toml uv.lock ./
# Cache mount: backend và mock dùng chung gói đã tải; mạng chậm không phải tải lại.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY mock_services/app ./mock_services/app

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
