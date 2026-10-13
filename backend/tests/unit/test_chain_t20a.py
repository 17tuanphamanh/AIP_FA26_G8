"""T20a — chuỗi node B3 → B6 → B11 → B12 (phase5 5.1.6 g1–g9, h3; bảng luật 4.4; PLAN-T20a TQ-12). Viết TỪ ĐẶC TẢ, trước code
— DỪNG 2 (`CHO_DUNG2`).

Node THẬT gọi tuần tự (mỗi bước qua `wrap_node` — lỗi lạ → E9 → assert đỏ), gộp update vào state. B3: ScriptedLLM `b03_classify`
trả đúng một ý như LLM "ngoan" (slot đích đúng chữ người dùng; slot chuẩn hoá `account_type`, `permission_level`, `duration` về giá
trị chuẩn — prompt v3, bảng 5.1.4). Tool: registry THẬT trên `tests/unit/_t20a.Env` (seed.json). `enabled_intents` tiêm 4 intent bằng
`dataclasses.replace`. B12: luật thật `config/policy.json`; không luật nào → `DisabledEstimator` → E5 `llm_layer_disabled`.
"""

import dataclasses
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.domain.states import (
    S_ASSESSING,
    S_CLASSIFYING,
    S_DIAGNOSING,
    S_ESCALATED,
    S_EXECUTING,
    S_RETRIEVING,
)
from app.domain.ticket_state import RiskDecision
from app.graph.builder import wrap_node
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b03_classify, b06_diagnose, b11_slots, b12_assess
from app.llm.providers.scripted import Reply
from app.risk.context import build_ctx
from app.settings import get_policy
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.llm import make_gateway, repo_registry
from tests.fakes.rag import FakeRag
from tests.unit._t20a import Env, rc

PROMPTS = Path(__file__).resolve().parents[3] / "config" / "prompts"
FOUR = frozenset({"vpn", "account", "software", "access"})
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ bình thường"}

# T20a DỪNG 2 (phase5 5.1.9): chuỗi node + prompt v3/v2 — xfail(strict) tới khi hiện thực (phase5 4.10).
CHO_DUNG2 = frozenset({"test_g_chain_b3_b6_b11_b12", "test_g2_other_persons_account_target_is_other",
                       "test_h3_prompt_versions_and_contract"})  # fmt: skip


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.name in CHO_DUNG2 or getattr(request.node, "originalname", None) in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError),
                                              reason="T20a DỪNG 2"))  # fmt: skip


async def chain(user: str, text: str, intent: str, action_hint: str | None, slots: dict[str, str]) -> tuple[
    dict[str, Any], MemoryAudit, Env]:  # fmt: skip
    """B3 → B6 → B11 → B12; dừng (assert) ngay khi một bước không ra trạng thái mong đợi."""
    env = Env()
    item = {"type": intent, "confidence": 0.93, "span": text, "action_hint": action_hint, "slots": dict(slots)}
    gw = make_gateway({"b02_injection_judge": lambda _: Reply(NOT_ATTACK),
                       "b03_classify": lambda _: Reply({"intents": [item], "is_multi": False})}, clock=env.clock)  # fmt: skip
    h = GraphHarness(clock=env.clock, directory=env.directory(), llm=gw.client, rag=FakeRag())
    audit = MemoryAudit()
    state: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_CLASSIFYING, "redacted_request": text, "reasoning_loops": 0,
        "conversation": [], "requester_context": rc(user), "clarification_turns": 0,
    }  # fmt: skip
    steps = (("b03_classify", b03_classify, S_DIAGNOSING), ("b06_diagnose", b06_diagnose, S_RETRIEVING),
             ("b11_slots", b11_slots, S_ASSESSING), ("b12_assess", b12_assess, None))  # fmt: skip
    for name, module, expect in steps:
        deps = dataclasses.replace(h.deps(), enabled_intents=FOUR)
        run = RunContext(turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
                         clock=env.clock, txlog=MemoryTxLog())  # fmt: skip
        with bind_run(run):
            update = await wrap_node(name, module.make(deps))(dict(state))
        state = {**state, **update}
        if expect is not None:
            assert state["status"] == expect, (name, state.get("exit_code"), state.get("escalation_reason_detail"),
                                               [(r["step"], r["event"]) for r in audit.rows])  # fmt: skip
    return state, audit, env


