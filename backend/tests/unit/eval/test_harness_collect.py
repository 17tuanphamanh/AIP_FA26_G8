"""G2 mốc 2 — dựng `PredictionRecord` từ DB (`app.eval.collect`) theo luật của `predictions.py:19-33`.

`FakeDb` đọc đúng câu SQL `collect` phát ra (lọc step, chiếu khoá) → đột biến trên câu SQL (đổi step, bỏ khoá) làm test đỏ. Soát
thêm mọi câu SQL: chỉ đọc; `detail` chỉ ở dạng `detail->>'route'`/`'strategy'` (câu `step = 'B13/B14'`), `detail->>'turn'` (câu
`step = 'B11'`) và `detail->'grounding'->>'kb_gap'` (câu `step = 'B10'`, P6 22/10) — chốt 17/10 + Dương 18/10.
"""

import re
from typing import Any

import pytest
from app.eval.collect import AbortRun, MultiLeaf, RunMeta, collect
from app.eval.dataset import Scenario
from app.eval.predictions import PredictionRecord
from app.eval.stack import StackError
from tests.unit.eval.fake_stack import FakeDb, real_scenario

TID = "T-0001"
META = RunMeta(run_id="0123456789ab", strategy="hybrid", split="test")
START = "2026-10-19T10:00:00+07:00"  # giờ bắt đầu kịch bản — runner truyền (`Case.started_at`)


def scn(**gold: Any) -> Scenario:
    over: dict[str, Any] = {"expected_route": "HITL", "gold_doc_ids": ["kb-a"]}
    over.update(gold)
    return Scenario.model_validate(real_scenario("S1", family="F1", turns=["x"], **over))


def log4(db: FakeDb, route: str | None = "HITL", strategy: str | None = "hybrid", step: str = "B13/B14", **cols: Any) -> None:
    detail: dict[str, Any] = {"factors": {"SENTINEL_FACTOR": 1}, "thresholds": {"SENTINEL_TH": 0.5}}
    if route is not None:
        detail["route"] = route
    if strategy is not None:
        detail["strategy"] = strategy
    base: dict[str, Any] = {"decided_by": "llm", "raw_prob": 0.4, "calibrated_prob": None, "p_method": "self_report"}
    base.update(cols)
    db.log(TID, step, "risk_decided", detail, **base)


def full_db() -> FakeDb:
    """Lá đơn ý: hỏi lại 1 lần, B8 hai dòng, qua M5 (llm, HITL), có phiếu duyệt, đóng resolved."""
    db = FakeDb()
    db.add_ticket(TID, intent="vpn", final_state="S_RESOLVED", close_reason="resolved_user_confirmed", resolution_path="approved")
    db.log(TID, "B8", "retrieved", doc_ids=["kb-old"])
    db.log(TID, "B11", "asked", {"turn": 0, "missing": ["device_id"]})
    db.log(TID, "B8", "retrieved", doc_ids=["kb-a", "kb-b"])
    db.log(TID, "B11", "action_built", {"turn": 1})
    log4(db)
    db.approvals.append({"ticket_id": TID, "approval_id": "A1", "approver_id": "l1_01", "status": "approved"})
    return db


def test_collect_full_record() -> None:
    r = collect(full_db(), scn(), TID, META, started_at=START)
    assert isinstance(r, PredictionRecord)
    assert (r.run_id, r.strategy, r.split, r.scenario_id, r.family) == ("0123456789ab", "hybrid", "test", "S1", "F1")
    assert (r.ticket_id, r.parent_ticket_id) == (TID, None)
    assert (r.expected_route, r.route, r.decided_by, r.raw_prob, r.calibrated_prob, r.p_method) == (
        "HITL", "HITL", "llm", 0.4, None, "self_report")  # fmt: skip
    assert (r.final_state, r.exit_code, r.close_reason, r.resolution_path) == (
        "S_RESOLVED", None, "resolved_user_confirmed", "approved")  # fmt: skip
    assert r.has_approval is True
    assert r.clarification_turns == 1
    assert (r.intent, r.gold_intent) == ("vpn", "vpn")
    assert r.doc_ids == ("kb-a", "kb-b") and r.gold_doc_ids == ("kb-a",)
    assert (r.schema_version, r.run_started_at) == ("1.1", START)
    assert (r.fold, r.hidden_factor, r.in_business_hours) == (None,) * 3
    assert (r.kb_gap, r.m5_aborted) == (None, False)  # full_db không có dòng B10; có audit nhưng không có dòng lớp bọc lỗi


