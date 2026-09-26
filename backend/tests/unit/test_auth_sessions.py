"""Phiên: refresh xoay vòng + CSRF, dùng lại token cũ → thu hồi cả họ, 2 refresh đồng thời, thu hồi
≤ 30 giây (TC31), terminated → mọi phiên chết, logout-all, thu hồi của admin + xác nhận lại."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from app.auth.models import SessionRecord
from app.auth.service import AuthError, AuthService
from app.core.clock import FakeClock
from tests.fakes.auth import EPOCH, InMemoryAuthStore, RecordingSink
from tests.unit.auth_helpers import auth_env


def _me(env, token: str) -> int:  # type: ignore[no-untyped-def]
    return int(env.client.get("/api/auth/me", headers=env.bearer(token)).status_code)


# ---- refresh -----------------------------------------------------------------------------------


def test_refresh_rotates_and_old_token_reuse_revokes_family() -> None:
    with auth_env() as env:
        env.login("an.nv")
        old_refresh = env.client.cookies.get("refresh")
        r = env.refresh()
        assert r.status_code == 200
        new_access = r.json()["access_token"]
        assert env.client.cookies.get("refresh") != old_refresh
        assert env.sink.of("token_refreshed")

        # kẻ trộm trình lại refresh token cũ (đã xoay) — client riêng, header Cookie tường minh
        csrf = "csrf-cua-ke-trom"
        env.client.cookies.clear()
        stolen = env.client.post(
            "/api/auth/refresh",
            headers={"Cookie": f"refresh={old_refresh}; csrf={csrf}", "X-CSRF-Token": csrf},
        )
        assert stolen.status_code == 401
        [reuse] = env.sink.of("refresh_reuse_detected")
        assert reuse.user_id == "nv001" and reuse.detail == {"revoked_sessions": 1}
        assert _me(env, new_access) == 401  # phiên mới cùng họ cũng chết
        store = env.store
        assert isinstance(store, InMemoryAuthStore)
        assert {s.revoke_reason for s in store.sessions.values()} == {"rotated", "reuse_detected"}


def test_refresh_requires_matching_csrf() -> None:
    with auth_env() as env:
        env.login("an.nv")
        assert env.client.post("/api/auth/refresh").status_code == 403
        r = env.client.post("/api/auth/refresh", headers={"X-CSRF-Token": "khac"})
        assert (r.status_code, r.json()) == (403, {"detail": "csrf"})
        assert env.sink.of("token_refreshed") == []
        assert env.refresh().status_code == 200


def test_refresh_expiry_is_absolute_from_login() -> None:
    with auth_env() as env:
        env.login("an.nv")
        env.clock.advance(timedelta(hours=7))
        assert env.refresh().status_code == 200  # xoay ở giờ thứ 7 …
        env.clock.advance(timedelta(hours=1))
        assert env.refresh().status_code == 401  # … không kéo dài quá 8 giờ từ lúc đăng nhập


class _YieldingStore(InMemoryAuthStore):
    """Nhường event loop sau khi đọc phiên — để hai refresh thật sự chen nhau."""

    async def get_session_by_refresh_hash(self, refresh_hash: str) -> SessionRecord | None:
        found = await super().get_session_by_refresh_hash(refresh_hash)
        await asyncio.sleep(0)
        return found


@pytest.mark.asyncio
async def test_two_concurrent_refreshes_second_is_reuse() -> None:
    """Hai tab refresh cùng lúc cùng token: cái thứ hai bị coi là reuse, cả họ bị thu hồi — hành vi
    đã biết, frontend xử lý ở Phase 7."""
    clock = FakeClock(EPOCH)
    sink = RecordingSink(clock)
    store = _YieldingStore(sink)
    with auth_env(store=store, sink=sink, clock=clock) as env:
        env.login("an.nv")
        token = env.client.cookies.get("refresh")
        auth = env.app.state.auth
    assert isinstance(auth, AuthService) and token
    results = await asyncio.gather(
        auth.refresh(token, ip=None), auth.refresh(token, ip=None), return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, AuthError)]
    assert len(ok) == 1 and len(failed) == 1 and failed[0].status == 401
    assert len(sink.of("refresh_reuse_detected")) == 1
    assert all(s.revoked_at is not None for s in store.sessions.values())  # cả họ chết


# ---- thu hồi -----------------------------------------------------------------------------------


def test_logout_same_instance_rejects_immediately() -> None:
    with auth_env() as env:
        token = env.token("an.nv")
        assert env.client.post("/api/auth/logout", headers=env.bearer(token)).status_code == 204
        assert _me(env, token) == 401
        assert env.refresh().status_code in (401, 403)  # cookie đã bị xoá
        assert env.sink.of("logout")[0].detail == {"scope": "session"}


def test_tc31_revocation_seen_by_other_instance_within_30s() -> None:
    """Instance B cache kết quả tra phiên ≤ 30 giây; logout ở instance A → B từ chối sau ≤ 30 giây."""
    clock = FakeClock(EPOCH)
    sink = RecordingSink(clock)
    store = InMemoryAuthStore(sink)
    shared = {"store": store, "sink": sink, "clock": clock}
    with auth_env(**shared) as a:  # type: ignore[arg-type]
        key = a.settings.jwt_signing_key
        with auth_env(**shared, jwt_signing_key=key) as b:  # type: ignore[arg-type]
            token = a.token("an.nv")
            assert _me(b, token) == 200  # B đã cache phiên
            assert a.client.post("/api/auth/logout", headers=a.bearer(token)).status_code == 204
            clock.advance(timedelta(seconds=29))
            assert _me(b, token) == 200  # còn trong cache — đúng giới hạn P6 cho phép
            clock.advance(timedelta(seconds=1))
            assert _me(b, token) == 401  # ≤ 30 giây


def test_terminated_user_all_sessions_die() -> None:
    with auth_env() as env:
        t1 = env.token("an.nv")
        t2 = env.token("an.nv")
        store = env.store
        assert isinstance(store, InMemoryAuthStore)
        store.users["nv001"] = replace(store.users["nv001"], employment_status="terminated")
        env.clock.advance(timedelta(seconds=30))
        assert _me(env, t1) == 401 and _me(env, t2) == 401
        assert env.refresh().status_code == 401
        assert all(s.revoked_at is not None for s in store.sessions.values())


def test_logout_all_kills_every_session() -> None:
    with auth_env() as env:
        t1 = env.token("an.nv")
        t2 = env.token("an.nv")
        assert env.client.post("/api/auth/logout-all", headers=env.bearer(t2)).status_code == 204
        assert _me(env, t1) == 401 and _me(env, t2) == 401
        assert env.sink.of("logout")[0].detail == {"scope": "all"}


# ---- thu hồi của admin (manager + xác nhận lại) -----------------------------------------------


def test_manager_revokes_user_sessions() -> None:
    with auth_env() as env:
        victim = env.token("an.nv")
        mgr = env.manager_token()
        r = env.client.post("/api/admin/users/nv001/revoke", headers=env.bearer(mgr))
        assert r.status_code == 204
        assert _me(env, victim) == 401
        [ev] = env.sink.of("session_revoked")
        assert ev.user_id == "nv001" and ev.detail == {"by": "it_mgr01", "revoked_sessions": 1}
        assert env.client.post("/api/admin/users/khong-co/revoke", headers=env.bearer(mgr)).status_code == 404


@pytest.mark.parametrize("username", ["ha.lt", "long.nh", "an.nv"])
def test_non_manager_cannot_revoke(username: str) -> None:
    with auth_env() as env:
        token = env.token(username)
        r = env.client.post("/api/admin/users/nv002/revoke", headers=env.bearer(token))
        assert r.status_code == 403
        [denied] = env.sink.of("permission_denied")
        assert denied.route == "/api/admin/users/{user_id}/revoke"
        assert denied.detail == {"reason": "role"}


def test_revoke_requires_login_within_10_minutes_even_after_refresh() -> None:
    with auth_env() as env:
        env.manager_token()
        env.clock.advance(timedelta(minutes=11))
        fresh_access = env.refresh().json()["access_token"]  # refresh KHÔNG tính là đăng nhập lại
        r = env.client.post("/api/admin/users/nv001/revoke", headers=env.bearer(fresh_access))
        assert (r.status_code, r.json()) == (403, {"detail": "reauth_required"})
        assert env.sink.of("permission_denied")[-1].detail == {"reason": "reauth_required"}


def test_token_version_mismatch_alone_rejects_token() -> None:
    """`tv` là lớp riêng: tăng token_version (không thu hồi phiên) cũng làm access token cũ chết."""
    with auth_env() as env:
        token = env.token("an.nv")
        asyncio.run(env.store.bump_token_version("nv001"))
        env.clock.advance(timedelta(seconds=30))  # qua cache
        assert _me(env, token) == 401
        store = env.store
        assert isinstance(store, InMemoryAuthStore)
        assert all(s.revoked_at is None for s in store.sessions.values())


def test_role_mismatch_alone_rejects_token() -> None:
    """Role trong token phải khớp `users.role` — lớp riêng, kể cả khi `tv` chưa đổi."""
    with auth_env() as env:
        token = env.token("ha.lt")
        store = env.store
        assert isinstance(store, InMemoryAuthStore)
        store.users["l1_01"] = replace(store.users["l1_01"], role="l2")
        env.clock.advance(timedelta(seconds=30))
        assert _me(env, token) == 401
