"""D-03 / P5 mục 8 "Mạng" / P6 test 9: chỉ svc_executor ghi được; svc_agent gọi endpoint ghi → 403."""

from datetime import UTC, datetime

import pytest
from app.ad import _require_portal
from app.main import create_app
from app.security import ServiceTokens, require_read, require_write
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from fastapi.testclient import TestClient

# /console: trang HTML cho người xem (trình duyệt không gắn được header token) — rào là APP_ENV dev/test, kiểm ở test_console.py.
# /portal: màn hình người dùng cuối, không token — cũng chỉ mở ở APP_ENV dev/test (test_every_portal_route_is_env_gated).
UNGUARDED = ("/health", "/_admin", "/console", "/portal")


def _guard(route: RouteContext) -> str | None:
    calls = {d.call for d in route.dependant.dependencies}
    if require_write in calls:
        return "write"
    if require_read in calls:
        return "read"
    return None


# FastAPI ≥ 0.140 gói router con thành _IncludedRouter; iter_route_contexts duỗi phẳng kèm prefix và
# dependency ở cấp include.
ROUTES = [r for r in iter_route_contexts(create_app(tokens=ServiceTokens("", "")).routes)
          if isinstance(r.original_route, APIRoute)]  # fmt: skip
GUARDED = [r for r in ROUTES if not r.path.startswith(UNGUARDED)]
WRITE_ROUTES = [r for r in GUARDED if _guard(r) == "write"]
READ_ROUTES = [r for r in GUARDED if _guard(r) == "read"]


def _url(route: RouteContext) -> str:
    return (route.path.replace("{user_id}", "nv001").replace("{device_id}", "LAP-0342")
            .replace("{name}", "zoom").replace("{path:path}", "finance/Q3"))  # fmt: skip


def _method(route: RouteContext) -> str:
    return next(iter(route.methods))


def test_every_non_admin_route_is_guarded() -> None:
    assert GUARDED, "không thấy route nào"
    assert [r.path for r in GUARDED if _guard(r) is None] == []


def test_every_portal_route_is_env_gated() -> None:
    portal = [r for r in ROUTES if r.path.startswith("/portal")]
    assert {r.path for r in portal} == {"/portal", "/portal/login", "/portal/change-password"}
    assert all(_require_portal in {d.call for d in r.dependant.dependencies} for r in portal)


def test_every_post_except_authenticate_is_a_write() -> None:
    posts = {r.path for r in GUARDED if _method(r) == "POST"} - {"/ad/authenticate"}
    assert posts == {r.path for r in WRITE_ROUTES}
    # 8 tool ghi + 5 tool hoàn tác (P5 mục 4) + /ad/change-password (F2) + /vpn/connect (mock-fidelity F4) — hai cái cuối chưa có tool backend
    assert len(WRITE_ROUTES) == 15


@pytest.mark.parametrize("route", WRITE_ROUTES, ids=lambda r: r.path)
def test_write_rejects_agent_and_worker(
    route: RouteContext, client: TestClient, agent: dict[str, str], worker: dict[str, str]
) -> None:
    for headers in (agent, worker):
        resp = client.request(_method(route), _url(route), headers=headers, json={})
        assert resp.status_code == 403, (route.path, resp.text)


@pytest.mark.parametrize("route", WRITE_ROUTES + READ_ROUTES, ids=lambda r: r.path)
def test_missing_or_unknown_token_is_401(route: RouteContext, client: TestClient) -> None:
    for headers in ({}, {"X-Service-Token": "x" * 43}):
        resp = client.request(_method(route), _url(route), headers=headers, json={})
        assert resp.status_code == 401, (route.path, resp.text)


@pytest.mark.parametrize("route", READ_ROUTES, ids=lambda r: r.path)
def test_read_rejects_worker(route: RouteContext, client: TestClient, worker: dict[str, str]) -> None:
    resp = client.request(_method(route), _url(route), headers=worker, json={})
    assert resp.status_code == 403


def test_read_accepts_agent_and_executor(
    client: TestClient, agent: dict[str, str], executor: dict[str, str]
) -> None:
    for headers in (agent, executor):
        assert client.get("/ad/users/nv001", headers=headers).status_code == 200


def test_executor_can_write(client: TestClient, executor: dict[str, str]) -> None:
    resp = client.post("/ad/users/nv007/unlock", headers=executor, json={"account_type": "email"})
    assert resp.status_code == 200
    assert resp.json()["was_locked"] is True


@pytest.mark.parametrize(
    "tokens",
    [
        ServiceTokens("", ""),  # chưa cấu hình
        ServiceTokens("a" * 20, "b" * 43),  # quá ngắn
        ServiceTokens("c" * 43, "c" * 43),  # agent trùng executor
    ],
    ids=["empty", "short", "duplicate"],
)
def test_unconfigured_tokens_give_503(tokens: ServiceTokens) -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    with TestClient(create_app(tokens=tokens, now=lambda: now)) as c:
        for headers in ({}, {"X-Service-Token": ""}, {"X-Service-Token": tokens.executor}):
            assert c.get("/ad/users/nv001", headers=headers).status_code == 503
        assert c.get("/health").status_code == 200
