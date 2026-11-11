"""`app.audit.check` (P5 — `scripts/audit_check.py`) phần THUẦN, không DB. Phase 4 chặng 4d DỪNG 1, viết TỪ ĐẶC TẢ trước thân code:
phase4 mục 7.1 P5, 7.2; PLAN-4d mục 2.1 (`app/audit/check.py`), mục 3 (a1–a6), mục 4 "Bảng điểm cho Q-4d-1 phương án A" (ĐÃ CHỐT, mục 9),
TQ-5…TQ-8.

- a1: `required` — với từng điểm 1–8: dòng ĐỦ → 0; xoá từng trường bắt buộc → đúng `Missing(ticket, point, log_id, fields)` (cột
  tên trần, khoá detail `detail.<khoá>`, lồng `detail.grounding.top_score`).
- a2: điểm áp dụng theo dòng có mặt; điểm 8 chỉ khi `final_state` có; "(có khoá)" nhận giá trị None/rỗng/False, "≠ null" thì không.
- a3: quét bí mật — mỗi luật `kind="secret"` của `config/privacy_patterns.json` + canary, trong cột text và lá JSON lồng; MỌI cột
  chuỗi/JSON của `AuditLog` (liệt kê từ kiểu cột của model — không viết tay).
- a4: bản đã che, hash hex 64, mã máy → 0 trúng (không dùng luật `entropy` — TQ-7).
- a5: `render` (bảng, dòng bí mật, KẾT LUẬN) + `main` tham số sai → 2; đầu ra không chứa giá trị bí mật/canary. (`main` có DB → PG.)
- a6: `scan_log` — trúng có số dòng (từ 1), `ticket_id` None, không mang giá trị.
"""

import copy
import dataclasses
import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.audit.check import (
    Missing,
    Report,
    SecretHit,
    SecretScanner,
    main,
    render,
    required,
    scan_log,
    scan_rows,
)
from app.db.models import AuditLog
from app.settings import Settings
from sqlalchemy import JSON, String

T = "tk-a"
T0 = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
CONFIG_DIR = Settings(_env_file=None).config_dir  # type: ignore[call-arg]
MASK = "[BÍ_MẬT_ĐÃ_ẨN]"
HEX64 = hashlib.sha256(b"x").hexdigest()
_CANARY_PARTS = ("Canary#4d", "audit", "q7")
CANARY = "-".join(_CANARY_PARTS)  # ghép lúc chạy (gitleaks)
# Ghép lúc chạy — viết liền thì gitleaks coi là khoá thật.
_API_KEY_PARTS = ("sk", "Ab3dEf6hIj9kLm2nOp")
SAMPLES: dict[str, str] = {
    "pem": "\n".join(("-----BEGIN " + "CERTIFICATE-----", "MIIBszCCAVmgAwIBAgIUa1b2c3", "-----END " + "CERTIFICATE-----")),
    "jwt": "token " + ".".join(("eyJ" + "hbGci0x", "eyJ" + "zdWIi0y", "c2lnbm" + "F0dXJl")),
    "api_key": "khoá " + "-".join(_API_KEY_PARTS),
    "password": "mật khẩu là " + "Tr0ub" + "4dor99",
    "otp": "mã OTP: " + "48" + "2913",
}
TEXT_COLUMNS = sorted(c.name for c in AuditLog.__table__.columns if isinstance(c.type, String) and c.name != "ticket_id")
JSON_COLUMNS = sorted(c.name for c in AuditLog.__table__.columns if isinstance(c.type, JSON))


def _scanner(*canaries: str) -> SecretScanner:
    return SecretScanner.from_config(CONFIG_DIR, canaries=canaries)


def _row(log_id: int, step: str, event: str, detail: dict[str, Any] | None = None, **cols: Any) -> dict[str, Any]:
    return {"log_id": log_id, "ticket_id": T, "step": step, "event": event, "detail": detail or {}, **cols}


# ---- dòng ĐỦ cho từng điểm (bảng mục 4 PLAN-4d) ------------------------------------------------------------------------------------

P1_B3 = _row(1, "B3", "intent_classified", {"layer": "model", "dropped_slot_keys": [], "intent": "vpn", "confidence": 0.92},
             intent="vpn")  # fmt: skip
P1_B4 = _row(2, "B4", "intent_low_confidence", {"layer": "llm", "dropped_slot_keys": ["device_registered"], "intent": "vpn",
                                                "confidence": 0.41})  # fmt: skip