def test_collect_v11_unavailable_null() -> None:
    """V11-Q1/Q3/Q5: chưa có nguồn hợp lệ → `null` tường minh (KHÔNG False giả). Log 4 có khoá `kb_gap` trong `detail` KHÔNG phải nguồn
    (nguồn là B10 `detail.grounding.kb_gap`); câu SQL soát ở `test_sql_detail_keys_whitelist`."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    db.log(TID, "B13/B14", "risk_decided", {"route": "HITL", "strategy": "hybrid", "kb_gap": True},
           decided_by="llm", raw_prob=0.4, calibrated_prob=None, p_method="self_report")  # fmt: skip
    r = collect(db, scn(), TID, META, started_at=START)
    assert (r.fold, r.kb_gap, r.hidden_factor, r.in_business_hours) == (None,) * 4
    assert detail_violations(db.queries) == []


# ---- kb_gap (audit B10 detail.grounding.kb_gap, chỉ ca đi lớp LLM) -----------------------------------------------------------


def grounding(db: FakeDb, kb_gap: Any, *, event: str = "needs_action") -> None:
    db.log(TID, "B10", event, {"grounding": {"top_score": 0.2, "above_threshold": not kb_gap, "kb_gap": kb_gap}})


@pytest.mark.parametrize("value", [True, False])
def test_kb_gap_from_b10_grounding_for_llm_case(value: bool) -> None:
    db = full_db()
    grounding(db, value)
    r = collect(db, scn(), TID, META, started_at=START)
    assert r.decided_by == "llm" and r.kb_gap is value
    assert detail_violations(db.queries) == []


def test_kb_gap_last_valued_b10_row_wins_and_null_rows_skipped() -> None:
    db = full_db()
    grounding(db, True)
    grounding(db, False)
    db.log(TID, "B10", "other", {"need_type": "action"})  # dòng B10 không có grounding → bỏ qua
    assert collect(db, scn(), TID, META, started_at=START).kb_gap is False


def test_kb_gap_null_when_no_b10_grounding() -> None:
    db = full_db()
    db.log(TID, "B10", "other", {"need_type": "action"})
    assert collect(db, scn(), TID, META, started_at=START).kb_gap is None


def test_kb_gap_only_for_llm_decided_cases() -> None:
    """Ca do luật quyết (hoặc không tới M5) không mang `kb_gap` dù có dòng B10 grounding."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, decided_by="rule", raw_prob=None, p_method=None)
    grounding(db, True)
    r = collect(db, scn(), TID, META, started_at=START)
    assert r.decided_by == "rule" and r.kb_gap is None
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    r2 = collect(db, scn(), TID, META, started_at=START)
    assert r2.route is None and r2.kb_gap is None


def test_kb_gap_unexpected_value_raises() -> None:
    db = full_db()
    grounding(db, "maybe")
    with pytest.raises(ValueError, match="kb_gap"):
        collect(db, scn(), TID, META, started_at=START)


# ---- intent (tickets.intent → dự phòng audit B3) ----------------------------------------------------------------------------


def test_intent_from_ticket_does_not_query_b3() -> None:
    db = full_db()
    db.log(TID, "B3", "intent_classified", {}, intent="account")
    r = collect(db, scn(), TID, META, started_at=START)
    assert r.intent == "vpn"
    assert not any("step = 'B3'" in q for q in db.queries)


def test_intent_null_ticket_falls_back_to_last_b3_intent() -> None:
    db = full_db()
    db.tickets[TID]["intent"] = None
    db.log(TID, "B3", "intent_classified", {}, intent="account")
    db.log(TID, "B3", "intent_classified", {}, intent="software")
    db.log(TID, "B3", "classifier_unavailable", {})  # intent null → bỏ qua
    assert collect(db, scn(), TID, META, started_at=START).intent == "software"


def test_intent_missing_everywhere_is_null() -> None:
    db = full_db()
    db.tickets[TID]["intent"] = None
    db.log(TID, "B3", "classifier_unavailable", {})
    assert collect(db, scn(), TID, META, started_at=START).intent is None


# ---- m5_aborted (audit lớp bọc lỗi ở S_ASSESSING) ---------------------------------------------------------------------------


@pytest.mark.parametrize("event", ["turn_budget_exceeded", "unhandled_exception"])
def test_m5_aborted_true_for_boundary_event_at_assessing(event: str) -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]  # M5 bị ngắt: không có dòng điểm log 4
    db.log(TID, "b12_assess", event, {"node": "b12_assess"}, from_status="S_ASSESSING")  # step = tên node (boundary.py)
    r = collect(db, scn(), TID, META, started_at=START)
    assert r.route is None and r.m5_aborted is True


@pytest.mark.parametrize(
    ("step", "event", "from_status"),
    [
        ("B3", "unhandled_exception", "S_CLASSIFYING"),  # E9 tại B3: M5 chưa chạy
        ("B11", "turn_budget_exceeded", "S_CLARIFYING"),  # hết hạn lượt khi hỏi lại
        ("B12", "risk_decided", "S_ASSESSING"),  # đúng trạng thái nhưng KHÔNG phải sự kiện của lớp bọc lỗi
        ("B17", "unhandled_exception", "S_EXECUTING"),  # sau M5
    ],
)
def test_m5_aborted_false_for_other_audit_rows(step: str, event: str, from_status: str) -> None:
    db = full_db()
    db.log(TID, step, event, {}, from_status=from_status)
    assert collect(db, scn(), TID, META, started_at=START).m5_aborted is False


