"""Người dự phòng + xem phiếu (IDOR) qua HTTP — Phase 4 chặng 4c DỪNG 2. Viết TỪ ĐẶC TẢ, trước thân code:
phase4 mục 6.1 P4, P6 + 6.2 c5–c9; PLAN-4c mục 2.1 (hợp đồng + "Bổ sung khi dựng khung S7"), TQ-9, TQ-11, TQ-12.

- c5: dự phòng quyết TRƯỚC nhắc 2 → 403 (+1 `permission_denied`, không resume); SAU nhắc 2 → 202 `decided_as="backup"`, audit B16
  `detail.decided_as="backup"`, `approver_id` của phiếu KHÔNG đổi, `decided_by` = người dự phòng. Người duyệt chính → `decided_as="primary"`.
- c6: dự phòng là CHÍNH người gửi (dựng tay — B15 4b không bao giờ chọn vậy) → 403.
- c7: `GET /api/approvals/{id}`: được giao → 200 + ghi `first_viewed_at`; dự phòng trước nhắc 2 / L1 khác → 404 GIỐNG HỆT id không có /
  id hỏng (+1 `permission_denied` chỉ khi bản ghi có thật); dự phòng sau nhắc 2 → 200 `role_as="backup"` + ghi; manager không được giao
  → 200 `role_as="viewer"`, KHÔNG ghi; L2 / nhân viên → 403 (tầng 2).
- c8: xem 2 lần → `first_viewed_at` giữ lần đầu; phiếu đã đóng → không ghi.
- c9: `intended_action` trong checkpoint đổi sau khi tạo phiếu (hash phiếu giữ nguyên) → 409 `plan_changed`, không thân `ApprovalView`,
  `first_viewed_at` vẫn NULL.
- `ApprovalView` 200: đúng các khoá hợp đồng; `action` = object đã băm (`hash_action` khớp `action_plan_hash`), `facts = action.facts`,
  `procedure` theo `ActionMeta.procedure_doc` (+ tiêu đề hoặc null), `request_summary` ≤ 500 ký tự đầu của `tickets.redacted_request`.

`desk_env`: node GIẢ tới B15 — người duyệt `l1_01` (ha.lt), không dự phòng, hành động `FAKE_ACTION` (không có trong `action_metadata`).
Dự phòng / nhắc 2 đặt thẳng vào bảng giả (`env.h.approvals._table[aid]`); hành động thật đặt vào checkpoint bằng `aupdate_state`.
Người dùng (`seed_ad_users`): ha.lt = l1_01, duc.pv = l1_02, long.nh = l2_01, quan.tm = it_mgr01 (manager, MFA), an.nv = nv001,
binh.tt = nv002.
"""

import dataclasses
from datetime import datetime, timedelta
from typing import Any

import httpx
import pyotp
import pytest
from app.auth.mfa import MfaCipher, enroll
from app.auth.models import UserRecord
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import S_PENDING_APPROVAL
from app.domain.ticket_state import RiskDecision
from app.graph.fakes import FAKE_ACTION
from app.main import create_app
from app.settings import get_action_metadata
from pydantic import BaseModel
from tests.fakes.auth import DEMO_PASSWORD
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env
from tests.unit.auth_helpers import auth_settings

pytestmark = pytest.mark.asyncio

PRIMARY = "l1_01"  # ha.lt — người duyệt của B15 giả trong desk_env
BACKUP = "l1_02"  # duc.pv — dự phòng đặt tay
VIEW_ROUTE = "/api/approvals/{approval_id}"
# Đổi có chủ ý ở F6: 12 khoá P6 (PLAN-4c 2.1 / spec 6.1 P6, giữ nguyên kể cả `risk` thô) + `affected` + `risk_view` = 14 khoá.
VIEW_KEYS = {
    "approval_id", "ticket_id", "status", "deadline", "requester", "request_summary", "action", "action_plan_hash", "risk",
    "facts", "role_as", "procedure", "affected", "risk_view",
}  # fmt: skip
DECISION_202_KEYS = {"approval_id", "ticket_id", "status", "notices", "decided_as"}  # PLAN-4c 2.1, TQ-12
NOT_FOUND = {"detail": "not_found"}
FORBIDDEN = {"detail": "forbidden"}
PLAN_CHANGED = {"detail": "plan_changed"}


# ---- helpers ---------------------------------------------------------------------------------------------------------------


async def _login(env: DeskEnv, username: str) -> dict[str, str]:
    """Đăng nhập; manager bắt buộc MFA — lần đầu 401 (tạo dòng users), enroll qua đúng hàm CLI, đăng nhập kèm OTP (khuôn
    `test_approvals_route_chain._headers`)."""
    r = await env.login(username)
    if r.status_code != 200:
        assert r.status_code == 401, r.text
        key = env.settings.mfa_enc_key
        assert key is not None
        enrolled = await enroll(env.store, env.sink, MfaCipher(key), username=username, by="ops", reason="test")
        otp = pyotp.TOTP(enrolled.secret).at(env.clock.now())
        r = await env.client.post("/api/auth/login", json={"username": username, "password": DEMO_PASSWORD, "otp": otp})
        assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _pending(env: DeskEnv, requester: str = "an.nv", text: str = "VPN không vào được") -> tuple[str, str]:
    """Ticket của `requester` tới chờ duyệt (B15 giả giao `l1_01`). Trả (ticket_id, approval_id)."""
    headers = await _login(env, requester)
    ticket = await env.create(headers, text)
    await env.drain()
    assert (await env.ticket(ticket, headers))["status"] == S_PENDING_APPROVAL
    aid = env.approval_of(ticket)
    row = env.h.approvals._table[aid]
    assert (row["approver_id"], row.get("backup_approver_id"), row["status"]) == (PRIMARY, None, "pending")
    return ticket, aid


