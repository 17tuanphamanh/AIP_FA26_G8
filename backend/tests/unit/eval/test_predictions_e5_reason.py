"""M2 (ĐP 08/11): tách `policy_deny` khỏi `llm_layer_disabled` KHÔNG đổi hình dạng `predictions.jsonl`.

- Hợp đồng v1.1 không có trường lý do chuyển (`test_predictions.test_fields_exact` ghim tập trường; ở đây ghim riêng phần M2).
- Dòng điểm log 4 (`step = 'B13/B14'`) của ca deny và ca lớp AI lỗi vẫn có đủ khoá `detail` mà `collect.LOG4_FIELDS` đọc; giá trị
  `route`/`strategy` như trước, lý do mới chỉ nằm ở `detail.escalation_reason_detail` (collect không đọc).
"""

import re

import pytest
from app.eval.collect import LOG4_FIELDS, LOG4_STEP
from app.eval.predictions import PredictionRecord
from app.graph.nodes import b12_assess
from app.risk.models import RuleVerdict
from tests.unit.test_b12_assess import _action, _node, _state

DETAIL_KEYS_READ = frozenset(re.findall(r"detail->>'(\w+)'", LOG4_FIELDS))


def test_prediction_record_has_no_reason_field() -> None:
    assert not {"reason_detail", "escalation_reason_detail"} & set(PredictionRecord.model_fields)
    assert DETAIL_KEYS_READ == {"route", "strategy", "kb_gap"}


@pytest.mark.asyncio
async def test_log4_row_of_deny_still_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = RuleVerdict(matched=True, decision="deny", rule_id="R12", all_matched=["R12"], description="Cấm")
    monkeypatch.setattr(b12_assess, "evaluate", lambda action, ctx: verdict)
    _, h, _ = await _node(_state())
    [row] = [r for r in h.audit.rows if r["step"] == LOG4_STEP]
    assert (row["detail"]["route"], row["detail"]["strategy"], row["decided_by"]) == ("ESCALATE_L2", "hybrid", "rule")
    assert {"route", "strategy"} <= set(row["detail"]) and "kb_gap" not in row["detail"]  # kb_gap chỉ ca LLM, như trước


@pytest.mark.asyncio
async def test_log4_row_of_llm_down_still_readable() -> None:
    _, h, _ = await _node(_state(intended_action=_action(owner=False)))
    [row] = [r for r in h.audit.rows if r["step"] == LOG4_STEP]
    assert (row["event"], row["detail"]["route"], row["detail"]["strategy"], row["decided_by"]) == (
        "llm_layer_disabled", "ESCALATE_L2", "hybrid", "llm")
