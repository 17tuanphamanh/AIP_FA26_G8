"""Ghi chú bàn giao L2 thành câu tiếng Việt (ĐP 02/11 12:45) — bảng nhãn `audit/labels.py` + phần (3) `why_escalated`."""

import re
from typing import Any

import pytest
from app.audit.handoff import INJECTION_SUSPECTED_NOTE, build_handoff
from app.audit.labels import (
    DECIDED_BY_LABELS,
    EXIT_LABELS,
    REASON_LABELS,
    ROUTE_LABELS,
    exit_label,
    reason_label,
)
from app.domain.exit_codes import REASON_DETAILS, ExitCode
from app.domain.ticket_state import RiskDecision
from app.settings import get_escalation_templates

TEMPLATES = get_escalation_templates()
THRESHOLD = 0.5
_CODE_LIKE = re.compile(r"\b(?:E\d|[a-z]+_[a-z_]+|AUTO|HITL|ESCALATE_L2|R\d{2})\b")


def _risk(**kw: Any) -> RiskDecision:
    base: dict[str, Any] = {
        "decided_by": "llm", "policy_decision": None, "matched_rule_id": None, "raw_prob": 0.83, "calibrated_prob": 0.71,
        "p_method": "sampling_k5", "risk_level": "medium", "route": "HITL", "thresholds": (0.2, 0.8),
        "reason": "Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,71 (ngưỡng 0,20/0,80) → chờ duyệt",
    }  # fmt: skip
    return RiskDecision(**(base | kw))


def _why(**state: Any) -> str:
    return build_handoff(state, TEMPLATES, retrieval_threshold=THRESHOLD).why_escalated


def test_every_exit_code_and_reason_has_label() -> None:
    assert set(EXIT_LABELS) == set(ExitCode)
    assert REASON_DETAILS <= set(REASON_LABELS), sorted(REASON_DETAILS - set(REASON_LABELS))
    assert set(ROUTE_LABELS) == {"AUTO", "HITL", "ESCALATE_L2"} and set(DECIDED_BY_LABELS) == {"rule", "llm", "model"}
    for label in [*EXIT_LABELS.values(), *REASON_LABELS.values(), *ROUTE_LABELS.values(), *DECIDED_BY_LABELS.values()]:
        assert label and not _CODE_LIKE.search(label), label  # nhãn là chữ thường, không lẫn mã


@pytest.mark.parametrize("code", [c.value for c in ExitCode])
def test_first_sentence_is_label_then_code(code: str) -> None:
    why = _why(exit_code=code)
    assert why.startswith(f"Lý do chuyển: {EXIT_LABELS[ExitCode(code)]} · {code}. Mức ưu tiên: ")


@pytest.mark.parametrize("reason", sorted(REASON_DETAILS))
def test_reason_detail_label_then_code(reason: str) -> None:
    why = _why(exit_code="E5", escalation_reason_detail=reason)
    assert f"Chi tiết: {REASON_LABELS[reason]} · {reason}." in why
    assert why.index(REASON_LABELS[reason]) < why.index(f"· {reason}")


def test_unknown_codes_fall_back_to_other() -> None:
    assert exit_label("E42", None) == "Khác · E42"
    assert reason_label("la_qua") == "Khác · la_qua"
    assert "Chi tiết: Khác · la_qua." in _why(exit_code="E2", escalation_reason_detail="la_qua")


def test_e1_injection_suspected_uses_own_label_once() -> None:
    why = _why(exit_code="E1", escalation_reason_detail="injection_suspected")
    assert why.startswith("Lý do chuyển: Nghi tấn công, cần người xem · E1. Mức ưu tiên: Thường.")
    assert "Chi tiết:" not in why and why.count("Nghi tấn công, cần người xem") == 1
    assert INJECTION_SUSPECTED_NOTE in why
    assert "Ngoài phạm vi" not in why


@pytest.mark.parametrize(("route", "label"), list(ROUTE_LABELS.items()))
def test_risk_line_route_and_decider_no_raw_keys(route: str, label: str) -> None:
    why = _why(exit_code="E5", escalation_reason_detail="llm_high_risk", risk=_risk(route=route))
    assert f"Đánh giá rủi ro: {label} · {route} (Theo đánh giá của AI) — " in why
    for raw in ("p=", "bởi llm", "bởi rule", "policy_decision", "calibrated_prob", "decided_by"):
        assert raw not in why, raw


def test_risk_line_rule_shows_rule_id_last() -> None:
    risk = _risk(decided_by="rule", policy_decision="deny", matched_rule_id="R12", raw_prob=None, calibrated_prob=None,
                 p_method=None, route="ESCALATE_L2", thresholds=None, reason="Cấm cấp quyền cho tài khoản bị vô hiệu hoá")  # fmt: skip
    why = _why(exit_code="E5", risk=risk)
    assert "Đánh giá rủi ro: Chuyển kỹ thuật viên L2 · ESCALATE_L2 (Theo luật · R12) — Cấm cấp quyền cho tài khoản bị vô hiệu hoá." in why
    assert "deny" not in why
