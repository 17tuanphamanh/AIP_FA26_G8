"""E2E cổng 4 — chặng 4d (phase4 mục 7.3). DỪNG 1: i8b, i13, i14, i14b, i16, i17 (test-writer, viết TỪ ĐẶC TẢ trước thân code;
PLAN-4d mục 2.1 "e2e", mục 3, mục 9 điều kiện 3) + i8a, i8c (agent chính). DỪNG 2 (PLAN-4d mục 11): Q-4d-3 — i8b/i8c nay E5 ở B16,
i8d (B17 lớp 2 sau crash + recover); i1–i7, i9–i12, i15 (agent chính — kiểm hành vi 4b/4c đã có, răng chứng bằng bảng nối MẪU B).

Môi trường = `gate3_env` (create_app + `_open` node THẬT + `VpnExecutor`, mock THẬT, Postgres + Qdrant testcontainer, KB ingest thật,
ScriptedLLM `vpn_scripts`, FakeClock) + bước HITL chung ở `gate4_env`. Ca HITL chuẩn: nv003 `chau.hm` "gia hạn VPN cho máy LAP-0501"
→ R19 (mọi giờ) → phiếu l1_01 (`ha.lt`), dự phòng l1_02 (`duc.pv`). Lời gọi GHI đếm ở NƠI NHẬN (mock).

Mỗi test thêm ticket của nó vào `TICKETS` (cấp module); **i17 đặt CUỐI file** quét `audit_check` trên đúng danh sách đó; chạy riêng i17
(danh sách rỗng) → FAIL rõ lý do (điều kiện 3), không xanh giả.
"""

