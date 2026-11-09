"""M9 A3 — `/api/alerts`, `POST /api/alerts/{id}/ack` không cần DB (chốt Q-M9-A3-2 ở #10, Q-M9-A3-1 ở #6, duyệt plan A3).

- 401 không token; 403 cho L1, L2, nhân viên (chỉ manager có `alert:read`) + `permission_denied`; L1 ack id không tồn tại vẫn
  403 (không lộ id có hay không). Marker `("alert:read", None, False)` cho cả hai route.
- 422 thân `{"error": "invalid_request", "fields": [...]}`: `status` lạ / rỗng, `audience` lạ, `limit` ngoài 1–200, id ack
  không phải số / ≤ 0 / quá BIGINT; `status=` / `audience=` / `limit=` rỗng (ghi chú FE). Tham số sai mà không token / sai
  quyền → 401 / 403, không 422 (review PR #30).
- GET hợp lệ mà thiếu DSN monitor → 503 `monitor_unavailable`.
- Thuần: `audience_of` (luật lạ → `("manager",)`), `AlertView` đúng 12 khoá, `detail` không phải object → `{}`.
- `REGISTRY` khi API import đã đủ mọi luật worker chạy (subprocess — tránh `REGISTRY` đã đầy do test khác import trước).
"""

import ast
import json
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, get_args

import pytest
from app.api.alerts import AlertView, AudienceParam, _view
from app.main import create_app
from app.monitor.queries.alerts import (
    _WINDOW_WHERE,
    DEFAULT_AUDIENCE,
    AlertPage,
    AlertRow,
    audience_of,
    list_alerts,
)
from app.monitor.rules import AUDIENCE_VALUES, REGISTRY, RuleSpec
from tests.fakes.auth import EPOCH
from tests.unit.auth_helpers import AuthEnv, auth_env, auth_settings
from tests.unit.test_auth_route_scan import route_auth

