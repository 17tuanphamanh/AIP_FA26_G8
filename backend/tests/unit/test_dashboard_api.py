"""M9 A3 — `/api/dashboard/*` không cần DB (kế hoạch M9 4.5; duyệt plan A3 ở #10).

- `resolve_window` thuần: mặc định 7 ngày, một đầu, ≤ 90 ngày (biên), `from < to`, chặn biên năm (2000 … now + 1 ngày), tràn
  khi đổi múi giờ → 422; kết quả UTC.
- Thứ tự: không token + cửa sổ sai → 401; L2 + cửa sổ sai / 91 ngày → 403 (cả hai route) — kiểm cửa sổ nằm trong THÂN
  handler, sau quyền. Cửa sổ hợp lệ mà thiếu DSN monitor → 503 (đã qua kiểm tham số, không rơi về `engines.main`).
- Quyền business: nhân viên, L2 → 403 + `permission_denied`. AI: L1 → 403.
- Model `metrics` tường minh: tập trường = hằng chỉ số, mọi trường bắt buộc và nhận `None` (Q-M9-A3-3).
- OpenAPI: thân lỗi thật (422 = `InvalidRequestBody`, không phải `HTTPValidationError`), GET có 503, POST ack có 404/409;
  phần OpenAPI của 4 path A3 = fixture `openapi_m9_a3.json` (hợp đồng FE, review PR #30).
- `from=` / `to=` rỗng → 422 (ghi chú FE).

Không có `MONITOR_DATABASE_URL` (autouse) → mọi request qua được kiểm tham số đều dừng ở 503: phân biệt "422" với "đã qua".
`auth_env` dùng FakeClock `EPOCH` (2099-09-26 08:00 UTC) làm "now".
"""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import UnionType
from typing import Any, get_args

import pytest
from app.api.dashboard import (
    MIN_SAMPLE,
    WINDOW_LO,
    AiMetrics,
    BusinessAll,
    BusinessAllCounts,
    BusinessAllMetrics,
    BusinessOwn,
    BusinessOwnMetrics,
    business_scope,
    resolve_window,
)
from app.api.errors import InvalidRequest
from app.main import create_app
from app.monitor.queries.ai import AI_METRICS
from app.monitor.queries.business import (
    BUSINESS_METRICS,
    COUNTED_KEYS,
    OWN_KEYS,
    BusinessMetrics,
    GroupCount,
    RatioCount,
    WeightedCount,
    WeightedRate,
)
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


@pytest.mark.parametrize(
    ("route", "param"), [(r, p) for r in ROUTES for p in ("from", "to")], ids=["business-from", "business-to", "ai-from", "ai-to"]
)
def test_empty_window_param_422(env: AuthEnv, route: str, param: str) -> None:
    """Ghi chú FE: `from=` / `to=` rỗng → 422, không phải cửa sổ mặc định — muốn mặc định thì KHÔNG gửi tham số."""
    status, body = _get(env, route, env.manager_token(), **{param: ""})
    assert (status, body) == (422, {"error": "invalid_request", "fields": [f"query.{param}"]})


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


# ---- OpenAPI: hợp đồng FE (review PR #30, 7) --------------------------------------------------------------------------

OPENAPI_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "openapi_m9_a3.json"
A3_PATHS = (*ROUTES, "/api/alerts", "/api/alerts/{alert_id}/ack")
_SCHEMA_REF = "#/components/schemas/"