P1_B4_OOS = _row(3, "B4", "intent_out_of_scope", {"layer": "model", "dropped_slot_keys": [], "intent": None, "confidence": None})
P1_B4_MULTI = _row(4, "B4", "multi_intent_not_enabled", {"layer": "llm", "dropped_slot_keys": []})
# D-84: dòng B4 thật của `b03_classify._reverse_action` (intent/confidence None — rẽ trước khi chọn ý)
P1_B4_REVERSE = _row(4, "B4", "reverse_action_requested", {"layer": "llm", "dropped_slot_keys": [], "intent": None, "confidence": None,
                                                           "reverse_action": "compromised"})  # fmt: skip
P2_B6 = _row(5, "B6", "diagnosed", {"tools_called": ["vpn_status"], "facts": {"cert_status": "expired"}, "tool_retry_count": 0})
P2_B7 = _row(6, "B7", "facts_merged", {"tools_called": [], "facts": {}, "tool_retry_count": 1})
P3_RETRIEVED = _row(7, "B8", "retrieved", {"query": "gia hạn vpn", "top_score": 0.83}, kb_version=HEX64)
P3_ERROR = _row(8, "B8", "retrieval_error", {"query": "gia hạn vpn", "error_stage": "search"}, kb_version=HEX64)
P3_ERROR_ALIAS = _row(9, "B8", "retrieval_error", {"query": "gia hạn vpn", "error_stage": "alias"})
P3_B9 = _row(10, "B9", "no_evidence", {"grounding": {"top_score": 0.12}}, kb_version=HEX64)
P4 = _row(11, "B13/B14", "risk_decided", {"route": "HITL", "policy_sha256": HEX64}, decided_by="rule",
          policy_decision="approval_required", risk_level="medium", reason="R19")  # fmt: skip
P5 = _row(12, "B15", "queued", {"choice_reason": "primary"}, approver_id="l1_01", deadline=T0 + timedelta(minutes=30),
          conflict_detected=False, action_plan_hash=HEX64)  # fmt: skip
P6_APPROVED = _row(13, "B16", "approved", {"decided_without_view": False, "decided_as": "primary"}, approval_result="approved",
                   response_time_seconds=42.0)  # fmt: skip
P6_REJECTED = _row(14, "B16", "rejected", {"decided_without_view": True, "decided_as": "backup"}, approval_result="rejected",
                   response_time_seconds=0.0, note="không đủ lý do")  # fmt: skip
P6_TIMEOUT = _row(15, "B16", "approval_timeout", {"decided_without_view": True}, approval_result="timeout")
P7_OK = _row(16, "B18", "executed_ok", {"success": True, "write_calls": 1, "action_plan_hash_matched": True})
P7_FAILED = _row(17, "B17", "exec_failed", {"success": False, "write_calls": 1, "action_plan_hash_matched": True})
P7_INTERRUPTED = _row(18, "B17", "exec_interrupted", {"success": None, "write_calls": 0, "action_plan_hash_matched": True})
P8 = _row(19, "B20", "closed", final_state="S_RESOLVED", close_reason="resolved_user_confirmed")

FULL = [P1_B3, P1_B4, P1_B4_OOS, P1_B4_MULTI, P2_B6, P2_B7, P3_RETRIEVED, P3_ERROR, P3_ERROR_ALIAS, P3_B9, P4, P5, P6_APPROVED,
        P6_REJECTED, P6_TIMEOUT, P7_OK, P7_FAILED, P7_INTERRUPTED, P8]  # fmt: skip


def _without(row: dict[str, Any], field: str) -> dict[str, Any]:
    """Bỏ một trường bắt buộc: cột (`approver_id`) hoặc khoá detail (`detail.x`, lồng `detail.grounding.top_score`)."""
    out = copy.deepcopy(row)
    if not field.startswith("detail."):
        out.pop(field, None)
        return out
    node = out["detail"]
    *path, last = field.split(".")[1:]
    for part in path:
        node = node[part]
    del node[last]
    return out


def _with(row: dict[str, Any], field: str, value: Any) -> dict[str, Any]:
    out = copy.deepcopy(row)
    if not field.startswith("detail."):
        out[field] = value
        return out
    node = out["detail"]
    *path, last = field.split(".")[1:]
    for part in path:
        node = node[part]
    node[last] = value
    return out


# ---- a1: dòng đủ → 0; xoá từng trường bắt buộc → đúng Missing ---------------------------------------------------------------------