def _row(env: DeskEnv, aid: str) -> dict[str, Any]:
    return env.h.approvals._table[aid]


def _set_backup(env: DeskEnv, aid: str, *, reminded_2: bool, backup: str = BACKUP) -> None:
    """Dự phòng đặt tay (B15 giả không chọn dự phòng). Trước nhắc 2 = ĐÃ nhắc 1 nhưng chưa nhắc 2 (ca sát biên nhất)."""
    row = _row(env, aid)
    row["backup_approver_id"] = backup
    row["reminder_1_at"] = env.clock.now()
    row["reminder_2_at"] = env.clock.now() if reminded_2 else None


async def _view(env: DeskEnv, aid: str, headers: dict[str, str]) -> httpx.Response:
    return await env.client.get(f"/api/approvals/{aid}", headers=headers)


async def _decide(env: DeskEnv, aid: str, headers: dict[str, str], **body: Any) -> httpx.Response:
    return await env.client.post(f"/api/approvals/{aid}/decision", json=body or {"decision": "approved"}, headers=headers)


def _resumes(env: DeskEnv, ticket: str) -> int:
    return sum(1 for t in env.h.turns.of(ticket) if t["event_type"] == "resume")


def _b16(env: DeskEnv, ticket: str) -> dict[str, Any]:
    rows = [r for r in env.h.audit.rows if r["ticket_id"] == ticket and r["step"] == "B16"]
    assert len(rows) == 1, env.h.audit.events(ticket)
    return rows[0]


def _vpn_action(requested_for: str = "nv001") -> Action:
    m = get_action_metadata().of("vpn")["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target="device:LAP-0501", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": "LAP-0501"},
        facts={"device_owner_is_requester": True, "device_registered": True},
    )  # fmt: skip


async def _put_action(env: DeskEnv, ticket: str, aid: str, action: Action) -> None:
    """Hành động thật vào checkpoint + hash khớp ở phiếu (PLAN-4c 2.1 "Muốn thấy giá trị")."""
    await env.h.runner.graph.aupdate_state(
        env.h.runner.config(ticket), {"intended_action": action, "action_plan_hash": hash_action(action)}
    )
    _row(env, aid)["action_plan_hash"] = hash_action(action)


def _as_json(value: Any) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


async def _assert_404_like_missing(env: DeskEnv, aid: str, headers: dict[str, str], user_id: str) -> None:
    """404 cho phiếu có thật GIỐNG HỆT (status + từng byte thân + content-length) 404 cho id không có / id hỏng; +1 `permission_denied`
    CHỈ cho bản ghi có thật (khuôn `api/tickets` A21, `test_auth_idor`)."""
    denied = env.denied()
    real = await _view(env, aid, headers)
    assert real.status_code == 404, real.text
    assert real.json() == NOT_FOUND
    assert env.denied() == denied + 1
    event = env.sink.of("permission_denied")[-1]
    assert (event.user_id, event.route) == (user_id, VIEW_ROUTE)
    for fake in ("999999", "abc"):
        missing = await _view(env, fake, headers)
        assert missing.status_code == 404, (fake, missing.text)
        assert missing.content == real.content, fake
        assert missing.headers.get("content-length") == real.headers.get("content-length"), fake
    assert env.denied() == denied + 1  # id không có / hỏng: KHÔNG ghi
    assert _row(env, aid).get("first_viewed_at") is None


# ---- c5: người dự phòng quyết -------------------------------------------------------------------------------------------------


async def test_c5_backup_before_reminder2_decide_403_no_resume() -> None:
    """c5 (P4, Q-4-O): dự phòng đã nhắc 1 nhưng CHƯA nhắc 2 → 403 + 1 `permission_denied`, không resume, phiếu vẫn `pending`."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _set_backup(env, aid, reminded_2=False)
        duc = await _login(env, "duc.pv")
        denied = env.denied()
        r = await _decide(env, aid, duc)
        assert r.status_code == 403, r.text
        assert env.denied() == denied + 1
        assert env.sink.of("permission_denied")[-1].user_id == BACKUP
        await env.drain()
        assert _resumes(env, ticket) == 0 and env.late(ticket) == []
        assert env.h.approvals.status(aid) == "pending"


async def test_c5_backup_after_reminder2_decide_202_decided_as_backup() -> None:
    """c5 (P4, TQ-12): sau nhắc 2 → 202, thân `decided_as="backup"`; B16 audit `detail.decided_as="backup"`; `approver_id` của phiếu
    KHÔNG đổi (vẫn l1_01), `decided_by` = l1_02."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _set_backup(env, aid, reminded_2=True)
        duc = await _login(env, "duc.pv")
        denied = env.denied()
        r = await _decide(env, aid, duc)
        assert r.status_code == 202, r.text
        body = r.json()
        assert set(body) == DECISION_202_KEYS
        assert (body["status"], body["decided_as"], str(body["approval_id"]), body["ticket_id"]) == (
            "accepted", "backup", aid, ticket)  # fmt: skip
        assert env.denied() == denied
        await env.drain()
        assert _resumes(env, ticket) == 1
        row = _row(env, aid)
        assert (row["status"], row["approver_id"], row["decided_by"]) == ("approved", PRIMARY, BACKUP)
        assert _b16(env, ticket)["detail"]["decided_as"] == "backup"


