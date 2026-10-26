"""Phase 6 chặng 6C DỪNG 2 — B17 nhận AUTO do LLM (D-42) và `full_auto` (Q-6-8 = C). Viết TỪ ĐẶC TẢ trước code (phase6 bảng 6.4
c9–c12; 6.1 P4, P6; 6.6 (5), (8); 6.8 Q-6-8 = C điều kiện 2; PLAN-6C TQ-7, TQ-10).

B17 (P6 / TQ-10): ca KHÔNG qua duyệt + luật HIỆN HÀNH (policy + Clock lúc B17) không khớp chỉ được đi tiếp khi
`state.risk.decided_by == "llm"` ∧ `state.risk.route == "AUTO"` ∧ `state.action_plan_hash == hash_action(action)`; đi tiếp = kiểm người
(D-15) rồi thực thi, điểm log 7 `action_plan_hash_matched = True`. Ngược lại giữ E5 `recheck_failed` (`detail.recheck="not_approved"`).
Kiểm lại luật vẫn chạy TRƯỚC: luật hiện hành `deny` / `approval_required` → E5 dù LLM đã cho AUTO.

`full_auto` (P4 / TQ-7, chỉ EVAL): B12 không gọi `evaluate`, không gọi estimator, không dựng `RiskDecision` (`risk = None`); điểm 4
`detail` ĐÚNG 3 khoá `{strategy: "full_auto", route: "AUTO", policy_sha256}`, cột `decided_by` NULL; `goto S_EXECUTING` → B17; KHÔNG đặt
`action_plan_hash`. B17 giữ kiểm lại luật → `deny`/`approval_required`/không khớp → E5; `allow` → thực thi.

Khuôn: `test_b17_execute.Env` (node B17 thật, `PlanExecutor` thật trên registry ghi thật + hệ thống ghi giả đếm ở NƠI NHẬN —
`FakeVpnWrites` cho VPN, `_t24.FakeWrites` cho AD/phần mềm/file — CHUNG một registry; AD giả sau registry đọc thật); node B12 như
`test_b12_llm._node` (gateway thật + ScriptedLLM `vpn_scripts`). Luật = `config/policy.json` thật; "không luật nào khớp" dựng bằng
dữ liệu state (facts, `ctx_flags`, người hưởng lợi) + Clock; luật giả chỉ ở một ca deny (khuôn `test_deny_is_e5_even_if_approved`).
"""

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.risk_factors import FactorCode
from app.domain.states import S_ASSESSING, S_CONFIRMING, S_ESCALATED, S_EXECUTING
from app.domain.ticket_state import ExecutionResult, RiskDecision
from app.executor.plan_executor import PlanExecutor
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b12_assess, b17_execute
from app.risk.estimator import RiskEstimate
from app.risk.models import RuleVerdict
from app.risk.strategy import Strategy
from app.settings import get_action_metadata
from app.tools.breaker import BreakerBoard
from app.tools.registry import ToolRegistry
from tests.fakes.executor import FakeVpnWrites, MemoryTxLog
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.risk_estimator import FakeRiskEstimator
from tests.fixtures.llm.vpn import vpn_scripts
from tests.unit._t24 import TZ, FakeWrites
from tests.unit._t24 import action as t24_action

pytestmark = pytest.mark.asyncio

POLICY = Path(__file__).resolve().parents[3] / "config" / "policy.json"
POLICY_SHA = hashlib.sha256(POLICY.read_bytes()).hexdigest()
IN_HOURS = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN
AFTER_HOURS = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)  # thứ Ba 20:00 giờ VN
ME, COLLEAGUE = "nv001", "nv002"
APPROVER = "l1_01"  # người duyệt thật trong roster (khuôn `test_b17_execute.APPROVER`)
THRESHOLDS = (0.25, 0.75)  # policy.json constants THRESHOLD_LOW/HIGH


# ---- dữ liệu ---------------------------------------------------------------------------------------------------------------


def _requester(user: str = ME) -> RequesterContext:
    return RequesterContext(
        user_id=user, role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=IN_HOURS,
    )  # fmt: skip


