"""Dựng lỗi httpx cho test tool mà không cần mạng."""

import httpx

REQ = httpx.Request("GET", "http://mock:8100/x")


def status_error(code: int) -> httpx.HTTPStatusError:
    resp = httpx.Response(code, request=REQ, json={"detail": f"http_{code}"})
    return httpx.HTTPStatusError(f"{code}", request=REQ, response=resp)


def timeout_error() -> httpx.TimeoutException:
    return httpx.ReadTimeout("hết giờ", request=REQ)


def connect_error() -> httpx.ConnectError:
    return httpx.ConnectError("không kết nối được", request=REQ)
