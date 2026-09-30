"""Đăng nhập 8 bước (P6 mục 4) qua HTTP với AD/store/sink giả và FakeClock.

TC24 (sai 1 lần), TC25 (khoá 15 phút), khoá username không có dòng users trả phản hồi GIỐNG HỆT
user thật bị khoá, giới hạn dải IP, disabled/terminated, MFA, role_changed, role trong body bị bỏ
qua, AD lỗi → 503, canary (không mật khẩu/token trong log và security_events).
"""

import asyncio
import io
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from app.auth.service import GENERIC_LOGIN_ERROR
from app.auth.username_hash import stored_username, username_key
from app.core.logging import JsonFormatter, RedactSecretsFilter
from app.domain.alerts import BRUTEFORCE_RULE_ID, bruteforce_subject
from tests.fakes.auth import (
    DEMO_PASSWORD,
    FakeAdUser,
    FakeIdentityProvider,
    seed_ad_users,
)
from tests.unit.auth_helpers import AuthEnv, auth_env


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env() as e:
        yield e


def _username_key(env: AuthEnv) -> bytes:
    secret = env.settings.jwt_signing_key
    assert secret is not None  # auth_settings luôn đặt khoá
    return username_key(secret.get_secret_value().encode("utf-8"))


def _cookie_header(env: AuthEnv, name: str, response_headers: list[str]) -> str:
    return next(h for h in response_headers if h.startswith(f"{name}="))


# ---- đăng nhập thành công --------------------------------------------------------------------


def test_login_success_sets_tokens_cookies_and_syncs_user(env: AuthEnv) -> None:
    r = env.login("an.nv")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "csrf_token"}
    assert body["expires_in"] == 15 * 60
    cookies = r.headers.get_list("set-cookie")
    refresh = _cookie_header(env, "refresh", cookies).lower()
    assert "httponly" in refresh and "secure" in refresh and "samesite=strict" in refresh
    assert "path=/api/auth" in refresh
    csrf = _cookie_header(env, "csrf", cookies).lower()
    assert "httponly" not in csrf and "secure" in csrf and "path=/" in csrf
    assert env.client.cookies.get("csrf") == body["csrf_token"]

    me = env.client.get("/api/auth/me", headers=env.bearer(body["access_token"])).json()
    assert me["user_id"] == "nv001" and me["role"] == "employee"
    assert "ticket:create" in me["permissions"] and "ticket:read:any" not in me["permissions"]
    assert [e.event_type for e in env.sink.events] == ["login_success"]


@pytest.mark.asyncio
async def test_login_syncs_manager_chain_first() -> None:
    with auth_env() as env:
        assert env.login("an.nv").status_code == 200
        user = await env.store.get_user("nv001")
        boss = await env.store.get_user("fin_head")
    assert user is not None and user.manager_id == "fin_head" and user.department == "finance"
    assert boss is not None and boss.role == "employee"


def test_role_in_body_is_ignored(env: AuthEnv) -> None:
    token = env.token("an.nv", role="manager", groups=["IT-Manager"])
    assert env.client.get("/api/auth/me", headers=env.bearer(token)).json()["role"] == "employee"


# ---- TC24, TC25 ------------------------------------------------------------------------------


def test_tc24_one_wrong_password(env: AuthEnv) -> None:
    r = env.login("an.nv", "sai-mat-khau")
    assert r.status_code == 401
    assert r.json() == {"detail": GENERIC_LOGIN_ERROR}
    assert len(env.sink.of("login_failed")) == 1
    assert env.sink.of("account_locked") == []
    assert env.alerts.rows == {}  # một lần sai không phải sự cố an ninh [Chốt 1.3]


