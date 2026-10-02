"""B16 tự so hash khi duyệt — Phase 4 chặng 4d DỪNG 2, Q-4d-3 (phase4 mục 7.7 #8; PLAN-4d mục 11.2, TQ-14 đã duyệt). Viết TRƯỚC code.

Nhánh `approved`, SAU `approvals.close` (phiếu vẫn `approved` — TQ-14a), TRƯỚC `goto(S_EXECUTING)`: so `hash_action(intended_action)` với
`state.action_plan_hash` (lớp state — đúng phép so của cấm F3) rồi với `approvals.action_plan_hash` (lớp phiếu); lệch → `S_ESCALATED` E5
step `B16` event `action_plan_changed_since_approval`, dòng audit mang đủ điểm log 6 + `hash_source`, `hash_old`, `hash_new`,
`action_plan_hash_matched=False` (TQ-14b); B16 không gửi tin, B20 gửi mẫu E5 (TQ-14c). Cấm F3 giữ làm lớp cuối; B17 hai lớp giữ nguyên.

Graph: node GIẢ tới B15 (`l1-fake`) + B16 chung + B17 giả (`CountingExecutor` — đếm lời gọi thực thi) + B20 thật.
- q1 lệch hash STATE · q2 lệch hash PHIẾU · q3 đối chứng khớp · q4 cả hai lệch → `state` · q5 hash state thiếu · q6 chạy lại sau crash ·
  q7 `audit_check` điểm 6 nhận dòng mới.
"""

import hashlib
from datetime import timedelta
from typing import Any

import pytest
from app.audit.check import Missing, required
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_PENDING_APPROVAL
from app.graph.late_event import deliver_event
from app.graph.worker_jobs import WorkerJobs
from app.settings import get_action_metadata, get_escalation_templates
from tests.fakes.graph import Crash, GraphHarness

pytestmark = pytest.mark.asyncio

APPROVER = "l1-fake"  # B15 giả (NodeDeps.approver_id mặc định)
CHANGED = "action_plan_changed_since_approval"
OTHER_HASH = hashlib.sha256(b"q: phieu duoc duyet cho ke hoach khac").hexdigest()
POINT6 = {"view_duration", "decided_without_view", "decided_as", "reason_code", "close_applied"}
HASH_KEYS = {"hash_source", "hash_old", "hash_new", "action_plan_hash_matched"}


def _action(device: str = "LAP-0501", **params: Any) -> Action:
    m = get_action_metadata().of("vpn")["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target=f"device:{device}", requested_for="nv-fake", scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": device, **params},
        facts={"device_owner_is_requester": True},
    )  # fmt: skip


async def _pending(h: GraphHarness, action: Action) -> tuple[str, dict[str, Any]]:
    """Ticket `t1` chờ duyệt; hành động thật + hash KHỚP ở cả state lẫn phiếu (như B15 thật). Trả (approval_id, dòng phiếu giả)."""
    await h.submit("t1")
    await h.runner.graph.aupdate_state(
        h.runner.config("t1"), {"intended_action": action, "action_plan_hash": hash_action(action)}
    )
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.next) == (S_PENDING_APPROVAL, ("approval_wait",))
    aid = str(snap.values["approval_id"])
    row = h.deadlines.approvals[aid]
    row["action_plan_hash"] = hash_action(action)
    return aid, row


async def _tamper_state(h: GraphHarness, action: Action) -> None:
    """Đổi `intended_action` trong checkpoint lúc phiếu còn chờ (TC26) — hash state GIỮ giá trị lúc tạo phiếu."""
    await h.runner.graph.aupdate_state(h.runner.config("t1"), {"intended_action": action})


async def _approve(h: GraphHarness, *, after: timedelta = timedelta(seconds=90), view: float | None = 20.0) -> None:
    h.clock.advance(after)
    ev = {"kind": "approved", "note": None, "approver_id": APPROVER, "at": h.clock.now().isoformat(), "reason_code": None,
          "view_duration": view, "decided_as": "primary"}  # fmt: skip
    await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, ev)


def _e5_row(h: GraphHarness) -> dict[str, Any]:
    rows = [r for r in h.audit.rows if r["ticket_id"] == "t1" and r["step"] == "B16"]
    assert [(r["step"], r["event"]) for r in rows] == [("B16", CHANGED)], h.audit.events("t1")
    return rows[0]


