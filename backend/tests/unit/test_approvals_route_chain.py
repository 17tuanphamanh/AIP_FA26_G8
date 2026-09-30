"""`POST /api/approvals/{id}/decision` kiểm xung đột bằng CÙNG `conflict_type` với B15 (Phase 4 chặng 4b P4, Q-4-R; phase4 mục 5.3
b2, b2b). Viết TỪ ĐẶC TẢ — khuôn `test_approvals_api.py` + `tests/fakes/desk.py`.

Chuỗi quản lý của người quyết dựng từ BẢNG `users` (theo `manager_id`, ≤ 5 cấp, chặn vòng) — dòng `users` do đăng nhập tạo (đồng bộ AD
kéo theo chuỗi quản lý). Người dùng dựng RIÊNG (không dùng `seed_ad_users`: bản đó có `l1_01 → it_mgr01`): seed sau P14
`l1_01 (ha.lt) → l1_lead (khoa.dv) → it_mgr01 (quan.tm)`. Phiếu do B15 GIẢ tạo, giao `l1_01` (người duyệt giả của harness).

- b2: `l1_lead` (sếp trực tiếp) gửi → `l1_01` quyết → 403 + `permission_denied` +1, không resume.
- b2b: `it_mgr01` (sếp của sếp) gửi → 403 (chuỗi 2 cấp, Q-4-R; M-4b-11 "route dùng hàm riêng chỉ sếp trực tiếp" phải đỏ ở đây).
- Biên ≤ 5 cấp: sếp cấp 5 → 403; cấp 6 → 202. Đối chứng: người ngoài chuỗi (nv001) → 202.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pyotp
import pytest
from app.auth.mfa import MfaCipher, enroll
from app.domain.states import S_PENDING_APPROVAL
from tests.fakes.auth import DEMO_PASSWORD, FakeAdUser
from tests.fakes.desk import APPROVER, DeskEnv, desk_env
from tests.fakes.identity import ad_user

pytestmark = pytest.mark.asyncio


def _chain_people() -> list[FakeAdUser]:
    return [
        FakeAdUser("it_mgr01", "quan.tm", ["IT-Users", "IT-Manager"], None, department="IT"),
        FakeAdUser("l1_lead", "khoa.dv", ["IT-Users", "IT-L1"], "it_mgr01", department="IT"),
        FakeAdUser("l1_01", "ha.lt", ["IT-Users", "IT-L1"], "l1_lead", department="IT"),
        FakeAdUser("fin_head", "lan.dt", ["IT-Users"], None, department="finance"),
        FakeAdUser("nv001", "an.nv", ["IT-Users"], "fin_head", department="finance"),
    ]


def _deep_people() -> list[FakeAdUser]:
    """l1_01 → m1 → m2 → m3 → m4 → m5 → m6 (m6 là sếp cấp 6 của người duyệt)."""
    ms = [FakeAdUser(f"m{i}", f"m{i}.boss", ["IT-Users"], f"m{i + 1}" if i < 6 else None, department="IT")
          for i in range(1, 7)]  # fmt: skip
    return [FakeAdUser("l1_01", "ha.lt", ["IT-Users", "IT-L1"], "m1", department="IT"), *ms]


@asynccontextmanager
async def _env(people: list[FakeAdUser]) -> AsyncIterator[DeskEnv]:
    """desk_env với danh bạ RIÊNG: AD của đăng nhập (`idp`) và AD của B1 (`h.ad`) cùng người, cùng `manager_id`."""
    async with desk_env() as env:
        env.idp.users = {u.user_id: u for u in people}
        env.h.ad.users = {
            u.user_id: ad_user(u.user_id, username=u.username, groups=tuple(u.groups), department=u.department,
                               manager_id=u.manager_id, employment_status=u.employment_status, hired_at=u.hired_at)
            for u in people
        }  # fmt: skip
        yield env


async def _headers(env: DeskEnv, username: str) -> dict[str, str]:
    r = await env.login(username)
    if r.status_code == 200:
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    # manager: bắt buộc MFA — lần đầu 401 (tạo dòng users), enroll qua đúng hàm CLI, đăng nhập kèm OTP (khuôn auth_helpers)
    assert r.status_code == 401, r.text
    key = env.settings.mfa_enc_key
    assert key is not None
    enrolled = await enroll(env.store, env.sink, MfaCipher(key), username=username, by="ops", reason="test")
    otp = pyotp.TOTP(enrolled.secret).at(env.clock.now())
    r = await env.client.post("/api/auth/login", json={"username": username, "password": DEMO_PASSWORD, "otp": otp})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _resumes(env: DeskEnv, ticket: str) -> int:
    return sum(1 for t in env.h.turns.of(ticket) if t["event_type"] == "resume")


async def _pending_from(env: DeskEnv, requester: str) -> tuple[str, str]:
    headers = await _headers(env, requester)
    ticket = await env.create(headers)
    await env.drain()
    assert (await env.ticket(ticket, headers))["status"] == S_PENDING_APPROVAL
    aid = env.approval_of(ticket)
    assert env.h.approvals._table[aid]["approver_id"] == APPROVER == "l1_01"
    return ticket, aid


def _manager_of(env: DeskEnv, user_id: str) -> str | None:
    row = env.store.users.get(user_id)
    assert row is not None, f"chưa có dòng users {user_id}"
    return row.manager_id


async def _decide(env: DeskEnv, aid: str, headers: dict[str, str]) -> Any:
    return await env.client.post(f"/api/approvals/{aid}/decision", json={"decision": "approved"}, headers=headers)


async def _assert_denied(env: DeskEnv, ticket: str, aid: str, l1: dict[str, str]) -> None:
    denied = env.denied()
    r = await _decide(env, aid, l1)
    assert r.status_code == 403, r.text
    assert env.denied() == denied + 1
    await env.drain()
    assert _resumes(env, ticket) == 0 and env.late(ticket) == []
    assert env.h.approvals.status(aid) == "pending"


@pytest.mark.parametrize(
    ("requester", "note"),
    [pytest.param("khoa.dv", "b2-sep-truc-tiep", id="b2-l1_lead"), pytest.param("quan.tm", "b2b-chuoi-2-cap", id="b2b-it_mgr01")],
)
async def test_b2_requester_in_approver_chain_from_users_table_403(requester: str, note: str) -> None:
    """b2/b2b (phase4 5.3; P4 "route dựng chain từ bảng users, ≤ 5 cấp — MỘT định nghĩa `conflict_type`"): người gửi nằm trong chuỗi
    quản lý của người được giao (`l1_01`) → `boss_of_approver` → 403 + `permission_denied`, không resume, phiếu vẫn `pending`."""
    async with _env(_chain_people()) as env:
        l1 = await _headers(env, "ha.lt")  # đồng bộ l1_01 kéo theo chuỗi l1_lead → it_mgr01
        ticket, aid = await _pending_from(env, requester)
        assert (_manager_of(env, "l1_01"), _manager_of(env, "l1_lead"), _manager_of(env, "it_mgr01")) == (
            "l1_lead", "it_mgr01", None), note  # fmt: skip
        await _assert_denied(env, ticket, aid, l1)


async def test_b2_control_requester_outside_chain_202() -> None:
    """Đối chứng b2: nv001 (ngoài chuỗi của l1_01) gửi → l1_01 quyết được (202) — 403 ở trên là do chuỗi, không do dựng người."""
    async with _env(_chain_people()) as env:
        l1 = await _headers(env, "ha.lt")
        ticket, aid = await _pending_from(env, "an.nv")
        denied = env.denied()
        r = await _decide(env, aid, l1)
        assert r.status_code == 202, r.text
        assert env.denied() == denied
        await env.drain()
        assert _resumes(env, ticket) == 1


async def test_b2_chain_level_5_boss_403() -> None:
    """Biên ≤ 5 cấp (Q-4-R, MAX_CHAIN_DEPTH): m5 là sếp cấp 5 của l1_01 trong bảng users → 403."""
    async with _env(_deep_people()) as env:
        l1 = await _headers(env, "ha.lt")  # tạo m1…m5 (m5.manager_id NULL — cấp 6 bị cắt khi đồng bộ)
        ticket, aid = await _pending_from(env, "m5.boss")
        assert [_manager_of(env, u) for u in ("l1_01", "m1", "m2", "m3", "m4")] == ["m1", "m2", "m3", "m4", "m5"]
        await _assert_denied(env, ticket, aid, l1)


async def test_b2_chain_level_6_boss_not_conflict_202() -> None:
    """Biên ≤ 5 cấp: m6 là sếp cấp 6 (m5 đăng nhập → dòng m5 trỏ m6) → ngoài chuỗi 5 cấp → không xung đột → 202."""
    async with _env(_deep_people()) as env:
        l1 = await _headers(env, "ha.lt")
        await _headers(env, "m5.boss")  # dòng m5.manager_id = m6
        ticket, aid = await _pending_from(env, "m6.boss")
        assert [_manager_of(env, u) for u in ("l1_01", "m1", "m2", "m3", "m4", "m5")] == ["m1", "m2", "m3", "m4", "m5", "m6"]
        r = await _decide(env, aid, l1)
        assert r.status_code == 202, r.text
        await env.drain()
        assert _resumes(env, ticket) == 1