async def test_c5_primary_decide_202_decided_as_primary() -> None:
    """c5 đối chứng: người được giao quyết (phiếu có dự phòng đã nhắc 2) → 202 `decided_as="primary"`; B16 `decided_as="primary"`."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        _set_backup(env, aid, reminded_2=True)
        ha = await _login(env, "ha.lt")
        r = await _decide(env, aid, ha, decision="rejected", note="sai máy", reason_code="wrong_device")
        assert r.status_code == 202, r.text
        assert set(r.json()) == DECISION_202_KEYS
        assert r.json()["decided_as"] == "primary"
        await env.drain()
        row = _row(env, aid)
        assert (row["status"], row["approver_id"], row["decided_by"]) == ("rejected", PRIMARY, PRIMARY)
        assert _b16(env, ticket)["detail"]["decided_as"] == "primary"


# ---- c6: dự phòng là người gửi --------------------------------------------------------------------------------------------------


async def test_c6_backup_is_requester_after_reminder2_decide_403() -> None:
    """c6: duc.pv (L1, có `approval:decide`) tự gửi ticket; phiếu giao l1_01, dự phòng đặt tay = l1_02 (chính người gửi), đã nhắc 2 →
    duc.pv quyết → 403 (xung đột `self`, P4 "cùng kiểm xung đột") + 1 `permission_denied`, không resume, phiếu `pending`."""
    async with desk_env() as env:
        ticket, aid = await _pending(env, requester="duc.pv")
        assert env.h.tickets.rows[ticket]["requester_id"] == BACKUP
        _set_backup(env, aid, reminded_2=True)
        duc = await _login(env, "duc.pv")
        denied = env.denied()
        r = await _decide(env, aid, duc)
        assert r.status_code == 403, r.text
        assert env.denied() == denied + 1
        await env.drain()
        assert _resumes(env, ticket) == 0 and env.late(ticket) == []
        assert env.h.approvals.status(aid) == "pending"


async def test_c6_backup_is_requester_view_404() -> None:
    """c6 + TQ-11 ("xung đột → không được xem như người được giao"): dự phòng = người gửi, đã nhắc 2 → không có vai trò; L1 không có
    `audit:read:all` → 404 giống hệt id không có, KHÔNG ghi `first_viewed_at`."""
    async with desk_env() as env:
        _, aid = await _pending(env, requester="duc.pv")
        _set_backup(env, aid, reminded_2=True)
        await _assert_404_like_missing(env, aid, await _login(env, "duc.pv"), BACKUP)


# ---- c7: xem phiếu theo vai trò ---------------------------------------------------------------------------------------------------


async def test_c7_assignee_view_200_primary_writes_first_viewed_at() -> None:
    """c7 hàng 1: người được giao → 200 `role_as="primary"` + ghi `first_viewed_at` = giờ app (FakeClock)."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        ha = await _login(env, "ha.lt")
        assert _row(env, aid).get("first_viewed_at") is None
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        assert (r.json()["role_as"], r.json()["status"]) == ("primary", "pending")
        assert _row(env, aid)["first_viewed_at"] == env.clock.now()


async def test_c7_backup_before_reminder2_view_404_same_as_missing() -> None:
    """c7 hàng 2: dự phòng (đã nhắc 1, chưa nhắc 2) → 404 giống hệt id không có / id hỏng; +1 `permission_denied`; không ghi."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        _set_backup(env, aid, reminded_2=False)
        await _assert_404_like_missing(env, aid, await _login(env, "duc.pv"), BACKUP)


async def test_c7_other_l1_view_404_same_as_missing() -> None:
    """c7 hàng 3 (M-4c-4): L1 khác (không được giao, không phải dự phòng) → 404 giống hệt; +1 `permission_denied`; không ghi."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        await _assert_404_like_missing(env, aid, await _login(env, "duc.pv"), BACKUP)


async def test_c7_backup_after_reminder2_view_200_backup_writes() -> None:
    """c7 + P6 "dự phòng đủ điều kiện → xem + ghi": sau nhắc 2 → 200 `role_as="backup"` + ghi `first_viewed_at`."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        _set_backup(env, aid, reminded_2=True)
        duc = await _login(env, "duc.pv")
        env.clock.advance(timedelta(seconds=40))
        denied = env.denied()
        r = await _view(env, aid, duc)
        assert r.status_code == 200, r.text
        assert r.json()["role_as"] == "backup"
        assert _row(env, aid)["first_viewed_at"] == env.clock.now()
        assert env.denied() == denied


async def test_c7_manager_not_assigned_view_200_viewer_no_write() -> None:
    """c7 hàng 4 (M-4c-6): manager (`audit:read:all`) không được giao → 200 `role_as="viewer"`, `first_viewed_at` VẪN NULL, không
    `permission_denied`."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        quan = await _login(env, "quan.tm")
        denied = env.denied()
        r = await _view(env, aid, quan)
        assert r.status_code == 200, r.text
        assert set(r.json()) == VIEW_KEYS
        assert r.json()["role_as"] == "viewer"
        assert _row(env, aid).get("first_viewed_at") is None
        assert env.denied() == denied


@pytest.mark.parametrize("who", ["long.nh", "an.nv", "binh.tt"], ids=["l2", "nhan-vien-nguoi-gui", "nhan-vien-khac"])
async def test_c7_l2_and_employee_view_403(who: str) -> None:
    """c7 hàng 5–6: L2 / nhân viên (kể cả chính người gửi) → 403 `{"detail": "forbidden"}` ở tầng 2 (`require`), +1
    `permission_denied`, không ghi."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        headers = await _login(env, who)
        denied = env.denied()
        r = await _view(env, aid, headers)
        assert r.status_code == 403, r.text
        assert r.json() == FORBIDDEN
        assert env.denied() == denied + 1
        assert _row(env, aid).get("first_viewed_at") is None


# ---- c8: ghi lần đầu -------------------------------------------------------------------------------------------------------------


async def test_c8_view_twice_keeps_first_viewed_at() -> None:
    """c8: xem 2 lần (tua đồng hồ giữa hai lần) → `first_viewed_at` giữ lần đầu."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        ha = await _login(env, "ha.lt")
        first = env.clock.now()
        assert (await _view(env, aid, ha)).status_code == 200
        env.clock.advance(timedelta(minutes=2))
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        assert _row(env, aid)["first_viewed_at"] == first


