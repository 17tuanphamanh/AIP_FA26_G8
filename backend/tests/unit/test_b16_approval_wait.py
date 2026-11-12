"""B16 (`approval_wait`, node CHUNG — PLAN-4c TQ-1) — Phase 4 chặng 4c P1, P2 (phase4 6.1, 6.2 c1, c2, c11) + d1, d7.

- P1: từ chối → MỘT tin `kind=rejection` (theo mẫu, `needs="none"`) qua `effects.once("notify_user", step="B16")`; ghi chú che L1
  lại ở B16 (route đã che — node không tin đầu vào, TQ-2) TRƯỚC `close` → `approvals.note`, cột `audit_logs.note`, tin nhắn cùng MỘT
  bản đã che (Q-4c-1 điều kiện). Output guard chặn ghi chú → bỏ câu "Ghi chú…", `note_suppressed=true`.
- P2: điểm log 6 ở cả 3 nhánh: cột `approval_result` (khoá state), `note` (chỉ rejected) + `response_time_seconds` qua `audit_columns`
  (= `ev.at − phiếu.created_at`; timeout NULL); `detail` ĐÚNG khoá `view_duration, decided_without_view, decided_as, reason_code,
  close_applied` (+ `note_suppressed` ở rejected). Nguồn (TQ-5): quyết định → sự kiện; timeout → `first_viewed_at` của phiếu.
- d1: `approvals.decided_at` đặt ở approved / rejected / timeout (B16) và ở nhánh worker đóng phiếu khi ticket đã đi tiếp (`mark_fired`).

Graph: node GIẢ tới B15 (`l1-fake`, SLA 30 phút) + B16 chung. Hành động thật đặt vào checkpoint bằng `aupdate_state` khi cần nhãn.
"""

from datetime import timedelta
from typing import Any

import pytest
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_PENDING_APPROVAL, S_REJECTED
from app.graph.fakes import FAKE_ACTION
from app.graph.late_event import LateEvent, deliver_event
from app.graph.worker_jobs import WorkerJobs
from app.guard.privacy import guard_from_settings
from app.llm.registry import load_prompts
from app.settings import get_action_metadata, get_settings
from tests.fakes.desk import desk_env
from tests.fakes.graph import Crash, GraphHarness

pytestmark = pytest.mark.asyncio

APPROVER = "l1-fake"  # B15 giả (NodeDeps.approver_id mặc định)
PHONE = "0912345678"
NOTE = f"Máy không đúng chủ, liên hệ tôi qua {PHONE} nhé"
NOTE_MASKED = "Máy không đúng chủ, liên hệ tôi qua <SĐT_1> nhé"
POINT6 = {"view_duration", "decided_without_view", "decided_as", "reason_code", "close_applied"}
REJECTION_HEAD = "Yêu cầu gia hạn chứng chỉ VPN cho máy LAP-0501 chưa được duyệt. Lý do: sai máy."


def _vpn_action() -> Action:
    m = get_action_metadata().of("vpn")["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target="device:LAP-0501", requested_for="nv-fake", scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": "LAP-0501"}, facts={"device_owner_is_requester": True},
    )  # fmt: skip


async def _pending(h: GraphHarness, ticket: str = "t1", *, action: Action | None = None) -> dict[str, Any]:
    """Ticket tới chờ duyệt (B15 giả); `action` → đặt hành động thật (+ hash khớp) vào checkpoint. Trả dòng phiếu (bảng giả)."""
    await h.submit(ticket)
    if action is not None:
        await h.runner.graph.aupdate_state(
            h.runner.config(ticket), {"intended_action": action, "action_plan_hash": hash_action(action)}
        )
    snap = await h.runner.snapshot(ticket)
    assert (snap.values["status"], snap.next) == (S_PENDING_APPROVAL, ("approval_wait",))
    return h.deadlines.approvals[str(snap.values["approval_id"])]


def _event(h: GraphHarness, kind: str, **over: Any) -> dict[str, Any]:
    """Sự kiện như route duyệt dựng (2b-3 + 4c): `at` giờ app, `view_duration` tính dưới khoá lúc bấm, `decided_as`."""
    ev: dict[str, Any] = {"kind": kind, "note": None, "approver_id": APPROVER, "at": h.clock.now().isoformat(),
                          "reason_code": None, "view_duration": None, "decided_as": "primary"}  # fmt: skip
    ev.update(over)
    return ev