def _vpn(*, owner: bool, registered: bool = True) -> Action:
    """Khuôn `test_b17_execute._action`: gia hạn VPN máy LAP-0342."""
    meta = get_action_metadata().root["vpn"]["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target="device:LAP-0342", requested_for=ME, scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params={"device_id": "LAP-0342"},
        facts={"device_registered": registered, "device_owner_is_requester": owner, "cert_status": "expired",
               "cert_days_to_expiry": -3, "last_connection_ok": False},
    )  # fmt: skip


def _account_colleague() -> Action:
    """TC37: đặt lại mật khẩu AD tài khoản THƯỜNG của đồng nghiệp — R01 đòi `target_is_other` false; R03–R05 không thoả."""
    return t24_action("reset_password", rf=COLLEAGUE, params={"account_type": "ad"},
                      facts={"target_user_status": "active", "target_account_privilege": "standard_user",
                             "target_is_service_account": False})  # fmt: skip


def _software_other_device() -> Action:
    """Cài phần mềm miễn phí trong danh mục CHO NGƯỜI KHÁC — R11 đòi `target_is_other` false; R13–R15 không thoả."""
    return t24_action("install_software", rf=COLLEAGUE,
                      facts={"in_catalog": True, "license_paid": False, "requires_local_admin": False,
                             "device_owner_is_requester": False})  # fmt: skip


def _software_own() -> Action:
    """R11 allow: cài phần mềm miễn phí trong danh mục lên máy của chính mình (`device_owner_is_requester` — khuôn N1 `_software`)."""
    return t24_action("install_software", facts={"in_catalog": True, "license_paid": False, "requires_local_admin": False,
                                                 "device_owner_is_requester": True})  # fmt: skip


def _access_grant(**facts: Any) -> Action:
    """§8.2: cấp quyền MỚI thư mục độ nhạy thấp cùng phòng ban (read) — không luật `grant_permission` nào khớp (R07 high, R08 full,
    R09 khác phòng, R12 disabled+security)."""
    base: dict[str, Any] = {"resource_sensitivity": "low", "same_department": True, "target_user_status": "active"}
    return t24_action("grant_permission", facts={**base, **facts})


def _access_deny() -> Action:
    """R12 (deny): cấp quyền cho tài khoản bị vô hiệu hoá vì lý do bảo mật (cùng phòng — R09 không khớp)."""
    return t24_action("grant_permission", rf="nv004", facts={"resource_sensitivity": "low", "same_department": True,
                                                             "target_user_status": "disabled",
                                                             "target_disable_reason": "security"})  # fmt: skip


def _access_full() -> Action:
    """R08 (approval_required): cấp toàn quyền thư mục."""
    return t24_action("grant_permission", params={"resource_path": "finance/public-reports", "permission_level": "full",
                                                  "duration_days": 30},
                      facts={"resource_sensitivity": "low", "same_department": True, "target_user_status": "active"})  # fmt: skip


INTENT = {"renew_vpn_cert": "vpn", "reset_password": "account", "install_software": "software",
          "grant_permission": "access"}  # fmt: skip
WRITE_TOOL = {"renew_vpn_cert": "renew_vpn_cert", "reset_password": "reset_password",
              "install_software": "install_software", "grant_permission": "grant_permission"}  # fmt: skip


def _base_state(action: Action, *, other: bool, status: str) -> dict[str, Any]:
    return {
        "ticket_id": "t1", "turn_id": "T1", "status": status, "intent": INTENT[action.type], "reasoning_loops": 1,
        "requester_context": _requester(), "intended_action": action, "ctx_flags": {"target_is_other": other},
        "redacted_request": "yêu cầu hỗ trợ", "slots": {"action": action.type}, "facts": {}, "kb_version": "a" * 64,
    }  # fmt: skip


def llm_risk(route: str = "AUTO", p: float = 0.05) -> RiskDecision:
    """`RiskDecision` như B12 dựng ở đường LLM (bảng 5.3 bước 4): `decided_by="llm"`, `policy_decision=None`."""
    level = {"AUTO": "low", "HITL": "medium", "ESCALATE_L2": "high"}[route]
    return RiskDecision(
        decided_by="llm", policy_decision=None, matched_rule_id=None, raw_prob=p, calibrated_prob=p,
        p_method="self_report", risk_level=level, route=route, reason="Không luật nào khớp. (test)",  # type: ignore[arg-type]
        thresholds=THRESHOLDS,
    )  # fmt: skip