@pytest.mark.asyncio
async def test_tc25_five_failures_lock_15_minutes() -> None:
    with auth_env() as env:
        assert env.login("an.nv").status_code == 200  # có dòng users
        for _ in range(5):
            assert env.login("an.nv", "sai").status_code == 401
        [locked] = env.sink.of("account_locked")
        assert locked.detail["reason"] == "threshold" and locked.user_id == "nv001"
        user = await env.store.get_user("nv001")
        assert user is not None and user.locked_until == env.clock.now() + timedelta(minutes=15)
        [alert] = env.alerts.of(BRUTEFORCE_RULE_ID)  # báo Trưởng BP (P9 luật 3)
        assert (alert.subject, alert.window_start, alert.severity) == (
            "nv001", env.clock.now(), "critical")
        assert alert.detail == {"user_id": "nv001", "username": "an.nv", "source": "login"}

        r = env.login("an.nv")  # đúng mật khẩu nhưng đang khoá
        assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
        assert env.sink.of("account_locked")[-1].detail == {"reason": "still_locked"}
        assert env.idp.authenticate_calls == 6  # đang khoá thì không hỏi AD
        assert len(env.alerts.rows) == 1  # still_locked không sinh cảnh báo mới

        env.clock.advance(timedelta(minutes=15))
        assert env.login("an.nv").status_code == 200

        env.clock.advance(timedelta(minutes=11))  # đợt khoá thứ hai → cảnh báo thứ hai
        for _ in range(5):
            env.login("an.nv", "sai")
        assert len(env.alerts.of(BRUTEFORCE_RULE_ID)) == 2


def test_two_users_locked_same_instant_get_two_alerts(env: AuthEnv) -> None:
    """Quyết định Q1: khoá chống trùng có người dùng — gộp 2 người = bỏ sót sự cố an ninh."""
    env.login("an.nv")
    env.login("binh.tt")
    for _ in range(5):  # FakeClock đứng yên: hai đợt khoá cùng một thời điểm
        env.login("an.nv", "sai")
        env.login("binh.tt", "sai")
    alerts = env.alerts.of(BRUTEFORCE_RULE_ID)
    assert sorted(a.subject for a in alerts) == ["nv001", "nv002"]
    assert {a.window_start for a in alerts} == {env.clock.now()}


def test_unknown_username_lock_alert_uses_hashed_username_subject(env: AuthEnv) -> None:
    """Phase 4 P2 (Việc treo 10 — `bruteforce_alert(username=…)`): username ma khoá → vẫn đúng 1 cảnh báo, nhưng `subject` và
    `detail.username` dựng từ giá trị BĂM (trước đây `"username:khong.ton.tai"` nguyên văn vào bảng `alerts`)."""
    for _ in range(5):
        env.login("khong.ton.tai", "sai")
    [alert] = env.alerts.of(BRUTEFORCE_RULE_ID)
    stored = stored_username("khong.ton.tai", known=False, key=_username_key(env))
    assert alert.subject == bruteforce_subject(None, stored) and alert.detail["user_id"] is None
    assert alert.detail["username"] == stored
    assert "khong.ton.tai" not in repr(alert)


def test_failures_outside_window_do_not_lock(env: AuthEnv) -> None:
    for _ in range(4):
        env.login("an.nv", "sai")
    env.clock.advance(timedelta(minutes=10, seconds=1))
    env.login("an.nv", "sai")
    assert env.sink.of("account_locked") == []
    assert env.login("an.nv").status_code == 200


def test_mfa_enrolled_events_do_not_count_as_failures(env: AuthEnv) -> None:
    env.login("ha.lt")
    env.enroll_mfa("ha.lt")
    for _ in range(4):
        env.login("ha.lt", "sai")
    assert env.sink.of("account_locked") == []  # 4 lỗi + mfa_enrolled ≠ 5


# ---- khoá username chưa có dòng users: phản hồi giống hệt ------------------------------------