@pytest.mark.parametrize("status", ["approved", "rejected", "timeout"])
async def test_c8_closed_approval_view_no_write(status: str) -> None:
    """c8 + P6 (`UPDATE … WHERE first_viewed_at IS NULL AND status='pending'`): phiếu đã đóng → người được giao xem được (200, `status`
    đúng) nhưng KHÔNG ghi `first_viewed_at`."""
    async with desk_env() as env:
        _, aid = await _pending(env)
        _row(env, aid).update(status=status, decided_at=env.clock.now(), decided_by=PRIMARY, note="x")
        ha = await _login(env, "ha.lt")
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status
        assert _row(env, aid).get("first_viewed_at") is None


# ---- c9: kế hoạch đổi sau khi tạo phiếu ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["chi-action", "action-va-hash-state", "khong-action"])
async def test_c9_plan_changed_409_no_view_no_write(change: str) -> None:
    """c9 (G4-13, M-4c-5): sau khi tạo phiếu, `intended_action` trong checkpoint đổi — hash của PHIẾU giữ nguyên → 409
    `{"detail": "plan_changed"}` (không khoá nào của `ApprovalView`), `first_viewed_at` vẫn NULL.
    - `chi-action`: chỉ đổi `intended_action`.
    - `action-va-hash-state`: đổi cả `action_plan_hash` trong state cho khớp action mới — route phải so với hash của PHIẾU (P6).
    - `khong-action`: `intended_action` = None (2.1: "không có `intended_action`" → 409)."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        before = _row(env, aid)["action_plan_hash"]
        action = _vpn_action()
        updates: dict[str, dict[str, Any]] = {
            "chi-action": {"intended_action": action},
            "action-va-hash-state": {"intended_action": action, "action_plan_hash": hash_action(action)},
            "khong-action": {"intended_action": None},
        }
        update = updates[change]
        await env.h.runner.graph.aupdate_state(env.h.runner.config(ticket), update)
        snap = await env.h.runner.snapshot(ticket)
        assert (snap.values["status"], snap.next) == (S_PENDING_APPROVAL, ("approval_wait",))
        assert snap.values["intended_action"] == update["intended_action"]
        assert _row(env, aid)["action_plan_hash"] == before != hash_action(action)
        ha = await _login(env, "ha.lt")
        r = await _view(env, aid, ha)
        assert r.status_code == 409, r.text
        assert r.json() == PLAN_CHANGED
        assert not VIEW_KEYS & set(r.json())
        assert _row(env, aid).get("first_viewed_at") is None


# ---- ApprovalView (P6, PLAN-4c 2.1) ---------------------------------------------------------------------------------------------


async def test_view_contract_fake_action_keys_and_values() -> None:
    """P6: đúng khoá hợp đồng; `approval_id/ticket_id/status/deadline` của phiếu; `requester` = {role, department} của
    `requester_context` (B1 thật: an.nv = employee/finance); `action` = object đã băm (`hash_action` == `action_plan_hash` của phiếu);
    `facts = action.facts`; `risk` = RiskDecision của checkpoint; `FAKE_ACTION` không có trong `action_metadata` → `procedure = null`."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        row = _row(env, aid)
        snap = await env.h.runner.snapshot(ticket)  # tiền điều kiện (dữ liệu dựng đúng) — chạy được trước khi có thân route
        rc = snap.values["requester_context"]
        assert (rc.role, rc.department) == ("employee", "finance")
        assert snap.values["intended_action"] == FAKE_ACTION
        assert hash_action(FAKE_ACTION) == row["action_plan_hash"]
        assert snap.values["risk"] is not None
        ha = await _login(env, "ha.lt")
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == VIEW_KEYS
        assert (str(body["approval_id"]), body["ticket_id"], body["status"]) == (aid, ticket, "pending")
        assert datetime.fromisoformat(body["deadline"]) == row["deadline"]
        sender = env.store.users.get(rc.user_id)  # Q3 (12/11): + mã + họ tên người gửi
        assert body["requester"] == {"user_id": rc.user_id, "full_name": sender.full_name if sender else None,
                                     "role": rc.role, "department": rc.department}  # fmt: skip
        assert body["action"] == FAKE_ACTION.model_dump(mode="json")
        assert body["action_plan_hash"] == row["action_plan_hash"] == hash_action(body["action"])
        assert body["facts"] == body["action"]["facts"]
        assert body["risk"] == _as_json(snap.values["risk"])
        assert body["role_as"] == "primary"
        assert body["procedure"] is None