def rule_risk(route: str) -> RiskDecision:
    decision, rule, level = {"AUTO": ("allow", "R20", "low"), "HITL": ("approval_required", "R18", "medium")}[route]
    return RiskDecision(
        decided_by="rule", policy_decision=decision, matched_rule_id=rule, raw_prob=None,  # type: ignore[arg-type]
        calibrated_prob=None, p_method=None, risk_level=level, route=route, reason="luật (test)",  # type: ignore[arg-type]
        thresholds=None,
    )  # fmt: skip


def llm_auto_state(action: Action, *, other: bool, **over: Any) -> dict[str, Any]:
    """State như ngay sau B12 đường LLM → AUTO (c5): `risk` llm/AUTO, `action_plan_hash = hash_action(action)`, KHÔNG
    `approval_id`/`approval_result`."""
    state = _base_state(action, other=other, status=S_EXECUTING)
    state.update(risk=llm_risk("AUTO"), action_plan_hash=hash_action(action))
    state.update(over)
    return state


# ---- môi trường --------------------------------------------------------------------------------------------------------------


class Env:
    """Node B12/B17 thật trên CHUNG một harness: AD giả (người gửi + người hưởng lợi), txlog chung cho B17 bước 0 và executor, hệ
    thống ghi giả VPN + AD/phần mềm/file sau MỘT registry ghi thật, gateway thật + ScriptedLLM `vpn_scripts`."""

    def __init__(self, at: datetime, *users: dict[str, Any]) -> None:
        self.clock = FakeClock(at)
        self.ad = FakeAd(*(users or (ad_user(ME), ad_user(COLLEAGUE), ad_user("nv004"))))
        self.txlog = MemoryTxLog()
        self.vpn_writes = FakeVpnWrites(self.clock)
        self.writes = FakeWrites(self.clock, self.txlog)
        self.gw: Gateway = make_gateway(vpn_scripts(), clock=self.clock)
        # người duyệt thật trong roster (`l1_01`, harness gieo dòng `users` + gộp vào AD) — chỉ dùng ở ca đối chứng qua duyệt
        self.h = GraphHarness(clock=self.clock, ad=self.ad, txlog=self.txlog, llm=self.gw.client, approver_id=APPROVER)
        breakers = BreakerBoard(self.clock, failure_threshold=5, window_seconds=60, open_seconds=30)
        registry = ToolRegistry({**self.vpn_writes.handlers(), **self.writes.handlers()}, breakers=breakers, clock=self.clock)
        self.executor: Any = PlanExecutor(registry, self.txlog, self.clock, tz=TZ)

    @contextmanager
    def run(self) -> Iterator[None]:
        with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=self.h.audit, effects=self.h.effects,
                                 spans=self.h.spans, clock=self.clock, txlog=self.txlog)):  # fmt: skip
            yield

    async def b17(self, state: dict[str, Any]) -> dict[str, Any]:
        deps = self.h.deps()
        deps.executor = self.executor
        with self.run():
            out: dict[str, Any] = await wrap_node("b17_execute", b17_execute.make(deps))(state)
        return out

    async def b12(
        self, state: dict[str, Any], *, strategy: Strategy, eval_mode: bool, estimator: FakeRiskEstimator
    ) -> dict[str, Any]:
        deps = self.h.deps()
        deps.estimator = estimator
        self.h.tickets.strategies[state["ticket_id"]] = strategy  # D-60: chiến lược chụp trên ticket (không qua deps)
        deps.eval_mode = eval_mode
        with self.run():
            out: dict[str, Any] = await wrap_node("b12_assess", b12_assess.make(deps))(state)
        return out

    def writes_total(self) -> int:
        return sum(self.vpn_writes.calls.values()) + self.writes.total()

    def write_calls(self) -> dict[str, int]:
        return {**dict(self.vpn_writes.calls), **dict(self.writes.calls)}

    def rows(self, event: str) -> list[dict[str, Any]]:
        return self.h.audit.of("t1", event)

    def b14_calls(self) -> list[str]:
        return [c.prompt_id for c in self.gw.llm.calls if c.prompt_id.startswith("b14")]


