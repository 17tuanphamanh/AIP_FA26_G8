"""M2 (ĐP 08/11): tách lý do E5 — luật cấm (`policy_deny`) khỏi lớp AI lỗi (`llm_layer_disabled`).

- B12: nhánh luật `deny` → E5 `policy_deny`; lỗi estimator → E5 `llm_layer_disabled` + `detail.estimator_error` như cũ. Route, mã thoát
  (E5), điểm log 4 giữ nguyên (dòng deny chỉ thêm `detail.escalation_reason_detail` như mọi nhánh E5 khác của goto).
- Ghi chú bàn giao L2: luật cấm → câu E5 như cũ; lớp AI lỗi → câu riêng. Cảnh báo deny nối vào MỌI E5; L2 không "hoàn tất" được cả hai
  (B20 5.1 không đổi).
- `eval/predictions` không đổi hình dạng: `eval/test_predictions_e5_reason.py` (cần `EVAL_MODE` của conftest thư mục eval).
"""

from typing import Any

import pytest
from app.audit.handoff import build_handoff, is_deny_case
from app.audit.labels import REASON_LABELS
from app.core.errors import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.domain.escalation_close import cannot_complete
from app.domain.exit_codes import REASON_DETAILS, ExitCode
from app.domain.states import S_ESCALATED
from app.domain.ticket_state import RiskDecision
from app.graph.nodes import b12_assess
from app.risk.models import RuleVerdict
from app.settings import EscalationTemplates, get_escalation_templates
from pydantic import ValidationError
from tests.unit.test_b12_assess import POINT4, SpyEstimator, _action, _node, _state

TEMPLATES = get_escalation_templates()
AI_DOWN_NOTE = "Hệ thống chưa đánh giá được rủi ro do lớp AI lỗi — cần kỹ thuật viên đánh giá thủ công."
DENY = RuleVerdict(matched=True, decision="deny", rule_id="R12", all_matched=["R12", "R20"], description="Cấm")


# ---- B12 ---------------------------------------------------------------------------------------------------------------------


def test_policy_deny_is_a_known_reason_with_label() -> None:
    assert "policy_deny" in REASON_DETAILS and "llm_layer_disabled" in REASON_DETAILS
    assert REASON_LABELS["policy_deny"] == "Không được phép theo chính sách"


@pytest.mark.asyncio
async def test_b12_deny_rule_reason_policy_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b12_assess, "evaluate", lambda action, ctx: DENY)
    out, h, _ = await _node(_state())
    assert (out["status"], out["next"], out["exit_code"]) == (S_ESCALATED, "b20_audit", "E5")
    assert out["escalation_reason_detail"] == "policy_deny"
    risk = RiskDecision.model_validate(out["risk"])
    assert (risk.decided_by, risk.policy_decision, risk.matched_rule_id, risk.route) == ("rule", "deny", "R12", "ESCALATE_L2")
    [row] = h.audit.of("t1", "risk_decided")
    assert row["exit_code"] == "E5" and row["step"] == "B13/B14"
    assert row["detail"]["escalation_reason_detail"] == "policy_deny"
    assert set(row["detail"]) - {"escalation_reason_detail"} == POINT4  # điểm log 4 không đổi hình dạng


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [LLMUnavailable("x"), LLMSchemaError("x"), LLMBudgetExceeded("x")])
async def test_b12_estimator_error_stays_llm_layer_disabled(exc: Exception) -> None:
    out, h, _ = await _node(_state(intended_action=_action(owner=False)), estimator=SpyEstimator(exc=exc))
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E5", "llm_layer_disabled")
    [row] = h.audit.of("t1", "llm_layer_disabled")
    assert row["detail"]["estimator_error"] == type(exc).__name__
    assert row["detail"]["escalation_reason_detail"] == "llm_layer_disabled"
    assert RiskDecision.model_validate(out["risk"]).route == "ESCALATE_L2"


