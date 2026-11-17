"""D-98 (TA chốt 17/11): tin E5 cho người dùng nêu "Lý do chính: …" ghép từ nhãn CỐ ĐỊNH theo mã.

- `llm_high_risk`: nhãn theo `state.risk_factors` (mã B14 chọn, tập đóng `FactorCode`; B12 đặt), đúng thứ tự, bỏ trùng, tối đa 3; mã không khai
  nhãn (`no_policy_evidence`, `routine_low_risk`) bị bỏ qua; không còn nhãn nào → không có vế lý do.
- `policy_deny`: nhãn theo `matched_rule_id` (R12, R21); luật không khai → không có vế lý do.
- Mã khác E5, lý do khác, thiếu `risk` → "". Không chép chữ tự do (`reason` của RiskDecision có xác suất, tên luật) vào tin.
- `risk_factors` là khoá state riêng (không nằm trong `RiskDecision` — phiếu duyệt `RiskView` giữ nguyên hợp đồng); B12 đặt ở nhánh
  `llm_high_risk`.
"""

from typing import Any

import pytest
from app.domain.risk_factors import FactorCode
from app.domain.ticket_state import RiskDecision
from app.graph.nodes.b20_audit import REASON_MAX, user_reason_suffix
from app.settings import EscalationTemplates, get_escalation_templates
from pydantic import ValidationError

T = get_escalation_templates()


def _risk(**kw: Any) -> RiskDecision:
    base: dict[str, Any] = {
        "decided_by": "llm", "policy_decision": None, "matched_rule_id": None, "raw_prob": 0.9, "calibrated_prob": None,
        "p_method": "self_report", "risk_level": "high", "route": "ESCALATE_L2",
        "reason": "Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,90", "thresholds": (0.3, 0.7),
    }  # fmt: skip
    return RiskDecision.model_validate(base | kw)


def _state(reason: str | None, risk: Any, code: str = "E5", factors: Any = None) -> dict[str, Any]:
    return {"exit_code": code, "escalation_reason_detail": reason, "risk": risk, "risk_factors": factors}


def test_llm_high_risk_lists_user_labels_in_order() -> None:
    codes = ["target_is_other", "no_policy_evidence", "outside_business_hours"]
    got = user_reason_suffix(_state("llm_high_risk", _risk(), factors=codes), T)
    assert got == " Lý do chính: yêu cầu làm cho tài khoản hoặc máy của người khác; yêu cầu gửi ngoài giờ hành chính."


def test_dict_risk_after_checkpoint_roundtrip_same_result() -> None:
    risk = _risk(decided_by="rule", policy_decision="deny", matched_rule_id="R21")
    assert user_reason_suffix(_state("policy_deny", risk.model_dump(mode="json")), T) == user_reason_suffix(
        _state("policy_deny", risk), T
    ) != ""


def test_at_most_three_labels_and_no_duplicates() -> None:
    codes = ("target_is_other", "target_is_other", "privileged_target", "service_account", "sensitive_data")
    got = user_reason_suffix(_state("llm_high_risk", _risk(), factors=codes), T)
    assert got.count(";") == REASON_MAX - 1
    assert got.count(T.user_reason_factors[FactorCode.TARGET_IS_OTHER]) == 1


@pytest.mark.parametrize("codes", [None, [], ["no_policy_evidence"], ["routine_low_risk", "no_policy_evidence"], ["khong_co"]])
def test_no_user_facing_factor_no_suffix(codes: list[str] | None) -> None:
    assert user_reason_suffix(_state("llm_high_risk", _risk(), factors=codes), T) == ""


@pytest.mark.parametrize(("rule", "want"), [("R21", "danh sách bị cấm"), ("R12", "bị khoá")])
def test_policy_deny_uses_rule_label(rule: str, want: str) -> None:
    risk = _risk(decided_by="rule", policy_decision="deny", matched_rule_id=rule, raw_prob=None, p_method=None,
                 reason="Phần mềm bị cấm", thresholds=None)  # fmt: skip
    got = user_reason_suffix(_state("policy_deny", risk), T)
    assert got.startswith(" Lý do chính: ") and want in got and rule not in got


@pytest.mark.parametrize(
    ("reason", "code", "risk"),
    [
        ("policy_deny", "E5", _risk(matched_rule_id="R99")),  # luật không khai nhãn
        ("policy_deny", "E5", None),  # thiếu risk
        ("approval_target_unverified", "E5", _risk()),  # lý do E5 khác
        ("llm_high_risk", "E1", _risk()),  # mã khác
    ],
)
def test_other_cases_no_suffix(reason: str, code: str, risk: Any) -> None:
    assert user_reason_suffix(_state(reason, risk, code, factors=["target_is_other"]), T) == ""


def test_suffix_never_copies_free_text() -> None:
    risk = _risk(reason="Mô hình 0,90 · R21 · xác suất")
    got = user_reason_suffix(_state("llm_high_risk", risk, factors=[f.value for f in FactorCode]), T)
    for leak in ("0,9", "xác suất", "R21", "Mô hình", "no_policy", "routine"):
        assert leak not in got


def test_risk_factors_is_state_key_not_risk_decision_field() -> None:
    from app.domain.ticket_state import STATE_KEYS

    assert "risk_factors" in STATE_KEYS and "factors" not in RiskDecision.model_fields


def test_label_validation() -> None:
    raw = T.model_dump(mode="json")
    raw["user_reason_rules"] = {"X1": "nhãn"}
    with pytest.raises(ValidationError, match="mã luật lạ"):
        EscalationTemplates.model_validate(raw)
    raw = T.model_dump(mode="json")
    raw["user_reason_factors"] = {"target_is_other": "kết thúc bằng chấm."}
    with pytest.raises(ValidationError):
        EscalationTemplates.model_validate(raw)


def test_every_deny_rule_has_user_label() -> None:
    """Luật `deny` nào cũng có câu lý do cho người dùng — thêm luật cấm mới mà quên nhãn thì đỏ ở đây."""
    import json
    from pathlib import Path

    from app.settings import get_settings

    rules = json.loads(Path(get_settings().config_dir, "policy.json").read_text(encoding="utf-8"))["rules"]
    deny = {r["id"] for r in rules if r["type"] == "deny"}
    assert deny and deny <= set(T.user_reason_rules)


def test_b12_llm_high_risk_sets_risk_factors() -> None:
    import inspect

    from app.graph.nodes import b12_assess

    src = inspect.getsource(b12_assess)
    i = src.index('escalation_reason_detail="llm_high_risk"')
    assert "risk_factors=[f.value for f in est.factors]" in src[i : i + 200]
