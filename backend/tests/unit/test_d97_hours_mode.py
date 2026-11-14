"""D-97 (TA chốt 14/11) — giả lập giờ hành chính cho demo.

- `build_ctx(..., hours_mode=)`: `outside` / `inside` ghi đè ĐÚNG fact `within_business_hours`; `real` tính từ giờ thật; lạ → lỗi.
- B12 (ca VPN TC02): giờ thật 10:00 + `outside` → R18 → chờ duyệt; 20:00 + `inside` → R20 tự xử lý; điểm 4 ghi `hours_mode` khi
  khác `real`, giờ thật thì detail giữ nguyên khoá như cũ.
- API: `GET /api/hours-mode` mọi vai trò đã đăng nhập; `PUT /api/admin/hours-mode` chỉ Trưởng BP (`policy:edit` + đăng nhập lại);
  422 / 409; mỗi lần đổi ghi `policy_saved {kind: hours_mode, from, to}`.
"""

from typing import Any

import pytest
from app.core.clock import FakeClock
from app.db.hours_mode import StaticHoursMode, as_mode
from app.domain.states import S_ASSESSING, S_EXECUTING
from app.graph.nodes import b12_assess
from app.risk.context import build_ctx
from app.risk.estimator import DisabledEstimator
from app.settings import get_policy
from tests.fakes.desk import DeskEnv, desk_env
from tests.fakes.graph import GraphHarness
from tests.fakes.llm import make_gateway
from tests.unit.test_b12_assess import AFTER_HOURS, IN_HOURS, _risk, _run, _state
from tests.unit.test_d67_strategy_api import _manager

pytestmark = pytest.mark.asyncio

ROUTE, ADMIN = "/api/hours-mode", "/api/admin/hours-mode"


# ---- build_ctx ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("at", "mode", "within"),
    [
        (IN_HOURS, "real", True), (AFTER_HOURS, "real", False),
        (IN_HOURS, "outside", False), (AFTER_HOURS, "outside", False),
        (IN_HOURS, "inside", True), (AFTER_HOURS, "inside", True),
    ],
)  # fmt: skip
async def test_build_ctx_hours_mode_overrides_only_within(at: Any, mode: str, within: bool) -> None:
    ctx = build_ctx(_state(), at, get_policy().business_hours, hours_mode=mode)
    assert ctx.within_business_hours is within
    assert ctx.now == at  # không đổi đồng hồ


async def test_build_ctx_default_is_real_and_unknown_mode_raises() -> None:
    hours = get_policy().business_hours
    assert build_ctx(_state(), AFTER_HOURS, hours).within_business_hours is False
    with pytest.raises(ValueError, match="hours_mode"):
        build_ctx(_state(), IN_HOURS, hours, hours_mode="ngoai")


async def test_as_mode_unknown_value_falls_back_to_real() -> None:
    assert as_mode("outside") == "outside"
    assert as_mode("lạ") == "real"
    assert as_mode(None) == "real"


# ---- B12 ----------------------------------------------------------------------------------------------------------------


async def _b12(at: Any, mode: str) -> tuple[dict[str, Any], GraphHarness]:
    gw = make_gateway({})
    h = GraphHarness(clock=FakeClock(at), llm=gw.client)
    deps = h.deps()
    deps.estimator = DisabledEstimator()
    deps.hours_mode = StaticHoursMode(mode)  # type: ignore[arg-type]
    with _run(h):
        out = await b12_assess.make(deps)(_state())
    return out, h


async def test_b12_simulated_outside_in_real_hours_requires_approval_r18() -> None:
    out, h = await _b12(IN_HOURS, "outside")
    assert (out["status"], out["next"]) == (S_ASSESSING, "b15_prepare_approval")
    risk = _risk(out)
    assert (risk.policy_decision, risk.matched_rule_id, risk.route) == ("approval_required", "R18", "HITL")
    [row] = h.audit.of("t1", "risk_decided")
    assert row["detail"]["hours_mode"] == "outside"
    assert set(row["detail"]["all_matched"]) == {"R18", "R20"}


async def test_b12_simulated_inside_after_hours_auto_r20() -> None:
    out, h = await _b12(AFTER_HOURS, "inside")
    assert (out["status"], out["next"]) == (S_EXECUTING, "b17_execute")
    assert (_risk(out).matched_rule_id, _risk(out).route) == ("R20", "AUTO")
    [row] = h.audit.of("t1", "risk_decided")
    assert row["detail"]["hours_mode"] == "inside"


async def test_b12_real_mode_detail_has_no_hours_mode_key() -> None:
    out, h = await _b12(IN_HOURS, "real")
    assert _risk(out).matched_rule_id == "R20"
    [row] = h.audit.of("t1", "risk_decided")
    assert "hours_mode" not in row["detail"]


# ---- API ----------------------------------------------------------------------------------------------------------------


async def test_get_default_real_for_any_logged_in_role() -> None:
    async with desk_env() as env:
        r = await env.client.get(ROUTE, headers=await env.token("an.nv"))
        assert r.status_code == 200
        assert r.json() == {"mode": "real", "modes": ["real", "outside", "inside"], "changed_by": None,
                            "changed_at": None, "eval_mode": False}  # fmt: skip
        assert (await env.client.get(ROUTE)).status_code == 401


async def test_put_only_manager() -> None:
    async with desk_env() as env:
        for user in ("an.nv", "ha.lt"):
            r = await env.client.put(ADMIN, json={"mode": "outside"}, headers=await env.token(user))
            assert r.status_code == 403
        assert env.hours.state.mode == "real" and env.hours.events == []


async def _put(env: DeskEnv, headers: dict[str, str], body: Any) -> Any:
    return await env.client.put(ADMIN, json=body, headers=headers)


async def test_put_manager_switch_logs_policy_saved_and_get_reflects() -> None:
    async with desk_env() as env:
        mgr = await _manager(env)
        r = await _put(env, mgr, {"mode": "outside"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["mode"], body["changed_by"]) == ("outside", "it_mgr01")
        assert env.hours.events == [{"event_type": "policy_saved", "user_id": "it_mgr01",
                                     "detail": {"kind": "hours_mode", "from": "real", "to": "outside"}}]  # fmt: skip
        got = (await env.client.get(ROUTE, headers=await env.token("an.nv"))).json()
        assert (got["mode"], got["changed_by"]) == ("outside", "it_mgr01")
        assert (await _put(env, mgr, {"mode": "outside"})).json() == {"detail": "same_as_current"}
        assert (await _put(env, mgr, {"mode": "real"})).status_code == 200
        assert [e["detail"]["to"] for e in env.hours.events] == ["outside", "real"]


@pytest.mark.parametrize("body", [{"mode": "ngoai"}, {"mode": ""}, {}, {"mode": "outside", "x": 1}, {"mode": 1}])
async def test_put_invalid_body_422(body: Any) -> None:
    async with desk_env() as env:
        r = await _put(env, await _manager(env), body)
        assert r.status_code == 422
        assert env.hours.events == []
