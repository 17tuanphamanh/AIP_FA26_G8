"""M9 A3 — `/api/alerts`, `POST /api/alerts/{id}/ack` không cần DB (chốt Q-M9-A3-2 ở #10, Q-M9-A3-1 ở #6, duyệt plan A3).

- 401 không token; 403 cho L1, L2, nhân viên (chỉ manager có `alert:read`) + `permission_denied`; L1 ack id không tồn tại vẫn
  403 (không lộ id có hay không). Marker `("alert:read", None, False)` cho cả hai route.
- 422 thân `{"error": "invalid_request", "fields": [...]}`: `status` lạ / rỗng, `audience` lạ, `limit` ngoài 1–200, id ack
  không phải số / ≤ 0 / quá BIGINT.
- GET hợp lệ mà thiếu DSN monitor → 503 `monitor_unavailable`.
- Thuần: `audience_of` (luật lạ → `("manager",)`), `AlertView` đúng 12 khoá, `detail` không phải object → `{}`.
- `REGISTRY` khi API import đã đủ mọi luật worker chạy (subprocess — tránh `REGISTRY` đã đầy do test khác import trước).
"""

import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from app.api.alerts import AlertView, AudienceParam, _view
from app.main import create_app
from app.monitor.queries.alerts import DEFAULT_AUDIENCE, AlertRow, audience_of
from app.monitor.rules import AUDIENCE_VALUES, REGISTRY, RuleSpec
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
