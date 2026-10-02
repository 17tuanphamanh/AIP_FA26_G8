"""E2E cổng 4 — phần DỪNG 1 của chặng 4d (phase4 mục 7.3 i8b, i13, i14, i14b, i16, i17; PLAN-4d mục 2.1 "e2e", mục 3, mục 9 điều
kiện 3). Viết TỪ ĐẶC TẢ trước thân code. i8a (đổi checkpoint sau duyệt — crash + recover) và i8c (đổi lúc chờ → cấm 3 → E9) do agent
chính viết (sau i8b); i1–i7, i9–i12, i15 riêng lẻ là DỪNG 2 (i16 tự chạy
luồng i1, i2 bên trong).

Môi trường = `gate3_env` (create_app + `_open` node THẬT + `VpnExecutor`, mock THẬT, Postgres + Qdrant testcontainer, KB ingest thật,
ScriptedLLM `vpn_scripts`, FakeClock) + bước HITL chung ở `gate4_env`. Ca HITL chuẩn: nv003 `chau.hm` "gia hạn VPN cho máy LAP-0501"
→ R19 (mọi giờ) → phiếu l1_01 (`ha.lt`), dự phòng l1_02 (`duc.pv`). Lời gọi GHI đếm ở NƠI NHẬN (mock).

Mỗi test thêm ticket của nó vào `TICKETS` (cấp module); **i17 đặt CUỐI file** quét `audit_check` trên đúng danh sách đó; chạy riêng i17
(danh sách rỗng) → FAIL rõ lý do (điều kiện 3), không xanh giả.
"""

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from app.audit.check import Missing, SecretHit, load, readonly_engine, render, run
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import S_ESCALATED, S_PENDING_APPROVAL
from app.executor.txlog import SqlTxLog
from app.guard.privacy import NOTICE_SECRET
from sqlalchemy.ext.asyncio import create_async_engine
from tests.e2e.gate3_env import (
    api,
    at_ict,
    audit_detail,
    audit_events,
    escalation,
    gate3,
    open_turn,
    rows,
    scalar,
)
from tests.e2e.gate4_env import (
    APPROVER,
    B3_FULL,
    BACKUP,
    CHAU,
    HITL_TEXT,
    OTHER_DEVICE_TEXT,
    OVERRIDE_ROUTE,
    approval_id,
    audit_report,
    control_ticket,
    decide,
    execute,
    override,
    override_rows,
    pending_hitl,
    plant_row,
    rejected_hitl,
    resolved_hitl,
    scanner,
    side_counts,
    ticket_row,
    writes,
)
from tests.e2e.mock_server import MockServer
from tests.fakes.graph import Crash
from tests.fixtures.llm.vpn import vpn_scripts
from tests.integration.pg import PgUrls
from tests.integration.scan import tables_containing
from tests.integration.test_guard_pg import _decoded_checkpoints

pytestmark = pytest.mark.asyncio

TICKETS: list[str] = []  # ticket của MỌI test trong file — i17 (cuối file) quét audit_check trên danh sách này
CHANGED = "action_plan_changed_since_approval"
FORBIDDEN = {"detail": "forbidden"}
REAUTH = {"detail": "reauth_required"}
TICKET_OPEN = {"detail": "ticket_open"}
SAME = {"detail": "same_as_original"}
ALREADY = {"detail": "already_overridden"}
MASK = "[BÍ_MẬT_ĐÃ_ẨN]"
_I14_PARTS, _I16_PARTS = ("Canary#4d", "i14", "w3"), ("Canary#4d", "i16", "x9q")
CANARY_I14 = "-".join(_I14_PARTS)  # ghép lúc chạy (gitleaks)
CANARY_I16 = "-".join(_I16_PARTS)


@dataclass(frozen=True)
class Stack:
    pg: PgUrls
    qdrant_url: str
    mock: MockServer


@pytest.fixture
def stack(migrated: PgUrls, qdrant_url: str, kb: None, mock_server: MockServer, reset: None) -> Stack:
    return Stack(migrated, qdrant_url, mock_server)


def _key(ticket: str, overrider: str) -> str:
    return hashlib.sha256(("override:" + ticket + ":" + overrider).encode()).hexdigest()