def _exit(out: dict[str, Any]) -> tuple[Any, Any, Any]:
    return out.get("status"), out.get("exit_code"), out.get("escalation_reason_detail")


def _assert_e5_recheck_zero_writes(env: Env, out: dict[str, Any]) -> None:
    got = _exit(out)
    assert got == (S_ESCALATED, "E5", "recheck_failed"), (got, env.h.audit.events("t1"))
    assert env.writes_total() == 0 and env.txlog.rows == [], env.write_calls()
    assert env.rows("executed_ok") == []


def _assert_executed(env: Env, out: dict[str, Any], action: Action) -> None:
    """Thực thi xong → B18: `S_CONFIRMING`, ≥ 1 lời gọi ghi (đếm ở nơi nhận), lời gọi ghi chính đúng 1 lần."""
    assert (out.get("status"), out.get("next")) == (S_CONFIRMING, "confirm_wait"), (
        _exit(out), env.h.audit.events("t1"), [r["detail"] for r in env.rows("recheck_failed")])
    assert env.writes_total() >= 1
    assert env.write_calls().get(WRITE_TOOL[action.type]) == 1, env.write_calls()
    assert env.rows("recheck_failed") == []


def _est(raw: float) -> RiskEstimate:
    return RiskEstimate(raw_prob=raw, p_method="self_report", factors=(FactorCode.ROUTINE_LOW_RISK,),
                        prompt_id="b14_risk_estimate", prompt_version="1", model="strong-gia",
                        evidence_trimmed=0)  # fmt: skip


# ---- c9: LLM-AUTO, hash khớp, luật hiện hành vẫn không khớp → thực thi ---------------------------------------------------------

C9_CASES = [
    pytest.param(lambda: _vpn(owner=False), False, id="vpn-may-nguoi-khac-G02"),
    pytest.param(_account_colleague, True, id="account-TC37-dat-lai-mk-dong-nghiep"),
    pytest.param(_software_other_device, True, id="software-cai-cho-nguoi-khac"),
    pytest.param(_access_grant, False, id="access-cap-quyen-moi-thap-cung-phong"),
]


@pytest.mark.parametrize(("make", "other"), C9_CASES)
async def test_c9_llm_auto_hash_matches_no_rule_executes(make: Callable[[], Action], other: bool) -> None:
    """c9 (P6, D-42, Q-6-7): state như sau B12 LLM-AUTO (`risk` llm/AUTO, `policy_decision=None`, `action_plan_hash` khớp, không
    phiếu), luật hiện hành (trong giờ) vẫn không khớp → kiểm người (D-15, ≥ 1 lời tra AD) → thực thi (≥ 1 lời gọi ghi) → B18
    `S_CONFIRMING`; `ExecutionResult.action_plan_hash_matched` và điểm log 7 `action_plan_hash_matched` = True; 0 phiếu."""
    env = Env(IN_HOURS)
    action = make()
    out = await env.b17(llm_auto_state(action, other=other))
    _assert_executed(env, out, action)
    assert ExecutionResult.model_validate(out["execution"]).action_plan_hash_matched is True
    [row] = env.rows("executed_ok")
    assert row["detail"]["action_plan_hash_matched"] is True
    assert row["detail"]["write_calls"] >= 1
    assert env.ad.calls >= 1  # D-15: kiểm người vẫn chạy
    assert env.h.approvals.count("t1") == 0


async def _approved(env: Env, action: Action) -> str:
    a_id = await env.h.approvals.create(
        "t1", APPROVER, env.clock.now() + timedelta(minutes=30), hash_action(action), backup_approver_id=None,
        conflict_detected=False, conflict_type=None,
    )  # fmt: skip
    await env.h.approvals.close(a_id, "approved", env.clock.now(), decided_by=APPROVER, note="ok")
    return a_id