def _risk(state: dict[str, Any]) -> RiskDecision:
    assert state.get("risk") is not None, (state.get("exit_code"), state.get("escalation_reason_detail"))
    return RiskDecision.model_validate(state["risk"])


def _all_matched(audit: MemoryAudit) -> list[str]:
    rows = [r for r in audit.rows if r["step"] == "B13/B14"]
    assert len(rows) == 1, [(r["step"], r["event"]) for r in audit.rows]
    return list(rows[0]["detail"]["all_matched"])


# (user, text, intent, action_hint, slots B3, decision, rule_id, all_matched, extra target)
BANG_G = [
    pytest.param("nv001", "Mình quên mật khẩu, đặt lại mật khẩu tài khoản AD giúp mình", "account", "reset_password",
                 {"account_type": "ad"}, "allow", "R01", ["R01"], "user:nv001", id="g1-nv001-dat-lai-mat-khau-AD-R01"),
    pytest.param("nv001", "Cài Zoom giúp em với", "software", "install_software", {"software_name": "Zoom"},
                 "allow", "R11", ["R11"], "device:LAP-0342", id="g3-nv001-cai-Zoom-khong-neu-may-R11"),
    pytest.param("nv001", "Cài AutoCAD cho em để vẽ bản vẽ", "software", "install_software", {"software_name": "AutoCAD"},
                 "approval_required", "R14", ["R14", "R15"], "device:LAP-0342", id="g4-nv001-cai-AutoCAD-R14-R15"),
    pytest.param("nv001", "Gia hạn quyền thư mục finance/public-reports thêm 30 ngày", "access", "extend_permission",
                 {"resource_path": "finance/public-reports", "duration": "30"}, "allow", "R10", ["R10"],
                 "folder:finance/public-reports", id="g5-nv001-gia-han-public-reports-30-R10"),
    pytest.param("nv002", "Gia hạn quyền thư mục finance/Q3 thêm 30 ngày", "access", "extend_permission",
                 {"resource_path": "finance/Q3", "duration": "30"}, "approval_required", "R09", ["R09"],
                 "folder:finance/Q3", id="g6-nv002-gia-han-finance-Q3-R09"),
    pytest.param("nv001", "Cho mình quyền đọc thư mục finance/public-reports trong 30 ngày", "access", "grant_permission",
                 {"resource_path": "finance/public-reports", "permission_level": "read", "duration": "30"},
                 None, None, [], "folder:finance/public-reports", id="g7-nv001-xin-read-public-reports-ho-L1-none"),
    pytest.param("nv001", "Cấp quyền đọc thư mục engineering/specs trong 30 ngày cho nv004", "access", "grant_permission",
                 {"resource_path": "engineering/specs", "permission_level": "read", "duration": "30",
                  "target_user": "nv004"}, "deny", "R12", ["R09", "R12"], "folder:engineering/specs",
                 id="g8-nv001-cap-cho-nv004-R12-deny-kem-R09"),
    pytest.param("nv007", "Tài khoản email của mình bị khoá, mở khoá giúp mình", "account", "unlock_account",
                 {"account_type": "email"}, "allow", "R02", ["R02"], "user:nv007", id="g9-nv007-mo-khoa-email-R02"),
]  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize(("user", "text", "intent", "hint", "slots", "decision", "rule", "matched", "target"), BANG_G)
async def test_g_chain_b3_b6_b11_b12(
    user: str, text: str, intent: str, hint: str, slots: dict[str, str], decision: str | None, rule: str | None,
    matched: list[str], target: str,
) -> None:  # fmt: skip
    """g1, g3–g9 (bảng 5.1.6, kỳ vọng chép từ bảng 4.4 + seed): quyết định B12 đúng luật; `allow` → `S_EXECUTING`;
    `approval_required` → B15 (`S_ASSESSING`); `deny` → E5; không luật nào (họ L1) → E5 `llm_layer_disabled`."""
    state, audit, _ = await chain(user, text, intent, hint, slots)
    assert state["intended_action"].target == target
    risk = _risk(state)
    assert (risk.policy_decision, risk.matched_rule_id) == (decision, rule), (risk, audit.rows[-1]["detail"])
    assert _all_matched(audit) == matched
    if decision == "allow":
        assert (state.get("status"), state.get("next")) == (S_EXECUTING, "b17_execute")
    elif decision == "approval_required":
        assert (state.get("status"), state.get("next")) == (S_ASSESSING, "b15_prepare_approval")
    elif decision == "deny":
        assert (state.get("status"), state.get("exit_code")) == (S_ESCALATED, "E5")
    else:
        assert (state.get("exit_code"), state.get("escalation_reason_detail")) == ("E5", "llm_layer_disabled")