def test_locked_ghost_username_responds_exactly_like_locked_real_user(env: AuthEnv) -> None:
    """Phase 4 P2–P3 (4a-3): username KHÔNG có dòng `users` lưu băm `"h:" + HMAC` — kỳ vọng đổi sang giá trị băm, ý test giữ
    nguyên (khoá như người thật, đếm qua cùng giá trị)."""
    assert env.login("an.nv").status_code == 200  # user thật, có dòng users → khoá cứng
    for name in ("an.nv", "khong.ton.tai", "binh.tt"):  # binh.tt có trong AD, chưa có dòng users
        for _ in range(5):
            env.login(name, "sai")
    real = env.login("an.nv")
    ghost = env.login("khong.ton.tai", "bat-ky")
    fresh_ad = env.login("binh.tt")  # mật khẩu ĐÚNG nhưng đang trong cửa sổ khoá
    for r in (ghost, fresh_ad):
        assert r.status_code == real.status_code == 401
        assert r.json() == real.json() == {"detail": GENERIC_LOGIN_ERROR}
        assert r.headers.get("set-cookie") == real.headers.get("set-cookie") is None
    reasons = [(e.username_attempted, e.detail["reason"]) for e in env.sink.of("account_locked")]
    key = _username_key(env)
    for name, known in (("an.nv", True), ("khong.ton.tai", False), ("binh.tt", False)):
        stored = stored_username(name, known=known, key=key)
        assert (stored, "threshold") in reasons and (stored, "still_locked") in reasons
    env.clock.advance(timedelta(minutes=10, seconds=1))  # cửa sổ trượt qua
    assert env.login("binh.tt").status_code == 200


# ---- dải IP ----------------------------------------------------------------------------------


def test_ip_range_limit_returns_429() -> None:
    with auth_env(client_ip="198.51.100.20") as env:
        for i in range(20):  # 20 username khác nhau → không username nào tới ngưỡng khoá
            env.login(f"ghost{i}", "sai")
        r = env.login("an.nv")
        assert r.status_code == 429
        assert {e.ip_prefix for e in env.sink.of("login_failed")} == {"198.51.100.0/24"}
        env.clock.advance(timedelta(minutes=10, seconds=1))
        assert env.login("an.nv").status_code == 200


# ---- trạng thái tài khoản, AD lỗi, role --------------------------------------------------------


@pytest.mark.parametrize("username", ["dung.dv", "em.lv"])  # disabled, terminated
def test_inactive_account_gets_generic_401(env: AuthEnv, username: str) -> None:
    r = env.login(username)
    assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
    assert env.sink.of("login_success") == []


def test_ad_down_returns_503_and_counts_nothing(env: AuthEnv) -> None:
    env.idp.down = True
    assert env.login("an.nv").status_code == 503
    assert env.sink.events == []


def test_more_than_one_privileged_group_fails_closed() -> None:
    idp = FakeIdentityProvider([*seed_ad_users(), FakeAdUser("x1", "hai.vt", ["IT-Users", "IT-L1", "IT-L2"])])
    with auth_env(idp=idp) as env:
        r = env.login("hai.vt")
        assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
        [denied] = env.sink.of("permission_denied")
        assert denied.detail == {"reason": "role_unmappable"}


def test_role_change_records_event_and_kills_old_tokens(env: AuthEnv) -> None:
    old = env.token("ha.lt")
    env.idp.set(FakeAdUser("l1_01", "ha.lt", ["IT-Users", "IT-L2"], "it_mgr01"))
    new = env.token("ha.lt")
    [changed] = env.sink.of("role_changed")
    assert changed.detail == {"from": "l1", "to": "l2"}
    assert env.client.get("/api/auth/me", headers=env.bearer(old)).status_code == 401
    assert env.client.get("/api/auth/me", headers=env.bearer(new)).json()["role"] == "l2"


def test_manager_chain_cycle_depth_and_missing_manager() -> None:
    chain = [FakeAdUser(f"c{i}", f"c{i}", ["IT-Users"], f"c{i + 1}") for i in range(8)]
    users = [
        *chain,  # c7 → c8 không tồn tại; sâu hơn 5 cấp
        FakeAdUser("a", "a.a", ["IT-Users"], "b"),
        FakeAdUser("b", "b.b", ["IT-Users"], "a"),  # vòng a ↔ b
    ]
    with auth_env(idp=FakeIdentityProvider(users)) as env:
        assert env.login("c0").status_code == 200
        assert env.login("a.a").status_code == 200
        store = env.store
        c5 = asyncio.run(store.get_user("c5"))
        c6 = asyncio.run(store.get_user("c6"))
        b = asyncio.run(store.get_user("b"))
    assert c5 is not None and c5.manager_id is None  # cấp 6 bị cắt → NULL = "không biết"
    assert c6 is None
    assert b is not None and b.manager_id is None  # vòng bị chặn