@pytest.mark.parametrize(("make", "via_approval"), [
    pytest.param(lambda: t24_action("reset_password", rf=ME, params={"account_type": "ad"},
                                    facts={"target_user_status": "active", "target_account_privilege": "standard_user",
                                           "target_is_service_account": False}), False, id="account-R01-allow"),
    pytest.param(_software_own, False, id="software-R11-allow"),
    pytest.param(_access_grant, True, id="access-grant-khong-luat-da-duyet"),
    pytest.param(_account_colleague, True, id="account-TC37-da-duyet"),
    pytest.param(_software_other_device, True, id="software-nguoi-khac-da-duyet"),
])  # fmt: skip
async def test_c9_env_control_rule_or_approval_paths_execute(make: Callable[[], Action], via_approval: bool) -> None:
    """Đối chứng môi trường c9 (không phải hành vi mới): cùng `Env`, cùng loại hành động đi đường CŨ (luật allow, hoặc qua duyệt
    đủ 3 điều kiện) → thực thi được — chứng minh c9 đỏ chỉ vì cổng D-42, không vì executor/hệ thống ghi giả của intent đó."""
    env = Env(IN_HOURS)
    action = make()
    other = action.requested_for != ME
    state = _base_state(action, other=other, status=S_EXECUTING)
    if via_approval:
        a_id = await _approved(env, action)
        state.update(approval_id=a_id, approval_result="approved", action_plan_hash=hash_action(action))
    out = await env.b17(state)
    _assert_executed(env, out, action)


async def test_c9_llm_auto_risk_as_checkpoint_dict_executes() -> None:
    """c9 (TQ-10 "risk đọc `RiskDecision.model_validate` từ state"): `risk` dạng dict (như đọc lại từ checkpoint/JSON) → cùng kết quả."""
    env = Env(IN_HOURS)
    action = _vpn(owner=False)
    out = await env.b17(llm_auto_state(action, other=False, risk=llm_risk("AUTO").model_dump(mode="json")))
    _assert_executed(env, out, action)
    assert ExecutionResult.model_validate(out["execution"]).action_plan_hash_matched is True


async def test_c9_llm_auto_beneficiary_terminated_still_e5_person() -> None:
    """c9 + P6 "Kiểm người (D-15) giữ nguyên": LLM-AUTO hợp lệ nhưng người hưởng lợi (đồng nghiệp) đã nghỉ việc → E5
    `person_no_longer_valid` (KHÔNG `recheck_failed` — đã qua cổng D-42), 0 lời gọi ghi."""
    env = Env(IN_HOURS, ad_user(ME), ad_user(COLLEAGUE, employment_status="terminated"))
    out = await env.b17(llm_auto_state(_account_colleague(), other=True))
    got = _exit(out)
    assert got == (S_ESCALATED, "E5", "person_no_longer_valid"), (got, env.h.audit.events("t1"))
    assert env.writes_total() == 0 and env.txlog.rows == []


# ---- c10: thiếu một điều kiện D-42 → E5 recheck_failed, 0 ghi ----------------------------------------------------------------

C10_CASES = [
    pytest.param({"action_plan_hash": "0" * 64}, id="a-hash-lech"),
    pytest.param({"action_plan_hash": None}, id="b-hash-None"),
    pytest.param({"risk": rule_risk("AUTO")}, id="c-rule-AUTO-khong-duyet"),
    pytest.param({"risk": rule_risk("HITL")}, id="c-rule-HITL-khong-duyet"),
    pytest.param({"risk": llm_risk("HITL", 0.5)}, id="d-llm-HITL"),
    pytest.param({"risk": llm_risk("ESCALATE_L2", 0.9)}, id="e-llm-L2"),
    pytest.param({"risk": None}, id="f-risk-None"),
]


@pytest.mark.parametrize("over", C10_CASES)
async def test_c10_llm_auto_condition_missing_is_e5_recheck_failed(over: dict[str, Any]) -> None:
    """c10 (P6, M-6C-1): ca không qua duyệt, luật hiện hành không khớp, thiếu MỘT vế D-42 — (a) hash lệch; (b) hash None;
    (c) `decided_by="rule"` không qua duyệt; (d) llm `route="HITL"`; (e) llm `ESCALATE_L2`; (f) `risk` None → E5 `recheck_failed`,
    `detail.recheck="not_approved"`, 0 lời gọi ghi, 0 `begun`."""
    env = Env(IN_HOURS)
    out = await env.b17(llm_auto_state(_vpn(owner=False), other=False, **over))
    _assert_e5_recheck_zero_writes(env, out)
    assert env.rows("recheck_failed")[0]["detail"]["recheck"] == "not_approved"


