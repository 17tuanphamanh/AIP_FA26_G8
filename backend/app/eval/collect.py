"""DB → `PredictionRecord` (hợp đồng v1.1, `predictions.py`) cho MỘT lá của harness G2. Chỉ đọc.

Câu SQL (mỗi câu một bảng / một step — `detail` chỉ đọc đúng khoá được phép, KHÔNG SELECT nguyên `detail`):
- `tickets`: cột điểm log 8 + `is_parent` (cha → `MultiLeaf`, không ghi bản ghi — `load_predictions` từ chối lá nhiều ý).
- Điểm log 4 = `step = 'B13/B14'` (KHÔNG phải `'B12'`): `detail->>'route'`, `detail->>'strategy'` (chốt 17/10) + cột rủi ro.
  Nhiều dòng cùng route → giữ một; khác route → `ValueError`. Thiếu khoá `route`/`strategy`, hoặc `strategy` ≠ manifest → `AbortRun`
  (dừng CẢ lượt, mã 2). Khoá `strategy` chưa kiểm được trong code node B12 (plan G2 mục 1) — thiếu thì dừng, không đoán tên khác.
- `step = 'B11'`: CHỈ `detail->>'turn'` + `event` (Dương 18/10, chờ Tuấn Anh xác nhận G2-Q14); `clarification_turns =
  max(turn + (event == 'asked'))` tính ở Python, bỏ dòng không có `turn`; không dòng nào → 0.
- `step = 'B8'`: cột `doc_ids`, dòng cuối theo `created_at` (hoà → `log_id`); không có → `None`.
- `approvals`: có dòng nào của lá → `has_approval`.
- v1.1: `run_started_at` = giờ bắt đầu kịch bản do runner truyền vào; `UNAVAILABLE` (chưa có nguồn hợp lệ — V11-Q1/Q3/Q5) →
  `null` tường minh.
- `kb_gap` (P6 22/10): CHỈ ca đi lớp LLM (`decided_by = llm`) — `step = 'B10'`, khoá `detail.grounding.kb_gap` (dòng cuối có giá trị);
  không có → `null` (runner đếm `kb_gap_missing`).
- `intent`: `tickets.intent` null → dòng `step = 'B3'` cuối có cột `intent` khác null; không có → `null` (runner đếm `intent_missing`).
- `m5_aborted` (P8 §5.4): có dòng `audit_logs` `event ∈ {turn_budget_exceeded, unhandled_exception}` (lớp bọc lỗi, `graph/boundary.py`)
  với `from_status = 'S_ASSESSING'` → `True`; ticket có audit mà không có dòng đó → `False`; ticket không có dòng audit nào → `null`
  (runner đếm `m5_aborted_unknown`). Chỉ đọc cột `event`, `from_status`, không đọc `detail`.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.domain.states import S_ASSESSING
from app.eval.dataset import Scenario
from app.eval.predictions import SCHEMA_VERSION, PredictionRecord, Split, Strategy
from app.eval.stack import Sql, StackError, quote

LOG4_STEP = "B13/B14"
LOG4_FIELDS = ("'route', detail->>'route', 'strategy', detail->>'strategy', 'decided_by', decided_by, 'raw_prob', raw_prob, "
               "'calibrated_prob', calibrated_prob, 'p_method', p_method")  # fmt: skip
B11_FIELDS = "'turn', detail->>'turn', 'event', event"
B8_FIELDS = "'doc_ids', doc_ids, 'created_at', created_at, 'log_id', log_id"
TICKET_FIELDS = ("'ticket_id', ticket_id, 'parent_ticket_id', parent_ticket_id, 'is_parent', is_parent, 'intent', intent, "
                 "'final_state', final_state, 'exit_code', exit_code, 'close_reason', close_reason, "
                 "'resolution_path', resolution_path")  # fmt: skip
RISK = ("decided_by", "raw_prob", "calibrated_prob", "p_method")
UNAVAILABLE = ("fold", "hidden_factor", "in_business_hours")  # v1.1 chưa có nguồn → null (manifest predictions_unavailable)
B10_FIELDS = "'kb_gap', detail->'grounding'->>'kb_gap'"
B3_FIELDS = "'intent', intent"
BOUNDARY_EVENTS = ("turn_budget_exceeded", "unhandled_exception")  # graph/boundary.py — lớp bọc lỗi của node
M5_STATUS = S_ASSESSING  # M5 (b12_assess) chạy khi ticket ở trạng thái này

type AbortReason = Literal["strategy_mismatch", "log4_missing_strategy", "log4_missing_route"]


class AbortRun(Exception):
    """Lỗi hệ thống của CẢ lượt (không phải của một ca) → runner dừng, mã 2, không ghi predictions. `reason` là mã cố định."""

    def __init__(self, reason: AbortReason) -> None:
        super().__init__(reason)
        self.reason = reason


class MultiLeaf(Exception):
    """Ticket là cha (nhiều ý) — hợp đồng v1 chưa nhận lá nhiều ý (Q-T29-1)."""


@dataclass(frozen=True)
class RunMeta:
    run_id: str
    strategy: Strategy
    split: Split


def _audit(sql: Sql, ticket_id: str, step: str, fields: str) -> list[dict[str, Any]]:
    return list(sql(
        f"SELECT coalesce(json_agg(json_build_object({fields}) ORDER BY log_id), '[]') "
        f"FROM audit_logs WHERE ticket_id = {quote(ticket_id)} AND step = '{step}'"
    ))  # fmt: skip


def _log4(sql: Sql, ticket_id: str, strategy: str) -> dict[str, Any]:
    rows = _audit(sql, ticket_id, LOG4_STEP, LOG4_FIELDS)
    if not rows:
        return {"route": None, **dict.fromkeys(RISK)}
    for r in rows:
        if r["route"] is None:
            raise AbortRun("log4_missing_route")
        if r["strategy"] is None:
            raise AbortRun("log4_missing_strategy")
        if r["strategy"] != strategy:
            raise AbortRun("strategy_mismatch")
    if len({r["route"] for r in rows}) > 1:
        raise ValueError("điểm log 4: nhiều dòng với route khác nhau (một lá chỉ qua b12_assess một lần)")
    first = rows[0]
    return {"route": first["route"], **{k: first[k] for k in RISK}}


def _clarification_turns(sql: Sql, ticket_id: str) -> int:
    best = 0
    for r in _audit(sql, ticket_id, "B11", B11_FIELDS):
        if r["turn"] is None:  # dòng của clarify_wait (hết hạn / chặn injection) — không có detail.turn
            continue
        best = max(best, int(r["turn"]) + (r["event"] == "asked"))
    return best


def _doc_ids(sql: Sql, ticket_id: str) -> list[str] | None:
    rows = _audit(sql, ticket_id, "B8", B8_FIELDS)
    if not rows:
        return None
    last = max(rows, key=lambda r: (datetime.fromisoformat(r["created_at"]), r["log_id"]))
    doc_ids = last["doc_ids"]
    return None if doc_ids is None else list(doc_ids)


def _kb_gap(sql: Sql, ticket_id: str) -> bool | None:
    """Audit B10 `detail.grounding.kb_gap` (dòng cuối có giá trị). `->>` trả chuỗi `true`/`false`; khác → `ValueError`."""
    value: str | None = None
    for r in _audit(sql, ticket_id, "B10", B10_FIELDS):
        if r["kb_gap"] is not None:
            value = r["kb_gap"]
    if value is None:
        return None
    if value not in ("true", "false"):
        raise ValueError("audit B10 detail.grounding.kb_gap: không phải true/false")
    return value == "true"


def _intent_from_b3(sql: Sql, ticket_id: str) -> str | None:
    """Dòng B3 (phân loại) cuối có cột `intent` khác null."""
    value: str | None = None
    for r in _audit(sql, ticket_id, "B3", B3_FIELDS):
        if r["intent"] is not None:
            value = r["intent"]
    return value


def _m5_aborted(sql: Sql, ticket_id: str) -> bool | None:
    events = ", ".join(f"'{e}'" for e in BOUNDARY_EVENTS)
    row = sql(
        "SELECT json_build_object('n', count(*), "
        f"'aborted', coalesce(bool_or(event IN ({events}) AND from_status = '{M5_STATUS}'), false)) "
        f"FROM audit_logs WHERE ticket_id = {quote(ticket_id)}"
    )  # fmt: skip
    if row is None or int(row["n"]) == 0:
        return None
    return bool(row["aborted"])


def _has_approval(sql: Sql, ticket_id: str) -> bool:
    return bool(sql(f"SELECT to_json(EXISTS (SELECT 1 FROM approvals WHERE ticket_id = {quote(ticket_id)}))"))


def collect(sql: Sql, scenario: Scenario, ticket_id: str, meta: RunMeta, *, started_at: str) -> PredictionRecord:
    ticket = sql(f"SELECT json_build_object({TICKET_FIELDS}) FROM tickets WHERE ticket_id = {quote(ticket_id)}")
    if ticket is None:
        raise StackError("không có dòng tickets của ticket vừa tạo")
    if ticket["is_parent"]:
        raise MultiLeaf
    log4 = _log4(sql, ticket_id, meta.strategy)
    intent = ticket["intent"] if ticket["intent"] is not None else _intent_from_b3(sql, ticket_id)
    record: dict[str, Any] = {
        "run_id": meta.run_id, "strategy": meta.strategy, "split": meta.split,
        "scenario_id": scenario.id, "family": scenario.family,
        "ticket_id": ticket["ticket_id"], "parent_ticket_id": ticket["parent_ticket_id"],
        "expected_route": scenario.gold.expected_route,
        **log4,
        **{k: ticket[k] for k in ("final_state", "exit_code", "close_reason", "resolution_path")}, "intent": intent,
        "has_approval": _has_approval(sql, ticket_id),
        "clarification_turns": _clarification_turns(sql, ticket_id),
        "gold_intent": scenario.gold_intent,
        "doc_ids": _doc_ids(sql, ticket_id), "gold_doc_ids": list(scenario.gold.gold_doc_ids),
        "schema_version": SCHEMA_VERSION, "run_started_at": started_at,
        **dict.fromkeys(UNAVAILABLE),
        "kb_gap": _kb_gap(sql, ticket_id) if log4["decided_by"] == "llm" else None,
        "m5_aborted": _m5_aborted(sql, ticket_id),
    }  # fmt: skip
    # qua JSON: `strict=True` từ chối list cho trường tuple (predictions.py:32-33)
    return PredictionRecord.model_validate_json(json.dumps(record))
