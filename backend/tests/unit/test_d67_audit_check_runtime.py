"""D-67 P1.4 — bất biến `audit/check.py` (`_point4_need`, dòng 117–125) ĐÚNG với dòng audit điểm 4 VẬN HÀNH (không EVAL_MODE) của
`rule_only` và `hybrid_guarded`: dòng do chính node B12 sinh (`eval_mode=False`, chiến lược chụp trên ticket) — không báo thiếu sai
(dòng đủ → []), không bỏ lọt (bỏ một trường bắt buộc → đúng trường đó).

Trước D-67 dòng vận hành không có `detail.strategy` (Q-6C-3) nên nhánh `rule_only` + `policy_decision` NULL của `audit_check` chỉ đạt
khi EVAL_MODE; nay B12 luôn ghi `detail.strategy` nên dòng vận hành của `rule_only` (không luật nào khớp → HITL) cũng đạt.
"""

import copy
from typing import Any

import pytest
from app.audit.check import Missing, required
from tests.fakes.risk_estimator import FakeRiskEstimator
from tests.unit.test_b12_llm import CAL, _est, _no_match, _node, _rule_match

T = "t1"
RULE_FIELDS = ("decided_by", "policy_decision", "risk_level", "reason", "detail.route", "detail.policy_sha256")
LLM_FIELDS = ("risk_level", "reason", "detail.route", "detail.policy_sha256", "raw_prob", "p_method", "detail.thresholds")


async def _runtime_point4(state: dict[str, Any], strategy: str, estimate: float = 0.05) -> dict[str, Any]:
    _, h, _ = await _node(state, estimator=FakeRiskEstimator(_est(estimate, 0)), calibrator=CAL, strategy=strategy,  # type: ignore[arg-type]
                            eval_mode=False)  # fmt: skip
    [row] = h.audit.of(T, "risk_decided")
    return {"log_id": 11, **copy.deepcopy(row)}


def _drop(row: dict[str, Any], field: str) -> dict[str, Any]:
    out = copy.deepcopy(row)
    if field.startswith("detail."):
        del out["detail"][field.removeprefix("detail.")]
    else:
        out[field] = None
    return out


CASES = [
    pytest.param("rule_only", "khong-khop", ("rule", None, "HITL"), RULE_FIELDS[:1] + RULE_FIELDS[2:], id="rule_only-khong-khop"),
    pytest.param("rule_only", "luat", ("rule", "allow", "AUTO"), RULE_FIELDS, id="rule_only-luat-allow"),
    pytest.param("hybrid_guarded", "luat", ("llm", "allow", "AUTO"), LLM_FIELDS, id="hybrid_guarded-allow-llm"),
    pytest.param("hybrid_guarded", "khong-khop", ("llm", None, "AUTO"), LLM_FIELDS, id="hybrid_guarded-khong-khop-llm"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("strategy", "path", "shape", "required_fields"), CASES)
async def test_runtime_point4_row_passes_audit_check(
    strategy: str, path: str, shape: tuple[str, str | None, str], required_fields: tuple[str, ...]
) -> None:
    """Dòng điểm 4 vận hành đủ trường → `required` không báo thiếu (không báo sai); `detail.strategy` = chiến lược của ticket."""
    row = await _runtime_point4(_rule_match() if path == "luat" else _no_match(), strategy)
    assert (row["decided_by"], row.get("policy_decision"), row["detail"]["route"]) == shape
    assert row["detail"]["strategy"] == strategy
    assert required(T, [row], final_state=None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("strategy", "path", "shape", "required_fields"), CASES)
async def test_runtime_point4_row_missing_field_is_reported(
    strategy: str, path: str, shape: tuple[str, str | None, str], required_fields: tuple[str, ...]
) -> None:
    """Không bỏ lọt: bỏ ĐÚNG một trường bắt buộc của dòng vận hành → `Missing` nêu đúng trường đó (trừ `decided_by` của dòng LLM:
    bỏ nó thì dòng rơi về danh sách luật — đã có test ở `test_audit_check_m5`)."""
    row = await _runtime_point4(_rule_match() if path == "luat" else _no_match(), strategy)
    for field in required_fields:
        # rule_only không khớp mất `decided_by` hoặc `detail.route` → ra khỏi nhánh `rule_only ∧ HITL` → danh sách luật cũ → thiếu
        # thêm `policy_decision` (thứ tự hợp đồng `RULE_FIELDS`) — vẫn bị bắt, chặt hơn chứ không lỏng hơn
        extra = row["decided_by"] == "rule" and row.get("policy_decision") is None and field in ("decided_by", "detail.route")
        want = tuple(f for f in RULE_FIELDS if f in (field, "policy_decision")) if extra else (field,)
        assert required(T, [_drop(row, field)], final_state=None) == [Missing(T, 4, 11, want)], field


@pytest.mark.asyncio
async def test_runtime_rule_only_without_strategy_annotation_still_flagged() -> None:
    """Đối chứng (không nới bất biến): dòng `rule_only` vận hành mất `detail.strategy` → `policy_decision` NULL bị báo thiếu như trước."""
    row = await _runtime_point4(_no_match(), "rule_only")
    del row["detail"]["strategy"]
    assert required(T, [row], final_state=None) == [Missing(T, 4, 11, ("policy_decision",))]