def test_a1_full_rows_every_point_no_missing() -> None:
    """Bảng mục 4: đủ mọi dòng của 8 điểm (kể cả `final_state` có + dòng B20) → []."""
    assert required(T, copy.deepcopy(FULL), final_state="S_RESOLVED") == []


P6_DECIDED = ("approval_result", "detail.decided_without_view", "response_time_seconds", "detail.decided_as")
P7_FIELDS = ("detail.success", "detail.write_calls", "detail.action_plan_hash_matched")
CASES: list[tuple[str, dict[str, Any], int, str]] = [
    # điểm 1
    *[("p1-b3", P1_B3, 1, f) for f in ("detail.layer", "detail.dropped_slot_keys", "detail.intent", "detail.confidence", "intent")],
    *[("p1-b4", P1_B4, 1, f) for f in ("detail.layer", "detail.dropped_slot_keys", "detail.intent", "detail.confidence")],
    *[("p1-b4-oos", P1_B4_OOS, 1, f) for f in ("detail.layer", "detail.dropped_slot_keys")],
    *[("p1-b4-multi", P1_B4_MULTI, 1, f) for f in ("detail.layer", "detail.dropped_slot_keys")],
    # điểm 2
    *[("p2-b6", P2_B6, 2, f) for f in ("detail.tools_called", "detail.facts", "detail.tool_retry_count")],
    *[("p2-b7", P2_B7, 2, f) for f in ("detail.tools_called", "detail.facts", "detail.tool_retry_count")],
    # điểm 3
    *[("p3-retrieved", P3_RETRIEVED, 3, f) for f in ("detail.query", "detail.top_score", "kb_version")],
    *[("p3-error", P3_ERROR, 3, f) for f in ("detail.query", "kb_version")],
    ("p3-error-alias", P3_ERROR_ALIAS, 3, "detail.query"),
    *[("p3-b9", P3_B9, 3, f) for f in ("kb_version", "detail.grounding.top_score")],
    # điểm 4
    *[("p4", P4, 4, f) for f in ("decided_by", "policy_decision", "risk_level", "reason", "detail.route", "detail.policy_sha256")],
    # điểm 5
    *[("p5", P5, 5, f) for f in ("approver_id", "deadline", "conflict_detected", "action_plan_hash", "detail.choice_reason")],
    # điểm 6
    *[("p6-approved", P6_APPROVED, 6, f) for f in P6_DECIDED],
    *[("p6-rejected", P6_REJECTED, 6, f) for f in (*P6_DECIDED, "note")],
    *[("p6-timeout", P6_TIMEOUT, 6, f) for f in ("approval_result", "detail.decided_without_view")],
    # điểm 7 (ticket có B16/approved → đòi cả action_plan_hash_matched)
    *[("p7-ok", P7_OK, 7, f) for f in P7_FIELDS],
    *[("p7-failed", P7_FAILED, 7, f) for f in P7_FIELDS],
    *[("p7-interrupted", P7_INTERRUPTED, 7, f) for f in P7_FIELDS],
]


@pytest.mark.parametrize(("row", "point", "field"), [(r, p, f) for _, r, p, f in CASES], ids=[f"{i}-{f}" for i, _, _, f in CASES])
def test_a1_drop_one_required_field_exact_missing(row: dict[str, Any], point: int, field: str) -> None:
    """a1 (M-4d-9 ở điểm 5): bỏ ĐÚNG một trường bắt buộc → đúng một `Missing(T, điểm, log_id dòng đó, (trường,))`."""
    rows = [_without(row, field)]
    if point == 7:
        rows.insert(0, copy.deepcopy(P6_APPROVED))  # ticket đi qua duyệt → điểm 7 đòi `action_plan_hash_matched`
    assert required(T, rows, final_state=None) == [Missing(T, point, row["log_id"], (field,))]


@pytest.mark.parametrize(("row", "point", "field"), [
    (P1_B3, 1, "detail.intent"), (P1_B3, 1, "detail.confidence"), (P1_B4, 1, "detail.intent"),
    (P2_B6, 2, "detail.tool_retry_count"),
])  # fmt: skip
def test_a1_not_null_field_with_none_value_is_missing(row: dict[str, Any], point: int, field: str) -> None:
    """Bảng mục 4 "≠ null": khoá CÓ nhưng giá trị None → vẫn thiếu."""
    assert required(T, [_with(row, field, None)], final_state=None) == [Missing(T, point, row["log_id"], (field,))]