@pytest.mark.parametrize("title", ["Quy trình gia hạn chứng chỉ VPN", None], ids=["co-tieu-de", "khong-tieu-de"])
async def test_view_real_action_procedure_and_hashed_object(title: str | None) -> None:
    """P6 + D-34: hành động thật `renew_vpn_cert` (LAP-0501) → `procedure = {doc_id: procedure_doc của action_metadata (KB-VPN-004),
    title: tiêu đề tài liệu | null}` (không có tiêu đề không chặn); `action` = đúng object đã băm, `facts = action.facts` (TQ-11)."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        action = _vpn_action()
        await _put_action(env, ticket, aid, action)
        snap = await env.h.runner.snapshot(ticket)
        assert (snap.values["intended_action"], snap.values["intent"], snap.next) == (action, "vpn", ("approval_wait",))
        doc_id = get_action_metadata().of("vpn")["renew_vpn_cert"].procedure_doc
        assert doc_id == "KB-VPN-004"
        if title is not None:
            env.h.approvals.titles[doc_id] = title
        ha = await _login(env, "ha.lt")
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == VIEW_KEYS
        assert body["procedure"] == {"doc_id": doc_id, "title": title}
        assert body["action"] == action.model_dump(mode="json")
        assert hash_action(body["action"]) == body["action_plan_hash"] == hash_action(action) == _row(env, aid)["action_plan_hash"]
        assert body["facts"] == action.facts == {"device_owner_is_requester": True, "device_registered": True}
        assert _row(env, aid)["first_viewed_at"] == env.clock.now()


async def test_view_request_summary_first_500_chars_of_redacted_request() -> None:
    """P6: `request_summary` = 500 ký tự đầu của `tickets.redacted_request` (bản ĐÃ che — không bao giờ câu gốc)."""
    async with desk_env() as env:
        text = f"VPN lỗi {SECRET} " + "máy chậm " * 90
        assert len(text) > 600
        ticket, aid = await _pending(env, text=text)
        redacted = env.h.tickets.rows[ticket]["redacted_request"]
        assert MASK in redacted and SECRET not in redacted
        r = await _view(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        summary = r.json()["request_summary"]
        assert summary == redacted[:500] and len(summary) == 500
        assert SECRET not in r.text


async def test_view_requester_is_l1_role_and_department() -> None:
    """P6 `requester{role, department}`: người gửi là L1 (duc.pv = l1 / it) — người được giao xem thấy đúng vai trò + phòng ban."""
    async with desk_env() as env:
        ticket, aid = await _pending(env, requester="duc.pv")
        rc = (await env.h.runner.snapshot(ticket)).values["requester_context"]
        assert (rc.user_id, rc.role, rc.department) == (BACKUP, "l1", "it")
        r = await _view(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        body = r.json()["requester"]
        assert (body["user_id"], body["role"], body["department"]) == (BACKUP, "l1", "it")  # Q3 (12/11): + user_id, full_name


# ---- F6: người bị tác động + khối rủi ro + response_model ----
#
# Hợp đồng F6 (lời giao agent chính): `affected` = {user_id = action.requested_for, is_requester, department, manager{status
# known|unknown, user_id, full_name}} đọc từ bảng `users` (desk_env: `env.store`) của NGƯỜI BỊ TÁC ĐỘNG, không phải người gửi;
# `risk_view` = null khi checkpoint `risk` None, ngược lại đúng 12 khoá (10 trường RiskDecision + `calibrated` + `auto_allowed`).
# Dữ liệu dựng tay theo D-43: mã luật giả R81.., ngưỡng giả (0.137, 0.863). Dòng `users` đặt TƯỜNG MINH SAU mọi lần đăng nhập
# (đăng nhập upsert dòng — đặt trước thì bị ghi đè).

AFFECTED_KEYS = {"user_id", "is_requester", "department", "manager"}
MANAGER_STATUSES = {"known", "unknown"}
RISK_VIEW_KEYS = {
    "decided_by", "policy_decision", "matched_rule_id", "risk_level", "route", "reason", "raw_prob", "calibrated_prob",
    "p_method", "thresholds", "calibrated", "auto_allowed",
}  # fmt: skip
RISK_FIELDS = RISK_VIEW_KEYS - {"calibrated", "auto_allowed"}  # fmt: skip
UNKNOWN_MANAGER = {"status": "unknown", "user_id": None, "full_name": None}
BOSS_NAME = "Lê Đình Sếp Giả"  # full_name đặt tay cho dòng users của fin_head
FAKE_THRESHOLDS = (0.137, 0.863)  # D-43: ngưỡng giả, không lấy từ config


class UsersReadError(RuntimeError):
    """Lỗi đọc bảng `users` tiêm vào ở f11 — phải nổi lên tới test (app không có handler Exception chung)."""


def _put_user(env: DeskEnv, user_id: str, *, username: str, department: str | None, manager_id: str | None,
              full_name: str = "Người thử giả") -> None:  # fmt: skip
    """Dòng `users` dựng tay: có rồi (đã đăng nhập) → `replace`, chưa có → `UserRecord` mới."""
    old = env.store.users.get(user_id)
    if old is not None:
        env.store.users[user_id] = dataclasses.replace(old, department=department, manager_id=manager_id, full_name=full_name)  # fmt: skip
        return
    env.store.users[user_id] = UserRecord(
        user_id=user_id, username=username, full_name=full_name, role="employee", department=department,
        manager_id=manager_id, employment_status="active", hired_at=None, is_privileged_account=False,
    )  # fmt: skip


def _requester_known(env: DeskEnv) -> None:
    """Người GỬI an.nv (nv001) có dòng users + sếp fin_head có dòng → nếu route lấy nhầm dòng người gửi thì sẽ ra `known`/finance."""
    assert "nv001" in env.store.users  # tiền điều kiện: an.nv đã đăng nhập (_pending)
    _put_user(env, "nv001", username="an.nv", department="finance", manager_id="fin_head")  # fmt: skip
    _put_user(env, "fin_head", username="lan.dt", department="finance", manager_id=None, full_name=BOSS_NAME)  # fmt: skip


def _account_action(requested_for: str = "nv002") -> Action:
    """`reset_password` (account) cho người khác — `requested_for` = người BỊ TÁC ĐỘNG (D-41); `account_type` ∈ slots.yaml (ad)."""
    m = get_action_metadata().of("account")["reset_password"]
    return Action(
        type="reset_password", target=f"user:{requested_for}", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"account_type": "ad"}, facts={},
    )  # fmt: skip


async def _put_account_action(env: DeskEnv, ticket: str, aid: str, action: Action) -> None:  # fmt: skip
    """Như `_put_action` + `intent="account"` trong checkpoint (hành động account thật đi kèm intent account)."""
    plan_hash = hash_action(action)
    update = {"intended_action": action, "action_plan_hash": plan_hash, "intent": "account"}  # fmt: skip
    await env.h.runner.graph.aupdate_state(env.h.runner.config(ticket), update)
    _row(env, aid)["action_plan_hash"] = plan_hash


async def _put_risk(env: DeskEnv, ticket: str, risk: RiskDecision | None) -> None:
    """Đặt `risk` vào checkpoint — không đổi hash phiếu, `intended_action` giữ nguyên."""
    await env.h.runner.graph.aupdate_state(env.h.runner.config(ticket), {"risk": risk})
    snap = await env.h.runner.snapshot(ticket)
    assert snap.values["risk"] == risk and snap.next == ("approval_wait",)


async def _no_none_text_precondition(env: DeskEnv, ticket: str) -> None:
    """f5 tiền điều kiện: dữ liệu KHÔNG do F6 sinh (lý do rủi ro của B12 giả, câu đã che) không chứa "không có" — để assert f5 trên
    `r.text` đỏ chỉ vì `affected`."""
    snap = await env.h.runner.snapshot(ticket)
    risk = snap.values.get("risk")
    assert risk is None or "không có" not in risk.reason, risk
    assert "không có" not in snap.values["redacted_request"]


def _assert_f5(r: httpx.Response) -> None:
    """f5: không giá trị nào nghĩa "không có quản lý" — chuỗi "không có" không xuất hiện; `manager.status` ∈ {known, unknown}."""
    assert "không có" not in r.text
    assert r.json()["affected"]["manager"]["status"] in MANAGER_STATUSES


async def _view_ok(env: DeskEnv, aid: str) -> dict[str, Any]:
    r = await _view(env, aid, await _login(env, "ha.lt"))
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert set(body) == VIEW_KEYS
    return body


async def test_f6_f1_f5_affected_is_requester_manager_known() -> None:
    """f1 + f5: người bị tác động = CHÍNH người gửi (vpn `requested_for="nv001"`); nv001 có dòng users (finance, manager_id
    fin_head), fin_head có dòng với full_name đặt tay → `affected` = {nv001, is_requester True, finance, manager known fin_head + tên}."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_action(env, ticket, aid, _vpn_action("nv001"))
        ha = await _login(env, "ha.lt")
        _requester_known(env)
        await _no_none_text_precondition(env, ticket)
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == VIEW_KEYS
        assert body["affected"] == {
            "user_id": "nv001", "is_requester": True, "department": "finance",
            "manager": {"status": "known", "user_id": "fin_head", "full_name": BOSS_NAME},
        }  # fmt: skip
        _assert_f5(r)


