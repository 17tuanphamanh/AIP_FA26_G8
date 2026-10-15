"""Phase 6 chặng 6C — `audit_check` điểm 4 theo `decided_by` (phase6 bảng 6.4 c13; 6.1 P7; 6.8 Q-6-8 = C điều kiện 1; PLAN-6C
TQ-11, Q-6C-3 = A). Viết TỪ ĐẶC TẢ trước code; khuôn dòng/Missing của `test_audit_check.py`.

Điểm 4 (`step="B13/B14"`, `event="risk_decided"`):
- `decided_by == "llm"` → bắt buộc ≠ null, ĐÚNG thứ tự: `decided_by, risk_level, reason, detail.route, detail.policy_sha256, raw_prob,
  p_method, detail.thresholds` — KHÔNG đòi `policy_decision`.
- `decided_by` NULL/vắng ∧ `detail.strategy == "full_auto"` ∧ `detail.route == "AUTO"` → chỉ đòi `detail.policy_sha256`.
- `decided_by == "rule"` ∧ `policy_decision` NULL ∧ `detail.strategy == "rule_only"` ∧ `detail.route == "HITL"` → đòi `decided_by,
  risk_level, reason, detail.route, detail.policy_sha256`.
- Còn lại → danh sách cũ `decided_by, policy_decision, risk_level, reason, detail.route, detail.policy_sha256` (NULL không ghi chú →
  thiếu `decided_by`; rule + `policy_decision` NULL không ghi chú `rule_only` → thiếu `policy_decision`).
"""

import copy
from typing import Any

import pytest
from app.audit.check import Missing, required
from tests.unit.test_audit_check import FULL, HEX64, P4, T, _row, _with, _without

LLM_FIELDS = ("decided_by", "risk_level", "reason", "detail.route", "detail.policy_sha256", "raw_prob", "p_method",
              "detail.thresholds")  # fmt: skip  — P7 / TQ-11, đúng thứ tự

P4_LLM = _row(11, "B13/B14", "risk_decided",
              {"route": "HITL", "policy_sha256": HEX64, "thresholds": [0.25, 0.75], "raw_prob": 0.02, "p_method": "self_report"},
              decided_by="llm", risk_level="medium", raw_prob=0.02, p_method="self_report",
              reason="Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,02 (chưa hiệu chỉnh — không tự xử lý) → "
                     "chờ người duyệt. Yếu tố: (không nêu).")  # fmt: skip
P4_FULL_AUTO = _row(11, "B13/B14", "risk_decided", {"strategy": "full_auto", "route": "AUTO", "policy_sha256": HEX64})  # Q-6-8 = C
P4_RULE_ONLY = _row(11, "B13/B14", "risk_decided", {"route": "HITL", "policy_sha256": HEX64, "strategy": "rule_only"},
                    decided_by="rule", policy_decision=None, risk_level="medium",
                    reason="Không luật nào khớp → chờ duyệt (chỉ-luật)")  # fmt: skip  — Q-6C-3


def _m(fields: tuple[str, ...], log_id: int = 11) -> list[Missing]:
    return [Missing(T, 4, log_id, fields)]


# ---- decided_by = "llm" ----------------------------------------------------------------------------------------------


def test_c13_llm_full_row_ok() -> None:
    """c13 (P7): dòng LLM đủ trường → []; không đòi `policy_decision` (cột vắng)."""
    assert "policy_decision" not in P4_LLM
    assert required(T, [copy.deepcopy(P4_LLM)], final_state=None) == []


def test_c13_llm_policy_decision_null_ok() -> None:
    """c13 (P7 "không đòi policy_decision"): cột `policy_decision` có mà NULL → vẫn đạt."""
    assert required(T, [_with(P4_LLM, "policy_decision", None)], final_state=None) == []


def test_c13_llm_missing_raw_prob() -> None:
    """c13 (M-6C-4): dòng LLM thiếu `raw_prob` → `[Missing(T, 4, log_id, ("raw_prob",))]`."""
    assert required(T, [_without(P4_LLM, "raw_prob")], final_state=None) == _m(("raw_prob",))


@pytest.mark.parametrize("field", LLM_FIELDS[1:])
def test_c13_llm_drop_each_required_field(field: str) -> None:
    """c13 (P7): bỏ ĐÚNG một trường bắt buộc của dòng LLM (trừ `decided_by` — bỏ nó thì dòng không còn là LLM) → đúng một trường."""
    assert required(T, [_without(P4_LLM, field)], final_state=None) == _m((field,))


@pytest.mark.parametrize("field", ["raw_prob", "p_method", "detail.thresholds", "risk_level"])
def test_c13_llm_field_none_is_missing(field: str) -> None:
    """c13 (P7 "≠ null"): khoá CÓ nhưng None → vẫn thiếu."""
    assert required(T, [_with(P4_LLM, field, None)], final_state=None) == _m((field,))


def test_c13_llm_all_missing_in_contract_order() -> None:
    """TQ-11: bỏ cả 7 trường (giữ `decided_by="llm"`) → `fields` đúng thứ tự hợp đồng."""
    row = copy.deepcopy(P4_LLM)
    for field in LLM_FIELDS[1:]:
        row = _without(row, field)
    assert required(T, [row], final_state=None) == _m(LLM_FIELDS[1:])