def test_a1_two_fields_missing_same_row_one_entry() -> None:
    """Thiếu 2 trường trên CÙNG một dòng → một `Missing` của dòng đó mang cả hai trường (thứ tự không ghim)."""
    rows = [_without(_without(P5, "approver_id"), "detail.choice_reason")]
    [m] = required(T, rows, final_state=None)
    assert (m.ticket_id, m.point, m.log_id) == (T, 5, P5["log_id"])
    assert set(m.fields) == {"approver_id", "detail.choice_reason"}


def test_a1_missing_is_frozen_with_contract_fields() -> None:
    m = Missing(T, 5, 12, ("approver_id",))
    assert [f.name for f in dataclasses.fields(m)] == ["ticket_id", "point", "log_id", "fields"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.point = 6  # type: ignore[misc]


# ---- điểm 8 -------------------------------------------------------------------------------------------------------------------------


def test_a1_point8_final_without_b20_row_missing_log_id_none() -> None:
    """Điểm 8: `tickets.final_state` có mà không có dòng B20 `closed` → `Missing(point=8, log_id=None)`."""
    [m] = required(T, [copy.deepcopy(P1_B3)], final_state="S_ESCALATED")
    assert (m.ticket_id, m.point, m.log_id) == (T, 8, None)
    assert m.fields  # tên trường thiếu (không ghim chữ)


def test_a1_point8_b20_without_final_state_column() -> None:
    [m] = required(T, [_without(P8, "final_state")], final_state="S_RESOLVED")
    assert (m.ticket_id, m.point, m.log_id) == (T, 8, P8["log_id"])
    assert "final_state" in m.fields


def test_a1_point8_b20_without_close_reason_and_exit_code() -> None:
    [m] = required(T, [_without(P8, "close_reason")], final_state="S_RESOLVED")
    assert (m.ticket_id, m.point, m.log_id) == (T, 8, P8["log_id"])
    assert any("close_reason" in f or "exit_code" in f for f in m.fields), m.fields


def test_a1_point8_exit_code_instead_of_close_reason_ok() -> None:
    """Điểm 8: `close_reason` HOẶC `exit_code`."""
    row = _row(19, "B20", "closed", final_state="S_ESCALATED", exit_code="E5")
    assert required(T, [row], final_state="S_ESCALATED") == []


SPLIT = _row(18, "B5", "split_into_2_children", {"children": 2, "verdicts": ["runnable", "runnable"]})  # dòng tách ý — chỉ ticket CHA


def test_a1_point8_parent_valid_aggregate_status_ok() -> None:
    """T20b Q-T20b-13 = A: cha đóng bình thường (D-30) không `close_reason`/`exit_code` — `detail.aggregate_status` hợp lệ → đạt."""
    row = _row(19, "B20", "closed", {"resolution_path": None, "aggregate_status": "PARTIALLY_REJECTED"}, final_state="S_RESOLVED")
    assert required(T, [copy.deepcopy(SPLIT), row], final_state="S_RESOLVED") == []


@pytest.mark.parametrize("detail", [{"aggregate_status": "SOMETHING_ELSE"}, {"aggregate_status": None}, {}],
                         ids=["la", "null", "thieu"])  # fmt: skip
def test_a1_point8_parent_bad_or_missing_aggregate_status_still_missing(detail: dict[str, Any]) -> None:
    """T20b Q-T20b-13 = A: cha mà `aggregate_status` lạ / null / vắng và không `close_reason`, `exit_code` → vẫn thiếu điểm 8."""
    row = _row(19, "B20", "closed", detail, final_state="S_RESOLVED")
    [m] = required(T, [copy.deepcopy(SPLIT), row], final_state="S_RESOLVED")
    assert (m.point, m.log_id, m.fields) == (8, 19, ("close_reason|exit_code",))


@pytest.mark.parametrize("first", [P1_B3, _row(1, "B5", "child_started")], ids=["la", "con"])
def test_a1_point8_non_parent_with_aggregate_status_still_missing(first: dict[str, Any]) -> None:
    """T20b Q-T20b-13 (bổ sung phiên git): ticket KHÔNG phải cha (lá / con — không có dòng B5 `split_into_<n>_children`) có
    `detail.aggregate_status` hợp lệ mà thiếu `close_reason` lẫn `exit_code` → VẪN thiếu điểm 8."""
    row = _row(19, "B20", "closed", {"aggregate_status": "ALL_RESOLVED"}, final_state="S_RESOLVED")
    [m] = required(T, [copy.deepcopy(first), row], final_state="S_RESOLVED")
    assert (m.point, m.log_id, m.fields) == (8, 19, ("close_reason|exit_code",))


def test_a1_point8_one_good_b20_row_is_enough() -> None:
    """Điểm 8 "≥ 1 dòng B20/closed có …": thêm một dòng B20 khác (không phải `closed`) không làm thiếu."""
    rows = [copy.deepcopy(P8), _row(20, "B20", "escalation_created")]
    assert required(T, rows, final_state="S_RESOLVED") == []


# ---- a2: điểm áp dụng theo dòng có mặt ------------------------------------------------------------------------------------------------


def test_a2_no_rows_open_ticket_nothing_required() -> None:
    assert required(T, [], final_state=None) == []


def test_a2_only_point1_rows_does_not_demand_points_2_to_8() -> None:
    """Không có dòng B15 → không đòi điểm 5; không có B16/B17/B18 → không đòi 6, 7; ticket mở → không đòi 8."""
    assert required(T, [copy.deepcopy(P1_B3)], final_state=None) == []


def test_a2_unrelated_events_not_checked() -> None:
    """Dòng có bước trùng nhưng sự kiện không thuộc bảng (B15 nhánh E, B3 khác, OVERRIDE) → không bị đòi trường điểm 1/4/5.
    Nhánh be-audit-diem4 (nợ ca (b), D-67): B13/B14 `llm_layer_disabled` NAY được soát như điểm 4 — bỏ khỏi danh sách này, kiểm ở
    `test_audit_check_llm_down.py`."""
    rows = [_row(30, "B15", "no_valid_approver"), _row(32, "B3", "injection_checked"),
            _row(33, "OVERRIDE", "override_recorded", {"reason_code": "policy_gap"}, overrider_id="l1_02")]  # fmt: skip
    assert required(T, rows, final_state=None) == []


def test_a2_point7_hash_matched_only_when_ticket_went_through_approval() -> None:
    """Điểm 7: `action_plan_hash_matched` CHỈ đòi khi ticket có `B16/approved` (đường AUTO không có)."""
    auto = _without(P7_OK, "detail.action_plan_hash_matched")
    assert required(T, [auto], final_state=None) == []
    assert required(T, [copy.deepcopy(P6_APPROVED), auto], final_state=None) == [
        Missing(T, 7, P7_OK["log_id"], ("detail.action_plan_hash_matched",))]  # fmt: skip


def test_a2_point7_txlog_before_recheck_exempt_from_hash_matched() -> None:
    """Điểm 7: `exec_interrupted` với `detail.stage="txlog_before_recheck"` (bước 0, chưa so hash) → không đòi hash_matched."""
    row = _row(18, "B17", "exec_interrupted", {"success": None, "write_calls": 0, "stage": "txlog_before_recheck"})
    assert required(T, [copy.deepcopy(P6_APPROVED), row], final_state=None) == []


def test_a2_point6_timeout_does_not_demand_response_time_or_decided_as_or_note() -> None:
    assert required(T, [copy.deepcopy(P6_TIMEOUT)], final_state=None) == []


def test_a2_point6_approved_does_not_demand_note() -> None:
    assert required(T, [_without(P6_APPROVED, "note")], final_state=None) == []


def test_a2_point3_alias_error_does_not_demand_kb_version() -> None:
    assert required(T, [copy.deepcopy(P3_ERROR_ALIAS)], final_state=None) == []


@pytest.mark.parametrize("row", [P1_B4_OOS, P1_B4_MULTI, P1_B4_REVERSE],
                         ids=["intent_out_of_scope", "multi_intent_not_enabled", "reverse_action_requested"])  # fmt: skip
def test_a2_point1_e1_events_exempt_from_intent_and_confidence(row: dict[str, Any]) -> None:
    assert required(T, [copy.deepcopy(row)], final_state=None) == []


@pytest.mark.parametrize(("row", "field", "value"), [
    (P1_B3, "detail.dropped_slot_keys", None),
    (P2_B6, "detail.facts", None),
    (P3_B9, "detail.grounding.top_score", None),
    (P6_TIMEOUT, "detail.decided_without_view", None),
    (P7_INTERRUPTED, "detail.success", None),
    (P2_B6, "detail.tool_retry_count", 0),
    (P5, "conflict_detected", False),
    (P6_APPROVED, "detail.decided_without_view", False),
    (P7_FAILED, "detail.success", False),
])  # fmt: skip
def test_a2_has_key_semantics_accepts_none_or_falsy(row: dict[str, Any], field: str, value: Any) -> None:
    """"(có khoá)" = khoá có là đủ (None được); "≠ null"/cột: 0 và False KHÔNG phải thiếu (không kiểm bằng truthiness)."""
    assert required(T, [_with(row, field, value)], final_state=None) == []


def test_a2_point8_not_demanded_when_ticket_open() -> None:
    assert required(T, [copy.deepcopy(P1_B3)], final_state=None) == []
    assert [m.point for m in required(T, [copy.deepcopy(P1_B3)], final_state="S_RESOLVED")] == [8]


# ---- a3: SecretScanner + scan_rows ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("rule", sorted(SAMPLES))
def test_a3_each_secret_rule_hits_once(rule: str) -> None:
    """Mỗi luật `kind="secret"` của config (pem, jwt, api_key, password, otp) trúng mẫu của nó — đúng id, đúng một lần."""
    assert _scanner().hits(SAMPLES[rule]) == [rule]
    assert _scanner().hits(SAMPLES[rule] + " | " + SAMPLES[rule]) == [rule]


def test_a3_secret_rule_ids_come_from_config() -> None:
    """Luật quét = đúng các luật `secret` của `config/privacy_patterns.json` (không `entropy`, không PII) — đủ 5 mẫu trúng 5 id."""
    text = " ;; ".join(SAMPLES.values())
    hits = _scanner().hits(text)
    assert sorted(hits) == sorted(SAMPLES) and len(hits) == len(set(hits))


def test_a3_canary_substring_case_sensitive() -> None:
    """TQ-7: canary là chuỗi con, phân biệt hoa/thường; nhiều canary vẫn chỉ một id `canary`."""
    s = _scanner(CANARY, "khac-" + "canary-2")
    assert s.hits(f"ghi chú:{CANARY}!") == ["canary"]
    assert s.hits(f"{CANARY} và khac-canary-2") == ["canary"]
    assert s.hits(CANARY.upper()) == []
    assert _scanner().hits(CANARY) == []  # không khai canary → không trúng


def test_a3_custom_rules_value_group_masked_not_counted() -> None:
    """`SecretScanner(rules, mask=…)`: nhóm `v` = mặt nạ + CHỈ dấu câu/khoảng trắng → không tính; sau mặt nạ còn chữ/số → TÍNH (Q-4d-8 = B,
    sửa chữ 7.7 #6 "bắt đầu bằng mặt nạ" — `pw=[M]-x` trước đây không tính, nay tính); lần trúng sau chưa che vẫn tính."""
    s = SecretScanner([("pw", re.compile(r"pw=(?P<v>\S+)")), ("tok", re.compile(r"TOK\d{3}"))], mask="[M]")
    assert s.hits("pw=[M]") == [] and s.hits("pw=[M].") == [] and s.hits("pw=[M]),") == []
    assert s.hits("pw=[M]abc123") == ["pw"] and s.hits("pw=[M]-x") == ["pw"]
    assert s.hits("pw=abc") == ["pw"]
    assert s.hits("pw=[M] rồi pw=abc") == ["pw"]
    assert s.hits("TOK123 TOK456") == ["tok"]
    assert sorted(s.hits("pw=abc TOK123")) == ["pw", "tok"]
    assert SecretScanner([], mask="[M]", canaries=("CAN-1",)).hits("x CAN-1 y") == ["canary"]


@pytest.mark.parametrize("column", TEXT_COLUMNS)
def test_a3_scan_rows_every_text_column(column: str) -> None:
    """MỌI cột chuỗi của `AuditLog` (liệt kê từ kiểu cột model) — canary trong cột → `SecretHit(T, "audit_logs.<cột>", log_id,
    "canary")`, không mang giá trị."""
    row = _row(7, "B3", "intent_classified")
    row[column] = f"đầu {CANARY} cuối"
    assert scan_rows([row], _scanner(CANARY)) == [SecretHit(T, f"audit_logs.{column}", 7, "canary")]


@pytest.mark.parametrize("column", JSON_COLUMNS)
def test_a3_scan_rows_every_json_column_nested_leaf(column: str) -> None:
    """MỌI cột JSON của `AuditLog` — canary ở lá chuỗi LỒNG (dict trong list trong dict), lá không phải chuỗi không làm hỏng."""
    value = {"a": [1, None, True, 2.5, {"b": {"c": f"x {CANARY}"}}], "n": 3}
    row = _row(8, "B3", "intent_classified")
    row[column] = value
    assert scan_rows([row], _scanner(CANARY)) == [SecretHit(T, f"audit_logs.{column}", 8, "canary")]


def test_a3_scan_rows_rules_in_text_and_json_columns() -> None:
    row = _row(9, "B16", "rejected", {"x": {"y": ["ok", SAMPLES["jwt"]]}}, note=SAMPLES["password"],
               intended_action={"params": {"k": SAMPLES["api_key"]}})  # fmt: skip
    hits = scan_rows([row], _scanner())
    assert set(hits) == {SecretHit(T, "audit_logs.note", 9, "password"), SecretHit(T, "audit_logs.detail", 9, "jwt"),
                         SecretHit(T, "audit_logs.intended_action", 9, "api_key")}  # fmt: skip
    assert len(hits) == 3


def test_a3_scan_rows_ref_and_ticket_per_row() -> None:
    rows = [{**_row(21, "B3", "x", note=f"a {CANARY}"), "ticket_id": "tk-1"},
            {**_row(22, "B3", "x", note="sạch"), "ticket_id": "tk-2"},
            {**_row(23, "B3", "x", reason=f"b {CANARY}"), "ticket_id": "tk-3"}]  # fmt: skip
    assert set(scan_rows(rows, _scanner(CANARY))) == {SecretHit("tk-1", "audit_logs.note", 21, "canary"),
                                                       SecretHit("tk-3", "audit_logs.reason", 23, "canary")}  # fmt: skip


def test_a3_json_leaf_not_json_dumped() -> None:
    """TQ-7: JSON đi từng LÁ chuỗi — canary có dấu nháy kép, gạch chéo ngược, chữ có dấu (bị escape nếu `json.dumps`) vẫn trúng."""
    tricky = 'Cá"nary\\4d-ư'
    row = _row(10, "B3", "x", {"msg": f"x {tricky} y"})
    assert scan_rows([row], _scanner(tricky)) == [SecretHit(T, "audit_logs.detail", 10, "canary")]


def test_a3_secret_hit_carries_no_value() -> None:
    """2.1: `SecretHit` KHÔNG mang giá trị — đúng 4 trường."""
    assert [f.name for f in dataclasses.fields(SecretHit)] == ["ticket_id", "column", "ref", "rule"]


# ---- a4: không báo nhầm -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    f"mật khẩu là {MASK}",
    f"mật khẩu của tôi là {MASK}, reset giúp",
    f"pass: {MASK}",
    f"otp: {MASK}",
    "gọi em <SĐT_1> hoặc <EMAIL_1>",
    HEX64,
    "LAP-0501",
    "device:LAP-0501",
    "Zx8Qw2Lp9" + "Vt4Rm7Kc3" + "Hn6Bj1Yd5",  # entropy cao — luật `entropy` KHÔNG dùng (TQ-7); ghép (gitleaks)
], ids=["mk-da-che", "mk-da-che-co-duoi", "pass-da-che", "otp-da-che", "pii-da-che", "hex64", "ma-may", "target", "entropy"])  # fmt: skip
def test_a4_redacted_hash_device_no_hit(text: str) -> None:
    assert _scanner(CANARY).hits(text) == []