LIST = "/api/alerts"
ACK = "/api/alerts/{alert_id}/ack"
BACKEND = Path(__file__).resolve().parents[2]
VIEW_KEYS = {
    "alert_id", "rule_id", "subject", "severity", "value", "window_start", "status", "detail", "audience", "acked_by",
    "acked_at", "created_at",
}  # fmt: skip
T = datetime(2030, 6, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_monitor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_DATABASE_URL", raising=False)


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env() as e:
        yield e


def _invalid(*fields: str) -> dict[str, Any]:
    return {"error": "invalid_request", "fields": list(fields)}


def _row(**over: Any) -> AlertRow:
    values: dict[str, Any] = {
        "alert_id": 7, "rule_id": "finalize_failed", "subject": "tk-1", "severity": "warning", "value": None,
        "window_start": T, "status": "open", "detail": {"node": "b20"}, "acked_by": None, "acked_at": None,
        "created_at": T,
    }  # fmt: skip
    return AlertRow(**(values | over))


# ---- 401 / 403 --------------------------------------------------------------------------------------------------------


def test_no_token_401(env: AuthEnv) -> None:
    for r in (env.client.get(LIST), env.client.post(ACK.format(alert_id=1))):
        assert (r.status_code, r.json()) == (401, {"detail": "unauthorized"})


@pytest.mark.parametrize("username", ["ha.lt", "long.nh", "an.nv"])
def test_alerts_l2_employee_403(env: AuthEnv, username: str) -> None:
    """L1 (`ha.lt`), L2 (`long.nh`), nhân viên (`an.nv`) → 403 ở cả GET và POST, mỗi lần một `permission_denied`."""
    headers = env.bearer(env.token(username))
    before = len(env.sink.of("permission_denied"))
    for r in (env.client.get(LIST, headers=headers), env.client.post(ACK.format(alert_id=1), headers=headers)):
        assert (r.status_code, r.json()) == (403, {"detail": "forbidden"})
    events = env.sink.of("permission_denied")[before:]
    assert [(e.route, e.detail.get("perm")) for e in events] == [(LIST, "alert:read"), (ACK, "alert:read")]


def test_l1_ack_403_even_missing_id(env: AuthEnv) -> None:
    r = env.client.post(ACK.format(alert_id=987654321), headers=env.bearer(env.token("ha.lt")))
    assert (r.status_code, r.json()) == (403, {"detail": "forbidden"})
    assert env.sink.of("permission_denied")[-1].route == ACK


def test_alert_routes_marker() -> None:
    app = create_app(auth_settings(), health_checks={})
    found = {(m, c.path): c.requirements for c in route_auth(app) for m in c.methods}
    assert found[("GET", LIST)] == (("alert:read", None, False),)
    assert found[("POST", ACK)] == (("alert:read", None, False),)


# ---- 422 --------------------------------------------------------------------------------------------------------------


def _manager_get(env: AuthEnv, **params: Any) -> tuple[int, Any]:
    r = env.client.get(LIST, params=params, headers=env.bearer(env.manager_token()))
    return r.status_code, r.json()


def test_status_unknown_422(env: AuthEnv) -> None:
    assert _manager_get(env, status="closed") == (422, _invalid("query.status"))


def test_status_empty_422(env: AuthEnv) -> None:
    """Tab "Tất cả" = KHÔNG gửi `status`; `?status=` rỗng → 422 (khớp hộp thư `/api/approvals`)."""
    assert _manager_get(env, status="") == (422, _invalid("query.status"))


def test_audience_unknown_422(env: AuthEnv) -> None:
    assert _manager_get(env, audience="l2") == (422, _invalid("query.audience"))


def test_limit_0_and_201_422(env: AuthEnv) -> None:
    token = env.manager_token()
    for limit in (0, 201):
        r = env.client.get(LIST, params={"limit": limit}, headers=env.bearer(token))
        assert (r.status_code, r.json()) == (422, _invalid("query.limit")), limit


def test_ack_bad_id_422(env: AuthEnv) -> None:
    token = env.manager_token()
    for alert_id in ("abc", "0", str(2**63)):
        r = env.client.post(f"/api/alerts/{alert_id}/ack", headers=env.bearer(token))
        assert (r.status_code, r.json()) == (422, _invalid("path.alert_id")), alert_id


@pytest.mark.parametrize("param", ["status", "audience", "limit"])
def test_empty_params_422(env: AuthEnv, param: str) -> None:
    """Ghi chú FE: tham số rỗng → 422, không phải "không lọc" / mặc định — muốn vậy thì KHÔNG gửi tham số. (Không có DSN
    monitor: qua được kiểm tham số thì ra 503, nên 422 ở đây đúng là do tham số rỗng.)"""
    assert _manager_get(env, **{param: ""}) == (422, _invalid(f"query.{param}"))


def test_order_401_403_before_422(env: AuthEnv) -> None:
    """Review PR #30 (nhỏ): thứ tự 401 → 403 → 422 trên cả hai route alerts — tham số sai không được trả 422 trước khi kiểm
    token / quyền. L1 ack id không phải số vẫn 403."""
    bad_get: dict[str, str | int] = {"status": "closed", "limit": 0}
    bad_ack = ACK.format(alert_id="abc")
    for headers, expected in (
        ({}, (401, {"detail": "unauthorized"})),
        (env.bearer(env.token("long.nh")), (403, {"detail": "forbidden"})),
    ):
        for r in (env.client.get(LIST, params=bad_get, headers=headers), env.client.post(bad_ack, headers=headers)):
            assert (r.status_code, r.json()) == expected, r.request.url
    r = env.client.post(bad_ack, headers=env.bearer(env.token("ha.lt")))
    assert (r.status_code, r.json()) == (403, {"detail": "forbidden"})


def test_get_valid_503_monitor_unavailable(env: AuthEnv) -> None:
    assert _manager_get(env, status="open", audience="dev", limit=5) == (503, {"detail": "monitor_unavailable"})


# ---- thuần ------------------------------------------------------------------------------------------------------------


def test_audience_of_known_and_unknown() -> None:
    assert audience_of("finalize_failed") == ("dev",)  # REGISTRY thật (luật 15)
    assert audience_of("execution_failed") == ("manager", "ops")
    assert audience_of("zzz-khong-co") == DEFAULT_AUDIENCE == ("manager",)
    fake = {"r_ops": RuleSpec("r_ops", "minute", lambda data, ctx: [], ("ops",))}  # type: ignore[arg-type]
    assert audience_of("r_ops", fake) == ("ops",)
    assert audience_of("finalize_failed", fake) == ("manager",)  # không có trong REGISTRY giả → mặc định
    assert sorted(get_args(AudienceParam.__value__)) == sorted(AUDIENCE_VALUES)  # tham số `?audience=` = giá trị luật


def test_alert_view_exact_12_keys() -> None:
    assert set(AlertView.model_fields) == VIEW_KEYS
    view = _view(_row()).model_dump(mode="json")
    assert set(view) == VIEW_KEYS
    assert view["audience"] == ["dev"]
    assert view["created_at"] == "2030-06-01T00:00:00Z"


@pytest.mark.parametrize("detail", [[1, 2], "x", 3, None], ids=["list", "str", "int", "none"])
def test_view_detail_non_dict_becomes_empty(detail: Any) -> None:
    assert _view(_row(detail=detail)).detail == {}
    assert _view({**_row().__dict__, "detail": detail}).detail == {}  # dòng RETURNING của ack


def test_registry_complete_on_api_import() -> None:
    """`audience` lấy từ `REGISTRY` lúc API chạy: import `app.api.alerts` (như `app.main`) phải đăng ký đủ mọi luật mà worker
    chạy. Luật đăng ký ở module API không import → nhãn rơi về `manager` sai mà không ai biết."""
    code = (
        "import json, app.api.alerts\n"
        "from app.monitor.rules import REGISTRY\n"
        "before = sorted(REGISTRY)\n"
        "import app.worker\n"
        "print(json.dumps([before, sorted(REGISTRY)]))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True, timeout=120,
        env={"PYTHONPATH": str(BACKEND), "PATH": "/usr/bin:/bin"},
    )  # fmt: skip
    before, after = json.loads(out.stdout.strip().splitlines()[-1])
    assert len(before) >= 7  # 7 luật sự kiện của B1 — quét rỗng thì đỏ
    assert before == after
    assert set(before) <= set(REGISTRY)


# ---- D13: khung giờ (lọc `window_start` trong [from, to)) ------------------------------------------------------------
# Không có driver async SQLite trong môi trường → chỉ kiểm CẤU TRÚC SQL bằng conn giả. Hành vi trên dữ liệu thật (nhiều hơn
# `limit` cảnh báo ngoài khoảng vẫn trả đủ cảnh báo trong khoảng; biên from/to trên Postgres) cần test `_pg` — chưa có.

QUERIES_SRC = BACKEND / "app" / "monitor" / "queries" / "alerts.py"
COLS = "alert_id, rule_id, subject, severity, value, window_start, status, detail, acked_by, acked_at, created_at"
W_FROM = datetime(2030, 6, 1, tzinfo=UTC)
W_TO = datetime(2030, 6, 8, tzinfo=UTC)


class _Rows:
    def all(self) -> list[Any]:
        return []


class SqlConn:
    """Ghi (câu SQL, tham số); không trả dòng nào."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, clause: Any, params: dict[str, Any]) -> _Rows:
        self.calls.append((clause.text, params))
        return _Rows()


async def _sql(**kw: Any) -> tuple[str, dict[str, Any]]:
    conn = SqlConn()
    await list_alerts(conn, **{"status": None, "audience": None, "limit": 200, **kw})  # type: ignore[arg-type]
    [call] = conn.calls
    return call


@pytest.mark.asyncio
async def test_list_alerts_sql_unchanged_without_window() -> None:
    """Không truyền khung giờ → câu SQL và tham số y như trước D13 (cùng thứ tự, cùng limit + 1)."""
    assert await _sql() == (
        f"SELECT {COLS} FROM alerts ORDER BY created_at DESC, alert_id DESC LIMIT :limit", {"limit": 201}
    )  # fmt: skip
    sql, params = await _sql(status="open", audience="dev", limit=5, frm=None, to=None)
    assert sql == (
        f"SELECT {COLS} FROM alerts WHERE (status = :status) AND (rule_id = ANY(CAST(:ids AS text[]))) "
        "ORDER BY created_at DESC, alert_id DESC LIMIT :limit"
    )
    assert set(params) == {"limit", "status", "ids"} and params["limit"] == 6


@pytest.mark.asyncio
async def test_list_alerts_window_in_where_before_limit() -> None:
    """Điều kiện khung giờ nằm trong WHERE (nối AND với status/audience), đứng TRƯỚC ORDER BY … LIMIT → lọc trước khi cắt."""
    sql, params = await _sql(frm=W_FROM, to=W_TO, limit=2)
    assert sql == f"SELECT {COLS} FROM alerts WHERE {_WINDOW_WHERE} ORDER BY created_at DESC, alert_id DESC LIMIT :limit"
    assert params == {"limit": 3, "frm": W_FROM, "to": W_TO}
    sql, params = await _sql(status="acked", audience="manager", frm=W_FROM, to=W_TO)
    where = sql.index(" WHERE ")
    assert where < sql.index(_WINDOW_WHERE) < sql.index(" ORDER BY ") < sql.index(" LIMIT ")
    assert sql[where:].count(" AND ") >= 2  # status AND audience AND khung giờ
    assert (params["frm"], params["to"], params["status"]) == (W_FROM, W_TO, "acked")


def test_list_alerts_window_condition() -> None:
    """Biên ghim bằng chữ: from GỒM (`>=`), to LOẠI (`<`). Cột lọc khai MỘT chỗ (`_WINDOW_COLUMN`): ngoài `_COLUMNS`, không
    hằng chuỗi nào khác trong module nhắc `window_start` (đổi sang `created_at` chỉ sửa một dòng)."""
    assert _WINDOW_WHERE == "(window_start >= :frm AND window_start < :to)"
    tree = ast.parse(QUERIES_SRC.read_text(encoding="utf-8"))
    docs = {
        id(o.body[0].value)
        for o in [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef))]
        if o.body and isinstance(o.body[0], ast.Expr) and isinstance(o.body[0].value, ast.Constant)
    }
    found = sorted(
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "window_start" in n.value and id(n) not in docs
    )  # fmt: skip
    assert found == sorted([COLS, "window_start"])


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (W_FROM, None),
        (None, W_TO),
        (datetime(2030, 6, 1), W_TO),  # noqa: DTZ001 — cố ý naive
        (W_TO, W_FROM),
        (W_FROM, W_FROM),
    ],
    ids=["chi-from", "chi-to", "naive", "nguoc", "bang"],
)
@pytest.mark.asyncio
async def test_list_alerts_window_args(frm: datetime | None, to: datetime | None) -> None:
    with pytest.raises(ValueError):
        await _sql(frm=frm, to=to)


def _get_as(env: AuthEnv, token: str, **params: Any) -> tuple[int, Any]:
    """Như `_manager_get` nhưng dùng lại token — `manager_token()` lần hai đăng ký MFA trùng."""
    r = env.client.get(LIST, params=params, headers=env.bearer(token))
    return r.status_code, r.json()


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    @asynccontextmanager
    async def snapshot(engines: Any) -> AsyncIterator[None]:
        yield None

    async def spy(conn: Any, **kw: Any) -> AlertPage:
        seen.append(kw)
        return AlertPage(rows=(), truncated=False)

    monkeypatch.setattr("app.api.alerts.read_snapshot", snapshot)
    monkeypatch.setattr("app.api.alerts.list_alerts", spy)
    return seen


def test_get_without_window_same_call(env: AuthEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """Không gửi `from`/`to` → không lọc (KHÔNG áp mặc định 7 ngày của dashboard); status/audience/limit như cũ."""
    seen = _spy(monkeypatch)
    token = env.manager_token()
    assert _get_as(env, token) == (200, {"items": [], "truncated": False})
    assert _get_as(env, token, status="open", audience="dev", limit=5) == (200, {"items": [], "truncated": False})
    assert seen == [
        {"status": None, "audience": None, "limit": 200, "frm": None, "to": None},
        {"status": "open", "audience": "dev", "limit": 5, "frm": None, "to": None},
    ]


def test_get_window_resolved_like_dashboard(env: AuthEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cùng cách nhận khung giờ của `/api/dashboard` (`resolve_window`): đổi về UTC; chỉ `from` → `to` = now (Clock của app);
    chỉ `to` → `from` = to − 7 ngày."""
    seen = _spy(monkeypatch)
    vn = timezone(timedelta(hours=7))
    frm, to = EPOCH - timedelta(days=3), EPOCH - timedelta(days=1)
    token = env.manager_token()
    assert _get_as(env, token, **{"from": frm.astimezone(vn).isoformat(), "to": to.isoformat()})[0] == 200
    assert _get_as(env, token, **{"from": frm.isoformat()})[0] == 200
    assert _get_as(env, token, to=to.isoformat())[0] == 200
    assert [(s["frm"], s["to"]) for s in seen] == [(frm, to), (frm, EPOCH), (to - timedelta(days=7), to)]
    assert seen[0]["frm"].tzinfo is UTC


@pytest.mark.parametrize(
    "window",
    [
        {"from": (EPOCH - timedelta(days=1)).isoformat(), "to": (EPOCH - timedelta(days=2)).isoformat()},
        {"from": (EPOCH - timedelta(days=91)).isoformat(), "to": EPOCH.isoformat()},
    ],
    ids=["nguoc", "91-ngay"],
)
def test_get_window_invalid_422(env: AuthEnv, monkeypatch: pytest.MonkeyPatch, window: dict[str, str]) -> None:
    seen = _spy(monkeypatch)
    assert _manager_get(env, **window) == (422, _invalid("query.from", "query.to"))
    assert seen == []


@pytest.mark.parametrize("param", ["from", "to"])
def test_get_window_empty_param_422(env: AuthEnv, param: str) -> None:
    assert _manager_get(env, **{param: ""}) == (422, _invalid(f"query.{param}"))


def test_get_window_order_401_403(env: AuthEnv) -> None:
    """Cửa sổ sai mà không token / sai quyền → 401 / 403, không 422 (kiểm cửa sổ trong THÂN handler, sau quyền)."""
    bad = {"from": (EPOCH - timedelta(days=1)).isoformat(), "to": (EPOCH - timedelta(days=2)).isoformat()}
    r = env.client.get(LIST, params=bad)
    assert (r.status_code, r.json()) == (401, {"detail": "unauthorized"})
    r = env.client.get(LIST, params=bad, headers=env.bearer(env.token("long.nh")))
    assert (r.status_code, r.json()) == (403, {"detail": "forbidden"})


def test_get_valid_window_503_monitor_unavailable(env: AuthEnv) -> None:
    window = {"from": (EPOCH - timedelta(days=2)).isoformat(), "to": EPOCH.isoformat()}
    assert _manager_get(env, **window) == (503, {"detail": "monitor_unavailable"})