async def _assert_e5(h: GraphHarness, *, source: str, old: str | None, new: str) -> dict[str, Any]:
    """Kỳ vọng chung q1/q2/q4/q5: E5 ở B16, điểm log 6 đủ, phiếu `approved`, 0 thực thi, 1 escalation, 1 tin mẫu E5."""
    snap = await h.runner.snapshot("t1")
    got = (snap.values["status"], snap.values.get("exit_code"), snap.values.get("escalation_reason_detail"))
    assert got == (S_ESCALATED, "E5", CHANGED), (got, h.audit.events("t1"))
    assert snap.values["approval_result"] == "approved"
    row = _e5_row(h)
    assert (row["approval_result"], row["response_time_seconds"], row["exit_code"]) == ("approved", 90.0, "E5")
    detail = dict(row["detail"])
    assert set(detail) >= POINT6 | HASH_KEYS, detail
    assert {k: detail[k] for k in HASH_KEYS} == {
        "hash_source": source, "hash_old": old, "hash_new": new, "action_plan_hash_matched": False}  # fmt: skip
    assert {k: detail[k] for k in POINT6} == {"view_duration": 20.0, "decided_without_view": False, "decided_as": "primary",
                                              "reason_code": None, "close_applied": 1}  # fmt: skip
    assert detail["escalation_reason_detail"] == CHANGED
    assert h.deadlines.approvals["1"]["status"] == "approved" and h.deadlines.approvals["1"]["decided_by"] == APPROVER  # TQ-14a
    assert h.executor.calls["t1"] == 0
    assert not [e for e in h.audit.events("t1") if e[0] == "B17"]
    assert h.audit.of("t1", "unhandled_exception") == []
    assert [(e["exit_code"], e["reason_detail"]) for e in h.escalations.of("t1")] == [("E5", CHANGED)]
    assert [text for t, text, _ in h.notifier.sent if t == "t1"] == [get_escalation_templates().of("E5").user_message]
    return row


# ---- q1–q5: các lớp so hash ---------------------------------------------------------------------------------------------------


async def test_q1_state_hash_mismatch_e5_at_b16_not_e9() -> None:
    """q1 (TC26, i8c ở unit): `intended_action` bị đổi lúc chờ → hash state (lúc tạo phiếu) ≠ hash hành động → B16 E5
    `hash_source="state"` — KHÔNG để cấm F3 ném `IllegalTransition` → E9."""
    h = GraphHarness()
    action, tampered = _action(), _action(duration_days=365)
    await _pending(h, action)
    await _tamper_state(h, tampered)
    await _approve(h)
    await _assert_e5(h, source="state", old=hash_action(action), new=hash_action(tampered))


async def test_q2_approval_hash_mismatch_e5_at_b16() -> None:
    """q2: state tự nhất quán (hành động + hash state khớp) nhưng hash PHIẾU (cái người duyệt đã xem, 4c P6) khác → B16 E5
    `hash_source="approval"`, `hash_old` = hash phiếu; B17 không chạy."""
    h = GraphHarness()
    action = _action()
    _, row = await _pending(h, action)
    row["action_plan_hash"] = OTHER_HASH
    await _approve(h)
    await _assert_e5(h, source="approval", old=OTHER_HASH, new=hash_action(action))


async def test_q3_both_hashes_match_executes_as_before() -> None:
    """q3 (đối chứng): khớp cả hai → `S_EXECUTING` → B17 (giả) thực thi đúng 1 lần → `S_CONFIRMING`; dòng B16 vẫn là `approved`."""
    h = GraphHarness()
    await _pending(h, _action())
    await _approve(h)
    snap = await h.runner.snapshot("t1")
    assert snap.values["status"] == S_CONFIRMING, h.audit.events("t1")
    assert h.executor.calls["t1"] == 1
    assert [e for e in h.audit.events("t1") if e[0] == "B16"] == [("B16", "approved")]
    assert h.audit.of("t1", CHANGED) == []


async def test_q4_both_layers_differ_reports_state_first() -> None:
    """q4: lệch cả hai lớp → báo lớp state (so trước — như B17)."""
    h = GraphHarness()
    action, tampered = _action(), _action("LAP-0999")
    _, row = await _pending(h, action)
    row["action_plan_hash"] = OTHER_HASH
    await _tamper_state(h, tampered)
    await _approve(h)
    await _assert_e5(h, source="state", old=hash_action(action), new=hash_action(tampered))