def test_a4_realistic_redacted_row_no_hit() -> None:
    row = _row(11, "B16", "rejected", {"policy_sha256": HEX64, "device_id": "LAP-0501", "note_suppressed": False,
                                       "reason": f"mật khẩu là {MASK}"},
               note=f"không đủ lý do, mật khẩu là {MASK}", action_plan_hash=HEX64, idempotency_key=HEX64, kb_version=HEX64,
               intended_action={"type": "renew_vpn_cert", "target": "device:LAP-0501", "params": {"device_id": "LAP-0501"}})  # fmt: skip
    assert scan_rows([row], _scanner(CANARY)) == []


# ---- a6: scan_log -----------------------------------------------------------------------------------------------------------------------


def test_a6_scan_log_line_numbers_from_1_no_ticket() -> None:
    lines = ["INFO khởi động", f"WARN {SAMPLES['password']}", "INFO ok", f"DEBUG x {CANARY} y\n", f"INFO {MASK}"]
    hits = scan_log(lines, _scanner(CANARY))
    assert sorted(hits, key=lambda h: h.ref) == [SecretHit(None, "log", 2, "password"), SecretHit(None, "log", 4, "canary")]


def test_a6_scan_log_clean_and_render_has_no_value() -> None:
    assert scan_log([f"mật khẩu là {MASK}", "LAP-0501", HEX64], _scanner(CANARY)) == []
    hits = scan_log([f"x {CANARY}", SAMPLES["password"]], _scanner(CANARY))
    out = render(Report(tickets=(), missing=(), secrets=tuple(hits)))
    assert "bí mật: log dòng 1 (luật canary)" in out and "bí mật: log dòng 2 (luật password)" in out
    assert CANARY not in out and "4dor99" not in out