def test_m5_aborted_false_when_stuck_in_b11_with_null_final_state() -> None:
    db = FakeDb()
    db.add_ticket(TID, intent="vpn")  # final_state null: kẹt ở B11, không bao giờ tới M5
    db.log(TID, "B11", "asked", {"turn": 0}, from_status="S_CLARIFYING")
    r = collect(db, scn(), TID, META, started_at=START)
    assert (r.final_state, r.route, r.m5_aborted) == (None, None, False)


def test_m5_aborted_null_when_ticket_has_no_audit_rows() -> None:
    db = FakeDb()
    db.add_ticket(TID, intent="vpn")
    r = collect(db, scn(), TID, META, started_at=START)
    assert r.m5_aborted is None


def test_collect_run_started_at_passthrough() -> None:
    r = collect(full_db(), scn(), TID, META, started_at="2026-10-19T03:00:00.5+00:00")
    assert r.run_started_at == "2026-10-19T03:00:00.5+00:00"


def test_log4_step_filter() -> None:
    """Điểm log 4 = `B13/B14`; dòng `B12` (cùng node, KHÔNG phải log 4) bị bỏ."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, route="AUTO", step="B12")
    log4(db, route="ESCALATE_L2")
    assert collect(db, scn(), TID, META, started_at=START).route == "ESCALATE_L2"
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    r = collect(db, scn(), TID, META, started_at=START)
    assert r.route is None and r.decided_by is None


def test_log4_dup_same_route_keep_one() -> None:
    db = full_db()
    log4(db)
    assert collect(db, scn(), TID, META, started_at=START).route == "HITL"


def test_log4_dup_diff_route_raises() -> None:
    db = full_db()
    log4(db, route="AUTO")
    with pytest.raises(ValueError, match="route khác nhau") as e:
        collect(db, scn(), TID, META, started_at=START)
    assert not isinstance(e.value, AbortRun)


def test_strategy_mismatch_aborts() -> None:
    db = full_db()
    log4(db, strategy="llm_only")
    with pytest.raises(AbortRun) as e:
        collect(db, scn(), TID, META, started_at=START)
    assert e.value.reason == "strategy_mismatch"


def test_strategy_missing_key_aborts() -> None:
    """Khoá `strategy` ở log 4 chưa kiểm được trong code (plan G2 mục 1): thiếu khoá → dừng lượt, KHÔNG đoán tên khoá khác."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, strategy=None)
    with pytest.raises(AbortRun) as e:
        collect(db, scn(), TID, META, started_at=START)
    assert e.value.reason == "log4_missing_strategy"


def test_route_missing_key_aborts() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, route=None)
    with pytest.raises(AbortRun) as e:
        collect(db, scn(), TID, META, started_at=START)
    assert e.value.reason == "log4_missing_route"


def test_turns_max_formula() -> None:
    """`max(turn + (event == 'asked'))`: hai lần hỏi (turn 0, 1) → 2; dạng `max(turn)` sẽ ra 1."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B11"]
    db.log(TID, "B11", "asked", {"turn": 0})
    db.log(TID, "B11", "asked", {"turn": 1})
    assert collect(db, scn(), TID, META, started_at=START).clarification_turns == 2


def test_turns_skip_rows_without_turn() -> None:
    """Dòng B11 của `clarify_wait` (hết hạn / chặn injection) không có `detail.turn` → bỏ qua."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B11"]
    db.log(TID, "B11", "asked", {"turn": 0})
    db.log(TID, "B11", "clarify_expired", {})
    assert collect(db, scn(), TID, META, started_at=START).clarification_turns == 1


def test_turns_no_b11_zero() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B11"]
    assert collect(db, scn(), TID, META, started_at=START).clarification_turns == 0