import asyncio
import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from app.audit.check import Missing, SecretHit, load, readonly_engine, render, run
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_PENDING_APPROVAL
from app.executor.txlog import SqlTxLog
from app.graph.fakes import FakeScenario
from app.graph.nodes import b12_assess
from app.guard.privacy import NOTICE_SECRET
from app.risk.models import RuleVerdict
from sqlalchemy.ext.asyncio import create_async_engine
from tests.e2e.gate3_env import (
    admin,
    api,
    at_ict,
    audit_detail,
    audit_events,
    calls,
    escalation,
    gate3,
    open_turn,
    rows,
    scalar,
    worker,
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
    login_manager,
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


async def test_i8b_approval_hash_changed_while_pending_e5_at_b16_zero_writes(stack: Stack) -> None:
    """i8b (P7 + Q-4d-3, M-4d-15/16): phiếu chờ → `UPDATE approvals SET action_plan_hash` (hash khác, 64 hex) → ha.lt duyệt (202) →
    B16 so hash PHIẾU (lớp 2 của B16 — DỪNG 2; trước đó B17 bắt) → E5 `action_plan_changed_since_approval` step **B16**,
    `detail.hash_source = "approval"`, `action_plan_hash_matched = false`; phiếu vẫn `approved` (TQ-14a); B17 không chạy, 0 lời gọi ghi
    (đếm ở mock), 0 dòng `transaction_log`. B17 lớp 2 trên e2e: i8d."""
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
    detail = await audit_detail(p.rw, ticket, "B16", CHANGED)
    assert (detail["hash_source"], detail["hash_old"], detail["action_plan_hash_matched"]) == ("approval", other_hash, False)
    assert not [e for e in await audit_events(p.rw, ticket) if e[0] == "B17"]
    assert await scalar(p.rw, "SELECT status FROM approvals WHERE approval_id = :a", a=int(aid)) == "approved"
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
    gọi ghi, 0 dòng `transaction_log`. Không thêm hook vào B17 (lõi). Đổi TRƯỚC khi duyệt thì B16 chặn trước (Q-4d-3) — xem i8c."""
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


async def test_i8c_intended_action_changed_while_pending_e5_at_b16_zero_writes(stack: Stack) -> None:
    """i8c (TC26 lúc chờ, Q-4d-3 — đổi kỳ vọng E9 → E5 ở DỪNG 2): `intended_action` trong checkpoint bị đổi lúc phiếu CÒN CHỜ → ha.lt
    duyệt → B16 so hash STATE trước `goto(S_EXECUTING)` → E5 `action_plan_changed_since_approval` step B16, `hash_source = "state"`,
    `hash_old`/`hash_new`; KHÔNG còn `IllegalTransition` F3 → E9 (không dòng `unhandled_exception`); B17 không chạy, 0 lời gọi ghi, 0
    dòng `transaction_log`. Cấm F3 vẫn là lớp cuối (M-4d-15 tắt so hash ở B16 → i8c ra lại E9)."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        runner = a.app.state.desk.runner
        values = (await runner.snapshot(ticket)).values
        action = Action.model_validate(values["intended_action"])
        tampered = action.model_copy(update={"params": {**action.params, "duration_days": 365}})
        await runner.graph.aupdate_state(runner.config(ticket), {"intended_action": tampered})
        r = await decide(a, aid, APPROVER)
        assert r.status_code == 202, r.text
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E5"), view
    assert (await escalation(p.rw, ticket))[:2] == ("E5", CHANGED)
    detail = await audit_detail(p.rw, ticket, "B16", CHANGED)
    assert (detail["hash_source"], detail["hash_old"], detail["hash_new"]) == (
        "state", values["action_plan_hash"], hash_action(tampered))
    assert detail["action_plan_hash_matched"] is False
    events = await audit_events(p.rw, ticket)
    assert not [e for e in events if e[0] == "B17" or e[1] == "unhandled_exception"], events
    assert await writes(stack.mock) == 0
    assert await rows(p.rw, "SELECT status FROM transaction_log WHERE ticket_id = :t", t=ticket) == []


async def test_i8d_approval_hash_changed_after_b16_checkpoint_b17_layer2_e5(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """i8d (P7, M-4d-10 — giữ răng e2e cho B17 lớp 2 sau Q-4d-3): ha.lt duyệt → B16 qua (hash khớp) → checkpoint `S_EXECUTING` →
    process chết đầu B17 (khuôn i8a) → `UPDATE approvals SET action_plan_hash` (hash phiếu đổi SAU khi B16 đã so) → API `recover` → B17
    lớp 1 qua (state khớp), lớp 2 bắt → E5 step B17 `hash_source = "approval"`, 0 lời gọi ghi, 0 dòng `transaction_log`."""
    crash = _crash_b17_once(monkeypatch)
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        crash["on"] = True
        r = await decide(a, aid, APPROVER)
        assert r.status_code == 202, r.text
        assert crash["on"] is False, "B17 chưa chạy tới bước 0"
        runner = a.app.state.desk.runner
        assert (await runner.snapshot(ticket)).values["status"] == "S_EXECUTING"
        other_hash = hashlib.sha256(b"i8d: ke hoach khac").hexdigest()
        assert await execute(p.rw, "UPDATE approvals SET action_plan_hash = :h WHERE approval_id = :a",
                             h=other_hash, a=int(aid)) == 1  # fmt: skip
        await runner.recover(ticket, await open_turn(p.rw, ticket))
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E5"), view
    assert (await escalation(p.rw, ticket))[:2] == ("E5", CHANGED)
    assert ("B16", "approved") in await audit_events(p.rw, ticket)
    detail = await audit_detail(p.rw, ticket, "B17", CHANGED)
    assert (detail["hash_source"], detail["hash_old"], detail["action_plan_hash_matched"]) == ("approval", other_hash, False)
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


# ---- DỪNG 2 (S7, PLAN-4d mục 11.4): i1–i7, i9–i12, i15 — kiểm hành vi 4b/4c ĐÃ CÓ trên stack e2e (TQ-11) ---------------------------


async def _relogin(a: Any, *users: str) -> None:
    """Access token sống 15 phút — tua FakeClock quá đó thì đăng nhập lại (refresh chưa cần ở e2e)."""
    for username in users:
        await a.login(username)


async def _created_at_app_clock(p: Any, aid: str, at: datetime) -> None:
    """`approvals.created_at` theo giờ DB (`now()` — 6.4 #7), mốc nhắc tính từ cột đó; e2e chạy FakeClock → đặt lại bằng giờ app lúc
    tạo phiếu (khuôn test PG nhắc `test_b16_reminders_pg`)."""
    assert await execute(p.rw, "UPDATE approvals SET created_at = :c WHERE approval_id = :a", c=at, a=int(aid)) == 1


def _notices(caplog: pytest.LogCaptureFixture, aid: str) -> list[tuple[str, str]]:
    """Thông báo người duyệt (Phase 4 chỉ log — `approval/store.log_approver_notice`): (người nhận, loại) của phiếu `aid`."""
    return [(str(r.args[1]), str(r.args[2])) for r in caplog.records
            if r.name == "app.approval.store" and isinstance(r.args, tuple) and len(r.args) == 3 and str(r.args[0]) == aid]  # fmt: skip


async def _late_events(rw: Any, ticket: str) -> list[dict[str, Any]]:
    return [dict(r[0]) for r in await rows(rw, "SELECT detail FROM audit_logs WHERE ticket_id = :t AND event = 'late_event' "
                                               "ORDER BY log_id", t=ticket)]  # fmt: skip


async def test_i1_tc07_approve_execute_confirm_resolved_points_1_to_8(stack: Stack) -> None:
    """i1 (TC07-vpn): chau.hm gia hạn LAP-0501 → R19 → ha.lt duyệt → gia hạn ĐÚNG 1 lời gọi ghi (mock nhận `POST
    /vpn/certs/nv003/renew`) → `S_CONFIRMING` → xác nhận → `S_RESOLVED`; `audit_check` trên ticket: 0 thiếu, 0 bí mật, và ticket có dòng
    áp dụng cho CẢ 8 điểm log."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await resolved_hitl(a, stack.mock)
        TICKETS.append(ticket)
    assert await calls(stack.mock, "/vpn/certs/nv003/renew") == 1 and await writes(stack.mock) == 1
    report = await audit_report(stack.pg, [ticket], [])
    assert (list(report.missing), list(report.secrets)) == ([], []), render(report)
    engine = readonly_engine(stack.pg.role("app_rw"))
    try:
        rows_by_ticket, finals = await load(engine, tickets=[ticket])
    finally:
        await engine.dispose()
    assert _covered(rows_by_ticket, finals) == set(range(1, 9))


async def test_i2_tc08_reject_with_note_rejection_message_no_write(stack: Stack) -> None:
    """i2 (TC08-vpn): ha.lt từ chối có note → `S_REJECTED` `rejected_by_approver`; người gửi nhận ĐÚNG 1 tin `rejection` (nêu máy
    LAP-0501 + ghi chú); phiếu `rejected` + `note`; 0 lời gọi ghi."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await rejected_hitl(a, note="máy không thuộc diện gia hạn")
        TICKETS.append(ticket)
        view = await a.view(ticket, CHAU)
    [msg] = [m for m in view["conversation"] if m.get("kind") == "rejection"]
    assert "LAP-0501" in msg["text"] and "máy không thuộc diện gia hạn" in msg["text"], msg
    assert await rows(p.rw, "SELECT status, note FROM approvals WHERE ticket_id = :t", t=ticket) == [
        ("rejected", "máy không thuộc diện gia hạn")]  # fmt: skip
    assert await writes(stack.mock) == 0


async def test_i3_reject_without_note_422_approval_stays_pending(stack: Stack) -> None:
    """i3 (cổng 4 [Chốt]): từ chối không note / note toàn khoảng trắng → 422 `rejected_requires_note`; phiếu vẫn `pending`, ticket
    vẫn chờ duyệt, 0 dòng B16, 0 `late_event`."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        for body in ({"decision": "rejected"}, {"decision": "rejected", "note": "   "}):
            r = await decide(a, aid, APPROVER, **body)
            assert (r.status_code, r.json()) == (422, {"detail": "rejected_requires_note"}), body
        assert (await a.view(ticket, CHAU))["status"] == S_PENDING_APPROVAL
    assert await scalar(p.rw, "SELECT status FROM approvals WHERE approval_id = :a", a=int(aid)) == "pending"
    assert not [e for e in await audit_events(p.rw, ticket) if e[0] == "B16"]
    assert await _late_events(p.rw, ticket) == []


async def test_i4_tc09_unregistered_device_approved_e7_exec_failed_handoff(stack: Stack) -> None:
    """i4 (TC09, Q-4-D): binh.tt "cấp lại VPN cho máy PC-0977" (chưa đăng ký) → R17 → phiếu l1_01 → ha.lt duyệt → B17 gửi lệnh cấp lại
    → mock 409 → E7 `exec_failed`; ghi chú bàn giao đủ 4 phần + "máy chưa đăng ký — đăng ký máy trước"; mock nhận đúng 1 lời gọi ghi."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10),
                     scripts=vpn_scripts(action="reissue_vpn_access")) as p, api(p) as a:  # fmt: skip
        ticket = await a.create("binh.tt", "cấp lại VPN cho máy PC-0977")
        TICKETS.append(ticket)
        assert (await a.view(ticket, "binh.tt"))["status"] == S_PENDING_APPROVAL
        assert await rows(p.rw, "SELECT approver_id, backup_approver_id FROM approvals WHERE ticket_id = :t", t=ticket) == [
            ("l1_01", "l1_02")]  # fmt: skip
        r = await decide(a, await approval_id(p.rw, ticket), APPROVER)
        assert r.status_code == 202, r.text
        view = await a.view(ticket, "binh.tt")
        values = await a.state(ticket)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E7"), view
    assert (await escalation(p.rw, ticket))[:2] == ("E7", "exec_failed")
    note = values["execution"].handoff_note  # khuôn h16 (test_gate3_vpn) — B20 chép vào ghi chú bàn giao
    for part in ("Đã làm:", "Lỗi ở bước:", "Hoàn tác:", "L2 cần làm tay:", "máy chưa đăng ký — đăng ký máy trước"):
        assert part in note, (part, note)
    assert await calls(stack.mock, "/vpn/access/nv002/reissue") == 1 and await writes(stack.mock) == 1


# i5 — bảng 3.2 trên stack. x5, x6 đã có e2e: test_gate3_vpn.py `test_h11_at_20h_…` (x5), `test_h14_g01_…` (x6); x14 = i15.
_X_ROWS = [
    # (id, người gửi, câu, chuẩn bị mock, approver, backup, conflict_detected, conflict_type, choice_reason)
    pytest.param(CHAU, HITL_TEXT, (), "l1_01", "l1_02", False, None, "normal", id="x1"),
    pytest.param(APPROVER, "gia hạn VPN cho máy PC-0124", (), "it_mgr01", None, True, "self", "conflict", id="x2"),
    pytest.param("khoa.dv", "gia hạn VPN cho máy LAP-0700", (), "it_mgr01", None, True, "boss_of_approver", "conflict", id="x3"),
    pytest.param(CHAU, HITL_TEXT, ("l1_01",), "l1_02", "it_mgr01", False, None, "normal", id="x7"),
    pytest.param(CHAU, HITL_TEXT, ("l1_01", "l1_02"), "it_mgr01", None, False, None, "no_valid_l1", id="x8"),
]  # fmt: skip


@pytest.mark.parametrize(("who", "text_", "disabled", "approver", "backup", "conflict", "ctype", "reason"), _X_ROWS)
async def test_i5_table_3_2_approver_choice_on_stack(
    stack: Stack, who: str, text_: str, disabled: tuple[str, ...], approver: str, backup: str | None, conflict: bool,
    ctype: str | None, reason: str,
) -> None:  # fmt: skip
    """i5 (bảng 3.2 x1–x3, x7, x8): B15 THẬT trên AD của mock — người duyệt/dự phòng/xung đột đúng bảng; audit B15 `queued`
    `detail.choice_reason`; 0 lời gọi ghi. x7/x8: ha.lt đăng nhập TRƯỚC (dòng `users`), rồi mới khoá trên mock."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        await a.login(APPROVER)
        for user_id in disabled:
            await admin(stack.mock, f"users/{user_id}/status", {"employment_status": "disabled"})
        ticket = await a.create(who, text_)
        TICKETS.append(ticket)
        assert (await a.view(ticket, who))["status"] == S_PENDING_APPROVAL
    assert await rows(p.rw, "SELECT approver_id, backup_approver_id, conflict_detected, conflict_type FROM approvals "
                            "WHERE ticket_id = :t", t=ticket) == [(approver, backup, conflict, ctype)]  # fmt: skip
    assert (await audit_detail(p.rw, ticket, "B15", "queued"))["choice_reason"] == reason
    assert await writes(stack.mock) == 0


async def test_i5_x4_head_is_requester_no_valid_approver_e5_no_approval(stack: Stack) -> None:
    """i5 x4: quan.tm (it_mgr01) LAP-0900 — l1_01 vướng sếp (chuỗi), Trưởng BP = chính người gửi → E5 `no_valid_approver`, 0 phiếu.
    Manager bắt buộc MFA → ghi danh trong tiến trình test + OTP theo FakeClock (`login_manager`). Ca này KHÔNG có ở gate4 (Q-4d-9 = B)."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        await login_manager(a, "quan.tm")
        ticket = await a.create("quan.tm", "gia hạn VPN cho máy LAP-0900")
        TICKETS.append(ticket)
        view = await a.view(ticket, "quan.tm")
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E5"), view
    assert (await escalation(p.rw, ticket))[:2] == ("E5", "no_valid_approver")
    assert await scalar(p.rw, "SELECT count(*) FROM approvals WHERE ticket_id = :t", t=ticket) == 0
    assert await writes(stack.mock) == 0


async def test_i5_x9_ad_error_at_approver_lookup_e2_no_approval(stack: Stack) -> None:
    """i5 x9: ha.lt đăng nhập TRƯỚC, rồi mock bơm 500 cho `GET /ad/users/l1_01` — chỉ B15 tra người duyệt đó (B1/B6 tra người gửi) →
    E2 `approver_lookup_error`, 0 phiếu, 0 lời gọi ghi."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        await a.login(APPROVER)
        await admin(stack.mock, "faults", {"path_prefix": "/ad/users/l1_01", "method": "GET", "mode": "error", "status": 500})
        ticket = await a.create(CHAU, HITL_TEXT)
        TICKETS.append(ticket)
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E2"), view
    assert (await escalation(p.rw, ticket))[:2] == ("E2", "approver_lookup_error")
    assert await scalar(p.rw, "SELECT count(*) FROM approvals WHERE ticket_id = :t", t=ticket) == 0
    assert await writes(stack.mock) == 0


async def test_i6_tc20_timeout_e6_no_write_approval_timeout(stack: Stack) -> None:
    """i6 (TC20, M-4d-6): không ai quyết → FakeClock +31 phút → worker quét → E6; phiếu `timeout` + `decided_at`; dòng B16
    `approval_timeout` (`response_time_seconds` NULL); 0 lời gọi ghi, 0 `transaction_log`. Hết hạn KHÔNG BAO GIỜ tự thực thi."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        p.clock.advance(timedelta(minutes=31))
        async with worker(p) as jobs:
            await jobs.scan_deadlines()  # DB e2e dùng chung cả module: phiếu chờ của test trước cũng hết hạn — chỉ khẳng định ticket NÀY
        await _relogin(a, CHAU)
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E6"), view
    assert (await escalation(p.rw, ticket))[0] == "E6"
    [(status, decided_at)] = await rows(p.rw, "SELECT status, decided_at FROM approvals WHERE approval_id = :a", a=int(aid))
    assert status == "timeout" and decided_at is not None
    assert await rows(p.rw, "SELECT approval_result, response_time_seconds FROM audit_logs WHERE ticket_id = :t AND step = 'B16'",
                      t=ticket) == [("timeout", None)]  # fmt: skip
    assert await writes(stack.mock) == 0
    assert await rows(p.rw, "SELECT status FROM transaction_log WHERE ticket_id = :t", t=ticket) == []


async def test_i7_tc27_late_click_409_approval_still_pending_then_worker_e6(stack: Stack) -> None:
    """i7 (TC27, Q2 2b-3, M-4d-7): quá hạn nhưng worker CHƯA quét → ha.lt bấm duyệt → 409 + đúng 1 `late_event` (`reason=expired`,
    `approval_id`); phiếu VẪN `pending` (bấm muộn không đổi phiếu); worker quét → E6, phiếu `timeout`; 0 lời gọi ghi."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        p.clock.advance(timedelta(minutes=31))
        await _relogin(a, APPROVER, CHAU)
        r = await decide(a, aid, APPROVER)
        assert r.status_code == 409, r.text
        [late] = await _late_events(p.rw, ticket)
        assert (late["reason"], late["approval_id"]) == ("expired", aid), late
        assert await scalar(p.rw, "SELECT status FROM approvals WHERE approval_id = :a", a=int(aid)) == "pending"
        assert (await a.view(ticket, CHAU))["status"] == S_PENDING_APPROVAL
        async with worker(p) as jobs:
            await jobs.scan_deadlines()  # như i6: không đếm toàn cục — khẳng định trên ticket/phiếu này
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E6"), view
    assert await scalar(p.rw, "SELECT status FROM approvals WHERE approval_id = :a", a=int(aid)) == "timeout"
    assert len(await _late_events(p.rw, ticket)) == 1
    assert await writes(stack.mock) == 0


async def test_i9_primary_and_backup_click_together_one_execution(stack: Stack) -> None:
    """i9 (tranh chấp): sau nhắc 2 (dự phòng được quyền), ha.lt và duc.pv bấm duyệt CÙNG LÚC → mã {202, 409}; đúng 1 lần thực thi (1
    lời gọi ghi); phiếu `approved`, `decided_by` = người nhận 202; đúng 1 `late_event`; đúng 1 dòng B16 `approved`."""
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        created = p.clock.now()
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        await _created_at_app_clock(p, aid, created)
        p.clock.advance(timedelta(minutes=25))  # đã qua m2 (24 phút / SLA 30): chỉ nhắc 2, đặt cả hai cột (4c P3)
        async with worker(p) as jobs:
            await jobs.scan_deadlines()
        assert await scalar(p.rw, "SELECT reminder_2_at IS NOT NULL FROM approvals WHERE approval_id = :a", a=int(aid))
        await _relogin(a, APPROVER, BACKUP, CHAU)
        first, second = await asyncio.gather(decide(a, aid, APPROVER), decide(a, aid, BACKUP))
        await a.drain()
        codes = (first.status_code, second.status_code)
        assert sorted(codes) == [202, 409], (first.text, second.text)
        winner = "l1_01" if first.status_code == 202 else "l1_02"
        view = await a.view(ticket, CHAU)
    assert view["status"] == S_CONFIRMING, view
    assert await writes(stack.mock) == 1
    assert await rows(p.rw, "SELECT status, decided_by FROM approvals WHERE approval_id = :a", a=int(aid)) == [("approved", winner)]
    assert len(await _late_events(p.rw, ticket)) == 1
    # late_event của người bấm sau mang step của trạng thái chờ nó nhắm tới = "B16" (graph/late_event.py:67 — đúng thiết kế); thứ tự giữa
    # hai dòng tuỳ lúc người sau chạm khoá phiếu → so tập đã sắp
    b16 = sorted(e for e in await audit_events(p.rw, ticket) if e[0] == "B16")
    assert b16 == [("B16", "approved"), ("B16", "late_event")], b16


async def test_i10_deny_rule_e5_no_approval_queue(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    """i10 (x13, cổng 4 "deny không vào hàng đợi duyệt" [Chốt]): luật `deny` tiêm bằng monkeypatch (khuôn x13 unit — KHÔNG thêm vào
    policy.json) → B12 E5, `escalations.is_deny_case`; 0 phiếu, 0 dòng step B15, 0 lời gọi ghi."""
    verdict = RuleVerdict(matched=True, decision="deny", rule_id="R12", all_matched=["R12", "R19", "R20"], description="Cấm")
    monkeypatch.setattr(b12_assess, "evaluate", lambda action, ctx: verdict)
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await a.create(CHAU, HITL_TEXT)
        TICKETS.append(ticket)
        view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["exit_code"]) == (S_ESCALATED, "E5"), view
    assert await rows(p.rw, "SELECT exit_code, is_deny_case FROM escalations WHERE ticket_id = :t", t=ticket) == [("E5", True)]
    assert await rows(p.rw, "SELECT policy_decision FROM audit_logs WHERE ticket_id = :t AND event = 'risk_decided'",
                      t=ticket) == [("deny",)]  # fmt: skip
    assert await scalar(p.rw, "SELECT count(*) FROM approvals WHERE ticket_id = :t", t=ticket) == 0
    assert not [e for e in await audit_events(p.rw, ticket) if e[0] == "B15"]
    assert await writes(stack.mock) == 0


async def test_i11_l2_cannot_decide_or_view_403(stack: Stack) -> None:
    """i11: long.nh (l2_01, không có `approval:decide`) → quyết 403, xem phiếu 403 (tầng 2), mỗi route 1 `permission_denied`; phiếu
    vẫn `pending`, `first_viewed_at` NULL."""
    denied_sql = ("SELECT detail->>'perm' FROM security_events WHERE event_type = 'permission_denied' AND user_id = 'l2_01' "
                  "ORDER BY event_id")  # DB dùng chung cả module → so phần TĂNG THÊM trong test này
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        before = len(await rows(p.rw, denied_sql))
        r = await decide(a, aid, "long.nh")
        assert (r.status_code, r.json()) == (403, FORBIDDEN)
        headers = a.tokens["long.nh"]
        r = await a.client.get(f"/api/approvals/{aid}", headers=headers)
        assert (r.status_code, r.json()) == (403, FORBIDDEN)
    assert (await rows(p.rw, denied_sql))[before:] == [("approval:decide",), ("approval:decide",)]
    assert await rows(p.rw, "SELECT status, first_viewed_at FROM approvals WHERE approval_id = :a", a=int(aid)) == [
        ("pending", None)]  # fmt: skip


async def test_i12_reminders_50_80_percent_then_backup_decides(stack: Stack, caplog: pytest.LogCaptureFixture) -> None:
    """i12 (c3 + c5 trên stack): SLA 30 phút — +14 phút quét: không nhắc; +15: nhắc 1 CHỈ người duyệt; duc.pv (dự phòng) quyết → 403;
    +24: nhắc 2 cho người duyệt + dự phòng; duc.pv quyết → 202 `decided_as=backup` → thực thi (1 lời gọi ghi) → `S_CONFIRMING`; dòng
    B16 `detail.decided_as="backup"`. Mỗi (người, loại) đúng 1 lần."""
    caplog.set_level(logging.INFO, logger="app.approval.store")
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        created = p.clock.now()
        ticket, aid = await pending_hitl(a)
        TICKETS.append(ticket)
        await _created_at_app_clock(p, aid, created)
        assert await scalar(p.rw, "SELECT deadline - created_at FROM approvals WHERE approval_id = :a", a=int(aid)) == timedelta(
            minutes=30)  # fmt: skip
        assert _notices(caplog, aid) == [("l1_01", "new")]
        async with worker(p) as jobs:
            p.clock.advance(timedelta(minutes=14))
            await jobs.scan_deadlines()
            assert _notices(caplog, aid) == [("l1_01", "new")]
            p.clock.advance(timedelta(minutes=1))
            await jobs.scan_deadlines()
            assert _notices(caplog, aid) == [("l1_01", "new"), ("l1_01", "reminder_1")]
            await _relogin(a, BACKUP)
            r = await decide(a, aid, BACKUP)
            assert (r.status_code, r.json()) == (403, FORBIDDEN)  # dự phòng TRƯỚC nhắc 2
            p.clock.advance(timedelta(minutes=9))
            await jobs.scan_deadlines()
            await jobs.scan_deadlines()  # quét lại: không nhắc lần 2
        assert sorted(_notices(caplog, aid)) == sorted([("l1_01", "new"), ("l1_01", "reminder_1"), ("l1_01", "reminder_2"),
                                                       ("l1_02", "reminder_2")])  # fmt: skip
        await _relogin(a, BACKUP, CHAU)
        r = await decide(a, aid, BACKUP)
        assert r.status_code == 202 and r.json()["decided_as"] == "backup", r.text
        view = await a.view(ticket, CHAU)
    assert view["status"] == S_CONFIRMING, view
    assert await writes(stack.mock) == 1
    assert (await audit_detail(p.rw, ticket, "B16", "approved"))["decided_as"] == "backup"
    assert await rows(p.rw, "SELECT decided_by FROM approvals WHERE approval_id = :a", a=int(aid)) == [("l1_02",)]


def _crash_after_approval_create_once(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Process "chết" ở hook `after_approval_create` của B15 THẬT (phiếu đã tạo, `notify_approver` CHƯA gửi) — một lần, bật bằng cờ."""
    armed = {"on": True}
    original = FakeScenario.hook

    async def hook(self: FakeScenario, state: Mapping[str, Any], label: str) -> None:
        if armed["on"] and label == "after_approval_create":
            armed["on"] = False
            raise Crash("process chết sau approval_create, trước notify_approver")
        await original(self, state, label)

    monkeypatch.setattr(FakeScenario, "hook", hook)
    return armed


async def test_i15_tc33_crash_after_approval_create_recover_one_approval_one_notice(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """i15 (TC33, x14): process chết SAU khi tạo phiếu, TRƯỚC khi báo người duyệt → API `recover` → B15 chạy lại (`peek`, không chọn
    lại người) → đúng 1 phiếu (l1_01 giữ nguyên), `side_effects` `approval_create` 1 + `notify_approver` 1, 1 dòng B15 `queued`,
    `S_PENDING_APPROVAL`; 0 lời gọi ghi."""
    crash = _crash_after_approval_create_once(monkeypatch)
    async with gate3(stack.pg, stack.qdrant_url, stack.mock, clock=at_ict(10), scripts=vpn_scripts()) as p, api(p) as a:
        ticket = await a.create(CHAU, HITL_TEXT)
        TICKETS.append(ticket)
        assert crash["on"] is False, "B15 chưa tới hook after_approval_create"
        assert await scalar(p.rw, "SELECT count(*) FROM approvals WHERE ticket_id = :t", t=ticket) == 1
        await a.app.state.desk.runner.recover(ticket, await open_turn(p.rw, ticket))
        view = await a.view(ticket, CHAU)
    assert view["status"] == S_PENDING_APPROVAL, view
    assert await rows(p.rw, "SELECT approver_id, status FROM approvals WHERE ticket_id = :t", t=ticket) == [("l1_01", "pending")]
    effects = await rows(p.rw, "SELECT kind, count(*) FROM side_effects WHERE ticket_id = :t AND kind IN ('approval_create', "
                               "'notify_approver') GROUP BY kind ORDER BY kind", t=ticket)  # fmt: skip
    assert effects == [("approval_create", 1), ("notify_approver", 1)]
    assert [e for e in await audit_events(p.rw, ticket) if e[0] == "B15"] == [("B15", "queued")]
    assert await writes(stack.mock) == 0


# ---- i17 (CUỐI FILE): audit_check trên mọi ticket của file -------------------------------------------------------------------------


_POINT_ROWS: dict[int, set[tuple[str, str]]] = {
    1: {("B3", "intent_classified")}, 2: {("B6", "diagnosed")}, 3: {("B8", "retrieved"), ("B8", "retrieval_error"), ("B9", "no_evidence")},
    4: {("B13/B14", "risk_decided")}, 5: {("B15", "queued")},
    6: {("B16", "approved"), ("B16", "rejected"), ("B16", "approval_timeout"), ("B16", CHANGED)},  # Q-4d-3: + dòng B16 E5
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