# ---- a5: render, Report.ok, main (tham số) ---------------------------------------------------------------------------------------------


def test_a5_report_ok() -> None:
    assert Report(tickets=("tk-1",), missing=(), secrets=()).ok is True
    assert Report(tickets=("tk-1",), missing=(Missing("tk-1", 5, 1, ("approver_id",)),), secrets=()).ok is False
    assert Report(tickets=("tk-1",), missing=(), secrets=(SecretHit("tk-1", "audit_logs.note", 1, "canary"),)).ok is False


def test_a5_render_table_secret_lines_conclusion() -> None:
    report = Report(
        tickets=("tk-1", "tk-2"),
        missing=(Missing("tk-1", 5, 11, ("approver_id",)),),
        secrets=(SecretHit("tk-2", "audit_logs.detail", 12, "canary"),),
    )
    out = render(report)
    assert "| ticket | điểm thiếu | trường thiếu |" in out
    row = [line for line in out.splitlines() if "tk-1" in line and "approver_id" in line]
    assert row and "5" in row[0], out
    assert "bí mật: audit_logs.detail dòng 12 (luật canary)" in out
    assert out.strip().splitlines()[-1] == "KẾT LUẬN: 1 thiếu, 1 bí mật (2 ticket)"


def test_a5_render_clean_conclusion() -> None:
    out = render(Report(tickets=("tk-1",), missing=(), secrets=()))
    assert out.strip().splitlines()[-1] == "KẾT LUẬN: 0 thiếu, 0 bí mật (1 ticket)"