async def test_q5_state_hash_missing_is_mismatch_hash_old_null() -> None:
    """q5: hash state thiếu (None) — không chứng minh được "cùng kế hoạch" → E5 `hash_source="state"`, `hash_old` null (như B17 lớp
    1), dù hash phiếu khớp hành động."""
    h = GraphHarness()
    action = _action()
    await _pending(h, action)
    await h.runner.graph.aupdate_state(h.runner.config("t1"), {"action_plan_hash": None})
    await _approve(h)
    await _assert_e5(h, source="state", old=None, new=hash_action(action))


async def test_q8_missing_action_not_compared_f3_still_blocks_e9() -> None:
    """q8 (soát 4d DỪNG 2, ghi chú S10): thiếu `intended_action` lúc duyệt = bug → B16 KHÔNG so (không E5 giả) → cấm F3 chặn
    `S_PENDING_APPROVAL → S_EXECUTING` → E9 như trước Q-4d-3; 0 thực thi."""
    h = GraphHarness()
    await _pending(h, _action())
    await h.runner.graph.aupdate_state(h.runner.config("t1"), {"intended_action": None})
    await _approve(h)
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"]) == (S_ESCALATED, "E9"), h.audit.events("t1")
    assert h.audit.of("t1", CHANGED) == [] and h.executor.calls["t1"] == 0


# ---- q6: chạy lại sau crash -------------------------------------------------------------------------------------------------------


async def test_q6_crash_before_e5_audit_rerun_once() -> None:
    """q6: process chết SAU `close` (phiếu đã `approved`), TRƯỚC dòng audit B16 E5 → phục hồi chạy lại B16 cùng sự kiện → đúng 1 dòng
    B16 E5 (`close_applied=0` — phiếu đóng từ lần đầu), 1 escalation, 1 tin, 0 thực thi."""
    h = GraphHarness()
    action, tampered = _action(), _action(duration_days=365)
    await _pending(h, action)
    await _tamper_state(h, tampered)
    h.audit.crash_once.add(CHANGED)
    with pytest.raises(Crash):
        await _approve(h)
    assert h.deadlines.approvals["1"]["status"] == "approved"
    h.restart(can_execute=False)
    h.clock.advance(timedelta(minutes=3))
    assert await WorkerJobs(h.runner, h.deadlines, h.turns).scan_stale_turns() == 1
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"]) == (S_ESCALATED, "E5"), h.audit.events("t1")
    row = _e5_row(h)
    assert (row["detail"]["hash_source"], row["detail"]["close_applied"]) == ("state", 0)
    assert len(h.escalations.of("t1")) == 1 and h.notifier.count("t1") == 1
    assert h.executor.calls["t1"] == 0


# ---- q7: audit_check điểm 6 nhận dòng B16 E5 -----------------------------------------------------------------------------------------


_E5_ROW: dict[str, Any] = {
    "log_id": 7, "step": "B16", "event": CHANGED, "approval_result": "approved", "response_time_seconds": 12.5,
    "detail": {"view_duration": None, "decided_without_view": True, "decided_as": "primary", "reason_code": None,
               "close_applied": 1, "hash_source": "approval", "hash_old": OTHER_HASH, "hash_new": "a" * 64,
               "action_plan_hash_matched": False},
}  # fmt: skip


def _without(field: str) -> dict[str, Any]:
    row = {**_E5_ROW, "detail": dict(_E5_ROW["detail"])}
    if field.startswith("detail."):
        del row["detail"][field.removeprefix("detail.")]
    else:
        row[field] = None
    return row


async def test_q7_audit_check_point6_full_e5_row_ok_false_is_not_missing() -> None:
    """q7 (đối chứng): dòng B16 E5 đủ → 0 thiếu; `action_plan_hash_matched=False`, `decided_without_view=True`, `view_duration` null
    KHÔNG bị coi là thiếu."""
    assert required("tk-q7", [_E5_ROW], final_state=None) == []


@pytest.mark.parametrize("field", [
    "approval_result", "response_time_seconds", "detail.decided_as", "detail.hash_source", "detail.action_plan_hash_matched",
    "detail.decided_without_view",
])  # fmt: skip
async def test_q7_audit_check_point6_e5_row_missing_field(field: str) -> None:
    """q7: dòng `B16/action_plan_changed_since_approval` thuộc điểm 6 (TQ-14b) — đòi như `approved` + `detail.hash_source`,
    `detail.action_plan_hash_matched` khác null; thiếu từng trường → đúng một `Missing(point=6)`."""
    assert required("tk-q7", [_without(field)], final_state=None) == [Missing("tk-q7", 6, 7, (field,))]