def test_doc_ids_last_b8() -> None:
    """Dòng cuối theo `created_at` (không theo log_id)."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B8"]
    db.log(TID, "B8", "retrieved", doc_ids=["kb-late"], created_at="2026-10-19T10:00:59+07:00")
    db.log(TID, "B8", "retrieved", doc_ids=["kb-early"], created_at="2026-10-19T10:00:01+07:00")
    assert collect(db, scn(), TID, META, started_at=START).doc_ids == ("kb-late",)


def test_doc_ids_none_when_no_b8() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B8"]
    assert collect(db, scn(), TID, META, started_at=START).doc_ids is None


def test_route_none_no_risk_fields() -> None:
    db = FakeDb()
    db.add_ticket(TID, final_state="S_ESCALATED", exit_code="E2", resolution_path="escalated")
    r = collect(db, scn(), TID, META, started_at=START)
    assert (r.route, r.decided_by, r.raw_prob, r.calibrated_prob, r.p_method) == (None,) * 5
    assert r.has_approval is False and r.intent is None


def test_timeout_open_ticket_record() -> None:
    """Hết giờ: ticket còn mở → 4 trường điểm log 8 = None; route lấy nếu đã có log 4."""
    db = FakeDb()
    db.add_ticket(TID, intent="vpn")
    db.log(TID, "B11", "asked", {"turn": 0})
    r = collect(db, scn(), TID, META, started_at=START)
    assert (r.final_state, r.exit_code, r.close_reason, r.resolution_path) == (None,) * 4
    assert r.route is None and r.clarification_turns == 1


def test_calibrated_prob_passes_through() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, calibrated_prob=0.3)
    assert collect(db, scn(), TID, META, started_at=START).calibrated_prob == 0.3


def test_multi_leaf_raises() -> None:
    db = full_db()
    db.tickets[TID]["is_parent"] = True
    with pytest.raises(MultiLeaf):
        collect(db, scn(), TID, META, started_at=START)


def test_ticket_missing_raises() -> None:
    with pytest.raises(StackError):
        collect(FakeDb(), scn(), TID, META, started_at=START)


def test_collect_unlabeled_record() -> None:
    """Dữ liệu thật tới 25/10: `gold.expected_route = null` → bản ghi mang `expected_route = None` (đếm `unlabeled` ở runner)."""
    r = collect(full_db(), scn(expected_route=None), TID, META, started_at=START)
    assert r.expected_route is None and r.route == "HITL"
    assert PredictionRecord.model_validate_json(r.model_dump_json()) == r


def test_gold_intent_multi_none() -> None:
    r = collect(full_db(), scn(intents=["vpn", "account"]), TID, META, started_at=START)
    assert r.gold_intent is None


# ---- soát câu SQL ----------------------------------------------------------------------------------------------------

_DETAIL = re.compile(r"\bdetail\b((?:->'\w+')*->>'(\w+)')?")
_ALLOWED = {"B13/B14": {"route", "strategy"}, "B11": {"turn"}, "B10": {"grounding.kb_gap"}}


def detail_violations(queries: list[str]) -> list[str]:
    bad = []
    for q in queries:
        step = m.group(1) if (m := re.search(r"step = '([^']+)'", q)) else None
        for use in _DETAIL.finditer(q):
            path = ".".join(re.findall(r"'(\w+)'", use.group(1) or ""))  # detail->'a'->>'k' → "a.k"
            if use.group(2) is None or path not in _ALLOWED.get(step or "", set()):
                bad.append(f"{step}: {use.group(0)}")
    return bad


def test_sql_detail_keys_whitelist() -> None:
    db = full_db()
    grounding(db, False)
    collect(db, scn(), TID, META, started_at=START)
    assert db.queries, "không có câu SQL nào — soát rỗng không được tính là qua"
    assert any("detail->>'route'" in q for q in db.queries)  # đối chứng: soát có thấy khoá được phép
    assert any("detail->'grounding'->>'kb_gap'" in q for q in db.queries)
    assert detail_violations(db.queries) == []


def test_whitelist_catches_full_detail() -> None:
    """Đối chứng cho bộ soát: SELECT nguyên detail / khoá lạ / `turn` ở câu log 4 đều bị bắt."""
    assert detail_violations(["SELECT detail FROM audit_logs WHERE step = 'B13/B14'"])
    assert detail_violations(["SELECT detail->>'factors' FROM audit_logs WHERE step = 'B13/B14'"])
    assert detail_violations(["SELECT detail->>'turn' FROM audit_logs WHERE step = 'B13/B14'"])
    assert detail_violations(["SELECT detail->>'route' FROM audit_logs WHERE step = 'B11'"])
    assert detail_violations(["SELECT detail->'grounding'->>'top_score' FROM audit_logs WHERE step = 'B10'"])
    assert detail_violations(["SELECT detail->'grounding' FROM audit_logs WHERE step = 'B10'"])
    assert detail_violations(["SELECT detail->'grounding'->>'kb_gap' FROM audit_logs WHERE step = 'B13/B14'"])
    assert detail_violations(["SELECT detail->'grounding'->>'kb_gap' FROM audit_logs WHERE step = 'B10'"]) == []


def test_sql_read_only_statements() -> None:
    db = full_db()
    collect(db, scn(), TID, META, started_at=START)
    for q in db.queries:
        assert q.lstrip().upper().startswith("SELECT")
        assert not re.search(r"\b(UPDATE|INSERT|DELETE|ALTER|DROP|TRUNCATE|GRANT)\b", q, re.IGNORECASE)