async def _denied(rw: Any, user_id: str, reason: str) -> list[dict[str, Any]]:
    return [dict(r[0]) for r in await rows(
        rw, "SELECT detail FROM security_events WHERE event_type = 'permission_denied' AND user_id = :u AND route = :r "
            "AND detail->>'reason' = :reason ORDER BY event_id", u=user_id, r=OVERRIDE_ROUTE, reason=reason)]  # fmt: skip


# ---- i8b: P7 — hash PHIẾU bị đổi lúc chờ → duyệt → B17 E5 ------------------------------------------------------------------------


async def test_i8b_approval_hash_changed_while_pending_e5_zero_writes(stack: Stack) -> None:
    """i8b (P7, TQ-10, M-4d-10): phiếu chờ → `UPDATE approvals SET action_plan_hash` (hash khác, 64 hex) → ha.lt duyệt (202) → B17
    lớp 2 → E5 `action_plan_changed_since_approval`, `detail.hash_source = "approval"`, `action_plan_hash_matched = false`, 0 lời gọi
    ghi (đếm ở mock), 0 dòng `transaction_log`."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        other_hash = hashlib.sha256(b"i8b: ke hoach khac").hexdigest()
        assert await execute(p.rw, "UPDATE approvals SET action_plan_hash = :h WHERE approval_id = :a",
                             h=other_hash, a=int(aid)) == 1  # fmt: skip
        r = await decide(a, aid, APPROVER)
        assert r.status_code == 202, r.text
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E5"), view
    assert (await escalation(p.rw, ticket))[:2] == ("E5", CHANGED)
    detail = await audit_detail(p.rw, ticket, "B17", CHANGED)
    assert (detail["hash_source"], detail["action_plan_hash_matched"], detail["write_calls"]) == ("approval", False, 0)
    assert await writes(stack.mock) == 0
    assert await rows(p.rw, "SELECT status FROM transaction_log WHERE ticket_id = :t", t=ticket) == []


# ---- i8a: TC26 — đổi `intended_action` SAU khi duyệt, TRƯỚC B17 → B17 lớp 1 (hash state) E5 -----------------------------------------


def _crash_b17_once(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Process "chết" ở lời gọi `has_begun` ĐẦU TIÊN của B17 (bước 0) — tức SAU checkpoint của B16 (`S_EXECUTING`, đã duyệt), TRƯỚC mọi
    bước kiểm của B17. Trên đường resume B16 → B17, `has_begun` chỉ B17 gọi (boundary/runner chỉ gọi khi lỗi / cạn lượt). Bật bằng cờ."""
    armed = {"on": False}
    original = SqlTxLog.has_begun

    async def has_begun(self: SqlTxLog, ticket_id: str) -> bool:
        if armed["on"]:
            armed["on"] = False
            raise Crash("process chết sau checkpoint của B16, trước B17")
        return await original(self, ticket_id)

    monkeypatch.setattr(SqlTxLog, "has_begun", has_begun)
    return armed


