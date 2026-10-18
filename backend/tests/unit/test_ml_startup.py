"""Gói 1 (D-52; `dac-ta-bat-2-model.md` 4.7): bật `review` mà ml-service báo `model_missing` → backend log cảnh báo lúc khởi
động (chạy như shadow), không chặn khởi động; đọc `/health` lỗi → cảnh báo "không kiểm được". Không mạng (MockTransport).
Agent chính viết (test-writer không có ca này — PLAN 5.2)."""

import logging
from typing import Any

import httpx
import pytest
from app.ml.startup import warn_if_guard_missing

pytestmark = pytest.mark.asyncio


def _http(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _health(injection: Any) -> Any:
    return lambda _: httpx.Response(200, json={"status": "ok", "models": {"injection": injection, "intent": "missing"}})


@pytest.mark.parametrize(("handler", "status", "warns"), [
    (_health("missing"), "missing", "model_missing"),
    (_health({"model": "injection-clf", "version": "v3-seed123"}), "loaded", None),
    (lambda _: httpx.Response(503, json={"status": "loading"}), "unknown", "không đọc được"),
    (lambda _: httpx.Response(200, json={"status": "ok"}), "unknown", "không đọc được"),
    (_health(None), "unknown", "không đọc được"),  # dạng lạ → không coi là đã nạp (soát DỪNG 2)
])  # fmt: skip
async def test_warn_if_guard_missing(handler: Any, status: str, warns: str | None, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    async with _http(handler) as http:
        assert await warn_if_guard_missing(http, "http://ml:8200") == status
    if warns is None:
        assert caplog.records == []
    else:
        assert warns in caplog.text and "ml:8200" not in caplog.text  # không log URL


async def test_connect_error_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("không kết nối", request=request)

    async with _http(down) as http:
        assert await warn_if_guard_missing(http, "http://ml:8200") == "unknown"