@pytest.mark.parametrize("boss_row", [True, False], ids=["sep-co-dong", "sep-khong-dong"])  # fmt: skip
async def test_f6_f2_f5_affected_other_person_manager_known(boss_row: bool) -> None:
    """f2 + f5: account `requested_for="nv002"` ≠ người gửi nv001; nv002 có dòng (finance, manager fin_head) → is_requester False,
    manager `known`. Biến thể `sep-khong-dong`: fin_head KHÔNG có dòng users → vẫn `known`, user_id "fin_head", full_name None."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_account_action(env, ticket, aid, _account_action("nv002"))
        ha = await _login(env, "ha.lt")
        _requester_known(env)
        _put_user(env, "nv002", username="binh.tt", department="finance", manager_id="fin_head")  # fmt: skip
        if not boss_row:
            env.store.users.pop("fin_head")
            assert "fin_head" not in env.store.users and env.store.users["nv002"].manager_id == "fin_head"  # fmt: skip
        await _no_none_text_precondition(env, ticket)
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        assert r.json()["affected"] == {
            "user_id": "nv002", "is_requester": False, "department": "finance",
            "manager": {"status": "known", "user_id": "fin_head", "full_name": BOSS_NAME if boss_row else None},
        }  # fmt: skip
        _assert_f5(r)


async def test_f6_f3_f5_affected_row_without_manager_unknown() -> None:
    """f3 + f5: người bị tác động nv002 có dòng users nhưng `manager_id` NULL → manager `unknown` (user_id/full_name None),
    `department` vẫn lấy từ dòng (đặt "hr" — khác phòng người gửi để không trùng ngẫu nhiên). Người gửi có sếp `known`."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_account_action(env, ticket, aid, _account_action("nv002"))
        ha = await _login(env, "ha.lt")
        _requester_known(env)
        _put_user(env, "nv002", username="binh.tt", department="hr", manager_id=None)
        await _no_none_text_precondition(env, ticket)
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        assert r.json()["affected"] == {"user_id": "nv002", "is_requester": False, "department": "hr", "manager": UNKNOWN_MANAGER}  # fmt: skip
        _assert_f5(r)


