"""G2 mốc 2 — dựng `PredictionRecord` từ DB (`app.eval.collect`) theo luật của `predictions.py:19-33`.

`FakeDb` đọc đúng câu SQL `collect` phát ra (lọc step, chiếu khoá) → đột biến trên câu SQL (đổi step, bỏ khoá) làm test đỏ. Soát
thêm mọi câu SQL: chỉ đọc; `detail` chỉ ở dạng `detail->>'route'`/`'strategy'` (câu `step = 'B13/B14'`) và `detail->>'turn'` (câu
`step = 'B11'`) — chốt 17/10 + Dương 18/10.
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
    r = collect(full_db(), scn(), TID, META)
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


def test_log4_step_filter() -> None:
    """Điểm log 4 = `B13/B14`; dòng `B12` (cùng node, KHÔNG phải log 4) bị bỏ."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, route="AUTO", step="B12")
    log4(db, route="ESCALATE_L2")
    assert collect(db, scn(), TID, META).route == "ESCALATE_L2"
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    r = collect(db, scn(), TID, META)
    assert r.route is None and r.decided_by is None


def test_log4_dup_same_route_keep_one() -> None:
    db = full_db()
    log4(db)
    assert collect(db, scn(), TID, META).route == "HITL"


def test_log4_dup_diff_route_raises() -> None:
    db = full_db()
    log4(db, route="AUTO")
    with pytest.raises(ValueError, match="route khác nhau") as e:
        collect(db, scn(), TID, META)
    assert not isinstance(e.value, AbortRun)


def test_strategy_mismatch_aborts() -> None:
    db = full_db()
    log4(db, strategy="llm_only")
    with pytest.raises(AbortRun) as e:
        collect(db, scn(), TID, META)
    assert e.value.reason == "strategy_mismatch"


def test_strategy_missing_key_aborts() -> None:
    """Khoá `strategy` ở log 4 chưa kiểm được trong code (plan G2 mục 1): thiếu khoá → dừng lượt, KHÔNG đoán tên khoá khác."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, strategy=None)
    with pytest.raises(AbortRun) as e:
        collect(db, scn(), TID, META)
    assert e.value.reason == "log4_missing_strategy"


def test_route_missing_key_aborts() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, route=None)
    with pytest.raises(AbortRun) as e:
        collect(db, scn(), TID, META)
    assert e.value.reason == "log4_missing_route"


def test_turns_max_formula() -> None:
    """`max(turn + (event == 'asked'))`: hai lần hỏi (turn 0, 1) → 2; dạng `max(turn)` sẽ ra 1."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B11"]
    db.log(TID, "B11", "asked", {"turn": 0})
    db.log(TID, "B11", "asked", {"turn": 1})
    assert collect(db, scn(), TID, META).clarification_turns == 2