def test_c13_llm_row_losing_decided_by_falls_back_to_old_list() -> None:
    """P7 + Q-6-8 điều kiện 1 (suy từ hợp đồng): dòng LLM mất `decided_by` (không ghi chú `full_auto`) → danh sách cũ → thiếu
    `decided_by` VÀ `policy_decision` (thứ tự hai trường không ghim — khuôn `test_a1_two_fields_missing_same_row_one_entry`)."""
    [m] = required(T, [_without(P4_LLM, "decided_by")], final_state=None)
    assert (m.ticket_id, m.point, m.log_id) == (T, 4, 11)
    assert set(m.fields) == {"decided_by", "policy_decision"}


def test_c13_full_ticket_with_llm_point4_ok() -> None:
    """Cả bộ dòng đủ 8 điểm (`test_audit_check.FULL`), điểm 4 thay bằng dòng LLM → []."""
    rows = [copy.deepcopy(P4_LLM) if r is P4 else copy.deepcopy(r) for r in FULL]
    assert required(T, rows, final_state="S_RESOLVED") == []


# ---- decided_by NULL: full_auto (Q-6-8 = C) ---------------------------------------------------------------------------


@pytest.mark.parametrize("decided_by", ["vang", "null"])
def test_c13_null_full_auto_auto_with_sha_ok(decided_by: str) -> None:
    """c13 + Q-6-8 điều kiện 1: `decided_by` NULL/vắng + `detail.strategy="full_auto"` + `route="AUTO"` + `policy_sha256` → đạt."""
    row = copy.deepcopy(P4_FULL_AUTO) if decided_by == "vang" else _with(P4_FULL_AUTO, "decided_by", None)
    assert required(T, [row], final_state=None) == []


def test_c13_null_full_auto_missing_sha() -> None:
    """P7 / TQ-11: NULL + full_auto + AUTO nhưng thiếu `detail.policy_sha256` → chỉ đòi trường đó."""
    assert required(T, [_without(P4_FULL_AUTO, "detail.policy_sha256")], final_state=None) == _m(("detail.policy_sha256",))


def test_c13_null_without_annotation_missing_decided_by() -> None:
    """c13 + Q-6-8 điều kiện 1 (M-6C-7): NULL không ghi chú → thiếu `decided_by` (giữ `test_audit_check.py:150`)."""
    assert required(T, [_without(P4, "decided_by")], final_state=None) == _m(("decided_by",))
    assert required(T, [_with(P4, "decided_by", None)], final_state=None) == _m(("decided_by",))


def test_c13_null_full_auto_but_route_hitl_missing_decided_by() -> None:
    """Q-6-8 điều kiện 1 ("và detail.route == AUTO"): NULL + `strategy=full_auto` nhưng route HITL → thiếu `decided_by`."""
    row = _with(_with(_without(P4, "decided_by"), "detail.strategy", "full_auto"), "detail.route", "HITL")
    assert required(T, [row], final_state=None) == _m(("decided_by",))


def test_c13_null_other_strategy_annotation_missing_decided_by() -> None:
    """Q-6-8: NULL CHỈ hợp lệ với `full_auto` — ghi chú chiến lược khác (`hybrid`, route AUTO) → thiếu `decided_by`."""
    row = _with(_with(_without(P4, "decided_by"), "detail.strategy", "hybrid"), "detail.route", "AUTO")
    assert required(T, [row], final_state=None) == _m(("decided_by",))


# ---- decided_by = "rule" + policy_decision NULL: rule_only (Q-6C-3) ------------------------------------------------------


def test_q6c3_rule_only_hitl_policy_decision_null_ok() -> None:
    """Q-6C-3 = A: `decided_by="rule"` + `policy_decision` NULL + `detail.strategy="rule_only"` + route HITL → đạt."""
    assert required(T, [copy.deepcopy(P4_RULE_ONLY)], final_state=None) == []
    assert required(T, [_without(P4_RULE_ONLY, "policy_decision")], final_state=None) == []  # cột vắng cũng là NULL


@pytest.mark.parametrize("field", ["risk_level", "reason", "detail.policy_sha256"])
def test_q6c3_rule_only_still_requires_fields(field: str) -> None:
    """Q-6C-3 / hợp đồng: nhánh rule_only vẫn đòi `risk_level`, `reason`, `detail.policy_sha256` (bỏ một → đúng trường đó)."""
    assert required(T, [_without(P4_RULE_ONLY, field)], final_state=None) == _m((field,))


def test_q6c3_rule_policy_decision_null_without_annotation_missing() -> None:
    """Q-6C-3: rule + `policy_decision` NULL không ghi chú `rule_only` → thiếu `policy_decision`."""
    row = _with(P4, "policy_decision", None)
    assert required(T, [row], final_state=None) == _m(("policy_decision",))


@pytest.mark.parametrize(("key", "value"), [("detail.route", "AUTO"), ("detail.strategy", "hybrid")],
                         ids=["rule_only-route-AUTO", "strategy-hybrid"])  # fmt: skip
def test_q6c3_rule_only_exemption_needs_both_conditions(key: str, value: Any) -> None:
    """Q-6C-3 ("CHỈ hợp lệ khi strategy == rule_only ∧ route == HITL"): lệch một vế → thiếu `policy_decision`."""
    assert required(T, [_with(P4_RULE_ONLY, key, value)], final_state=None) == _m(("policy_decision",))


def test_rule_row_unchanged() -> None:
    """P7 "decided_by=rule → như cũ": dòng luật đủ → []; bỏ `policy_decision` → thiếu đúng trường đó."""
    assert required(T, [copy.deepcopy(P4)], final_state=None) == []
    assert required(T, [_without(P4, "policy_decision")], final_state=None) == _m(("policy_decision",))