async def _decide(h: GraphHarness, ev: dict[str, Any], ticket: str = "t1") -> None:
    await deliver_event(h.runner, ticket, S_PENDING_APPROVAL, ev)


def _b16(h: GraphHarness, ticket: str = "t1") -> dict[str, Any]:
    rows = [r for r in h.audit.rows if r["ticket_id"] == ticket and r["step"] == "B16"]
    assert len(rows) == 1, h.audit.events(ticket)
    return rows[0]


def _rejections(h: GraphHarness, ticket: str = "t1") -> list[tuple[str, str, str]]:
    return [s for s in h.notifier.sent if s[0] == ticket and s[1].startswith("Yêu cầu")]


# ---- c1: tin từ chối -------------------------------------------------------------------------------------------------------


async def test_c1_rejection_one_message_phone_masked_in_message_audit_and_approval() -> None:
    """c1 + điều kiện Q-4c-1: ghi chú có SĐT (route giả không che SĐT) → B16 che → tin, `approvals.note`, cột `audit_logs.note`
    đều là bản đã che; đúng 1 tin `rejection`, `needs="none"`, ref của `notify_user`."""
    h = GraphHarness()
    await _pending(h, action=_vpn_action())
    await _decide(h, _event(h, "rejected", note=NOTE, reason_code="wrong_device"))
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["close_reason"]) == (S_REJECTED, "rejected_by_approver")
    text = f"{REJECTION_HEAD} Ghi chú của người duyệt: {NOTE_MASKED}"
    [(_, sent, needs)] = _rejections(h)
    assert (sent, needs) == (text, "none")
    msgs = [m for m in snap.values["conversation"] if m.get("kind") == "rejection"]
    assert len(msgs) == 1
    assert msgs[0] == {"role": "assistant", "kind": "rejection", "text": text, "ref": msgs[0]["ref"], "needs": "none"}
    assert msgs[0]["ref"] is not None
    row = _b16(h)
    assert (row["event"], row["note"], h.approvals._table["1"]["note"]) == ("rejected", NOTE_MASKED, NOTE_MASKED)
    everything = repr((h.audit.rows, h.approvals._table, h.notifier.sent, snap.values["conversation"]))
    assert PHONE not in everything
    assert h.effects.count("t1", "notify_user") == 1  # B20 không gửi thêm tin ở nhánh từ chối (không exit_code)


async def test_c1_crash_after_notify_before_audit_rerun_sends_once() -> None:
    """c1 "chạy lại": process chết SAU `notify_user`, TRƯỚC dòng audit B16 → phục hồi chạy lại B16 cùng lượt → `effects.once` trả ref
    cũ, KHÔNG gửi lần 2; sự kiện quyết định giao lần nữa → 409 (late), vẫn 1 tin."""
    h = GraphHarness()
    await _pending(h, action=_vpn_action())
    h.audit.crash_once.add("rejected")
    with pytest.raises(Crash):
        await _decide(h, _event(h, "rejected", note="không hợp lệ", reason_code="wrong_device"))
    assert len(_rejections(h)) == 1  # đã gửi trước khi chết
    h.restart(can_execute=False)
    h.clock.advance(timedelta(minutes=3))
    assert await WorkerJobs(h.runner, h.deadlines, h.turns).scan_stale_turns() == 1
    snap = await h.runner.snapshot("t1")
    assert snap.values["status"] == S_REJECTED
    assert len(_rejections(h)) == 1 and h.effects.count("t1", "notify_user") == 1
    assert len([m for m in snap.values["conversation"] if m.get("kind") == "rejection"]) == 1
    with pytest.raises(LateEvent):
        await _decide(h, _event(h, "rejected", note="lần hai", reason_code="other"))
    assert len(_rejections(h)) == 1


async def test_c1_crash_while_sending_then_recover_sends_once() -> None:
    """Chết NGAY khi gửi (chưa gửi được) → phục hồi gửi đúng 1 lần."""
    h = GraphHarness()
    await _pending(h, action=_vpn_action())
    h.notifier.crash_once.add("t1")
    with pytest.raises(Crash):
        await _decide(h, _event(h, "rejected", note="không hợp lệ"))
    assert _rejections(h) == []
    h.restart(can_execute=False)
    h.clock.advance(timedelta(minutes=3))
    assert await WorkerJobs(h.runner, h.deadlines, h.turns).scan_stale_turns() == 1
    assert len(_rejections(h)) == 1