def test_a5_render_from_real_scan_has_no_secret_value() -> None:
    """M-4d-13: render từ kết quả quét THẬT (canary + mật khẩu trong dòng) — đầu ra không có giá trị nào."""
    rows = [_row(41, "B16", "rejected", {"k": f"x {CANARY}"}, note=SAMPLES["password"]),
            _row(42, "B15", "queued", {"t": SAMPLES["api_key"]})]  # fmt: skip
    hits = scan_rows(rows, _scanner(CANARY))
    assert len(hits) == 3
    out = render(Report(tickets=(T,), missing=tuple(required(T, rows, final_state=None)), secrets=tuple(hits)))
    for value in (CANARY, "4dor99", SAMPLES["api_key"].split()[-1]):
        assert value not in out
    assert out.strip().splitlines()[-1].endswith("bí mật (1 ticket)")


def _code(argv: list[str]) -> Any:
    """`main` trả mã; argparse lỗi tham số thì ném `SystemExit(2)` — chấp nhận cả hai."""
    try:
        return main(argv)
    except SystemExit as exc:
        return exc.code


@pytest.mark.parametrize("argv", [
    [],  # thiếu cả ticket lẫn --since
    ["tk-1", "--since", "2026-10-01T00:00:00+07:00"],  # cả hai
    ["--since", "khong-phai-ngay"],
    ["--canary"],
    ["tk-1", "--log"],
    ["--canary", "x"],  # chỉ có canary — vẫn thiếu phạm vi
], ids=["rong", "ca-hai", "since-sai", "canary-thieu-gia-tri", "log-thieu-duong-dan", "chi-canary"])  # fmt: skip
def test_a5_main_bad_arguments_exit_2(argv: list[str]) -> None:
    """P5 / 2.1: `[TICKET_ID ...] | --since ISO` — đúng một trong hai; sai → 2 (không đụng DB)."""
    assert _code(argv) == 2


def test_a5_main_bad_arguments_output_has_no_canary(capsys: pytest.CaptureFixture[str]) -> None:
    assert _code(["--canary", CANARY]) == 2
    captured = capsys.readouterr()
    assert CANARY not in captured.out and CANARY not in captured.err
