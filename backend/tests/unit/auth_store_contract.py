"""Bộ test hợp đồng AuthStore — CHUNG cho bản in-memory (unit, `test_auth_store_memory.py`) và bản
SQL (integration, `test_auth_store_sql.py`), để bản giả không lệch bản thật.

Lớp con cung cấp fixture `env` → `StoreEnv`. Tên lớp không bắt đầu bằng `Test` nên pytest không
thu thập lớp gốc. Mỗi test dùng id ngẫu nhiên — DB integration dùng chung giữa các test.
"""

import asyncio
import dataclasses
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.auth.models import SessionRecord, UserSync
from app.auth.ports import AuthStore, SecurityEventSink
from app.auth.tokens import hash_refresh_token, new_refresh_token
from app.core.clock import FakeClock


@dataclass
class StoreEnv:
    store: AuthStore
    sink: SecurityEventSink
    clock: FakeClock


def _uid(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _sync(env: StoreEnv, user_id: str, *, role: Any = "employee", manager_id: str | None = None,
          status: str = "active") -> UserSync:  # fmt: skip
    return UserSync(user_id, f"name-{user_id}", "Tên", role, "it", manager_id, status, None, False,
                    env.clock.now())  # fmt: skip


def _session(env: StoreEnv, user_id: str, family: uuid.UUID | None = None,
             created_offset: timedelta = timedelta()) -> SessionRecord:  # fmt: skip
    now = env.clock.now() + created_offset
    return SessionRecord(
        session_id=uuid.uuid4().hex, user_id=user_id, token_family_id=family or uuid.uuid4(),
        refresh_token_hash=hash_refresh_token(new_refresh_token()), created_at=now,
        expires_at=now + timedelta(hours=8), ip_prefix="203.0.113.0/24",
    )  # fmt: skip


HCM = ZoneInfo("Asia/Ho_Chi_Minh")  # múi giờ khác UTC — đầu vào cố ý không chuẩn


def assert_utc(value: object) -> None:
    """Mọi datetime trả về phải có tzinfo ĐÚNG là timezone.utc (không chỉ "tương đương UTC" như
    ZoneInfo("Etc/UTC") của psycopg). Duyệt mọi trường của dataclass để trường mới cũng bị soi."""
    if value is None:
        return
    if isinstance(value, datetime):
        assert value.tzinfo is UTC, f"tzinfo={value.tzinfo!r}, cần timezone.utc"
        return
    if isinstance(value, tuple):
        for item in value:
            assert_utc(item)
        return
    assert dataclasses.is_dataclass(value), type(value)
    for f in dataclasses.fields(value):
        field_value = getattr(value, f.name)
        if isinstance(field_value, datetime):
            assert_utc(field_value)


class AuthStoreContract:
    @pytest.mark.asyncio
    async def test_every_returned_datetime_is_timezone_utc(self, env: StoreEnv) -> None:
        uid = _uid()
        # upsert trả về
        assert_utc(await env.store.upsert_user(_sync(env, uid)))
        until = env.clock.now().astimezone(HCM) + timedelta(minutes=15)
        await env.store.set_locked_until(uid, until)
        for user in (
            await env.store.get_user(uid),
            await env.store.get_user_by_username(f"name-{uid}"),
            (await env.store.upsert_user(_sync(env, uid)))[0],
        ):
            assert user is not None and user.locked_until == until  # cùng thời điểm
            assert_utc(user)

        s = _session(env, uid)
        s = replace(s, created_at=s.created_at.astimezone(HCM), expires_at=s.expires_at.astimezone(HCM))
        await env.store.create_session(s)
        for got in (await env.store.get_session(s.session_id),
                    await env.store.get_session_by_refresh_hash(s.refresh_token_hash)):  # fmt: skip
            assert got is not None and (got.created_at, got.expires_at) == (s.created_at, s.expires_at)
            assert_utc(got)

        new = _session(env, uid, s.token_family_id, created_offset=timedelta(minutes=5))
        new = replace(new, created_at=new.created_at.astimezone(HCM))
        now_hcm = env.clock.now().astimezone(HCM)
        assert await env.store.rotate_session(s.session_id, new, now_hcm)
        for sid in (s.session_id, new.session_id):
            assert_utc(await env.store.get_session(sid))
        await env.store.revoke_session(new.session_id, "logout", now_hcm)
        revoked = await env.store.get_session(new.session_id)
        assert revoked is not None and revoked.revoked_at == now_hcm
        assert_utc(revoked)

        started = await env.store.login_started_at(new.session_id)
        assert started == s.created_at
        assert_utc(started)

    @pytest.mark.asyncio
    async def test_upsert_insert_then_update_returns_previous_role(self, env: StoreEnv) -> None:
        uid = _uid()
        user, previous = await env.store.upsert_user(_sync(env, uid))
        assert previous is None and user.role == "employee" and user.token_version == 0
        user, previous = await env.store.upsert_user(_sync(env, uid, role="l1"))
        assert previous == "employee" and user.role == "l1"
        by_name = await env.store.get_user_by_username(f"name-{uid}")
        assert by_name is not None and by_name.user_id == uid

    @pytest.mark.asyncio
    async def test_upsert_new_user_concurrently_reports_created_exactly_once(self, env: StoreEnv) -> None:
        """Q-4a-6: "role cũ = None" ⟺ CHÍNH lời gọi này tạo dòng — quyết định từ kết quả INSERT … ON CONFLICT, không từ SELECT
        trước (SELECT … FOR UPDATE trên dòng chưa có không khoá gì → hai lời gọi đồng thời cùng thấy "chưa có")."""
        uid = _uid()
        results = await asyncio.gather(*(env.store.upsert_user(_sync(env, uid)) for _ in range(4)))
        assert sorted(previous is None for _, previous in results) == [False, False, False, True]
        assert {previous for _, previous in results} == {None, "employee"}

    @pytest.mark.asyncio
    async def test_upsert_username_taken_by_other_user_is_rejected(self, env: StoreEnv) -> None:
        """Trùng `username` với user_id KHÁC → lỗi (không ghi đè, không "tạo mới"); dòng cũ nguyên vẹn."""
        first, other = _uid(), _uid()
        await env.store.upsert_user(_sync(env, first))
        clash = replace(_sync(env, other), username=f"name-{first}")
        with pytest.raises(Exception):  # noqa: B017 — ValueError (SQL: ON CONFLICT DO NOTHING + không có dòng; giả)
            await env.store.upsert_user(clash)
        assert await env.store.get_user(other) is None
        kept = await env.store.get_user_by_username(f"name-{first}")
        assert kept is not None and kept.user_id == first

    @pytest.mark.asyncio
    async def test_upsert_keeps_token_version_lock_and_mfa(self, env: StoreEnv) -> None:
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        assert await env.store.bump_token_version(uid) == 1
        until = env.clock.now() + timedelta(minutes=15)
        await env.store.set_locked_until(uid, until)
        await env.store.set_mfa_secret(uid, b"\x00\x01bi-mat")
        user, _ = await env.store.upsert_user(_sync(env, uid, status="probation"))
        assert (user.token_version, user.locked_until, user.mfa_secret_enc) == (1, until, b"\x00\x01bi-mat")
        assert user.employment_status == "probation"

    @pytest.mark.asyncio
    async def test_manager_fk_enforced(self, env: StoreEnv) -> None:
        with pytest.raises(Exception):  # noqa: B017 — FK: IntegrityError (SQL) / ValueError (giả)
            await env.store.upsert_user(_sync(env, _uid(), manager_id=_uid("khong-co")))
        boss = _uid("boss")
        await env.store.upsert_user(_sync(env, boss))
        user, _ = await env.store.upsert_user(_sync(env, _uid(), manager_id=boss))
        assert user.manager_id == boss

    @pytest.mark.asyncio
    async def test_count_failures_uses_auth_failures_only(self, env: StoreEnv) -> None:
        name, ip = _uid("name"), f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.0/24"
        since = env.clock.now()
        env.clock.advance(timedelta(seconds=1))
        for event in ("login_failed", "mfa_failed", "login_success", "account_locked"):
            await env.sink.record(event, username_attempted=name, ip_prefix=ip)
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        await env.sink.record("mfa_enrolled", user_id=uid, username_attempted=name,
                              detail={"by": "ops", "reason": "x"})  # fmt: skip
        await env.sink.record("mfa_reset", user_id=uid, username_attempted=name, ip_prefix=ip,
                              detail={"by": "ops", "reason": "x"})  # fmt: skip
        assert await env.store.count_failures((name,), since) == 2  # chỉ login_failed + mfa_failed
        assert await env.store.count_ip_failures(ip, since) == 2
        assert await env.store.count_failures((name,), env.clock.now()) == 0  # "sau since", không bằng

    @pytest.mark.asyncio
    async def test_count_failures_sums_every_value_once(self, env: StoreEnv) -> None:
        """Q-4a-5: (nguyên văn, bản băm) trong MỘT câu `IN` — cộng đúng từng dòng một lần, không đếm tên khác, không đếm đôi
        khi tuple lặp giá trị."""
        raw, hashed, other = _uid("name"), "h:" + uuid.uuid4().hex * 2, _uid("name")
        since = env.clock.now()
        env.clock.advance(timedelta(seconds=1))
        for name, n in ((raw, 2), (hashed, 3), (other, 4)):
            for _ in range(n):
                await env.sink.record("login_failed", username_attempted=name)
        assert await env.store.count_failures((raw, hashed), since) == 5
        assert await env.store.count_failures((hashed,), since) == 3
        assert await env.store.count_failures((raw, raw), since) == 2
        assert await env.store.count_failures((_uid("khong-co"),), since) == 0

    @pytest.mark.asyncio
    async def test_last_failure_at_is_max_over_values_after_since(self, env: StoreEnv) -> None:
        """Q-4a-6: thời điểm lần sai CUỐI (view `auth_failures`) trên CẢ tập giá trị — cùng điều kiện với `count_failures`."""
        raw, hashed, other = _uid("name"), "h:" + uuid.uuid4().hex * 2, _uid("name")
        since = env.clock.now()
        env.clock.advance(timedelta(seconds=1))
        await env.sink.record("login_failed", username_attempted=hashed)
        t_hashed = env.clock.now()
        env.clock.advance(timedelta(seconds=1))
        await env.sink.record("mfa_failed", username_attempted=raw)
        t_raw = env.clock.now()
        env.clock.advance(timedelta(seconds=1))
        await env.sink.record("login_success", username_attempted=raw)  # không phải lần sai
        await env.sink.record("login_failed", username_attempted=other)  # tên khác
        last = await env.store.last_failure_at((raw, hashed), since)
        assert last == t_raw
        assert_utc(last)
        assert await env.store.last_failure_at((hashed,), since) == t_hashed
        assert await env.store.last_failure_at((raw, hashed), t_raw) is None  # "sau since", không bằng
        assert await env.store.last_failure_at((_uid("khong-co"),), since) is None

    @pytest.mark.asyncio
    async def test_session_lookup_and_revoke(self, env: StoreEnv) -> None:
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        s = _session(env, uid)
        await env.store.create_session(s)
        assert await env.store.get_session(s.session_id) == s
        assert await env.store.get_session_by_refresh_hash(s.refresh_token_hash) == s
        await env.store.revoke_session(s.session_id, "logout", env.clock.now())
        got = await env.store.get_session(s.session_id)
        assert got is not None and got.revoke_reason == "logout" and not got.usable(env.clock.now())
        # thu hồi lần 2 không ghi đè lý do cũ
        await env.store.revoke_session(s.session_id, "admin", env.clock.now())
        got = await env.store.get_session(s.session_id)
        assert got is not None and got.revoke_reason == "logout"

    @pytest.mark.asyncio
    async def test_rotate_is_atomic_once(self, env: StoreEnv) -> None:
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        old = _session(env, uid)
        await env.store.create_session(old)
        a, b = _session(env, uid, old.token_family_id), _session(env, uid, old.token_family_id)
        results = await asyncio.gather(
            env.store.rotate_session(old.session_id, a, env.clock.now()),
            env.store.rotate_session(old.session_id, b, env.clock.now()),
        )
        assert sorted(results) == [False, True]
        winner = a if results[0] else b
        loser = b if results[0] else a
        assert await env.store.get_session(winner.session_id) is not None
        assert await env.store.get_session(loser.session_id) is None
        rotated = await env.store.get_session(old.session_id)
        assert rotated is not None and rotated.revoke_reason == "rotated"

    @pytest.mark.asyncio
    async def test_revoke_family_and_user(self, env: StoreEnv) -> None:
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        fam = uuid.uuid4()
        s1, s2, other = _session(env, uid, fam), _session(env, uid, fam), _session(env, uid)
        for s in (s1, s2, other):
            await env.store.create_session(s)
        assert await env.store.revoke_family(fam, "reuse_detected", env.clock.now()) == 2
        still = await env.store.get_session(other.session_id)
        assert still is not None and still.revoked_at is None
        assert await env.store.revoke_user_sessions(uid, "user_disabled", env.clock.now()) == 1
        assert await env.store.revoke_user_sessions(uid, "user_disabled", env.clock.now()) == 0

    @pytest.mark.asyncio
    async def test_login_started_at_is_min_of_family(self, env: StoreEnv) -> None:
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        first = _session(env, uid)
        later = _session(env, uid, first.token_family_id, created_offset=timedelta(hours=2))
        await env.store.create_session(first)
        await env.store.create_session(later)
        assert await env.store.login_started_at(later.session_id) == first.created_at
        assert await env.store.login_started_at("khong-co") is None

    @pytest.mark.asyncio
    async def test_duplicate_refresh_hash_rejected(self, env: StoreEnv) -> None:
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        s = _session(env, uid)
        await env.store.create_session(s)
        dup = SessionRecord(uuid.uuid4().hex, uid, uuid.uuid4(), s.refresh_token_hash, s.created_at,
                            s.expires_at)  # fmt: skip
        with pytest.raises(Exception):  # noqa: B017 — UNIQUE refresh_token_hash
            await env.store.create_session(dup)

    # ---- A4 (bn-a, migration 0016 — dời từ 0015): bước TOTP đã chấp nhận ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_accept_totp_step_strictly_increasing(self, env: StoreEnv) -> None:
        store = env.store
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        assert await store.accept_totp_step(uid, 100) is True  # chưa có bước nào
        assert await store.accept_totp_step(uid, 100) is False  # cùng bước = dùng lại
        assert await store.accept_totp_step(uid, 99) is False  # bước cũ hơn
        assert await store.accept_totp_step(uid, 101) is True
        assert await store.accept_totp_step(uid, 100) is False  # mốc đã lên 101

    @pytest.mark.asyncio
    async def test_accept_totp_step_concurrent_same_step_exactly_once(self, env: StoreEnv) -> None:
        store = env.store
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        results = await asyncio.gather(*[store.accept_totp_step(uid, 500) for _ in range(5)])
        assert sorted(results) == [False, False, False, False, True]

    @pytest.mark.asyncio
    async def test_set_mfa_secret_clears_accepted_step_and_upsert_keeps_it(self, env: StoreEnv) -> None:
        store = env.store
        uid = _uid()
        await env.store.upsert_user(_sync(env, uid))
        assert await store.accept_totp_step(uid, 300) is True
        await env.store.upsert_user(_sync(env, uid, status="probation"))  # đồng bộ AD không đụng bước đã nhận
        assert await store.accept_totp_step(uid, 300) is False
        await env.store.set_mfa_secret(uid, b"\x00secret-moi")  # enroll/reset: secret mới → bước cũ hết nghĩa
        assert await store.accept_totp_step(uid, 300) is True

    @pytest.mark.asyncio
    async def test_accept_totp_step_isolated_per_user(self, env: StoreEnv) -> None:
        store = env.store
        a, b = _uid(), _uid()
        for uid in (a, b):
            await env.store.upsert_user(_sync(env, uid))
        assert await store.accept_totp_step(a, 700) is True
        assert await store.accept_totp_step(b, 700) is True
