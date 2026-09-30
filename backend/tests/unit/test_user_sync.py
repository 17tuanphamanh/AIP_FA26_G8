"""`auth/user_sync.py::AdUserSync.sync_user_from_ad` — đồng bộ dòng `users` từ AD, tách NGUYÊN VẸN khỏi `AuthService` (Phase 4 chặng 4b
P5, Q-4-N; phase4 mục 4.10 #3, #11). B15 gọi hàm này để upsert người duyệt chưa từng đăng nhập (FK `approvals.approver_id`), không tạo
phiên. Viết TỪ ĐẶC TẢ, mức `AdUserSync` với `InMemoryAuthStore` + `RecordingSink` (count_failures đọc sự kiện đã ghi vào sink).

(a)(b) mang khoá username ma (Q-4a-6, 4.10 #3/#11): dòng VỪA tạo → đếm lần sai trong cửa sổ bằng `(username, "h:"+HMAC)`; ≥ ngưỡng →
       `locked_until` = lần sai cuối + thời gian khoá, không ghi sự kiện mới; `last` None → tính từ `now` (fail-closed).
(c)    dòng ĐÃ có → không đếm, không ghi đè `locked_until`.
(d)    chuỗi quản lý upsert TRƯỚC (FK `users.manager_id`), ≤ 5 cấp, chặn vòng; không tìm thấy / không ra role / quá sâu / vòng → NULL.
(e)(f) đổi role → token_version tăng + thu hồi phiên + `role_changed` + callback; disabled/terminated → thu hồi phiên + callback.
(g)    nhóm AD không ra role → None, không ghi gì. (h) `get_user` ném → lan ra.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from app.auth.models import SessionRecord, UserRecord
from app.auth.ports import IdentityUnavailable
from app.auth.user_sync import AdUserSync, LockPolicy
from app.auth.username_hash import stored_username
from app.core.clock import FakeClock
from tests.fakes.auth import (
    EPOCH,
    FakeAdUser,
    FakeIdentityProvider,
    InMemoryAuthStore,
    RecordingSink,
)

pytestmark = pytest.mark.asyncio

KEY = b"k" * 32  # khoá HMAC test công khai (như vector 4a-4), không phải bí mật
LOCK = LockPolicy(failure_window=timedelta(minutes=10), max_failures=5, lockout=timedelta(minutes=15))


def _people() -> list[FakeAdUser]:
    """Seed sau P14: ha.lt → khoa.dv → quan.tm; lan.dt (Finance) không có sếp."""
    return [
        FakeAdUser("it_mgr01", "quan.tm", ["IT-Users", "IT-Manager"], None, department="IT"),
        FakeAdUser("l1_lead", "khoa.dv", ["IT-Users", "IT-L1"], "it_mgr01", department="IT"),
        FakeAdUser("l1_01", "ha.lt", ["IT-Users", "IT-L1"], "l1_lead", department="IT"),
        FakeAdUser("l1_02", "duc.pv", ["IT-Users", "IT-L1"], "it_mgr01", department="IT"),
        FakeAdUser("fin_head", "lan.dt", ["IT-Users"], None, department="Finance"),
    ]


class SpyStore(InMemoryAuthStore):
    """Ghi lại lời đếm lần sai (tên + tham số) — kiểm "không đếm" ở dòng đã có và đúng khoá/cửa sổ ở dòng mới."""

    def __init__(self, sink: RecordingSink) -> None:
        super().__init__(sink)
        self.calls: list[tuple[str, tuple[str, ...], datetime]] = []

    async def count_failures(self, usernames: tuple[str, ...], since: datetime) -> int:
        self.calls.append(("count_failures", usernames, since))
        return await super().count_failures(usernames, since)

    async def last_failure_at(self, usernames: tuple[str, ...], since: datetime) -> datetime | None:
        self.calls.append(("last_failure_at", usernames, since))
        return await super().last_failure_at(usernames, since)


@dataclass
class Env:
    clock: FakeClock
    sink: RecordingSink
    store: SpyStore
    idp: FakeIdentityProvider
    sync: AdUserSync
    revoked: list[str] = field(default_factory=list)

    async def run(self, user_id: str) -> UserRecord | None:
        return await self.sync.sync_user_from_ad(self.idp.get_user, self.idp.users[user_id], self.clock.now())

    async def row(self, user_id: str) -> UserRecord | None:
        return await self.store.get_user(user_id)

    async def fail(self, username: str, n: int, *, hashed: bool = True) -> datetime:
        """n lần sai cách nhau 1 phút, ghi như đường đăng nhập ghi (username ma → băm) — trả thời điểm lần sai CUỐI."""
        value = stored_username(username, known=not hashed, key=KEY)
        for i in range(n):
            if i:
                self.clock.advance(timedelta(minutes=1))
            await self.sink.record("login_failed", username_attempted=value)
        return self.clock.now()


def _env(people: list[FakeAdUser] | None = None, store_cls: type[SpyStore] = SpyStore) -> Env:
    clock = FakeClock(EPOCH)
    sink = RecordingSink(clock)
    store = store_cls(sink)
    idp = FakeIdentityProvider(people if people is not None else _people())
    revoked: list[str] = []
    sync = AdUserSync(store=store, sink=sink, username_key=KEY, lock=LOCK, on_sessions_revoked=revoked.append)
    return Env(clock, sink, store, idp, sync, revoked)


async def _session(env: Env, user_id: str, sid: str = "s1") -> None:
    now = env.clock.now()
    await env.store.create_session(SessionRecord(session_id=sid, user_id=user_id, token_family_id=uuid4(),
                                                 refresh_token_hash=f"h-{sid}", created_at=now,
                                                 expires_at=now + timedelta(hours=8)))  # fmt: skip


# ---- (a)(b) mang khoá username ma sang dòng vừa tạo -------------------------------------------------------------------------


async def test_a_ghost_lock_carried_to_new_row_without_new_event() -> None:
    """(a) lan.dt chưa có dòng, sai ĐỦ ngưỡng (lưu băm) trong cửa sổ → sync tạo dòng → `locked_until` = lần sai cuối + khoá;
    không ghi sự kiện nào; đếm bằng đúng `(username, "h:"+HMAC)` từ `now − cửa sổ` (4.10 #2, #3)."""
    env = _env()
    last = await env.fail("lan.dt", LOCK.max_failures)
    env.clock.advance(timedelta(minutes=2))
    now = env.clock.now()
    events = len(env.sink.events)
    out = await env.run("fin_head")
    assert out is not None and out.user_id == "fin_head"
    row = await env.row("fin_head")
    assert row is not None and row.locked_until == last + LOCK.lockout
    assert len(env.sink.events) == events  # mang khoá: không sự kiện mới
    keys = {stored_username("lan.dt", known=False, key=KEY), "lan.dt"}
    counted = [c for c in env.store.calls if c[0] == "count_failures"]
    assert counted and all(set(c[1]) == keys and c[2] == now - LOCK.failure_window for c in counted), counted


async def test_a_ghost_lock_carried_when_row_created_as_manager_in_chain() -> None:
    """(a) qua chuỗi quản lý (4a-10, 4.10 #11 "B15 ensure người duyệt chưa có dòng"): quan.tm (chưa có dòng) bị khoá trượt khi là
    username ma → sync ha.lt tạo dòng it_mgr01 → khoá mang sang. M-4a-5 (bỏ phép đếm) phải đỏ sau khi tách."""
    env = _env()
    last = await env.fail("quan.tm", LOCK.max_failures)
    env.clock.advance(timedelta(minutes=1))
    await env.run("l1_01")
    boss = await env.row("it_mgr01")
    assert boss is not None and boss.locked_until == last + LOCK.lockout
    me = await env.row("l1_01")
    assert me is not None and me.locked_until is None  # ha.lt không có lần sai nào


async def test_b_below_threshold_new_row_not_locked() -> None:
    env = _env()
    await env.fail("lan.dt", LOCK.max_failures - 1)
    env.clock.advance(timedelta(minutes=1))
    await env.run("fin_head")
    row = await env.row("fin_head")
    assert row is not None and row.locked_until is None


async def test_b_failures_outside_window_not_counted() -> None:
    """Lần sai đầu rơi đúng mốc `now − cửa sổ` (view đếm `occurred_at > since`) → còn ngưỡng−1 → không khoá."""
    env = _env()
    first = env.clock.now()
    await env.fail("lan.dt", LOCK.max_failures)
    env.clock.set(first + LOCK.failure_window)
    await env.run("fin_head")
    row = await env.row("fin_head")
    assert row is not None and row.locked_until is None


async def test_b_verbatim_and_hashed_failures_sum() -> None:
    """Q-4a-5 (4.10 #2): lần sai lưu nguyên văn + lưu băm cộng dồn khi tạo dòng → đủ ngưỡng → khoá từ lần sai cuối."""
    env = _env()
    await env.fail("lan.dt", 2, hashed=False)
    env.clock.advance(timedelta(minutes=1))
    last = await env.fail("lan.dt", LOCK.max_failures - 2)
    env.clock.advance(timedelta(minutes=1))
    await env.run("fin_head")
    row = await env.row("fin_head")
    assert row is not None and row.locked_until == last + LOCK.lockout


class NoLastStore(SpyStore):
    """Store "lệch": đủ ngưỡng nhưng `last_failure_at` None — 4.10 #3: tính khoá từ `now` (fail-closed)."""

    async def count_failures(self, usernames: tuple[str, ...], since: datetime) -> int:
        await super().count_failures(usernames, since)
        return LOCK.max_failures

    async def last_failure_at(self, usernames: tuple[str, ...], since: datetime) -> datetime | None:
        await super().last_failure_at(usernames, since)
        return None


async def test_b_last_failure_missing_locks_from_now() -> None:
    env = _env(store_cls=NoLastStore)
    now = env.clock.now()
    await env.run("fin_head")
    row = await env.row("fin_head")
    assert row is not None and row.locked_until == now + LOCK.lockout


# ---- (c) dòng đã có: không đếm, không ghi đè ------------------------------------------------------------------------------


async def test_c_existing_row_neither_counts_nor_overwrites_lock() -> None:
    env = _env()
    await env.run("fin_head")  # tạo dòng (0 lần sai)
    env.clock.advance(timedelta(minutes=1))
    await env.fail("lan.dt", LOCK.max_failures)
    await env.fail("lan.dt", LOCK.max_failures, hashed=False)
    preset = env.clock.now() + timedelta(hours=1)
    await env.store.set_locked_until("fin_head", preset)
    env.store.calls.clear()
    await env.run("fin_head")
    assert [c[0] for c in env.store.calls] == []  # không count_failures, không last_failure_at
    row = await env.row("fin_head")
    assert row is not None and row.locked_until == preset


async def test_c_existing_unlocked_row_stays_unlocked_even_with_failures() -> None:
    env = _env()
    await env.run("fin_head")
    await env.fail("lan.dt", LOCK.max_failures)
    env.store.calls.clear()
    await env.run("fin_head")
    row = await env.row("fin_head")
    assert row is not None and row.locked_until is None
    assert env.store.calls == []


# ---- (d) chuỗi quản lý -------------------------------------------------------------------------------------------------------


async def test_d_manager_chain_created_first_no_session() -> None:
    """ha.lt → dòng l1_lead và it_mgr01 có, `manager_id` đúng chuỗi seed P14; không tạo phiên; không sự kiện."""
    env = _env()
    out = await env.run("l1_01")
    assert out is not None and (out.user_id, out.role, out.manager_id) == ("l1_01", "l1", "l1_lead")
    lead, head = await env.row("l1_lead"), await env.row("it_mgr01")
    assert lead is not None and (lead.role, lead.manager_id, lead.username) == ("l1", "it_mgr01", "khoa.dv")
    assert head is not None and (head.role, head.manager_id, head.username) == ("manager", None, "quan.tm")
    assert env.store.sessions == {}
    assert env.sink.events == []
    assert env.revoked == []


async def test_d_chain_deeper_than_5_is_cut() -> None:
    """c0 → c1 → … → c7 → c8 (không tồn tại): tạo c1…c5; c5.manager_id NULL ("không biết"); c6 không có dòng (khuôn
    `test_auth_login.py::test_manager_chain_cycle_depth_and_missing_manager`)."""
    chain = [FakeAdUser(f"c{i}", f"c{i}.u", ["IT-Users"], f"c{i + 1}") for i in range(8)]
    env = _env(chain)
    await env.run("c0")
    for i in range(1, 5):
        row = await env.row(f"c{i}")
        assert row is not None and row.manager_id == f"c{i + 1}", i
    c5 = await env.row("c5")
    assert c5 is not None and c5.manager_id is None
    assert await env.row("c6") is None


async def test_d_cycle_is_cut() -> None:
    env = _env([FakeAdUser("a", "a.a", ["IT-Users"], "b"), FakeAdUser("b", "b.b", ["IT-Users"], "a")])
    await env.run("a")
    a, b = await env.row("a"), await env.row("b")
    assert a is not None and a.manager_id == "b"
    assert b is not None and b.manager_id is None


async def test_d_manager_not_found_is_null() -> None:
    env = _env([FakeAdUser("x1", "x.one", ["IT-Users"], "khong_co")])
    out = await env.run("x1")
    assert out is not None and out.manager_id is None
    row = await env.row("x1")
    assert row is not None and row.manager_id is None
    assert await env.row("khong_co") is None


async def test_d_manager_without_role_is_null_and_not_created() -> None:
    """x1 → m1 → m2 (nhóm lạ, không ra role): m2 không có dòng, m1.manager_id NULL, x1 → m1."""
    env = _env([FakeAdUser("x1", "x.one", ["IT-Users"], "m1"), FakeAdUser("m1", "m.one", ["IT-Users"], "m2"),
                FakeAdUser("m2", "m.two", ["Khach"], None)])  # fmt: skip
    await env.run("x1")
    x1, m1 = await env.row("x1"), await env.row("m1")
    assert x1 is not None and x1.manager_id == "m1"
    assert m1 is not None and m1.manager_id is None
    assert await env.row("m2") is None


# ---- (e)(f) đổi role / bị khoá trong AD --------------------------------------------------------------------------------------


async def test_e_role_change_bumps_token_revokes_sessions_event_and_callback() -> None:
    env = _env()
    await env.run("l1_01")
    await _session(env, "l1_01")
    before = await env.row("l1_01")
    assert before is not None
    env.idp.set(replace(env.idp.users["l1_01"], groups=["IT-Users", "IT-L2"]))
    out = await env.run("l1_01")
    assert out is not None and out.role == "l2"
    after = await env.row("l1_01")
    assert after is not None and after.token_version == before.token_version + 1
    session = await env.store.get_session("s1")
    assert session is not None and session.revoked_at is not None and session.revoke_reason == "admin"
    [changed] = env.sink.of("role_changed")
    assert changed.detail == {"from": "l1", "to": "l2"}
    assert env.revoked == ["l1_01"]


async def test_e_same_role_no_bump_no_revoke_no_callback() -> None:
    env = _env()
    await env.run("l1_01")
    await _session(env, "l1_01")
    before = await env.row("l1_01")
    assert before is not None
    await env.run("l1_01")
    after = await env.row("l1_01")
    assert after is not None and after.token_version == before.token_version
    session = await env.store.get_session("s1")
    assert session is not None and session.revoked_at is None
    assert env.sink.of("role_changed") == [] and env.revoked == []


@pytest.mark.parametrize("status", ["disabled", "terminated"])
async def test_f_disabled_revokes_sessions_and_callback(status: str) -> None:
    env = _env()
    await env.run("l1_01")
    await _session(env, "l1_01")
    env.idp.set(replace(env.idp.users["l1_01"], employment_status=status))
    out = await env.run("l1_01")
    assert out is not None and out.employment_status == status
    session = await env.store.get_session("s1")
    assert session is not None and session.revoked_at is not None and session.revoke_reason == "user_disabled"
    assert env.revoked == ["l1_01"]
    assert env.sink.of("role_changed") == []  # nhóm không đổi → role không đổi


# ---- (g) nhóm không ra role; (h) AD lỗi --------------------------------------------------------------------------------------


@pytest.mark.parametrize("groups", [["IT-Users", "IT-L1", "IT-L2"], ["Khach"], []], ids=["hai-nhom-dac-quyen", "nhom-la", "rong"])
async def test_g_unmappable_role_returns_none_writes_nothing(groups: list[str]) -> None:
    """Nhóm AD không ra role → None; không ghi dòng nào (kể cả chuỗi quản lý), không sự kiện, không callback."""
    env = _env([*_people(), FakeAdUser("x1", "hai.vt", groups, "it_mgr01", department="IT")])
    assert await env.run("x1") is None
    assert env.store.users == {}
    assert env.sink.events == [] and env.revoked == []


class AdBoom(Exception):
    """Lỗi hệ thống giả của `get_user` — không trùng lớp nào của mã sản phẩm (kể cả NotImplementedError)."""


async def test_h_get_user_error_propagates() -> None:
    env = _env()

    async def broken(user_id: str) -> FakeAdUser | None:
        raise AdBoom(user_id)

    with pytest.raises(AdBoom):
        await env.sync.sync_user_from_ad(broken, env.idp.users["l1_01"], env.clock.now())
    assert await env.row("l1_01") is None  # chưa tạo được sếp → chưa upsert người đó (FK)


async def test_h_identity_unavailable_propagates() -> None:
    env = _env()
    env.idp.down = True
    with pytest.raises(IdentityUnavailable):
        await env.run("l1_01")