async def test_c10_hash_key_absent_is_e5() -> None:
    """c10 (b'): khoá `action_plan_hash` VẮNG hẳn trong state (không chỉ None) → E5 `recheck_failed`, 0 ghi."""
    env = Env(IN_HOURS)
    state = llm_auto_state(_vpn(owner=False), other=False)
    del state["action_plan_hash"]
    out = await env.b17(state)
    _assert_e5_recheck_zero_writes(env, out)


async def test_c10_risk_key_absent_is_e5() -> None:
    """c10 (f'): khoá `risk` VẮNG hẳn (state cũ) → không ngoại lệ D-42 → E5 `recheck_failed`, 0 ghi (không E9)."""
    env = Env(IN_HOURS)
    state = llm_auto_state(_vpn(owner=False), other=False)
    del state["risk"]
    out = await env.b17(state)
    _assert_e5_recheck_zero_writes(env, out)


async def test_c10_hash_of_other_action_is_e5() -> None:
    """c10 (a, kịch bản G4-13 cho LLM-AUTO): hash trong state là hash của hành động KHÁC (máy LAP-0999) — hành động đang chạy
    LAP-0342 → E5, 0 ghi."""
    env = Env(IN_HOURS)
    action = _vpn(owner=False)
    other = action.model_copy(update={"target": "device:LAP-0999", "params": {"device_id": "LAP-0999"}})
    out = await env.b17(llm_auto_state(action, other=False, action_plan_hash=hash_action(other)))
    _assert_e5_recheck_zero_writes(env, out)


# ---- c11: LLM-AUTO hash khớp nhưng luật HIỆN HÀNH nay khớp deny / approval_required → E5 ------------------------------------------


async def test_c11_llm_auto_now_after_hours_r18_approval_required_is_e5() -> None:
    """c11 (P6 "kiểm lại luật vẫn chạy trước", Clock HIỆN HÀNH): máy của chính mình nhưng cờ B6 `target_is_other` → trong giờ không
    luật nào (R20 đòi other false) — B12 lúc 10:00 cho LLM-AUTO; B17 chạy lúc 20:00 → R18 `approval_required` khớp → E5
    `recheck_failed`, 0 ghi."""
    env = Env(AFTER_HOURS)
    out = await env.b17(llm_auto_state(_vpn(owner=True), other=True))
    _assert_e5_recheck_zero_writes(env, out)
    assert env.rows("recheck_failed")[0]["detail"]["matched_rule_id"] == "R18"


async def test_c11_control_same_state_in_hours_executes() -> None:
    """Đối chứng c11: cùng state, B17 chạy TRONG giờ → không luật nào → ngoại lệ D-42 → thực thi (chứng minh ca trên E5 là do
    luật hiện hành, không do state)."""
    env = Env(IN_HOURS)
    action = _vpn(owner=True)
    out = await env.b17(llm_auto_state(action, other=True))
    _assert_executed(env, out, action)


async def test_c11_llm_auto_access_full_r08_approval_required_is_e5() -> None:
    """c11: LLM-AUTO hash khớp nhưng hành động khớp R08 (toàn quyền) `approval_required` theo policy hiện hành → E5, 0 ghi."""
    env = Env(IN_HOURS)
    out = await env.b17(llm_auto_state(_access_full(), other=False))
    _assert_e5_recheck_zero_writes(env, out)


async def test_c11_llm_auto_access_r12_deny_is_e5() -> None:
    """c11 + 6.6 (5): LLM-AUTO hash khớp nhưng hành động khớp R12 `deny` theo policy hiện hành → E5 `recheck_failed`, 0 ghi."""
    env = Env(IN_HOURS)
    out = await env.b17(llm_auto_state(_access_deny(), other=True))
    _assert_e5_recheck_zero_writes(env, out)