async def test_c1_unlabeled_action_generic_sentence_not_e9() -> None:
    """TQ-1: hành động giả (gate2 `vpn_reset_session`, không nhãn) → câu chung, ticket vẫn `S_REJECTED` (không E9)."""
    h = GraphHarness()
    await _pending(h)
    assert (await h.runner.snapshot("t1")).values["intended_action"] == FAKE_ACTION
    await _decide(h, _event(h, "rejected", note="không", reason_code="duplicate"))
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values.get("exit_code")) == (S_REJECTED, None)
    [(_, sent, _)] = _rejections(h)
    assert sent == "Yêu cầu của bạn chưa được duyệt. Lý do: yêu cầu trùng lặp. Ghi chú của người duyệt: không"


async def test_c1_http_reject_with_phone_masked_for_requester() -> None:
    """c1 qua route thật (`desk_env`: guard giả chỉ che SECRET — SĐT do B16 che): người gửi đọc ticket thấy 1 tin `rejection`
    không còn SĐT; phiếu lưu bản đã che."""
    async with desk_env() as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        ticket = await env.create(an)
        await env.drain()
        aid = env.approval_of(ticket)
        r = await env.client.post(f"/api/approvals/{aid}/decision", headers=l1,
                                  json={"decision": "rejected", "note": NOTE, "reason_code": "wrong_device"})  # fmt: skip
        assert r.status_code == 202
        await env.drain()
        view = await env.ticket(ticket, an)
        assert view["status"] == S_REJECTED
        [msg] = [m for m in view["conversation"] if m.get("kind") == "rejection"]
        assert NOTE_MASKED in msg["text"] and PHONE not in repr(view)
        assert env.h.approvals._table[aid]["note"] == NOTE_MASKED


# ---- c2, c11: điểm log 6 ---------------------------------------------------------------------------------------------------


async def test_c2_point6_approved() -> None:
    h = GraphHarness()
    row = await _pending(h)
    approved_hash = (await h.runner.snapshot("t1")).values["action_plan_hash"]
    h.clock.advance(timedelta(seconds=90))
    await _decide(h, _event(h, "approved", view_duration=30.0))
    b16 = _b16(h)
    assert (b16["event"], b16["approval_result"], b16.get("note")) == ("approved", "approved", None)
    assert b16["response_time_seconds"] == 90.0
    # E12 (soát 12/11) — đổi có chủ ý: + người ĐÃ bấm, + hash hành động đã duyệt
    assert b16["detail"] == {"view_duration": 30.0, "decided_without_view": False, "decided_as": "primary",
                             "reason_code": None, "close_applied": 1, "approver_id": APPROVER,
                             "action_plan_hash": approved_hash}  # fmt: skip
    assert row["decided_at"] == h.clock.now()  # d1


async def test_c2_point6_rejected() -> None:
    h = GraphHarness()
    row = await _pending(h, action=_vpn_action())
    h.clock.advance(timedelta(seconds=45))
    await _decide(h, _event(h, "rejected", note="không hợp lệ", reason_code="policy_violation", view_duration=12.5))
    b16 = _b16(h)
    assert (b16["approval_result"], b16["note"], b16["response_time_seconds"]) == ("rejected", "không hợp lệ", 45.0)
    assert set(b16["detail"]) == POINT6 | {"note_suppressed", "approver_id"}  # E12 (12/11): + người đã bấm
    assert b16["detail"] == {"view_duration": 12.5, "decided_without_view": False, "decided_as": "primary",
                             "reason_code": "policy_violation", "close_applied": 1, "note_suppressed": False,
                             "approver_id": APPROVER}  # fmt: skip
    assert row["decided_at"] == h.clock.now()  # d1