def a3_openapi(spec: dict[str, Any]) -> dict[str, Any]:
    """Phần OpenAPI của 4 path A3 + mọi schema chúng tham chiếu (bao đóng `$ref`, giữ thứ tự của app). Bỏ `openapi`/`info`:
    đổi version app không phải đổi API.

    Sinh lại fixture (chỉ khi CỐ Ý đổi API — FE code theo file này), từ thư mục `backend/` (env như `conftest.py` gốc):
        uv run python -c "import json, os, secrets; os.environ.update(APP_ENV_FILE='', APP_ENV='test', \\
        LLM_BACKEND='scripted', ML_SERVICE_TOKEN=secrets.token_urlsafe(32)); from app.main import create_app; \\
        from tests.unit.auth_helpers import auth_settings; from tests.unit.test_dashboard_api import OPENAPI_FIXTURE, \\
        a3_openapi; OPENAPI_FIXTURE.write_text(json.dumps(a3_openapi(create_app(auth_settings(), health_checks={}) \\
        .openapi()), indent=2, ensure_ascii=False) + '\\n', encoding='utf-8')"
    """
    paths = {p: spec["paths"][p] for p in A3_PATHS}
    schemas: dict[str, Any] = spec["components"]["schemas"]
    seen: set[str] = set()
    todo: list[Any] = [paths]
    while todo:
        node = todo.pop()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith(_SCHEMA_REF) and (name := ref.removeprefix(_SCHEMA_REF)) not in seen:
                seen.add(name)
                todo.append(schemas[name])
            todo.extend(node.values())
        elif isinstance(node, list):
            todo.extend(node)
    return {"paths": paths, "components": {"schemas": {k: v for k, v in schemas.items() if k in seen}}}


def test_openapi_a3_matches_fixture() -> None:
    """Hợp đồng 200 + lỗi của 4 path A3 = `fixtures/openapi_m9_a3.json` (khớp `openapi.json` trong mô tả PR #30). Bỏ
    `response_model` ở route trả `Any`, đổi kiểu trường, đổi mặc định… → đỏ; đổi API thì sửa fixture CÓ CHỦ Ý (lệnh trong
    `a3_openapi`)."""
    expected = json.loads(OPENAPI_FIXTURE.read_text(encoding="utf-8"))
    # fixture rỗng / thiếu thì đỏ. D13: 18 → 22 (RatioCount, GroupCount, WeightedCount, BusinessAllCounts)
    assert (len(expected["paths"]), len(expected["components"]["schemas"])) == (4, 22)
    assert a3_openapi(create_app(auth_settings(), health_checks={}).openapi()) == expected


# ---- D13: số đếm tử/mẫu + min_sample ----------------------------------------------------------------------------------

# Một cửa sổ, số tính tay: 3 lá đã kết thúc, 1 auto → automation 1/3; weighted routine 1/4, approval 0 lá, sensitive 2/2
# → weighted = (0,7·0,25 + 0,1·1) / 0,8 = 0,34375; raw = 3/6 = 0,5.
D13_WEIGHTED = WeightedRate(
    raw=0.5, weighted=0.34375, by_group={"routine": 0.25, "approval": None, "sensitive": 1.0},
    sensitivity={"60/30/10": 0.25 / 0.7, "80/15/5": 0.25 / 0.85},
)  # fmt: skip
D13_VALUES: dict[str, Any] = {
    "automation_rate": 1 / 3, "escalation_rate_raw": 1 / 3, "escalation_rate_weighted": D13_WEIGHTED,
    "deflection_rate": 0.0, "approval_expired_count": 0, "decided_by_distribution": {}, "top_matched_rules": [],
    "override_count": 0, "e1_split": None, "e3_cases": None,
}  # fmt: skip
D13_COUNTS: dict[str, Any] = {  # thiếu `deflection_rate` → response trả null cho khoá đó
    "automation_rate": RatioCount(num=1, den=3),
    "escalation_rate_raw": RatioCount(num=1, den=3),
    "escalation_rate_weighted": WeightedCount(
        den=6,
        by_group={
            "routine": GroupCount(num=1, den=4, weight=0.7),
            "approval": GroupCount(num=0, den=0, weight=0.2),
            "sensitive": GroupCount(num=2, den=2, weight=0.1),
        },
    ),
}