async def test_i8a_intended_action_changed_after_approval_before_b17_e5_zero_writes(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """i8a (TC26, TQ-10 — agent chính viết): ha.lt duyệt → B16 chuyển `S_EXECUTING` (checkpoint) → process chết đầu B17 → `intended_action`
    trong checkpoint bị đổi (thêm tham số; `action_plan_hash` của state lẫn phiếu GIỮ) → API `recover` (khuôn h15) → B17 so
    `hash_action(action)` với hash state (lớp 1) → E5 `action_plan_changed_since_approval`, không `hash_source` (lớp 2 không chạy), 0 lời
    gọi ghi, 0 dòng `transaction_log`. Không thêm hook vào B17 (lõi). Đổi TRƯỚC khi duyệt thì cấm 3 ở B16 chặn trước — xem i8c."""
    crash = _crash_b17_once(monkeypatch)
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        crash["on"] = True
        r = await decide(a, aid, APPROVER)
        assert r.status_code == 202, r.text
        assert crash["on"] is False, "B17 chưa chạy tới bước 0"
        runner = a.app.state.desk.runner
        values = (await runner.snapshot(ticket)).values
        assert (values["status"], values["approval_result"]) == ("S_EXECUTING", "approved")
        action = Action.model_validate(values["intended_action"])
        tampered = action.model_copy(update={"params": {**action.params, "duration_days": 365}})
        assert hash_action(tampered) != hash_action(action) == values["action_plan_hash"]
        await runner.graph.aupdate_state(runner.config(ticket), {"intended_action": tampered}, as_node="approval_wait")
        await runner.recover(ticket, await open_turn(p.rw, ticket))
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E5"), view
    assert (await escalation(p.rw, ticket))[:2] == ("E5", CHANGED)
    detail = await audit_detail(p.rw, ticket, "B17", CHANGED)
    assert "hash_source" not in detail
    assert (detail["hash_old"], detail["hash_new"]) == (hash_action(action), hash_action(tampered))
    assert detail["action_plan_hash_matched"] is False
    assert await writes(stack.mock) == 0
    assert await rows(p.rw, "SELECT status FROM transaction_log WHERE ticket_id = :t", t=ticket) == []


async def test_i8c_intended_action_changed_while_pending_blocked_by_f3_e9_zero_writes(stack: Stack) -> None:
    """i8c (lớp có từ Phase 2 — ghim lại ở cổng 4, lộ ra khi viết i8a): `intended_action` trong checkpoint bị đổi lúc phiếu CÒN CHỜ →
    ha.lt duyệt → B16 chuyển `S_PENDING_APPROVAL → S_EXECUTING` bị cấm 3 (`F3_plan_hash_mismatch`, hash state ≠ hash hành động) →
    boundary E9; B17 không chạy, 0 lời gọi ghi, 0 dòng `transaction_log`."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        runner = a.app.state.desk.runner
        action = Action.model_validate((await runner.snapshot(ticket)).values["intended_action"])
        tampered = action.model_copy(update={"params": {**action.params, "duration_days": 365}})
        await runner.graph.aupdate_state(runner.config(ticket), {"intended_action": tampered})
        r = await decide(a, aid, APPROVER)
        assert r.status_code == 202, r.text
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E9"), view
    assert not [e for e in await audit_events(p.rw, ticket) if e[0] == "B17"]
    assert await writes(stack.mock) == 0
    assert await rows(p.rw, "SELECT status FROM transaction_log WHERE ticket_id = :t", t=ticket) == []


# ---- i13: ghi đè ticket i1 bởi l1_02 -------------------------------------------------------------------------------------------------


async def test_i13_override_resolved_ticket_by_l1_02_one_row_ticket_unchanged(stack: Stack) -> None:
    """i13 (TC23, P4, M-4d-1, M-4d-5): ticket i1 (`S_RESOLVED`, quyết định gốc HITL — R19) → duc.pv ghi đè HITL→L2 → 201; đúng 1 dòng
    `step='OVERRIDE'` đủ cột; dòng `tickets` trước = sau (cả dòng); lượt/checkpoint/phiếu/side effect/escalation/txlog không đổi; 0 lời
    gọi ghi thêm; lần 2 → 409 `already_overridden`, vẫn 1 dòng."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await resolved_hitl(a, stack.mock)
        TICKETS.append(ticket)
        before_row = await ticket_row(p.rw, ticket)
        before_counts = await side_counts(p.rw, ticket)
        before_writes = await writes(stack.mock)
        r = await override(a, ticket, BACKUP, override_decision="L2", reason_code="too_risky_for_auto")
        assert r.status_code == 201, r.text
        assert r.json() == {"ticket_id": ticket, "original_decision": "HITL", "override_decision": "L2",
                            "reason_code": "too_risky_for_auto", "notices": []}  # fmt: skip
        again = await override(a, ticket, BACKUP, override_decision="AUTO", reason_code="other", note="đổi ý")
        assert (again.status_code, again.json()) == (409, ALREADY)
        at = p.clock.now()
    [row] = await override_rows(p.rw, ticket)
    assert row == {
        "created_at": at, "turn_id": None, "from_status": None, "to_status": None, "original_decision": "HITL",
        "override_decision": "L2", "overrider_id": "l1_02", "note": None, "detail": {"reason_code": "too_risky_for_auto"},
        "idempotency_key": _key(ticket, "l1_02"),
    }  # fmt: skip
    assert await ticket_row(p.rw, ticket) == before_row
    assert await side_counts(p.rw, ticket) == before_counts
    assert await writes(stack.mock) == before_writes == 1


# ---- i14: người gửi / ticket mở / same_as_original / note có mật khẩu ---------------------------------------------------------------


async def test_i14_requester_self_override_403_permission_denied(stack: Stack) -> None:
    """i14 (`can_override`, M-4d-12): ha.lt (l1, có `decision:override`) tự gửi ticket rồi tự ghi đè → 403 `forbidden` + đúng 1
    `permission_denied {perm, ticket_id, reason: self_override}`; 0 dòng OVERRIDE."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await a.create(APPROVER, OTHER_DEVICE_TEXT)
        TICKETS.append(ticket)
        r = await override(a, ticket, APPROVER, override_decision="L2", reason_code="policy_gap")
        assert (r.status_code, r.json()) == (403, FORBIDDEN)
    assert await _denied(p.rw, "l1_01", "self_override") == [
        {"perm": "decision:override", "ticket_id": ticket, "reason": "self_override"}]  # fmt: skip
    assert await override_rows(p.rw, ticket) == []


async def test_i14_open_ticket_409(stack: Stack) -> None:
    """i14 (M-4d-4): ticket còn chờ duyệt (`final_state` NULL) → 409 `ticket_open`; 0 dòng, ticket không đổi, phiếu vẫn pending."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        before = await ticket_row(p.rw, ticket)
        r = await override(a, ticket, BACKUP, override_decision="L2", reason_code="policy_gap")
        assert (r.status_code, r.json()) == (409, TICKET_OPEN)
        assert (await a.view(ticket, CHAU))["status"] == S_PENDING_APPROVAL
    assert await override_rows(p.rw, ticket) == []
    assert await ticket_row(p.rw, ticket) == before
    assert await scalar(p.rw, "SELECT status FROM approvals WHERE approval_id = :a", a=int(aid)) == "pending"


async def test_i14_same_as_original_422_then_password_note_redacted(stack: Stack) -> None:
    """i14 (M-4d-11, M-4d-3): ticket i2 (từ chối, gốc HITL) → ghi đè HITL → 422 `same_as_original` (0 dòng, không sự kiện bí mật);
    ghi đè L2 + `other` + note có mật khẩu → 201 `notices == [NOTICE_SECRET]`, cột `note` đã che, đúng 1 `privacy_secret_redacted`
    (route ghi đè), canary không ở bảng nào."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await rejected_hitl(a)
        TICKETS.append(ticket)
        same = await override(a, ticket, BACKUP, override_decision="HITL", reason_code="other", note=f"mật khẩu là {CANARY_I14}")
        assert (same.status_code, same.json()) == (422, SAME)
        assert await override_rows(p.rw, ticket) == []
        r = await override(a, ticket, BACKUP, override_decision="L2", reason_code="other",
                           note=f"người dùng gửi mật khẩu của tôi là {CANARY_I14} trong ticket")  # fmt: skip
        assert r.status_code == 201, r.text
        assert r.json()["notices"] == [NOTICE_SECRET] and r.json()["original_decision"] == "HITL"
    [row] = await override_rows(p.rw, ticket)
    assert MASK in str(row["note"]) and CANARY_I14 not in str(row["note"])
    assert await rows(p.rw, "SELECT detail FROM security_events WHERE event_type = 'privacy_secret_redacted' "
                            "AND ticket_id = :t AND route = :r", t=ticket, r=OVERRIDE_ROUTE) == [({"count": 1},)]  # fmt: skip
    assert await tables_containing(p.rw, CANARY_I14) == []


# ---- i14b: đăng nhập > 10 phút -----------------------------------------------------------------------------------------------------


async def test_i14b_login_older_than_10_minutes_403_then_relogin_201(stack: Stack) -> None:
    """i14b (P1, M-4d-2): duc.pv đăng nhập → FakeClock +11 phút (access token 15 phút còn hạn) → 403 `reauth_required`, 0 dòng
    OVERRIDE, đúng 1 `permission_denied` reason `reauth_required` trên route ghi đè; đăng nhập lại → 201."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await rejected_hitl(a)
        TICKETS.append(ticket)
        await a.login(BACKUP)
        p.clock.advance(timedelta(minutes=11))
        r = await override(a, ticket, BACKUP, override_decision="L2", reason_code="policy_gap")
        assert (r.status_code, r.json()) == (403, REAUTH)
        assert await override_rows(p.rw, ticket) == []
        assert await _denied(p.rw, "l1_02", "reauth_required") == [{"perm": "decision:override", "reason": "reauth_required"}]
        await a.login(BACKUP)
        r = await override(a, ticket, BACKUP, override_decision="L2", reason_code="policy_gap")
        assert r.status_code == 201, r.text
    assert len(await override_rows(p.rw, ticket)) == 1


# ---- i16: canary qua i1 + i2 + i13 ----------------------------------------------------------------------------------------------------


async def test_i16_canary_nowhere_after_i1_i2_i13_and_audit_check_not_blind(
    stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    """i16 (như e9, M-4d-8): mật khẩu-canary trong câu yêu cầu, note duyệt, note xác nhận (i1), note từ chối (i2), note ghi đè (i13)
    — guard regex MẶC ĐỊNH của `create_app`. Sau cùng: canary không ở bảng/cột nào (`tables_containing`), checkpoint giải mã, log;
    `audit_check.run --canary` trên các ticket đó: 0 trúng. ĐỐI CHỨNG không mù: ticket riêng có canary cài thẳng vào
    `audit_logs.detail` bằng SQL → `run` trúng đúng `SecretHit(ctl, "audit_logs.detail", log_id, "canary")`."""
    caplog.set_level(logging.DEBUG)
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        await a.login(APPROVER)
        await a.login(CHAU)
        r = await a.client.post("/api/tickets", json={"text": f"{HITL_TEXT}, mật khẩu của tôi là {CANARY_I16}"},
                                headers=a.tokens[CHAU])  # fmt: skip
        assert r.status_code == 202 and r.json()["notices"] == [NOTICE_SECRET], r.text
        t1 = str(r.json()["ticket_id"])
        TICKETS.append(t1)
        await a.drain()
        assert (await a.view(t1, CHAU))["status"] == S_PENDING_APPROVAL
        steps: Sequence[tuple[str, Mapping[str, Any], str]] = (
            (f"/api/approvals/{await approval_id(p.rw, t1)}/decision", {"decision": "approved", "note": f"ok, mk: {CANARY_I16}"},
             APPROVER),
            (f"/api/tickets/{t1}/confirm", {"confirmed": True, "note": f"xong, mật khẩu mới là {CANARY_I16}"}, CHAU),
        )  # fmt: skip
        for path, body, who in steps:
            r = await a.post(path, body, who)
            assert r.status_code == 202 and r.json()["notices"] == [NOTICE_SECRET], (path, r.text)
        assert (await a.view(t1, CHAU))["final_state"] == "S_RESOLVED"
        assert await writes(stack.mock) == 1

        t2, aid2 = await pending_hitl(a)
        TICKETS.append(t2)
        r = await decide(a, aid2, APPROVER, decision="rejected", note=f"không duyệt, pass: {CANARY_I16}")
        assert r.status_code == 202 and r.json()["notices"] == [NOTICE_SECRET], r.text
        assert (await a.view(t2, CHAU))["final_state"] == "S_REJECTED"

        r = await override(a, t1, BACKUP, override_decision="L2", reason_code="other", note=f"mật khẩu là {CANARY_I16}")
        assert r.status_code == 201 and r.json()["notices"] == [NOTICE_SECRET], r.text
    assert await writes(stack.mock) == 1

    assert await tables_containing(p.rw, CANARY_I16) == []
    for ticket in (t1, t2):
        decoded = await _decoded_checkpoints(p.rw, ticket)
        assert CANARY_I16 not in decoded, ticket
    assert MASK in await _decoded_checkpoints(p.rw, t1)  # đối chứng: bản đã che có mặt (quét không mù)
    assert CANARY_I16 not in caplog.text
    report = await audit_report(stack.pg, [t1, t2], [CANARY_I16])
    assert list(report.secrets) == [], render(report)

    ctl = await control_ticket(p.rw)
    log_id = await plant_row(p.rw, ctl, "B3", "intent_classified", {**B3_FULL, "ghi_chu": {"x": [f"lọt {CANARY_I16}"]}},
                             intent="vpn")  # fmt: skip
    leaked = await audit_report(stack.pg, [ctl], [CANARY_I16])
    assert list(leaked.secrets) == [SecretHit(ctl, "audit_logs.detail", log_id, "canary")]
    assert CANARY_I16 not in render(leaked)


# ---- i17 (CUỐI FILE): audit_check trên mọi ticket của file -------------------------------------------------------------------------


_POINT_ROWS: dict[int, set[tuple[str, str]]] = {
    1: {("B3", "intent_classified")}, 2: {("B6", "diagnosed")}, 3: {("B8", "retrieved"), ("B8", "retrieval_error"), ("B9", "no_evidence")},
    4: {("B13/B14", "risk_decided")}, 5: {("B15", "queued")}, 6: {("B16", "approved"), ("B16", "rejected"), ("B16", "approval_timeout")},
    7: {("B18", "executed_ok"), ("B17", "exec_failed"), ("B17", "exec_interrupted")},
}  # fmt: skip
_STEP_ONLY = {1: "B4", 2: "B7"}  # điểm 1: mọi dòng B4; điểm 2: mọi dòng B7 (bảng mục 4 PLAN-4d)


def _covered(rows_by_ticket: Mapping[str, Sequence[Mapping[str, Any]]], finals: Mapping[str, str | None]) -> set[int]:
    """Điểm log 1–8 có ÍT NHẤT một dòng áp dụng trong các ticket đã quét (bảng mục 4 PLAN-4d)."""
    covered = set()
    for ticket, found in rows_by_ticket.items():
        pairs = {(str(r["step"]), str(r["event"])) for r in found}
        for point, wanted in _POINT_ROWS.items():
            if pairs & wanted or any(step == _STEP_ONLY.get(point) for step, _ in pairs):
                covered.add(point)
        if finals.get(ticket) is not None and ("B20", "closed") in pairs:
            covered.add(8)
    return covered


async def test_i17_audit_check_every_ticket_of_this_file(migrated: PgUrls) -> None:
    """i17 (P5, bảng điểm mục 4 đã chốt, M-4d-9): `audit_check` trên MỌI ticket mà các test trên đã tạo → 0 thiếu, 0 bí mật; danh
    sách phủ đủ điểm 1–8. Điều kiện 3: danh sách rỗng (chạy riêng i17) → FAIL rõ lý do. ĐỐI CHỨNG: ticket riêng + dòng B15 `queued`
    thiếu `approver_id` (SQL) → `Missing(point=5)` có `approver_id`."""
    if not TICKETS:
        pytest.fail("i17 cần chạy cùng cả file test_gate4_hitl.py — danh sách ticket rỗng")
    engine = readonly_engine(migrated.role("app_rw"))
    try:
        rows_by_ticket, finals = await load(engine, tickets=list(TICKETS))
        assert set(rows_by_ticket) == set(TICKETS), sorted(set(TICKETS) - set(rows_by_ticket))
        assert _covered(rows_by_ticket, finals) == set(range(1, 9)), _covered(rows_by_ticket, finals)
        report = await run(engine, tickets=list(TICKETS), scanner=scanner([CANARY_I14, CANARY_I16]))
    finally:
        await engine.dispose()
    assert list(report.missing) == [], render(report)
    assert list(report.secrets) == [], render(report)
    assert report.ok is True

    rw = create_async_engine(migrated.role("app_rw"))
    try:
        ctl = await control_ticket(rw)
        log_id = await plant_row(rw, ctl, "B15", "queued", {"choice_reason": "primary"}, deadline=at_ict(10).now(),
                                 conflict_detected=False, action_plan_hash="b" * 64)  # fmt: skip
    finally:
        await rw.dispose()
    broken = await audit_report(migrated, [ctl], [])
    assert list(broken.missing) == [Missing(ctl, 5, log_id, ("approver_id",))]