@pytest.mark.parametrize("who", ["nv002", "fake"], ids=["account-nv002-khong-dong", "fake-action"])  # fmt: skip
async def test_f6_f4_f5_affected_no_users_row_unknown(who: str) -> None:
    """f4 + f5: người bị tác động KHÔNG có dòng users → manager `unknown`, department None, is_requester False. Người GỬI an.nv có
    dòng (finance) + sếp `known` → route lấy nhầm dòng người gửi thì đỏ.
    - `account-nv002-khong-dong`: account `requested_for="nv002"`, binh.tt chưa từng đăng nhập (không dòng).
    - `fake-action`: `FAKE_ACTION` mặc định của desk_env (`requested_for="fake"`)."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        if who == "nv002":
            await _put_account_action(env, ticket, aid, _account_action("nv002"))
        else:
            assert FAKE_ACTION.requested_for == "fake"
            snap = await env.h.runner.snapshot(ticket)
            assert snap.values["intended_action"] == FAKE_ACTION
        ha = await _login(env, "ha.lt")
        _requester_known(env)
        assert who not in env.store.users
        await _no_none_text_precondition(env, ticket)
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        assert r.json()["affected"] == {"user_id": who, "is_requester": False, "department": None, "manager": UNKNOWN_MANAGER}  # fmt: skip
        _assert_f5(r)


async def test_f6_f6_f10_risk_view_rule_twelve_keys() -> None:
    """f6 + f10: RiskDecision do LUẬT (R81 giả, approval_required, medium, HITL, không xác suất) → `risk_view` = đúng 12 khoá: các
    trường như checkpoint + `calibrated` False + `auto_allowed` False; `risk` thô giữ nguyên."""
    risk = RiskDecision(
        decided_by="rule", policy_decision="approval_required", matched_rule_id="R81", raw_prob=None, calibrated_prob=None,
        p_method=None, risk_level="medium", route="HITL", reason="Luật giả R81 đòi người duyệt", thresholds=None,
    )  # fmt: skip
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_risk(env, ticket, risk)
        body = await _view_ok(env, aid)
        assert set(body["risk_view"]) == RISK_VIEW_KEYS
        assert body["risk_view"] == {
            "decided_by": "rule", "policy_decision": "approval_required", "matched_rule_id": "R81", "risk_level": "medium",
            "route": "HITL", "reason": "Luật giả R81 đòi người duyệt", "raw_prob": None, "calibrated_prob": None,
            "p_method": None, "thresholds": None, "calibrated": False, "auto_allowed": False,
        }  # fmt: skip
        assert body["risk"] == risk.model_dump(mode="json")


async def test_f6_f7_f10_risk_view_llm_uncalibrated() -> None:
    """f7 + f10: LLM chưa hiệu chỉnh (raw 0.41, self_report, calibrated_prob None, ngưỡng giả) → `calibrated` False, `auto_allowed`
    False, `thresholds` ra JSON là list [0.137, 0.863]."""
    risk = RiskDecision(
        decided_by="llm", policy_decision=None, matched_rule_id=None, raw_prob=0.41, calibrated_prob=None,
        p_method="self_report", risk_level="medium", route="HITL", reason="Ước lượng giả mức trung bình",
        thresholds=FAKE_THRESHOLDS,
    )  # fmt: skip
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_risk(env, ticket, risk)
        body = await _view_ok(env, aid)
        view = body["risk_view"]
        assert set(view) == RISK_VIEW_KEYS
        assert {k: view[k] for k in RISK_FIELDS} == risk.model_dump(mode="json")
        assert view["thresholds"] == [0.137, 0.863]
        assert (view["calibrated"], view["auto_allowed"]) == (False, False)
        assert body["risk"] == risk.model_dump(mode="json")


async def test_f6_f8_f10_risk_view_llm_calibrated_auto() -> None:
    """f8 + f10: LLM có `calibrated_prob` 0.12, sampling_k5, route AUTO, low → `calibrated` True, `auto_allowed` True."""
    risk = RiskDecision(
        decided_by="llm", policy_decision=None, matched_rule_id=None, raw_prob=0.19, calibrated_prob=0.12,
        p_method="sampling_k5", risk_level="low", route="AUTO", reason="Ước lượng giả mức thấp", thresholds=FAKE_THRESHOLDS,
    )  # fmt: skip
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_risk(env, ticket, risk)
        view = (await _view_ok(env, aid))["risk_view"]
        assert set(view) == RISK_VIEW_KEYS
        assert {k: view[k] for k in RISK_FIELDS} == risk.model_dump(mode="json")
        assert (view["calibrated"], view["auto_allowed"]) == (True, True)


async def test_f6_f9_risk_none_risk_view_null() -> None:
    """f9: checkpoint `risk` None → `risk_view` null, `risk` null, vẫn đủ 14 khoá."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_risk(env, ticket, None)
        body = await _view_ok(env, aid)
        assert (body["risk"], body["risk_view"]) == (None, None)


async def test_f6_f11_users_read_error_raises_no_first_viewed_at() -> None:
    """f11: đọc `users` của người bị tác động (nv002) LỖI → lỗi nổi lên (không nuốt thành `unknown`), `first_viewed_at` KHÔNG ghi.
    Lỗi chỉ tiêm cho nv002, SAU khi ha.lt đã đăng nhập — tầng quyền / chuỗi của người duyệt vẫn đọc users bình thường."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        await _put_account_action(env, ticket, aid, _account_action("nv002"))
        ha = await _login(env, "ha.lt")
        _put_user(env, "nv002", username="binh.tt", department="finance", manager_id=None)  # fmt: skip
        original = env.store.get_user

        async def get_user(user_id: str) -> UserRecord | None:
            if user_id == "nv002":
                raise UsersReadError("bảng users giả đang lỗi")
            return await original(user_id)

        env.store.get_user = get_user  # type: ignore[method-assign]
        with pytest.raises(UsersReadError):
            await _view(env, aid, ha)
        assert _row(env, aid).get("first_viewed_at") is None


def _schema(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Theo `$ref` (nếu có) tới components."""
    ref = node.get("$ref")
    if isinstance(ref, str):
        resolved: dict[str, Any] = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        return resolved
    return node