async def test_c11_llm_auto_policy_now_deny_monkeypatched_is_e5(monkeypatch: pytest.MonkeyPatch) -> None:
    """c11 (khuôn `test_b17_execute.test_deny_is_e5_even_if_approved`): policy hiện hành nay `deny` cho ca G-02 → E5, 0 ghi."""
    verdict = RuleVerdict(matched=True, decision="deny", rule_id="R12", all_matched=["R12"], description="Cấm")
    monkeypatch.setattr(b17_execute, "evaluate", lambda action, ctx: verdict)
    env = Env(IN_HOURS)
    out = await env.b17(llm_auto_state(_vpn(owner=False), other=False))
    _assert_e5_recheck_zero_writes(env, out)


async def test_c11_llm_auto_policy_now_approval_required_monkeypatched_is_e5(monkeypatch: pytest.MonkeyPatch) -> None:
    """c11: policy hiện hành nay `approval_required` cho ca G-02, chưa duyệt → E5 `recheck_failed`, 0 ghi."""
    verdict = RuleVerdict(matched=True, decision="approval_required", rule_id="R18", all_matched=["R18"],
                          description="Ngoài giờ")  # fmt: skip
    monkeypatch.setattr(b17_execute, "evaluate", lambda action, ctx: verdict)
    env = Env(IN_HOURS)
    out = await env.b17(llm_auto_state(_vpn(owner=False), other=False))
    _assert_e5_recheck_zero_writes(env, out)


# ---- c12: full_auto (EVAL) — B12 bỏ M5, B17 vẫn kiểm lại luật ---------------------------------------------------------------------

FULL_AUTO_DETAIL = {"strategy": "full_auto", "route": "AUTO", "policy_sha256": POLICY_SHA}  # P4 / TQ-7 / Q-6-8 = C


def _b12_state(action: Action, *, other: bool) -> dict[str, Any]:
    return _base_state(action, other=other, status=S_ASSESSING)