@pytest.mark.asyncio
async def test_g2_other_persons_account_target_is_other() -> None:
    """g2 (họ L2): nv005 đặt lại mật khẩu cho nv001 → `requested_for=nv001`, `target_is_other=True` → không luật nào (R01 đòi
    `other` false; R03–R05 không thoả) → lớp LLM (`DisabledEstimator`) → E5 `llm_layer_disabled`."""
    state, audit, env = await chain("nv005", "Đặt lại mật khẩu tài khoản AD cho nv001 giúp mình", "account",
                                    "reset_password", {"account_type": "ad", "target_user": "nv001"})  # fmt: skip
    action = state["intended_action"]
    assert (action.requested_for, action.target) == ("nv001", "user:nv001")
    assert build_ctx(state, env.clock.now(), get_policy().business_hours).target_is_other is True
    assert set(env.tools.user_ids()) == {"nv001"}  # fact mô tả nv001 (P6), không phải người gửi
    assert (state.get("exit_code"), state.get("escalation_reason_detail")) == ("E5", "llm_layer_disabled")
    assert _all_matched(audit) == []


# ---- h3: prompt v3 / v2 ----------------------------------------------------------------------------------------------------


def test_h3_prompt_versions_and_contract() -> None:
    """h3 (P9): `b03_classify` v3, `b11_extract_slots` v2; registry nạp; `allowed_vars` KHÔNG đổi; vẫn 8 prompt; v3 liệt kê slot +
    `action_hint` hợp lệ của từng intent (bảng 5.1.4)."""
    b03 = yaml.safe_load((PROMPTS / "b03_classify.yaml").read_text(encoding="utf-8"))
    b11 = yaml.safe_load((PROMPTS / "b11_extract_slots.yaml").read_text(encoding="utf-8"))
    assert int(b03["version"]) == 3 and int(b11["version"]) == 2
    registry = repo_registry()
    assert len(registry) == 8
    by_id = {p.id: p for p in registry}
    assert set(by_id["b03_classify"].spec.allowed_vars) == {"redacted_request", "recent_messages", "label_hint"}
    assert set(by_id["b11_extract_slots"].spec.allowed_vars) == {"text", "missing", "intent"}
    system = b03["system"]
    for word in ("device_id", "error_code", "account_type", "target_user", "software_name", "resource_path",
                 "permission_level", "duration", "renew_vpn_cert", "reissue_vpn_access", "check_vpn_status",
                 "reset_password", "unlock_account", "install_software", "view_permissions", "grant_permission",
                 "extend_permission"):  # fmt: skip
        assert word in system, word
