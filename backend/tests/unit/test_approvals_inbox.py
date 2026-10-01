"""Hộp thư người duyệt `GET /api/approvals?mine=1[&status=…]` qua HTTP — Phase 4 chặng 4c DỪNG 2 (c10). Viết TỪ ĐẶC TẢ, trước thân
code: phase4 mục 6.1 P4, P5 + 6.2 c10; PLAN-4c mục 2.1 (hợp đồng + "Bổ sung khi dựng khung S7"), TQ-9, TQ-10; Q-4-E (hộp thư = API).

- Chỉ phiếu tôi được giao (`role_as="primary"`) + phiếu tôi là dự phòng ĐÃ qua nhắc 2 (`role_as="backup"`); dự phòng chưa nhắc 2 → không
  thấy; L1 khác không thấy phiếu người khác; manager (`audit:read:all`) cũng chỉ thấy phiếu của mình (`mine=1`).
- `require("approval:decide")` TRƯỚC kiểm tham số: L2 / nhân viên → 403 (kể cả thiếu `mine`).
- `mine` thiếu / ≠ `1` → 422 `{"error": "invalid_request", "fields": ["query.mine"]}`; `status` ngoài {pending, approved, rejected, timeout}
  → 422 `fields == ["query.status"]`.
- 200 `{"items": [...]}`, ≤ 50, `created_at` giảm dần; mỗi mục ĐÚNG 10 khoá; `action_type` = `intended_action.type`, `device_id` = phần sau
  `device:` của `intended_action.target` (khác → null), lấy từ dòng audit B15 `queued` CÙNG `action_plan_hash` của phiếu (5.7 #5).

`desk_env`: B15 giả giao `l1_01` (ha.lt), không dự phòng, KHÔNG ghi `intended_action` vào dòng `queued` → `action_type`/`device_id` null
trừ khi test thêm dòng audit như B15 thật ghi. Người duyệt khác / dự phòng / nhắc 2 đặt tay vào bảng giả.
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
from app.settings import get_action_metadata
from tests.fakes.auth import DEMO_PASSWORD
from tests.fakes.desk import DeskEnv, desk_env

pytestmark = pytest.mark.asyncio

PRIMARY = "l1_01"  # ha.lt
OTHER_L1 = "l1_02"  # duc.pv
ITEM_KEYS = {
    "approval_id", "ticket_id", "status", "created_at", "deadline", "reminder_1_at", "reminder_2_at", "role_as", "action_type",
    "device_id",
}  # fmt: skip
INBOX_LIMIT = 50


# ---- helpers ---------------------------------------------------------------------------------------------------------------


async def _login(env: DeskEnv, username: str) -> dict[str, str]:
    """Đăng nhập; manager bắt buộc MFA (khuôn `test_approvals_route_chain._headers`)."""
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


async def _pending(env: DeskEnv, headers: dict[str, str]) -> tuple[str, str]:
    ticket = await env.create(headers)
    await env.drain()
    assert (await env.ticket(ticket, headers))["status"] == S_PENDING_APPROVAL
    return ticket, env.approval_of(ticket)


async def _pendings(env: DeskEnv, n: int) -> list[tuple[str, str]]:
    """`n` phiếu của an.nv, mỗi phiếu tạo cách nhau 1 phút (FakeClock) → `created_at` khác nhau, tăng dần."""
    an = await _login(env, "an.nv")
    out = []
    for i in range(n):
        if i:
            env.clock.advance(timedelta(minutes=1))
        out.append(await _pending(env, an))
    return out


def _row(env: DeskEnv, aid: str) -> dict[str, Any]:
    return env.h.approvals._table[aid]


def _set_backup(env: DeskEnv, aid: str, backup: str, *, reminded_2: bool) -> None:
    row = _row(env, aid)
    row["backup_approver_id"] = backup
    row["reminder_1_at"] = env.clock.now()
    row["reminder_2_at"] = env.clock.now() if reminded_2 else None


async def _inbox(env: DeskEnv, headers: dict[str, str], query: str = "mine=1") -> httpx.Response:
    return await env.client.get(f"/api/approvals?{query}" if query else "/api/approvals", headers=headers)


def _ids_roles(r: httpx.Response) -> list[tuple[str, str]]:
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items"}
    return [(str(i["approval_id"]), i["role_as"]) for i in body["items"]]


def _action(target: str = "device:LAP-0501", action_type: str = "renew_vpn_cert") -> Action:
    m = get_action_metadata().of("vpn")[action_type]
    return Action(
        type=action_type, target=target, requested_for="nv001", scope=m.scope, privilege_level=m.privilege_level,
        reversible=m.reversible, reversibility=m.reversibility, data_sensitivity=m.data_sensitivity,
        params={"device_id": "LAP-0501"}, facts={"device_owner_is_requester": True},
    )  # fmt: skip


async def _store_view(env: DeskEnv, user_id: str) -> list[tuple[str, dict[str, Any] | None]]:
    """Tiền điều kiện: dữ liệu dựng tay đúng ngữ nghĩa nguồn (bảng giả `inbox` = SQL TQ-10) — chạy được trước khi có thân route."""
    return [(r.approval_id, r.intended_action) for r in await env.h.approvals.inbox(user_id, None, 500)]


def _queued(env: DeskEnv, ticket: str, plan_hash: str, action: Action) -> None:
    """Dòng audit B15 `queued` như B15 THẬT ghi (cột `action_plan_hash` + `intended_action` JSON có `type`, `target`) — PLAN-4c 2.1."""
    env.h.audit.rows.append({"ticket_id": ticket, "step": "B15", "event": "queued", "action_plan_hash": plan_hash,
                             "intended_action": action.model_dump(mode="json")})  # fmt: skip


# ---- c10: lọc theo vai trò ------------------------------------------------------------------------------------------------------


async def test_c10_mine_only_assigned_and_backup_after_reminder2() -> None:
    """c10 (P5 + P4): a1 giao l1_01; a2 giao l1_01, dự phòng l1_02 CHƯA nhắc 2; a3 giao l1_01, dự phòng l1_02 ĐÃ nhắc 2; a4 giao l1_02.
    ha.lt thấy a3, a2, a1 (primary, mới nhất trước), KHÔNG thấy a4; duc.pv thấy a4 (primary), a3 (backup), KHÔNG thấy a1 / a2."""
    async with desk_env() as env:
        (_, a1), (_, a2), (_, a3), (_, a4) = await _pendings(env, 4)
        _set_backup(env, a2, OTHER_L1, reminded_2=False)
        _set_backup(env, a3, OTHER_L1, reminded_2=True)
        _row(env, a4)["approver_id"] = OTHER_L1
        assert [a for a, _ in await _store_view(env, PRIMARY)] == [a3, a2, a1]
        assert [a for a, _ in await _store_view(env, OTHER_L1)] == [a4, a3]
        ha, duc = await _login(env, "ha.lt"), await _login(env, "duc.pv")
        assert _ids_roles(await _inbox(env, ha)) == [(a3, "primary"), (a2, "primary"), (a1, "primary")]
        assert _ids_roles(await _inbox(env, duc)) == [(a4, "primary"), (a3, "backup")]


async def test_c10_backup_appears_only_after_reminder2_is_set() -> None:
    """c10 (Q-4-O): cùng một phiếu — dự phòng không thấy khi `reminder_2_at` NULL, thấy (`role_as="backup"`) ngay khi có nhắc 2."""
    async with desk_env() as env:
        [(_, aid)] = await _pendings(env, 1)
        _set_backup(env, aid, OTHER_L1, reminded_2=False)
        duc = await _login(env, "duc.pv")
        assert _ids_roles(await _inbox(env, duc)) == []
        _row(env, aid)["reminder_2_at"] = env.clock.now()
        assert _ids_roles(await _inbox(env, duc)) == [(aid, "backup")]


async def test_c10_manager_sees_only_own_not_everything() -> None:
    """c10 "chỉ phiếu của tôi": manager có `approval:decide` + `audit:read:all` nhưng `mine=1` KHÔNG trả phiếu giao người khác."""
    async with desk_env() as env:
        await _pendings(env, 2)
        quan = await _login(env, "quan.tm")
        assert _ids_roles(await _inbox(env, quan)) == []


# ---- c10: hình dạng mục --------------------------------------------------------------------------------------------------------


async def test_c10_item_exactly_10_keys_and_values_fake_b15_null_action() -> None:
    """P5 / 2.1: mỗi mục ĐÚNG 10 khoá; giá trị khớp phiếu; B15 giả không ghi `intended_action` → `action_type`/`device_id` null."""
    async with desk_env() as env:
        [(ticket, aid)] = await _pendings(env, 1)
        _set_backup(env, aid, OTHER_L1, reminded_2=True)
        r = await _inbox(env, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        [item] = r.json()["items"]
        assert set(item) == ITEM_KEYS
        row = _row(env, aid)
        assert (str(item["approval_id"]), item["ticket_id"], item["status"], item["role_as"]) == (aid, ticket, "pending", "primary")
        assert datetime.fromisoformat(item["created_at"]) == row["created_at"]
        assert datetime.fromisoformat(item["deadline"]) == row["deadline"]
        assert datetime.fromisoformat(item["reminder_1_at"]) == row["reminder_1_at"]
        assert datetime.fromisoformat(item["reminder_2_at"]) == row["reminder_2_at"]
        assert (item["action_type"], item["device_id"]) == (None, None)


async def test_c10_reminders_null_when_not_reminded() -> None:
    async with desk_env() as env:
        await _pendings(env, 1)
        r = await _inbox(env, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        [item] = r.json()["items"]
        assert (item["reminder_1_at"], item["reminder_2_at"]) == (None, None)


async def test_c10_action_type_and_device_from_b15_queued_same_hash() -> None:
    """P5 + 5.7 #5: `action_type` = `intended_action.type`, `device_id` = phần sau `device:` — từ dòng audit B15 `queued` CÙNG
    `action_plan_hash` của phiếu."""
    async with desk_env() as env:
        [(ticket, aid)] = await _pendings(env, 1)
        _queued(env, ticket, _row(env, aid)["action_plan_hash"], _action())
        assert await _store_view(env, PRIMARY) == [(aid, _action().model_dump(mode="json"))]
        r = await _inbox(env, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        [item] = r.json()["items"]
        assert (item["action_type"], item["device_id"]) == ("renew_vpn_cert", "LAP-0501")


async def test_c10_device_id_null_when_target_not_device() -> None:
    """P5 / 2.1: `device_id` = phần sau `device:` HOẶC null — đích không phải `device:` → null, `action_type` vẫn có."""
    async with desk_env() as env:
        [(ticket, aid)] = await _pendings(env, 1)
        _queued(env, ticket, _row(env, aid)["action_plan_hash"], _action(target="user:nv001"))
        assert await _store_view(env, PRIMARY) == [(aid, _action(target="user:nv001").model_dump(mode="json"))]
        r = await _inbox(env, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        [item] = r.json()["items"]
        assert (item["action_type"], item["device_id"]) == ("renew_vpn_cert", None)


async def test_c10_queued_row_with_other_hash_not_used() -> None:
    """5.7 #5 / TQ-10: dòng audit B15 `queued` có hash KHÁC hash phiếu (kế hoạch cũ) → không dùng → `action_type` null."""
    async with desk_env() as env:
        [(ticket, aid)] = await _pendings(env, 1)
        other = _action(action_type="check_vpn_status")
        assert hash_action(other) != _row(env, aid)["action_plan_hash"]
        _queued(env, ticket, hash_action(other), other)
        assert await _store_view(env, PRIMARY) == [(aid, None)]
        r = await _inbox(env, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        [item] = r.json()["items"]
        assert (item["action_type"], item["device_id"]) == (None, None)


# ---- c10: lọc status, giới hạn, thứ tự ------------------------------------------------------------------------------------------


async def test_c10_status_filter() -> None:
    """P5: `status=pending|approved|rejected|timeout` lọc đúng; không `status` → mọi trạng thái, mới nhất trước."""
    async with desk_env() as env:
        (_, a1), (_, a2), (_, a3), (_, a4) = await _pendings(env, 4)
        for aid, status in ((a2, "approved"), (a3, "rejected"), (a4, "timeout")):
            _row(env, aid).update(status=status, decided_at=env.clock.now(), decided_by=PRIMARY, note="x")
        ha = await _login(env, "ha.lt")
        assert [a for a, _ in _ids_roles(await _inbox(env, ha))] == [a4, a3, a2, a1]
        for status, expected in (("pending", a1), ("approved", a2), ("rejected", a3), ("timeout", a4)):
            r = await _inbox(env, ha, f"mine=1&status={status}")
            assert [a for a, _ in _ids_roles(r)] == [expected], status
            assert r.json()["items"][0]["status"] == status


async def test_c10_at_most_50_newest_first() -> None:
    """P5: tối đa 50 mục, `created_at` giảm dần — 55 phiếu của l1_01 (đặt thẳng bảng giả) → đúng 50 phiếu MỚI nhất, theo thứ tự."""
    async with desk_env() as env:
        base = env.clock.now()
        for i in range(55):
            ticket, aid = f"tk-inbox-{i:02d}", str(100 + i)
            created = base - timedelta(hours=2) + timedelta(minutes=i)
            env.h.tickets.register(ticket, created, requester_id="nv001")
            env.h.approvals._table[aid] = {
                "ticket_id": ticket, "approver_id": PRIMARY, "deadline": base + timedelta(minutes=30), "status": "pending",
                "action_plan_hash": "h" * 64, "backup_approver_id": None, "conflict_detected": False, "conflict_type": None,
                "created_at": created,
            }  # fmt: skip
        assert [a for a, _ in await _store_view(env, PRIMARY)] == [str(100 + i) for i in range(54, -1, -1)]
        r = await _inbox(env, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == INBOX_LIMIT
        assert [str(i["approval_id"]) for i in items] == [str(100 + i) for i in range(54, 4, -1)]
        stamps = [datetime.fromisoformat(i["created_at"]) for i in items]
        assert stamps == sorted(stamps, reverse=True)


# ---- c10: 422 / 403 -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "mine=0", "mine=2", "mine=true", "mine=", "status=pending"],
                         ids=["thieu-mine", "mine-0", "mine-2", "mine-true", "mine-rong", "chi-status"])  # fmt: skip
async def test_c10_mine_missing_or_not_1_422(query: str) -> None:
    """c10 + P5: `mine` thiếu hoặc ≠ `1` → 422 `{"error": "invalid_request", "fields": ["query.mine"]}` (không trả `input`)."""
    async with desk_env() as env:
        await _pendings(env, 1)
        r = await _inbox(env, await _login(env, "ha.lt"), query)
        assert r.status_code == 422, r.text
        assert r.json() == {"error": "invalid_request", "fields": ["query.mine"]}


@pytest.mark.parametrize("status", ["PENDING", "open", "late_ignored", "pending,approved"])
async def test_c10_unknown_status_422(status: str) -> None:
    """2.1: `status` ngoài {pending, approved, rejected, timeout} → 422 `fields == ["query.status"]` (kể cả `late_ignored` — có trong
    CHECK DB nhưng không có trong hợp đồng P5)."""
    async with desk_env() as env:
        await _pendings(env, 1)
        r = await _inbox(env, await _login(env, "ha.lt"), f"mine=1&status={status}")
        assert r.status_code == 422, r.text
        assert r.json() == {"error": "invalid_request", "fields": ["query.status"]}


@pytest.mark.parametrize("who", ["long.nh", "an.nv", "binh.tt"], ids=["l2", "nhan-vien-nguoi-gui", "nhan-vien-khac"])
@pytest.mark.parametrize("query", ["mine=1", "", "mine=0&status=xyz"], ids=["mine-1", "thieu-mine", "tham-so-sai"])
async def test_c10_l2_and_employee_403_before_query_check(who: str, query: str) -> None:
    """P5 `require("approval:decide")` + TQ-10 (quyền TRƯỚC 422): L2 / nhân viên → 403 `{"detail": "forbidden"}` dù tham số đúng hay
    sai, +1 `permission_denied`."""
    async with desk_env() as env:
        await _pendings(env, 1)
        headers = await _login(env, who)
        denied = env.denied()
        r = await _inbox(env, headers, query)
        assert r.status_code == 403, r.text
        assert r.json() == {"detail": "forbidden"}
        assert env.denied() == denied + 1
