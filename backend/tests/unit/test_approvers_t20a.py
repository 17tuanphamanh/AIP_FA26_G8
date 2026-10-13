"""T20a — người duyệt 3 intent mới + khởi động với cấu hình thật (phase5 5.1.1 P10, P12; 5.1.6 b1, b2, h2; PLAN-T20a A13, A17).

- b1 (Việc treo 26, G5-7): B15 THẬT, `reset_password` cho `l1_01`, người gửi nv005, roster `account` (= roster VPN) →
  `targets_approver` với l1_01 → Trưởng BP `it_mgr01`, `choice_reason=conflict` (khuôn x11 của `test_b15_prepare_approval.py`).
- b2: `config/approvers.yaml` thật — 4 intent có roster (account/software/access = roster vpn); `check_approvers_config` xanh với
  `enabled_intents` 4 intent (tiêm vào Settings, KHÔNG bật thật).
- h2: `check_policy_config`, `check_intent_config`, `check_plans` với `ENABLED_INTENTS=["vpn"]` xanh; mặc định vẫn `["vpn"]`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from app.domain.action import Action
from app.domain.states import S_ASSESSING, S_PENDING_APPROVAL
from app.executor.plans import check_plans
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.fakes import fake_risk
from app.graph.nodes import b15_prepare_approval
from app.settings import (
    Settings,
    check_approvers_config,
    check_intent_config,
    check_policy_config,
    get_action_metadata,
    get_policy,
    get_slots,
    load_approvers,
)
from tests.fakes.graph import GraphHarness
from tests.unit._t20a import Env, rc

REPO = Path(__file__).resolve().parents[3]
FOUR = ["vpn", "account", "software", "access"]

# T20a DỪNG 2 (phase5 5.1.9, P10): roster 3 intent mới — xfail(strict) tới khi sửa `approvers.yaml` (phase5 4.10).
CHO_DUNG2 = frozenset({"test_b1_reset_password_for_l1_01_goes_to_head_conflict", "test_b2_repo_approvers_four_intents"})


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.name in CHO_DUNG2 or getattr(request.node, "originalname", None) in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError),
                                              reason="T20a DỪNG 2"))  # fmt: skip


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


# ---- b1 -------------------------------------------------------------------------------------------------------------------


@contextmanager
def _bound(h: GraphHarness) -> Iterator[None]:
    with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=h.audit, effects=h.effects, spans=h.spans,
                             clock=h.clock, txlog=h.txlog)):  # fmt: skip
        yield


@pytest.mark.asyncio
async def test_b1_reset_password_for_l1_01_goes_to_head_conflict() -> None:
    """b1 (P10, Việc treo 26): nv005 xin đặt lại mật khẩu cho l1_01 → B15 lấy roster `account` (l1_01/l1_02/it_mgr01) →
    `targets_approver` (requested_for == l1_01) → Trưởng BP it_mgr01, `conflict_type=targets_approver`, `choice_reason=conflict`."""
    env = Env()
    h = GraphHarness(clock=env.clock, directory=env.directory())  # AD giả = mọi người trong seed (roster + chuỗi quản lý)
    m = get_action_metadata().of("account")["reset_password"]
    action = Action(
        type="reset_password", target="user:l1_01", requested_for="l1_01", scope=m.scope, privilege_level=m.privilege_level,
        reversible=m.reversible, reversibility=m.reversibility, data_sensitivity=m.data_sensitivity,
        params={"account_type": "ad"},
        facts={"target_account_privilege": "elevated", "target_is_service_account": False, "target_user_status": "active"},
    )  # fmt: skip
    state: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_ASSESSING, "intent": "account", "reasoning_loops": 1,
        "requester_context": rc("nv005"), "intended_action": action, "ctx_flags": {"target_is_other": False},
        "slots": {"action": "reset_password", "account_type": "ad", "target_user": "l1_01"}, "risk": fake_risk("HITL"),
        "redacted_request": "đặt lại mật khẩu tài khoản AD cho l1_01",
    }  # fmt: skip
    with _bound(h):
        out = await wrap_node("b15_prepare_approval", b15_prepare_approval.make(h.deps()))(state)
    assert (out.get("status"), out.get("next")) == (S_PENDING_APPROVAL, "approval_wait"), h.audit.events("t1")
    a = await h.approvals.get(str(out["approval_id"]))
    assert a is not None
    assert (a.approver_id, a.backup_approver_id, a.conflict_detected, a.conflict_type) == (
        "it_mgr01", None, True, "targets_approver")
    [row] = h.audit.of("t1", "queued")
    assert row["detail"]["choice_reason"] == "conflict"
    assert row["detail"]["rejected_candidates"] == [{"user_id": "l1_01", "reason": "targets_approver"}]


# ---- b2 -------------------------------------------------------------------------------------------------------------------


def test_b2_repo_approvers_four_intents() -> None:
    """b2 (P10): `approvers.yaml` thật — account/software/access có roster = roster vpn (l1_01 / l1_02 / it_mgr01); khởi động với
    `enabled_intents` 4 intent (tiêm) qua `check_approvers_config` không ném."""
    approvers = load_approvers(REPO / "config" / "approvers.yaml")
    vpn = approvers.of("vpn")
    assert vpn is not None and (vpn.primary, vpn.backup, vpn.head) == ("l1_01", "l1_02", "it_mgr01")
    for intent in ("account", "software", "access"):
        roster = approvers.of(intent)
        assert roster is not None, f"approvers.yaml chưa có {intent}"
        assert roster == vpn, intent
    check_approvers_config(_settings(enabled_intents=FOUR), approvers)


# ---- h2 -------------------------------------------------------------------------------------------------------------------


def test_h2_startup_checks_with_vpn_only() -> None:
    """h2 (P12): settings thật `ENABLED_INTENTS=["vpn"]` → `check_policy_config`, `check_intent_config`, `check_plans`,
    `check_approvers_config` xanh; mặc định vẫn `["vpn"]` (không bật intent nào ở T20a)."""
    settings = _settings()
    assert settings.enabled_intents == ["vpn"]
    check_policy_config(get_policy(), get_slots(), get_action_metadata())
    check_intent_config(settings, get_slots(), get_action_metadata())
    check_plans(get_action_metadata().root, settings.enabled_intents)
    check_approvers_config(settings, load_approvers(REPO / "config" / "approvers.yaml"))
