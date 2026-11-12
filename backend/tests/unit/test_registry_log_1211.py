"""E11 soát 12/11 (agent 12): dòng log `tool:<tên>` của registry KHÔNG mang chữ của hệ thống ngoài.

Trước sửa: `ToolResult.error` của tool ghi = `"HTTPStatusError: 409 <detail>"` (detail do hệ thống đích viết, có thể nêu người/thiết bị),
lỗi mạng = `"ConnectError: <str(e)>"` (có thể mang URL chứa giá trị slot) → `_span` ghi nguyên chuỗi vào log. Nay log chỉ ghi NHÃN:
tên lớp lỗi, kèm mã HTTP nếu có. `ToolResult.error` giữ nguyên (executor đã quy về tập mã đóng bằng `error_kind`).
"""

import logging

import httpx
import pytest
from app.core.clock import FakeClock
from app.tools.registry import error_label
from tests.unit.test_tool_registry import Handler, _registry

pytestmark = pytest.mark.asyncio

SECRET = "nv001 LAP-0417 chi tiet noi bo"
REQ = httpx.Request("POST", f"http://mock:8100/ad/users/nv001/unlock?note={SECRET.replace(' ', '+')}")


def _status(code: int) -> httpx.HTTPStatusError:
    resp = httpx.Response(code, request=REQ, json={"detail": SECRET})
    return httpx.HTTPStatusError(f"{code} {SECRET}", request=REQ, response=resp)


@pytest.mark.parametrize(
    "exc",
    [_status(409), _status(503), httpx.ConnectError(f"không kết nối {REQ.url}", request=REQ),
     httpx.ReadTimeout(f"hết giờ {REQ.url}", request=REQ)],
    ids=["409", "503", "connect", "timeout"],
)  # fmt: skip
async def test_log_tool_ghi_khong_mang_chu_he_thong_ngoai(exc: Exception, caplog: pytest.LogCaptureFixture) -> None:
    reg = _registry(FakeClock(), unlock_account=Handler(exc))
    with caplog.at_level(logging.INFO, logger="app.tools.registry"):
        r = await reg.call("unlock_account", {"user_id": "nv001", "account_type": "email"}, caller_step="B17")
    assert r.error is not None
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "app.tools.registry"]
    assert lines and all("nv001" not in s and "LAP-0417" not in s and "noi bo" not in s for s in lines), lines
    assert any(type(exc).__name__ in s for s in lines)


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (None, None),
        ("HTTPStatusError: 409 user nv001 đã khoá", "HTTPStatusError: 409"),
        ("HTTPStatusError: 503", "HTTPStatusError: 503"),
        ("ConnectError: http://mock/ad/users/nv001", "ConnectError"),
        ("ReadTimeout: hết giờ", "ReadTimeout"),
        ("circuit_open", "circuit_open"),
        ("turn_budget_exceeded", "turn_budget_exceeded"),
        ("chữ lạ không dáng nào", "other"),
    ],
)  # fmt: skip
async def test_error_label(error: str | None, label: str | None) -> None:
    assert error_label(error) == label