async def test_c2_point6_timeout_response_time_null() -> None:
    h = GraphHarness()
    row = await _pending(h)
    h.clock.advance(timedelta(minutes=31))
    assert (await WorkerJobs(h.runner, h.deadlines, h.turns).scan_deadlines()).delivered == 1
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"]) == (S_ESCALATED, "E6")
    b16 = _b16(h)
    assert (b16["event"], b16["approval_result"], b16.get("note"), b16.get("response_time_seconds")) == (
        "approval_timeout", "timeout", None, None)
    assert b16["detail"] == {"view_duration": None, "decided_without_view": True, "decided_as": None,
                             "reason_code": None, "close_applied": 1}  # fmt: skip
    assert (row["status"], row["decided_at"]) == ("timeout", h.clock.now())  # d1


async def test_c2_timeout_after_view_decided_without_view_false() -> None:
    """TQ-5: nhánh timeout lấy `decided_without_view` từ `first_viewed_at` của phiếu."""
    h = GraphHarness()
    row = await _pending(h)
    row["first_viewed_at"] = h.clock.now() + timedelta(minutes=5)
    h.clock.advance(timedelta(minutes=31))
    await WorkerJobs(h.runner, h.deadlines, h.turns).scan_deadlines()
    assert _b16(h)["detail"]["decided_without_view"] is False


async def test_c11_approved_without_view() -> None:
    """c11: duyệt không xem (route gửi `view_duration=None`) → `decided_without_view=true`, `view_duration=null`."""
    h = GraphHarness()
    await _pending(h)
    await _decide(h, _event(h, "approved"))
    detail = _b16(h)["detail"]
    assert (detail["decided_without_view"], detail["view_duration"]) == (True, None)


async def test_c2_close_applied_zero_when_already_closed() -> None:
    """TQ-4: phiếu đã đóng trước khi B16 chạy (vd chạy lại) → `close` không đổi dòng → `close_applied=0`."""
    h = GraphHarness()
    row = await _pending(h)
    row.update(status="approved", decided_at=h.clock.now(), decided_by=APPROVER)
    await _decide(h, _event(h, "approved"))
    assert _b16(h)["detail"]["close_applied"] == 0


# ---- d1: decided_at ở nhánh worker đóng phiếu (ticket đã đi tiếp) ------------------------------------------------------------


async def test_d1_mark_fired_late_path_sets_decided_at() -> None:
    """d1 (A11): phiếu `pending` quá hạn mà ticket đã đi tiếp → worker 409 (late) → `mark_fired` đóng `timeout` + `decided_at`."""
    h = GraphHarness()
    await h.submit("t1", b12_assess="auto")
    assert (await h.runner.snapshot("t1")).values["status"] == S_CONFIRMING
    h.deadlines.approvals["9"] = {"ticket_id": "t1", "approver_id": APPROVER, "status": "pending",
                                  "deadline": h.clock.now() - timedelta(seconds=1), "created_at": h.clock.now()}  # fmt: skip
    report = await WorkerJobs(h.runner, h.deadlines, h.turns).scan_deadlines()
    assert report.late == 1
    assert (h.deadlines.approvals["9"]["status"], h.deadlines.approvals["9"].get("decided_at")) == ("timeout", h.clock.now())


# ---- d7: output guard chặn ghi chú -------------------------------------------------------------------------------------------


def _system_line() -> str:
    """Một đoạn ≥ 40 ký tự của dòng `system` trong prompt đã nạp — output guard coi là lộ prompt; privacy guard L1 để nguyên."""
    redactor = guard_from_settings(get_settings())
    for prompt in load_prompts(get_settings().config_dir / "prompts"):
        for line in prompt.spec.system.splitlines():
            line = line.strip()
            if len(line) >= 60 and redactor.redact_text(line).text == line:
                return line
    raise AssertionError("không có dòng system nào dùng được")


async def test_d7_output_guard_blocks_note_suppressed() -> None:
    h = GraphHarness()
    await _pending(h, action=_vpn_action())
    leaked = _system_line()
    await _decide(h, _event(h, "rejected", note=leaked, reason_code="wrong_device"))
    [(_, sent, _)] = _rejections(h)
    assert sent == REJECTION_HEAD and "Ghi chú" not in sent
    b16 = _b16(h)
    assert b16["detail"]["note_suppressed"] is True
    assert b16["note"] == leaked and h.approvals._table["1"]["note"] == leaked  # đã che L1 (không đổi); CHECK rejected_needs_note
