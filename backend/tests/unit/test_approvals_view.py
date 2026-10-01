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

from datetime import datetime, timedelta
from typing import Any

import httpx
import pyotp
import pytest
from app.auth.mfa import MfaCipher, enroll
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import S_PENDING_APPROVAL
from app.graph.fakes import FAKE_ACTION
from app.settings import get_action_metadata
from pydantic import BaseModel
from tests.fakes.auth import DEMO_PASSWORD
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env

pytestmark = pytest.mark.asyncio

PRIMARY = "l1_01"  # ha.lt — người duyệt của B15 giả trong desk_env
BACKUP = "l1_02"  # duc.pv — dự phòng đặt tay
VIEW_ROUTE = "/api/approvals/{approval_id}"
# Hợp đồng PLAN-4c 2.1 / spec 6.1 P6 LIỆT KÊ 12 tên khoá (2.1 ghi "ĐÚNG 13 khoá" nhưng chỉ kể 12 — xem báo cáo test-writer).
VIEW_KEYS = {
    "approval_id", "ticket_id", "status", "deadline", "requester", "request_summary", "action", "action_plan_hash", "risk",
    "facts", "role_as", "procedure",
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
        assert body["requester"] == {"role": rc.role, "department": rc.department}
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
        assert r.json()["requester"] == {"role": "l1", "department": "it"}