def _d13_fake(monkeypatch: pytest.MonkeyPatch, got: BusinessMetrics) -> list[str | None]:
    """Thay snapshot + truy vấn: route chạy thật tới chỗ dựng response; trả danh sách `approver_id` route đã truyền."""
    seen: list[str | None] = []

    @asynccontextmanager
    async def snapshot(engines: Any) -> AsyncIterator[None]:
        yield None

    async def fake(conn: Any, frm: datetime, to: datetime, *, approver_id: str | None = None) -> BusinessMetrics:
        seen.append(approver_id)
        return got

    monkeypatch.setattr("app.api.dashboard.read_snapshot", snapshot)
    monkeypatch.setattr("app.api.dashboard.business_metrics", fake)
    return seen


def test_counts_model_matches_constants() -> None:
    """Hai chiều: trường `BusinessAllCounts` = `COUNTED_KEYS` (⊆ BUSINESS_METRICS); mọi trường bắt buộc, nhận None; own KHÔNG có
    `counts` (3 khoá own là số đếm) mà có `sample`."""
    assert set(COUNTED_KEYS) <= set(BUSINESS_METRICS)
    assert set(BusinessAllCounts.model_fields) == set(COUNTED_KEYS)
    for name, field in BusinessAllCounts.model_fields.items():
        assert field.is_required(), name
        assert isinstance(field.annotation, UnionType) and type(None) in get_args(field.annotation), name
    assert {"min_sample", "counts"} <= set(BusinessAll.model_fields)
    assert {"min_sample", "sample"} <= set(BusinessOwn.model_fields) and "counts" not in BusinessOwn.model_fields
    assert MIN_SAMPLE == 20


def test_business_all_counts_json(env: AuthEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _d13_fake(monkeypatch, BusinessMetrics(values=D13_VALUES, unavailable=(), counts=D13_COUNTS))
    status, body = _get(env, ROUTES[0], env.manager_token())
    assert status == 200, body
    assert seen == [None]
    assert body["scope"] == "all" and body["min_sample"] == 20
    assert body["metrics"] == BusinessAllMetrics(**D13_VALUES).model_dump(mode="json")  # metrics y như trước D13
    assert body["metrics"]["escalation_rate_weighted"] == {
        "raw": 0.5, "weighted": 0.34375, "by_group": {"routine": 0.25, "approval": None, "sensitive": 1.0},
        "sensitivity": {"60/30/10": 0.25 / 0.7, "80/15/5": 0.25 / 0.85},
    }  # fmt: skip
    assert body["counts"] == {
        "automation_rate": {"num": 1, "den": 3},
        "escalation_rate_raw": {"num": 1, "den": 3},
        "escalation_rate_weighted": {
            "den": 6,
            "by_group": {
                "routine": {"num": 1, "den": 4, "weight": 0.7},
                "approval": {"num": 0, "den": 0, "weight": 0.2},
                "sensitive": {"num": 2, "den": 2, "weight": 0.1},
            },
        },
        "deflection_rate": None,
    }
    assert "sample" not in body


def test_business_counts_missing_all_null(env: AuthEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """`BusinessMetrics` không có số đếm (như spy test snapshot _pg) → `counts` đủ 4 khoá, đều null — không 500."""
    _d13_fake(monkeypatch, BusinessMetrics(values=dict.fromkeys(BUSINESS_METRICS), unavailable=()))
    status, body = _get(env, ROUTES[0], env.manager_token())
    assert status == 200, body
    assert body["counts"] == dict.fromkeys(COUNTED_KEYS)


def test_business_own_sample_json(env: AuthEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """L1: `sample` = số lá own trong cửa sổ (5), `min_sample` 20; không có `counts`; metrics đúng 3 khoá như cũ."""
    values = {"approval_expired_count": 1, "decided_by_distribution": {"llm": 1, "rule": 3}, "top_matched_rules": []}
    seen = _d13_fake(monkeypatch, BusinessMetrics(values=values, unavailable=(), sample=5))
    status, body = _get(env, ROUTES[0], env.token("ha.lt"))
    assert status == 200, body
    assert len(seen) == 1 and seen[0] is not None  # own: approver_id = người trong token
    assert (body["scope"], body["min_sample"], body["sample"]) == ("own", 20, 5)
    assert body["metrics"] == values
    assert "counts" not in body
