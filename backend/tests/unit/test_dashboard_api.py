"""M9 A3 — `/api/dashboard/*` không cần DB (kế hoạch M9 4.5; duyệt plan A3 ở #10).

- `resolve_window` thuần: mặc định 7 ngày, một đầu, ≤ 90 ngày (biên), `from < to`, chặn biên năm (2000 … now + 1 ngày), tràn
  khi đổi múi giờ → 422; kết quả UTC.
- Thứ tự: không token + cửa sổ sai → 401; L2 + cửa sổ sai / 91 ngày → 403 (cả hai route) — kiểm cửa sổ nằm trong THÂN
  handler, sau quyền. Cửa sổ hợp lệ mà thiếu DSN monitor → 503 (đã qua kiểm tham số, không rơi về `engines.main`).
- Quyền business: nhân viên, L2 → 403 + `permission_denied`. AI: L1 → 403.
- Model `metrics` tường minh: tập trường = hằng chỉ số, mọi trường bắt buộc và nhận `None` (Q-M9-A3-3).
- OpenAPI: thân lỗi thật (422 = `InvalidRequestBody`, không phải `HTTPValidationError`), GET có 503, POST ack có 404/409.

Không có `MONITOR_DATABASE_URL` (autouse) → mọi request qua được kiểm tham số đều dừng ở 503: phân biệt "422" với "đã qua".
`auth_env` dùng FakeClock `EPOCH` (2099-09-26 08:00 UTC) làm "now".
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from types import UnionType
from typing import Any, get_args

import pytest
from app.api.dashboard import (
    WINDOW_LO,
    AiMetrics,
    BusinessAllMetrics,
    BusinessOwnMetrics,
    business_scope,
    resolve_window,
)
from app.api.errors import InvalidRequest
from app.main import create_app
from app.monitor.queries.ai import AI_METRICS
from app.monitor.queries.business import BUSINESS_METRICS, OWN_KEYS
from fastapi.routing import APIRoute, iter_route_contexts
from tests.fakes.auth import EPOCH
from tests.unit.auth_helpers import AuthEnv, auth_env, auth_settings
from tests.unit.test_auth_route_scan import route_auth

NOW = EPOCH
DAY = timedelta(days=1)
US = timedelta(microseconds=1)
ROUTES = ("/api/dashboard/business", "/api/dashboard/ai")
UNAVAILABLE = {"detail": "monitor_unavailable"}


def _iso(ts: datetime) -> str:
    return ts.isoformat()


def _fields(exc: pytest.ExceptionInfo[InvalidRequest]) -> list[str]:
    return exc.value.fields


@pytest.fixture(autouse=True)
def _no_monitor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_DATABASE_URL", raising=False)


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env() as e:
        yield e


def _get(env: AuthEnv, route: str, token: str | None, **params: str) -> tuple[int, Any]:
    headers = env.bearer(token) if token else {}
    r = env.client.get(route, params=params, headers=headers)
    return r.status_code, r.json()


# ---- resolve_window (thuần) -------------------------------------------------------------------------------------------


def test_resolve_window_default_7_days() -> None:
    assert resolve_window(None, None, NOW) == (NOW - 7 * DAY, NOW)


def test_resolve_window_only_from() -> None:
    assert resolve_window(NOW - 30 * DAY, None, NOW) == (NOW - 30 * DAY, NOW)


def test_resolve_window_only_to() -> None:
    to = NOW - 40 * DAY
    assert resolve_window(None, to, NOW) == (to - 7 * DAY, to)


def test_resolve_window_90_days_ok() -> None:
    assert resolve_window(NOW - 90 * DAY, NOW, NOW) == (NOW - 90 * DAY, NOW)


def test_resolve_window_90_days_plus_1us() -> None:
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(NOW - 90 * DAY - US, NOW, NOW)
    assert _fields(exc) == ["query.from", "query.to"]


def test_resolve_window_equal() -> None:
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(NOW - DAY, NOW - DAY, NOW)
    assert _fields(exc) == ["query.from", "query.to"]


def test_resolve_window_inverted() -> None:
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(NOW - DAY, NOW - 2 * DAY, NOW)
    assert _fields(exc) == ["query.from", "query.to"]


def test_resolve_window_bounds() -> None:
    """`from` đúng LO qua, LO − 1 µs → `query.from`; `to` đúng now + 1 ngày qua, + 1 µs → `query.to`; chỉ có `to` gần LO →
    `from` mặc định < LO → `query.from` (không tràn)."""
    lo_now = WINDOW_LO + 30 * DAY
    assert resolve_window(WINDOW_LO, WINDOW_LO + DAY, lo_now) == (WINDOW_LO, WINDOW_LO + DAY)
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(WINDOW_LO - US, WINDOW_LO + DAY, lo_now)
    assert _fields(exc) == ["query.from"]
    assert resolve_window(NOW, NOW + DAY, NOW) == (NOW, NOW + DAY)
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(NOW, NOW + DAY + US, NOW)
    assert _fields(exc) == ["query.to"]
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(None, datetime(2000, 1, 3, tzinfo=UTC), NOW)
    assert _fields(exc) == ["query.from"]


def test_resolve_window_offset_overflow() -> None:
    """Đổi về UTC tràn (offset sát năm 9999 / năm 1) → 422 trường đó, không OverflowError."""
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(None, datetime(9999, 12, 31, 23, tzinfo=timezone(timedelta(hours=-5))), NOW)
    assert _fields(exc) == ["query.to"]
    with pytest.raises(InvalidRequest) as exc:
        resolve_window(datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))), None, NOW)
    assert _fields(exc) == ["query.from"]


def test_resolve_window_returns_utc() -> None:
    vn = timezone(timedelta(hours=7))
    frm, to = resolve_window(datetime(2099, 9, 1, 7, tzinfo=vn), datetime(2099, 9, 2, 7, tzinfo=vn), NOW)
    assert (frm, to) == (datetime(2099, 9, 1, tzinfo=UTC), datetime(2099, 9, 2, tzinfo=UTC))
    assert frm.tzinfo is UTC and to.tzinfo is UTC


# ---- thứ tự kiểm qua HTTP (cả hai route) ------------------------------------------------------------------------------

INVERTED = {"from": _iso(NOW - DAY), "to": _iso(NOW - 2 * DAY)}
DAYS_91 = {"from": _iso(NOW - 91 * DAY), "to": _iso(NOW)}


@pytest.mark.parametrize("route", ROUTES)
def test_order_401_inverted(env: AuthEnv, route: str) -> None:
    assert _get(env, route, None, **INVERTED) == (401, {"detail": "unauthorized"})


@pytest.mark.parametrize("route", ROUTES)
def test_order_403_inverted(env: AuthEnv, route: str) -> None:
    assert _get(env, route, env.token("long.nh"), **INVERTED) == (403, {"detail": "forbidden"})


@pytest.mark.parametrize("route", ROUTES)
def test_order_403_91_days(env: AuthEnv, route: str) -> None:
    assert _get(env, route, env.token("long.nh"), **DAYS_91) == (403, {"detail": "forbidden"})


@pytest.mark.parametrize("route", ROUTES)
def test_window_year_0001_422(env: AuthEnv, route: str) -> None:
    status, body = _get(env, route, env.manager_token(), to="0001-01-03T00:00:00Z")
    assert (status, body) == (422, {"error": "invalid_request", "fields": ["query.to"]})


@pytest.mark.parametrize("route", ROUTES)
def test_window_year_9999_422(env: AuthEnv, route: str) -> None:
    token = env.manager_token()
    status, body = _get(env, route, token, **{"from": "9999-01-01T00:00:00Z", "to": "9999-01-02T00:00:00Z"})
    assert (status, body["error"]) == (422, "invalid_request")
    status, body = _get(env, route, token, to="9999-12-31T23:00:00-05:00")
    assert (status, body) == (422, {"error": "invalid_request", "fields": ["query.to"]})


@pytest.mark.parametrize("route", ROUTES)
def test_window_naive_422(env: AuthEnv, route: str) -> None:
    status, body = _get(env, route, env.manager_token(), **{"from": "2099-09-20T00:00:00"})
    assert (status, body) == (422, {"error": "invalid_request", "fields": ["query.from"]})


@pytest.mark.parametrize("route", ROUTES)
def test_valid_window_503_monitor_unavailable(env: AuthEnv, route: str) -> None:
    assert _get(env, route, env.manager_token()) == (503, UNAVAILABLE)


@pytest.mark.parametrize("route", ROUTES)
def test_window_90_days_passes(env: AuthEnv, route: str) -> None:
    window = {"from": _iso(NOW - 90 * DAY), "to": _iso(NOW)}
    assert _get(env, route, env.manager_token(), **window) == (503, UNAVAILABLE)


# ---- quyền ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("username", ["an.nv", "long.nh"])
def test_business_l2_employee_403_event(env: AuthEnv, username: str) -> None:
    before = len(env.sink.of("permission_denied"))
    assert _get(env, ROUTES[0], env.token(username)) == (403, {"detail": "forbidden"})
    events = env.sink.of("permission_denied")[before:]
    assert [(e.route, e.detail.get("perm")) for e in events] == [(ROUTES[0], "dashboard:read:own")]


def test_ai_l1_403(env: AuthEnv) -> None:
    assert _get(env, ROUTES[1], env.token("ha.lt")) == (403, {"detail": "forbidden"})


def test_routes_marker() -> None:
    app = create_app(auth_settings(), health_checks={})
    found = {c.path: c for c in route_auth(app) if c.path in ROUTES}
    assert found[ROUTES[1]].requirements == (("dashboard:read:all", None, False),)
    assert found[ROUTES[0]].requirements == ((None, None, False),)
    [ctx] = [c for c in iter_route_contexts(app.routes) if isinstance(c.original_route, APIRoute) and c.path == ROUTES[0]]
    assert business_scope in {d.call for d in ctx.dependant.dependencies}


# ---- model metrics (Q-M9-A3-3) ----------------------------------------------------------------------------------------


def test_metrics_models_match_constants() -> None:
    assert len(BUSINESS_METRICS) == 10 and len(OWN_KEYS) == 3 and len(AI_METRICS) == 14  # quét rỗng thì đỏ
    assert set(BusinessAllMetrics.model_fields) == set(BUSINESS_METRICS)
    assert set(BusinessOwnMetrics.model_fields) == set(OWN_KEYS)
    assert set(AiMetrics.model_fields) == set(AI_METRICS)


@pytest.mark.parametrize("model", [BusinessAllMetrics, BusinessOwnMetrics, AiMetrics], ids=["all", "own", "ai"])
def test_metrics_models_all_required_nullable(model: Any) -> None:
    for name, field in model.model_fields.items():
        assert field.is_required(), name
        annotation = field.annotation
        assert isinstance(annotation, UnionType) and type(None) in get_args(annotation), name


# ---- OpenAPI: thân lỗi thật (duyệt plan A3, bổ sung 2) ----------------------------------------------------------------


def test_openapi_error_bodies() -> None:
    spec = create_app(auth_settings(), health_checks={}).openapi()

    def ref(path: str, method: str, code: str) -> str:
        return str(spec["paths"][path][method]["responses"][code]["content"]["application/json"]["schema"]["$ref"])

    gets = [*ROUTES, "/api/alerts"]
    for path in gets:
        assert set(spec["paths"][path]["get"]["responses"]) == {"200", "401", "403", "422", "503"}, path
        assert ref(path, "get", "422").endswith("/InvalidRequestBody"), path
        for code in ("401", "403", "503"):
            assert ref(path, "get", code).endswith("/ErrorDetail"), (path, code)
    ack = "/api/alerts/{alert_id}/ack"
    assert set(spec["paths"][ack]["post"]["responses"]) == {"200", "401", "403", "404", "409", "422"}
    assert ref(ack, "post", "422").endswith("/InvalidRequestBody")
    for code in ("401", "403", "404", "409"):
        assert ref(ack, "post", code).endswith("/ErrorDetail")
    body = spec["components"]["schemas"]["InvalidRequestBody"]
    assert set(body["required"]) == {"error", "fields"}