@pytest.mark.asyncio
async def test_b12_allow_and_hitl_have_no_reason_detail() -> None:
    out, _, _ = await _node(_state())
    assert "escalation_reason_detail" not in out and "exit_code" not in out


# ---- ghi chú bàn giao L2 -----------------------------------------------------------------------------------------------------


def _note(code: str, reason: str | None, **state: Any) -> Any:
    st: dict[str, Any] = {"exit_code": code, "redacted_request": "gia hạn VPN", **state}
    if reason is not None:
        st["escalation_reason_detail"] = reason
    return build_handoff(st, TEMPLATES, retrieval_threshold=0.5)


def test_handoff_policy_deny_same_as_before() -> None:
    risk = RiskDecision(decided_by="rule", policy_decision="deny", matched_rule_id="R12", raw_prob=None, calibrated_prob=None,
                        p_method=None, risk_level="high", route="ESCALATE_L2", reason="Cấm", thresholds=None)  # fmt: skip
    note = _note("E5", "policy_deny", risk=risk)
    assert note.next_for_l2 == f"{TEMPLATES.of('E5').next_for_l2} {TEMPLATES.deny_warning}"
    assert "Chi tiết: Không được phép theo chính sách · policy_deny." in note.why_escalated
    assert AI_DOWN_NOTE not in note.next_for_l2


def test_handoff_llm_layer_disabled_own_sentence_keeps_deny_warning() -> None:
    note = _note("E5", "llm_layer_disabled")
    assert note.next_for_l2 == f"{AI_DOWN_NOTE} {TEMPLATES.deny_warning}"
    assert TEMPLATES.of("E5").next_for_l2 not in note.next_for_l2


@pytest.mark.parametrize("reason", [None, "llm_high_risk", "recheck_failed", "approval_target_unverified"])
def test_handoff_other_e5_reasons_unchanged(reason: str | None) -> None:
    assert _note("E5", reason).next_for_l2 == f"{TEMPLATES.of('E5').next_for_l2} {TEMPLATES.deny_warning}"


@pytest.mark.parametrize("code", [c.value for c in ExitCode if c is not ExitCode.E5])
def test_handoff_ai_sentence_only_for_e5(code: str) -> None:
    """Mẫu theo lý do khai báo dưới E5 — mã khác cùng lý do (nếu có) vẫn câu của mã đó, không cảnh báo deny."""
    assert _note(code, "llm_layer_disabled").next_for_l2 == TEMPLATES.of(code).next_for_l2


@pytest.mark.parametrize("reason", ["policy_deny", "llm_layer_disabled"])
def test_both_reasons_are_deny_cases_l2_cannot_complete(reason: str) -> None:
    assert is_deny_case("E5")
    assert cannot_complete("completed", exit_code="E5", is_deny_case=is_deny_case("E5"))
    assert not cannot_complete("confirmed_denial", exit_code="E5", is_deny_case=True)


def test_templates_reason_keys_validated() -> None:
    raw = TEMPLATES.model_dump(mode="json")
    raw["codes"]["E5"]["next_for_l2_by_reason"] = {"khong_co_that": "x"}
    with pytest.raises(ValidationError, match="khong_co_that"):
        EscalationTemplates.model_validate(raw)
    raw["codes"]["E5"]["next_for_l2_by_reason"] = {"llm_layer_disabled": ""}
    with pytest.raises(ValidationError):
        EscalationTemplates.model_validate(raw)


def test_templates_loaded_by_reason() -> None:
    assert TEMPLATES.of("E5").next_for_l2_by_reason == {"llm_layer_disabled": AI_DOWN_NOTE}
    # D-84 (12/11): E1 có MỘT câu riêng cho `reverse_action_requested`; mã khác (trừ E5) vẫn không có
    assert set(TEMPLATES.of("E1").next_for_l2_by_reason) == {"reverse_action_requested"}
    assert all(not TEMPLATES.of(c.value).next_for_l2_by_reason for c in ExitCode if c not in (ExitCode.E5, ExitCode.E1))