# ---- MFA ---------------------------------------------------------------------------------------


def test_manager_not_enrolled_fails_closed(env: AuthEnv) -> None:
    r = env.login("quan.tm")
    assert (r.status_code, r.json()) == (401, {"detail": "mfa_not_enrolled"})
    [failed] = env.sink.of("mfa_failed")
    assert failed.detail == {"reason": "not_enrolled"} and failed.user_id == "it_mgr01"


def test_manager_mfa_flow(env: AuthEnv) -> None:
    env.login("quan.tm")
    secret = env.enroll_mfa("quan.tm")
    before = len(env.sink.of("mfa_failed"))
    assert env.login("quan.tm").json() == {"detail": "mfa_required"}  # chưa gửi OTP: chưa là lần sai
    assert len(env.sink.of("mfa_failed")) == before
    wrong = env.login("quan.tm", otp="000000" if env.otp(secret) != "000000" else "111111")
    assert (wrong.status_code, wrong.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
    assert env.sink.of("mfa_failed")[-1].detail == {"reason": "invalid_otp"}
    r = env.login("quan.tm", otp=env.otp(secret))
    assert r.status_code == 200
    me = env.client.get("/api/auth/me", headers=env.bearer(r.json()["access_token"])).json()
    assert me["role"] == "manager" and "policy:edit" in me["permissions"]


def test_mfa_optional_for_l1_until_enrolled(env: AuthEnv) -> None:
    assert env.login("ha.lt").status_code == 200
    secret = env.enroll_mfa("ha.lt")
    assert env.login("ha.lt").json() == {"detail": "mfa_required"}
    assert env.login("ha.lt", otp=env.otp(secret)).status_code == 200


# ---- cấu hình thiếu ------------------------------------------------------------------------------


def test_missing_jwt_key_returns_503_but_health_works() -> None:
    with auth_env(jwt_signing_key=None) as env:
        assert env.login("an.nv").status_code == 503
        assert env.client.post("/api/auth/refresh").status_code == 503
        assert env.client.get("/api/auth/me", headers=env.bearer("x")).status_code == 503
        assert env.client.get("/api/health").status_code == 200


# ---- canary ------------------------------------------------------------------------------------


def test_canary_no_password_or_token_in_logs_or_events() -> None:
    canary_pw = "Canary-Pw-9f3kQ!"
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactSecretsFilter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        idp = FakeIdentityProvider(password=canary_pw)
        with auth_env(idp=idp) as env:
            env.login("an.nv", "Wrong-" + canary_pw)
            r = env.login("an.nv", canary_pw)
            access, refresh = r.json()["access_token"], env.client.cookies.get("refresh")
            csrf = env.client.cookies.get("csrf")
            rr = env.refresh()
            access2 = rr.json()["access_token"]
            env.client.post("/api/auth/logout", headers=env.bearer(access2))
            logging.getLogger("app.test").info("thử lọt: token=%s password=%s", access, canary_pw)
            events = repr(env.sink.events)
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    logs = buf.getvalue()
    assert logs  # có log thật để soi
    for secret in (canary_pw, access, access2, refresh, csrf, DEMO_PASSWORD):
        assert secret and secret not in logs, "bí mật lọt vào log"
        assert secret not in events, "bí mật lọt vào security_events"


def test_cookie_expiry_accepts_postgres_timezone() -> None:
    """Hồi quy (make test 26/09): mốc đọc từ Postgres có tzinfo ZoneInfo("Etc/UTC"), không phải
    timezone.utc → Starlette từ chối khi đặt cookie → /api/auth/refresh 500 trên DB thật."""
    from zoneinfo import ZoneInfo

    from app.api.auth import _set_cookies
    from app.auth.models import IssuedTokens
    from starlette.responses import Response

    expires = datetime(2026, 9, 26, 16, 0, tzinfo=ZoneInfo("Etc/UTC"))
    response = Response()
    _set_cookies(response, IssuedTokens("a", "r", "c", 900, expires))
    cookies = response.headers.getlist("set-cookie")
    assert len(cookies) == 2 and all("16:00:00 GMT" in c for c in cookies)