def test_turns_skip_rows_without_turn() -> None:
    """Dòng B11 của `clarify_wait` (hết hạn / chặn injection) không có `detail.turn` → bỏ qua."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B11"]
    db.log(TID, "B11", "asked", {"turn": 0})
    db.log(TID, "B11", "clarify_expired", {})
    assert collect(db, scn(), TID, META).clarification_turns == 1


def test_turns_no_b11_zero() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B11"]
    assert collect(db, scn(), TID, META).clarification_turns == 0


def test_doc_ids_last_b8() -> None:
    """Dòng cuối theo `created_at` (không theo log_id)."""
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B8"]
    db.log(TID, "B8", "retrieved", doc_ids=["kb-late"], created_at="2026-10-19T10:00:59+07:00")
    db.log(TID, "B8", "retrieved", doc_ids=["kb-early"], created_at="2026-10-19T10:00:01+07:00")
    assert collect(db, scn(), TID, META).doc_ids == ("kb-late",)


def test_doc_ids_none_when_no_b8() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B8"]
    assert collect(db, scn(), TID, META).doc_ids is None


def test_route_none_no_risk_fields() -> None:
    db = FakeDb()
    db.add_ticket(TID, final_state="S_ESCALATED", exit_code="E2", resolution_path="escalated")
    r = collect(db, scn(), TID, META)
    assert (r.route, r.decided_by, r.raw_prob, r.calibrated_prob, r.p_method) == (None,) * 5
    assert r.has_approval is False and r.intent is None


def test_timeout_open_ticket_record() -> None:
    """Hết giờ: ticket còn mở → 4 trường điểm log 8 = None; route lấy nếu đã có log 4."""
    db = FakeDb()
    db.add_ticket(TID, intent="vpn")
    db.log(TID, "B11", "asked", {"turn": 0})
    r = collect(db, scn(), TID, META)
    assert (r.final_state, r.exit_code, r.close_reason, r.resolution_path) == (None,) * 4
    assert r.route is None and r.clarification_turns == 1


def test_calibrated_prob_passes_through() -> None:
    db = full_db()
    db.audit = [a for a in db.audit if a["step"] != "B13/B14"]
    log4(db, calibrated_prob=0.3)
    assert collect(db, scn(), TID, META).calibrated_prob == 0.3


def test_multi_leaf_raises() -> None:
    db = full_db()
    db.tickets[TID]["is_parent"] = True
    with pytest.raises(MultiLeaf):
        collect(db, scn(), TID, META)


def test_ticket_missing_raises() -> None:
    with pytest.raises(StackError):
        collect(FakeDb(), scn(), TID, META)


def test_collect_unlabeled_record() -> None:
    """Dữ liệu thật tới 25/10: `gold.expected_route = null` → bản ghi mang `expected_route = None` (đếm `unlabeled` ở runner)."""
    r = collect(full_db(), scn(expected_route=None), TID, META)
    assert r.expected_route is None and r.route == "HITL"
    assert PredictionRecord.model_validate_json(r.model_dump_json()) == r


def test_gold_intent_multi_none() -> None:
    r = collect(full_db(), scn(intents=["vpn", "account"]), TID, META)
    assert r.gold_intent is None


# ---- soát câu SQL ----------------------------------------------------------------------------------------------------

_DETAIL = re.compile(r"\bdetail\b(->>'(\w+)')?")
_ALLOWED = {"B13/B14": {"route", "strategy"}, "B11": {"turn"}}


def detail_violations(queries: list[str]) -> list[str]:
    bad = []
    for q in queries:
        step = m.group(1) if (m := re.search(r"step = '([^']+)'", q)) else None
        for use in _DETAIL.finditer(q):
            if use.group(2) is None or use.group(2) not in _ALLOWED.get(step or "", set()):
                bad.append(f"{step}: {use.group(0)}")
    return bad


def test_sql_detail_keys_whitelist() -> None:
    db = full_db()
    collect(db, scn(), TID, META)
    assert db.queries, "không có câu SQL nào — soát rỗng không được tính là qua"
    assert any("detail->>'route'" in q for q in db.queries)  # đối chứng: soát có thấy khoá được phép
    assert detail_violations(db.queries) == []


def test_whitelist_catches_full_detail() -> None:
    """Đối chứng cho bộ soát: SELECT nguyên detail / khoá lạ / `turn` ở câu log 4 đều bị bắt."""
    assert detail_violations(["SELECT detail FROM audit_logs WHERE step = 'B13/B14'"])
    assert detail_violations(["SELECT detail->>'factors' FROM audit_logs WHERE step = 'B13/B14'"])
    assert detail_violations(["SELECT detail->>'turn' FROM audit_logs WHERE step = 'B13/B14'"])
    assert detail_violations(["SELECT detail->>'route' FROM audit_logs WHERE step = 'B11'"])


def test_sql_read_only_statements() -> None:
    db = full_db()
    collect(db, scn(), TID, META)
    for q in db.queries:
        assert q.lstrip().upper().startswith("SELECT")
        assert not re.search(r"\b(UPDATE|INSERT|DELETE|ALTER|DROP|TRUNCATE|GRANT)\b", q, re.IGNORECASE)
