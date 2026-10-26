"""`audit_check` soát dòng `B13/B14 llm_layer_disabled` (đường fail-closed khi estimator lỗi) như điểm 4 — nợ ca (b) của gói tuần 8 (D-67).

Dòng mẫu sinh từ graph THẬT (`test_d67_hybrid_guarded_graph._graph`: hybrid_guarded lúc vận hành, luật R20 allow khớp, LLM mất kết
nối) — không dựng tay. Đủ → []; thiếu từng trường bắt buộc / khoá `detail.all_matched` → báo đúng trường đó; sai giá trị `decided_by`,
`exit_code`, `detail.route` → báo đúng trường đó; NULL `policy_decision`/`matched_rule_id`/`raw_prob`/`p_method` và vắng
`detail.strategy` hợp lệ CHỈ ở dòng này; dòng `risk_decided` không bị nới (đối chứng).
"""

import copy
from typing import Any

import pytest
import pytest_asyncio
from app.audit.check import LLM_DOWN_KEY, POINT4_KEY, Missing, required
from app.llm.providers.scripted import Unavailable
from tests.unit.test_audit_check import P4, _with
from tests.unit.test_audit_check import T as T_OLD
from tests.unit.test_d67_hybrid_guarded_graph import TRONG_GIO, _always, _graph

T = "t1"
REQUIRED = ("decided_by", "risk_level", "reason", "exit_code", "detail.route", "detail.policy_sha256", "detail.estimator_error")
VALUES = {"decided_by": "rule", "exit_code": "E9", "detail.route": "AUTO"}  # sai giá trị → báo đúng trường


@pytest_asyncio.fixture
async def rows() -> list[dict[str, Any]]:
    h, _, _ = await _graph(TRONG_GIO, _always(Unavailable()))
    return [{"log_id": i + 1, **copy.deepcopy(r)} for i, r in enumerate(r for r in h.audit.rows if r["ticket_id"] == T)]


def _down(rows: list[dict[str, Any]]) -> dict[str, Any]:
    [row] = [r for r in rows if (r["step"], r["event"]) == LLM_DOWN_KEY]
    return row


def _set(row: dict[str, Any], field: str, value: Any) -> dict[str, Any]:
    out = copy.deepcopy(row)
    if field.startswith("detail."):
        if value is _DROP:
            del out["detail"][field.removeprefix("detail.")]
        else:
            out["detail"][field.removeprefix("detail.")] = value
    else:
        out[field] = None if value is _DROP else value
    return out


_DROP = object()


def test_keys() -> None:
    assert LLM_DOWN_KEY == ("B13/B14", "llm_layer_disabled")
    assert POINT4_KEY == ("B13/B14", "risk_decided")  # không đổi


@pytest.mark.asyncio
async def test_real_row_complete_and_whole_ticket_ok(rows: list[dict[str, Any]]) -> None:
    row = _down(rows)
    assert (row["decided_by"], row["exit_code"], row["detail"]["route"]) == ("llm", "E5", "ESCALATE_L2")
    assert (row.get("policy_decision"), row.get("matched_rule_id"), row.get("raw_prob"), row.get("p_method")) == (None,) * 4
    assert required(T, [row], final_state=None) == []
    assert required(T, rows, final_state="S_ESCALATED") == []  # cả ticket (điểm 1–8)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", REQUIRED)
async def test_each_required_field_missing_is_reported(rows: list[dict[str, Any]], field: str) -> None:
    row = _down(rows)
    assert required(T, [_set(row, field, _DROP)], final_state=None) == [Missing(T, 4, row["log_id"], (field,))]


@pytest.mark.asyncio
async def test_all_matched_key_required(rows: list[dict[str, Any]]) -> None:
    row = _down(rows)
    assert required(T, [_set(row, "detail.all_matched", _DROP)], final_state=None) == [
        Missing(T, 4, row["log_id"], ("detail.all_matched",))]
    assert required(T, [_set(row, "detail.all_matched", [])], final_state=None) == []  # rỗng vẫn hợp lệ (khoá có)


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), list(VALUES.items()))
async def test_wrong_value_on_fail_closed_fields_is_reported(rows: list[dict[str, Any]], field: str, value: str) -> None:
    row = _down(rows)
    assert required(T, [_set(row, field, value)], final_state=None) == [Missing(T, 4, row["log_id"], (field,))]


@pytest.mark.asyncio
async def test_all_missing_in_contract_order(rows: list[dict[str, Any]]) -> None:
    row = _down(rows)
    for field in (*REQUIRED, "detail.all_matched"):
        row = _set(row, field, _DROP)
    assert required(T, [row], final_state=None) == [Missing(T, 4, row["log_id"], (*REQUIRED, "detail.all_matched"))]


@pytest.mark.asyncio
async def test_strategy_not_required_and_nullables_ok(rows: list[dict[str, Any]]) -> None:
    """Dòng vận hành trước D-67 không có `detail.strategy` → vẫn đạt; NULL rule/xác suất hợp lệ chỉ ở dòng này."""
    row = _set(_down(rows), "detail.strategy", _DROP)
    assert required(T, [row], final_state=None) == []


def test_risk_decided_not_loosened() -> None:
    """Đối chứng: dòng `risk_decided` luật mà `policy_decision` NULL vẫn bị báo thiếu như trước (nhánh mới không chạm `_point4_need`)."""
    row = _with(P4, "policy_decision", None)
    assert required(T_OLD, [row], final_state=None) == [Missing(T_OLD, 4, row["log_id"], ("policy_decision",))]
