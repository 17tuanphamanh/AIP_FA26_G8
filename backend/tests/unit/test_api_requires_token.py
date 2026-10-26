"""P5 tuần 8 — quét ĐỘNG mọi route `/api` của app backend (duyệt `app.routes` qua `iter_route_contexts`, MỌI method): gọi KHÔNG token
→ 401, trừ whitelist 3 route (P6 §5.2). Không liệt kê tay: route agent khác thêm sau (vd `/api/admin/strategy`) tự lọt lưới.

Khác `test_auth_route_scan` (soát TĨNH dấu `require()`): ở đây gọi HTTP thật, nên bắt cả route có `require` nhưng một dependency
khác chạy trước trả mã khác 401 khi thiếu token.

`ENABLE_SSE=false` (mặc định) → `GET /api/tickets/{id}/events` trả 404 TRƯỚC mọi kiểm khác (thiết kế, `api/events.py`: route coi như
không tồn tại) → quét chạy với SSE BẬT để route này cũng phải 401; ca SSE tắt kiểm riêng (404) — điểm lệch L4 BE đã duyệt.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute, iter_route_contexts
from tests.unit.auth_helpers import AuthEnv, auth_env

WHITELIST = {("POST", "/api/auth/login"), ("POST", "/api/auth/refresh"), ("GET", "/api/health")}
_PARAM = re.compile(r"\{[^}]+\}")
EVENTS = "/api/tickets/{ticket_id}/events"


def _api_routes(env: AuthEnv) -> list[tuple[str, str]]:
    """(method, path) của MỌI route dưới `/api`. Route `/api` không phải `APIRoute` (mount, websocket…) → fail: không quét được."""
    found: list[tuple[str, str]] = []
    other: list[str] = []
    for ctx in iter_route_contexts(env.app.routes):
        path = str(ctx.path)
        if not path.startswith("/api"):
            continue
        if not isinstance(ctx.original_route, APIRoute):
            other.append(path)
            continue
        found.extend((m, path) for m in sorted(ctx.methods or ()))
    assert other == [], f"route /api không quét được bằng HTTP: {other}"
    return sorted(found)


def _call(env: AuthEnv, method: str, path: str) -> int:
    return env.client.request(method, _PARAM.sub("x1", path)).status_code


def _not_401(env: AuthEnv) -> list[str]:
    return [f"{m} {p} → {code}" for m, p in _api_routes(env) if (m, p) not in WHITELIST and (code := _call(env, m, p)) != 401]


@contextmanager
def _env(**over: Any) -> Iterator[AuthEnv]:
    with auth_env(enable_sse=True, **over) as env:
        yield env


def test_every_api_route_without_token_is_401() -> None:
    with _env() as env:
        routes = _api_routes(env)
        assert len(routes) >= 25, routes  # phép quét không rỗng
        assert WHITELIST <= set(routes), "whitelist có route không còn tồn tại"
        assert ("GET", EVENTS) in routes and ("GET", "/api/escalations/queue") in routes
        assert _not_401(env) == []


def test_whitelist_is_exactly_three_routes_and_really_open() -> None:
    """Miễn có chủ đích: 3 route này KHÔNG trả 401 khi thiếu token (login/refresh tự kiểm thân/cookie, health mở)."""
    assert len(WHITELIST) == 3
    with _env() as env:
        for m, p in WHITELIST:
            assert _call(env, m, p) != 401, (m, p)


def test_scan_catches_a_route_added_later() -> None:
    """Route mới (vd của agent khác) quên gắn quyền → bị bắt mà không phải sửa test."""
    router = APIRouter()

    @router.get("/api/route-moi/{item_id}")
    async def forgotten(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @router.post("/api/route-moi-khac")
    async def forgotten_post() -> dict[str, str]:
        return {}

    with _env(extra_router=router) as env:
        assert _not_401(env) == ["GET /api/route-moi/{item_id} → 200", "POST /api/route-moi-khac → 200"]


def test_sse_disabled_events_route_is_404_before_auth() -> None:
    with auth_env() as env:  # ENABLE_SSE mặc định false
        assert _call(env, "GET", EVENTS) == 404