async def _full_auto_b12(env: Env, state: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """B12 với `strategy="full_auto"`, `eval_mode=True`; kiểm điểm 4 + 0 lời gọi estimator/`b14_*`/`evaluate`; trả update."""
    calls: list[Any] = []
    real = b12_assess.evaluate

    def spy(action: Action, ctx: Any) -> RuleVerdict:
        calls.append(action)
        return real(action, ctx)

    monkeypatch.setattr(b12_assess, "evaluate", spy)
    fake = FakeRiskEstimator(_est(0.05))
    out = await env.b12(state, strategy="full_auto", eval_mode=True, estimator=fake)
    assert (out.get("status"), out.get("next")) == (S_EXECUTING, "b17_execute"), (_exit(out), env.h.audit.events("t1"))
    assert "exit_code" not in out
    assert fake.calls == [] and env.b14_calls() == []  # không gọi estimator
    assert calls == []  # needs_rules(full_auto) False → không gọi evaluate (TQ-7)
    assert out.get("risk") is None  # không dựng RiskDecision
    assert out.get("action_plan_hash") is None  # TQ-7: không đặt hash
    [row] = env.rows("risk_decided")
    assert row["step"] == "B13/B14"
    assert row["detail"] == FULL_AUTO_DETAIL  # ĐÚNG 3 khoá
    assert row.get("decided_by") is None and row.get("policy_decision") is None
    assert row.get("raw_prob") is None and row.get("p_method") is None
    assert [e for e in env.h.audit.events("t1") if e[1] == "llm_layer_disabled"] == []
    [lin] = [r for r in env.h.audit.lineage if r["step"] == "B13/B14"]  # lineage cũ
    assert lin.get("prompt_id") is None and lin.get("p_method") is None
    return out


async def test_c12_full_auto_deny_point4_then_b17_e5_zero_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """c12 (P4, Q-6-8 = C điều kiện 2, 6.6 (8)): `full_auto` (EVAL) + ca luật `deny` (R12) → điểm 4 `decided_by` NULL, `detail` =
    {strategy: full_auto, route: AUTO, policy_sha256}, `risk` None, đi B17; B17 kiểm lại luật → E5 `recheck_failed`, 0 lời gọi
    ghi, 0 `begun`."""
    env = Env(IN_HOURS)
    state = _b12_state(_access_deny(), other=True)
    out = await _full_auto_b12(env, state, monkeypatch)
    monkeypatch.undo()
    out17 = await env.b17({**state, **out})
    _assert_e5_recheck_zero_writes(env, out17)


@pytest.mark.parametrize(("make", "other", "at"), [
    pytest.param(_access_full, False, IN_HOURS, id="R08-toan-quyen"),
    pytest.param(lambda: _vpn(owner=True), False, AFTER_HOURS, id="R18-ngoai-gio"),
])  # fmt: skip
async def test_c12_full_auto_approval_required_b17_e5(
    monkeypatch: pytest.MonkeyPatch, make: Callable[[], Action], other: bool, at: datetime
) -> None:
    """c12 (P4 "B17 giữ kiểm lại luật (ca approval_required/deny → E5 ở B17)"): `full_auto` + ca luật `approval_required` → B12 đi
    B17 (không B15, 0 phiếu); B17 chưa duyệt → E5 `recheck_failed`, 0 ghi."""
    env = Env(at)
    state = _b12_state(make(), other=other)
    out = await _full_auto_b12(env, state, monkeypatch)
    monkeypatch.undo()
    out17 = await env.b17({**state, **out})
    _assert_e5_recheck_zero_writes(env, out17)
    assert env.h.approvals.count("t1") == 0


async def test_c12_full_auto_no_rule_b17_e5_no_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """c12 (TQ-7 "B17 không có ngoại lệ cho NULL"): `full_auto` + ca không luật nào (G-02) → `risk` None, không `action_plan_hash` →
    B17 không áp D-42 → E5 `recheck_failed`, 0 ghi."""
    env = Env(IN_HOURS)
    state = _b12_state(_vpn(owner=False), other=False)
    out = await _full_auto_b12(env, state, monkeypatch)
    monkeypatch.undo()
    out17 = await env.b17({**state, **out})
    _assert_e5_recheck_zero_writes(env, out17)


async def test_c12_full_auto_allow_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """c12 (TQ-7 "`allow` → thực thi"): `full_auto` + ca luật `allow` (R20 trong giờ) → B17 kiểm lại luật allow → thực thi đúng 1 lần."""
    env = Env(IN_HOURS)
    action = _vpn(owner=True)
    state = _b12_state(action, other=False)
    out = await _full_auto_b12(env, state, monkeypatch)
    monkeypatch.undo()
    out17 = await env.b17({**state, **out})
    _assert_executed(env, out17, action)


@pytest.mark.parametrize(("make", "other", "at", "decision"), [
    pytest.param(_access_deny, True, IN_HOURS, "deny", id="deny-R12"),
    pytest.param(_access_full, False, IN_HOURS, "approval_required", id="approval_required-R08"),
    pytest.param(lambda: _vpn(owner=True), False, AFTER_HOURS, "approval_required", id="approval_required-R18"),
    pytest.param(lambda: _vpn(owner=True), False, IN_HOURS, "allow", id="allow-R20"),
    pytest.param(lambda: _vpn(owner=False), False, IN_HOURS, None, id="khong-luat-G02"),
])  # fmt: skip
async def test_c12_control_fixtures_under_hybrid(make: Callable[[], Action], other: bool, at: datetime,
                                                 decision: str | None) -> None:  # fmt: skip
    """Đối chứng c12: cùng state dưới `hybrid` → B12 ra đúng loại luật dùng trong ca `full_auto` (chứng minh fixture là ca deny /
    approval_required / allow / không khớp thật theo `config/policy.json`)."""
    env = Env(at)
    out = await env.b12(_b12_state(make(), other=other), strategy="hybrid", eval_mode=True,
                        estimator=FakeRiskEstimator(_est(0.5)))  # fmt: skip
    risk = RiskDecision.model_validate(out["risk"])
    assert risk.policy_decision == decision, (risk, env.h.audit.events("t1"))
    assert risk.decided_by == ("llm" if decision is None else "rule")