def _enum_values(spec: dict[str, Any], node: dict[str, Any]) -> set[Any]:
    """Tập giá trị enum của một property: `enum` nằm thẳng, `const` một giá trị, hoặc trong `anyOf`/`oneOf` (Literal | None sinh
    anyOf [{enum, type}, {type: null}]) — bỏ nhánh null."""
    node = _schema(spec, node)
    if "enum" in node:
        return {v for v in node["enum"] if v is not None}
    if "const" in node:
        return {node["const"]} - {None}
    out: set[Any] = set()
    for sub in [*node.get("anyOf", []), *node.get("oneOf", [])]:
        out |= _enum_values(spec, sub)
    return out


def _ref_name(node: dict[str, Any]) -> str | None:
    ref = node.get("$ref")
    return ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None


async def test_f6_f12_openapi_approval_view_schema() -> None:
    """f12: route có `response_model=ApprovalView` — 200 application/json `$ref` ApprovalView (14 khoá); `affected` → AffectedView
    (4 khoá), `manager` → ManagerRef (status enum {known, unknown}); `risk_view` → anyOf [RiskView, null]; RiskView 12 khoá với enum
    đúng, `calibrated`/`auto_allowed` boolean. (async chỉ vì `pytestmark` asyncio của module — không dùng desk_env.)"""
    spec = create_app(auth_settings(), health_checks={}).openapi()
    schemas = spec["components"]["schemas"]
    ok = spec["paths"][VIEW_ROUTE]["get"]["responses"]["200"]["content"]["application/json"]["schema"]  # fmt: skip
    assert _ref_name(ok) == "ApprovalView", ok
    view = schemas["ApprovalView"]["properties"]
    assert set(view) == VIEW_KEYS | {"matched_rules"}  # P3 tuần 8: khoá tuỳ chọn (không có dữ liệu B13/B14 → bỏ khoá)
    assert set(schemas["ApprovalView"]["required"]) == VIEW_KEYS
    assert _ref_name(view["affected"]) == "AffectedView", view["affected"]
    affected = schemas["AffectedView"]["properties"]
    assert set(affected) == AFFECTED_KEYS
    assert _ref_name(affected["manager"]) == "ManagerRef", affected["manager"]
    status = schemas["ManagerRef"]["properties"]["status"]
    assert _enum_values(spec, status) == MANAGER_STATUSES
    any_of = view["risk_view"].get("anyOf", [])
    branches = sorted((_ref_name(s) or s.get("type")) for s in any_of)
    assert branches == ["RiskView", "null"], view["risk_view"]
    risk = schemas["RiskView"]["properties"]
    assert set(risk) == RISK_VIEW_KEYS
    assert _enum_values(spec, risk["decided_by"]) == {"rule", "llm"}
    assert _enum_values(spec, risk["route"]) == {"AUTO", "HITL", "ESCALATE_L2"}
    assert _enum_values(spec, risk["risk_level"]) == {"low", "medium", "high"}
    assert _enum_values(spec, risk["p_method"]) == {"self_report", "sampling_k5"}
    assert _enum_values(spec, risk["policy_decision"]) == {"allow", "approval_required", "deny"}  # fmt: skip
    for key in ("calibrated", "auto_allowed"):
        assert risk[key].get("type") == "boolean", (key, risk[key])


@pytest.mark.parametrize(
    ("facts", "titles", "want"),
    [
        ({"target_is_service_account": True, "target_account_privilege": "admin"},
         {"KB-ACC-001": "Tự đặt lại mật khẩu tài khoản cá nhân", "KB-ACC-003": "Quy trình đặt lại mật khẩu tài khoản quản trị"},
         {"doc_id": "KB-ACC-003", "title": "Quy trình đặt lại mật khẩu tài khoản quản trị"}),
        ({"target_is_service_account": True, "target_account_privilege": "admin"},
         {"KB-ACC-001": "Tự đặt lại mật khẩu tài khoản cá nhân"},  # bài đặc quyền không có trong KB hiện hành → về bài thường
         {"doc_id": "KB-ACC-001", "title": "Tự đặt lại mật khẩu tài khoản cá nhân"}),
        ({"target_is_service_account": False, "target_account_privilege": "standard_user"},
         {"KB-ACC-001": "Tự đặt lại mật khẩu tài khoản cá nhân", "KB-ACC-003": "Quy trình đặt lại mật khẩu tài khoản quản trị"},
         {"doc_id": "KB-ACC-001", "title": "Tự đặt lại mật khẩu tài khoản cá nhân"}),
    ],
    ids=["dich-vu", "dich-vu-thieu-bai", "thuong"],
)  # fmt: skip
async def test_view_procedure_tai_khoan_dich_vu_1313(facts: dict[str, Any], titles: dict[str, str], want: dict[str, str]) -> None:
    """13/11: đặt lại mật khẩu `svc_backup` (dịch vụ, quản trị) → căn cứ KB-ACC-003, không phải KB-ACC-001 (tài khoản cá nhân)."""
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        m = get_action_metadata().of("account")["reset_password"]
        action = Action(
            type="reset_password", target="user:svc_backup", requested_for="svc_backup", scope=m.scope,
            privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
            data_sensitivity=m.data_sensitivity, params={"account_type": "ad"}, facts=facts,
        )  # fmt: skip
        await env.h.runner.graph.aupdate_state(env.h.runner.config(ticket), {"intent": "account"})
        await _put_action(env, ticket, aid, action)
        env.h.approvals.titles.update(titles)
        r = await _view(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        assert r.json()["procedure"] == want
