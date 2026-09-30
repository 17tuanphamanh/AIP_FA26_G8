"""Phase 4 P2–P3 (chốt Q-3e-14 + Q-4-S; phase4 mục 4.1, 4.5 4a-1…4a-4): username KHÔNG có dòng `users` → lưu `"h:" + HMAC`.

- 4a-1: username ma `matkhau123` → `security_events.username_attempted` = `h:` + 64 hex; chuỗi gốc không nằm ở sự kiện, cảnh báo,
  log (bản PG quét mọi bảng: `integration/test_auth_http_sql.py`).
- 4a-2: username CÓ dòng `users` sai mật khẩu → nguyên văn.
- 4a-3: username ma sai 5 lần trong 10 phút → khoá như người thật (đếm qua view bằng giá trị băm) — phản hồi giống hệt.
- 4a-4: `stored_username` tất định theo (username, khoá); khác `JWT_SIGNING_KEY` → khác; giá trị khớp công thức Q-4-S tính ĐỘC
  LẬP (hmac/hashlib + nhãn viết tay, không qua hàm của mã sản phẩm).
- Khoá HMAC không log, không nằm trong `repr(Settings)`/`repr(AuthService)`/`repr(TokenSigner)`; nhánh username ma không thêm
  truy vấn store (P3).
- Q-4a-5 (chuyển tiếp username ma → có dòng `users` giữa cửa sổ): đếm `IN (nguyên văn, bản băm)` — lần sai lưu băm trước đó
  không mất; `permission_denied(role_unmappable)` theo cùng quy tắc có/không dòng `users`.
- Q-4a-6 (username ma ĐÃ khoá theo cửa sổ trượt rồi mới có dòng): `_upsert` khi dòng VỪA tạo đếm lần sai trong cửa sổ, đủ ngưỡng
  → `locked_until` = lần sai cuối + thời gian khoá; dòng đã có: không đếm, không ghi đè.
"""

import asyncio
import hashlib
import hmac
import logging
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from app.auth.models import UserRecord
from app.auth.service import GENERIC_LOGIN_ERROR, LOGIN_ROUTE, AuthService
from app.auth.tokens import TokenSigner
from app.auth.username_hash import HASH_PREFIX, stored_username, username_key
from app.core.clock import FakeClock
from app.domain.alerts import BRUTEFORCE_RULE_ID
from pydantic import SecretStr
from tests.fakes.auth import (
    EPOCH,
    FakeAdUser,
    FakeIdentityProvider,
    InMemoryAuthStore,
    RecordingSink,
    seed_ad_users,
)
from tests.unit.auth_helpers import AuthEnv, auth_env

GHOST = "matkhau123"  # mật khẩu chữ thường + số gõ nhầm vào ô username — khớp USERNAME_PATTERN (3e), không có dòng users
HASHED = re.compile(r"^h:[0-9a-f]{64}$")


def _key(env: AuthEnv) -> bytes:
    secret = env.settings.jwt_signing_key
    assert secret is not None  # auth_settings luôn đặt khoá
    return username_key(secret.get_secret_value().encode("utf-8"))


def _everything(env: AuthEnv) -> str:
    return repr(env.sink.events) + repr(env.alerts.of(BRUTEFORCE_RULE_ID))


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env() as e:
        yield e


# ---- 4a-4: hàm thuần ------------------------------------------------------------------------------------------------


def test_4a4_stored_username_is_deterministic_per_key_and_prefixed() -> None:
    k1, k2 = username_key(b"k" * 32), username_key(b"j" * 32)
    a = stored_username(GHOST, known=False, key=k1)
    assert HASHED.match(a) and len(a) == 66 and a.startswith(HASH_PREFIX)
    assert a == stored_username(GHOST, known=False, key=k1)  # cùng đầu vào + cùng khoá → cùng kết quả
    assert a != stored_username(GHOST, known=False, key=k2)  # khác JWT_SIGNING_KEY → khác
    assert a != stored_username("matkhau124", known=False, key=k1)
    assert stored_username("an.nv", known=True, key=k1) == "an.nv"  # người có dòng users: nguyên văn
    assert username_key(b"k" * 32) == k1 and len(k1) == 32


def test_4a4_signer_derives_same_key_as_documented_formula() -> None:
    """Q-4-S: khoá = HMAC-SHA256(JWT_SIGNING_KEY, "auth-username-v1") — signer không lộ khoá ký, chỉ trả khoá dẫn xuất."""
    raw = "s" * 40
    signer = TokenSigner(SecretStr(raw), timedelta(minutes=15), FakeClock(EPOCH))
    assert signer.username_key() == username_key(raw.encode("utf-8")) != raw.encode("utf-8")


# Vector đáp án HMAC tính từ khoá test công khai b"k"*32 — KHÔNG phải bí mật (H6, soát bảo mật lượt 2).
KAT_KEY_K32 = "387a3e999a9a48ab938e03ae8f985578a5b39947a436d7deb90fd9a84b7878cc"  # GHOST, khoá ký b"k"*32 — tính bằng hmac/hashlib  # gitleaks:allow


def _q4s_formula(signing: bytes, username: str) -> str:
    """Công thức Q-4-S viết lại độc lập: HMAC(HMAC(khoá ký, "auth-username-v1"), username), SHA-256, tiền tố "h:"."""
    derived = hmac.new(signing, b"auth-username-v1", hashlib.sha256).digest()
    return "h:" + hmac.new(derived, username.encode("utf-8"), hashlib.sha256).hexdigest()


def test_4a4_known_answer_independent_of_product_code(env: AuthEnv) -> None:
    """Kỳ vọng KHÔNG tính bằng `username_key`/`stored_username` (security-reviewer lượt 2, H6): đổi nhãn, bỏ bước dẫn xuất
    (dùng thẳng khoá ký — mất tách miền Q-4-S) hay đổi hàm băm → đỏ. Đi hết đường thật: signer → service → sự kiện."""
    assert stored_username(GHOST, known=False, key=username_key(b"k" * 32)) == "h:" + KAT_KEY_K32
    assert _q4s_formula(b"k" * 32, GHOST) == "h:" + KAT_KEY_K32
    assert env.settings.jwt_signing_key is not None
    signing = env.settings.jwt_signing_key.get_secret_value().encode("utf-8")
    env.login(GHOST, "sai")
    [event] = env.sink.of("login_failed")
    assert event.username_attempted == _q4s_formula(signing, GHOST)
    assert event.username_attempted != "h:" + hmac.new(signing, GHOST.encode("utf-8"), hashlib.sha256).hexdigest()


# ---- 4a-1, 4a-2 -------------------------------------------------------------------------------------------------------


def test_4a1_ghost_username_is_stored_hashed_never_verbatim(env: AuthEnv) -> None:
    r = env.login(GHOST, "bat-ky")
    assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
    [event] = env.sink.of("login_failed")
    assert event.username_attempted == stored_username(GHOST, known=False, key=_key(env))
    assert HASHED.match(event.username_attempted or "")
    assert GHOST not in _everything(env)


def test_4a1_ghost_lock_event_and_alert_are_hashed(env: AuthEnv, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for _ in range(6):  # 5 lần → khoá (threshold) + 1 lần khi đang khoá (still_locked)
        env.login(GHOST, "bat-ky")
    stored = stored_username(GHOST, known=False, key=_key(env))
    reasons = {(e.username_attempted, e.detail["reason"]) for e in env.sink.of("account_locked")}
    assert reasons == {(stored, "threshold"), (stored, "still_locked")}
    [alert] = env.alerts.of(BRUTEFORCE_RULE_ID)
    assert alert.detail["username"] == stored
    assert GHOST not in _everything(env) and GHOST not in caplog.text


def test_4a2_known_username_wrong_password_is_verbatim(env: AuthEnv) -> None:
    assert env.login("an.nv").status_code == 200  # có dòng users
    env.login("an.nv", "sai")
    [event] = env.sink.of("login_failed")
    assert event.username_attempted == "an.nv"
    assert [e.username_attempted for e in env.sink.of("login_success")] == ["an.nv"]


def test_4a2_first_login_success_is_verbatim(env: AuthEnv) -> None:
    """Người AD đăng nhập lần đầu: bước 4 vừa tạo dòng `users` → `login_success` nguyên văn (người thật)."""
    assert env.login("binh.tt").status_code == 200
    assert [e.username_attempted for e in env.sink.of("login_success")] == ["binh.tt"]


# ---- 4a-3 -------------------------------------------------------------------------------------------------------------


def test_4a3_ghost_locked_after_5_failures_like_real_user(env: AuthEnv) -> None:
    for _ in range(4):
        env.login(GHOST, "sai")
    assert env.sink.of("account_locked") == []  # 4 < 5
    env.login(GHOST, "sai")  # lần 5 → khoá (đếm qua view bằng giá trị băm)
    assert [e.detail["reason"] for e in env.sink.of("account_locked")] == ["threshold"]
    r = env.login(GHOST, "sai")
    assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
    assert [e.detail["reason"] for e in env.sink.of("account_locked")] == ["threshold", "still_locked"]
    env.clock.advance(timedelta(minutes=10, seconds=1))  # cửa sổ trượt qua → hết khoá; 1 lỗi mới < 5 → không khoá lại
    env.login(GHOST, "sai")
    assert [e.detail["reason"] for e in env.sink.of("account_locked")] == ["threshold", "still_locked"]


# ---- Q-4a-5: chuyển tiếp username ma → có dòng users giữa cửa sổ ---------------------------------------------------------


def _failed_as(env: AuthEnv) -> list[str | None]:
    return [e.username_attempted for e in env.sink.of("login_failed")]


def _assert_locked_at_fifth(env: AuthEnv, username: str) -> None:
    """3 lần băm (chưa có dòng) + 2 lần nguyên văn (đã có dòng) → khoá đúng ở lần 5; đúng mật khẩu sau đó vẫn bị chặn."""
    hashed = stored_username(username, known=False, key=_key(env))
    env.login(username, "sai")  # lần 4
    assert env.sink.of("account_locked") == []
    env.login(username, "sai")  # lần 5
    assert _failed_as(env) == [hashed] * 3 + [username] * 2
    [locked] = env.sink.of("account_locked")
    assert (locked.username_attempted, locked.detail) == (username, {"reason": "threshold", "failures": 5})
    [alert] = env.alerts.of(BRUTEFORCE_RULE_ID)
    assert alert.detail["username"] == username
    r = env.login(username)  # đúng mật khẩu: locked_until chặn ở bước 2, trước AD
    assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
    assert [e.detail["reason"] for e in env.sink.of("account_locked")] == ["threshold", "still_locked"]


def test_q4a5a_ghost_failures_count_after_own_first_login(env: AuthEnv) -> None:
    """binh.tt (người AD chưa có dòng users) sai 3 lần (băm) → tự đăng nhập đúng (tạo dòng) → sai thêm 2 → khoá ở lần 5."""
    for _ in range(3):
        env.login("binh.tt", "sai")
    assert env.sink.of("account_locked") == []
    assert env.login("binh.tt").status_code == 200  # bước 4 tạo dòng users
    _assert_locked_at_fifth(env, "binh.tt")


@pytest.mark.parametrize(("subordinate", "manager"), [("binh.tt", "lan.dt"), ("ha.lt", "quan.tm")])
def test_q4a5b_ghost_failures_count_after_row_created_by_ensure_manager(
    env: AuthEnv, subordinate: str, manager: str
) -> None:
    """Như (a) nhưng dòng users của người quản lý do `_ensure_manager` tạo khi CẤP DƯỚI đăng nhập (người quản lý chưa từng
    đăng nhập). quan.tm là manager (bắt buộc MFA): chưa khoá thì đúng mật khẩu ra `mfa_not_enrolled`, khác 401 chung."""
    for _ in range(3):
        env.login(manager, "sai")
    assert env.login(subordinate).status_code == 200
    _assert_locked_at_fifth(env, manager)


def test_q4a5c_role_unmappable_username_attempted_follows_users_row() -> None:
    """permission_denied(role_unmappable): chưa có dòng users → băm (dù mật khẩu đúng — quy tắc theo dòng users, không theo
    AD); đã có dòng (role từng ánh xạ được, nay AD đổi nhóm) → nguyên văn."""
    idp = FakeIdentityProvider([*seed_ad_users(), FakeAdUser("x1", "hai.vt", ["IT-Users", "IT-L1", "IT-L2"])])
    with auth_env(idp=idp) as env:
        assert env.login("hai.vt").status_code == 401
        assert env.login("an.nv").status_code == 200  # tạo dòng users
        env.idp.set(FakeAdUser("nv001", "an.nv", ["Khach"], "fin_head", department="finance"))
        assert env.login("an.nv").status_code == 401
        denied = env.sink.of("permission_denied")
        assert [(e.username_attempted, e.route, e.detail) for e in denied] == [
            (stored_username("hai.vt", known=False, key=_key(env)), LOGIN_ROUTE, {"reason": "role_unmappable"}),
            ("an.nv", LOGIN_ROUTE, {"reason": "role_unmappable"}),
        ]
        assert "hai.vt" not in _everything(env)


# ---- Q-4a-6: username ma ĐÃ khoá rồi mới có dòng users → mang khoá sang locked_until -----------------------------------


def _auth(env: AuthEnv) -> AuthService:
    auth: AuthService = env.app.state.auth
    return auth


def _row(env: AuthEnv, username: str) -> UserRecord:
    user = asyncio.run(env.store.get_user_by_username(username))
    assert user is not None
    return user


def _fail_spaced(env: AuthEnv, username: str, n: int) -> datetime:
    """n lần sai mật khẩu cách nhau 1 phút (cùng nằm trong cửa sổ) — trả thời điểm lần sai CUỐI."""
    for i in range(n):
        if i:
            env.clock.advance(timedelta(minutes=1))
        env.login(username, "sai")
    return env.clock.now()


def _blocked_before_ad(env: AuthEnv, username: str) -> None:
    before, events = env.idp.authenticate_calls, len(env.sink.events)
    r = env.login(username)  # ĐÚNG mật khẩu
    assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
    assert env.idp.authenticate_calls == before  # chặn ở bước 2: AD nhận 0 lần gọi
    assert [(e.event_type, e.detail) for e in env.sink.events[events:]] == [("account_locked", {"reason": "still_locked"})]


def _reaches_ad_and_logs_in(env: AuthEnv, username: str) -> None:
    before = env.idp.authenticate_calls
    assert env.login(username).status_code == 200
    assert env.idp.authenticate_calls == before + 1


def test_q4a6a_ghost_lock_carried_to_new_row_blocks_before_ad(env: AuthEnv) -> None:
    """(a) lan.dt (chưa có dòng) sai ĐỦ ngưỡng → khoá trượt; binh.tt đăng nhập → `_ensure_manager` tạo dòng lan.dt SAU lần sai
    cuối 2 phút → `locked_until` = lần sai cuối + thời gian khoá (không tính từ lúc tạo) → lần kế tiếp (đúng mật khẩu) bị chặn,
    AD 0 lần gọi; hết khoá đúng mốc. Thay test ghim "tới AD tối đa 1 lần" của Q-4a-5."""
    cfg = _auth(env).config
    last = _fail_spaced(env, "lan.dt", cfg.max_failures)
    assert [e.detail["reason"] for e in env.sink.of("account_locked")] == ["threshold"]
    env.clock.advance(timedelta(minutes=2))
    assert env.login("binh.tt").status_code == 200
    assert _row(env, "lan.dt").locked_until == last + cfg.lockout
    assert [e.detail["reason"] for e in env.sink.of("account_locked")] == ["threshold"]  # mang khoá: không ghi sự kiện mới
    assert len(env.alerts.of(BRUTEFORCE_RULE_ID)) == 1  # … không cảnh báo mới
    _blocked_before_ad(env, "lan.dt")
    env.clock.advance(last + cfg.lockout - env.clock.now() - timedelta(seconds=1))
    _blocked_before_ad(env, "lan.dt")  # 1 giây trước mốc: còn khoá
    env.clock.advance(timedelta(seconds=2))
    _reaches_ad_and_logs_in(env, "lan.dt")


def test_q4a6b_below_threshold_new_row_not_locked(env: AuthEnv) -> None:
    """(b) sai ngưỡng−1 lần → tạo dòng → không khoá; lần kế tiếp tới AD và đăng nhập được."""
    cfg = _auth(env).config
    _fail_spaced(env, "lan.dt", cfg.max_failures - 1)
    assert env.login("binh.tt").status_code == 200
    assert _row(env, "lan.dt").locked_until is None
    _reaches_ad_and_logs_in(env, "lan.dt")


def test_q4a6c_failures_outside_window_not_counted(env: AuthEnv) -> None:
    """(c) đủ ngưỡng lần sai nhưng lúc tạo dòng lần ĐẦU vừa rơi khỏi cửa sổ (`occurred_at > now − cửa sổ`, không bằng) → còn
    ngưỡng−1 trong cửa sổ → không khoá."""
    cfg = _auth(env).config
    first = env.clock.now()
    _fail_spaced(env, "lan.dt", cfg.max_failures)
    env.clock.advance(first + cfg.failure_window - env.clock.now())
    assert env.login("binh.tt").status_code == 200
    assert _row(env, "lan.dt").locked_until is None
    _reaches_ad_and_logs_in(env, "lan.dt")


def test_q4a6d_existing_row_upsert_neither_counts_nor_overwrites_lock() -> None:
    """(d) dòng lan.dt ĐÃ có, `locked_until` đặt sẵn (khác mọi "lần sai cuối + khoá") và đủ ngưỡng lần sai trong cửa sổ →
    binh.tt đăng nhập lại (`_ensure_manager` → `_upsert` trên dòng đã có): `locked_until` giữ nguyên, không có lời đếm nào
    (`count_failures`/`last_failure_at`). Bảng `users` không có cột đếm lần sai — số lần sai luôn đếm từ view."""
    clock = FakeClock(EPOCH)
    sink = RecordingSink(clock)
    store = CountingStore(sink)
    with auth_env(store=store, sink=sink, clock=clock) as env:
        assert env.login("binh.tt").status_code == 200  # tạo dòng binh.tt + lan.dt
        cfg = _auth(env).config
        env.clock.advance(timedelta(minutes=1))
        _fail_spaced(env, "lan.dt", cfg.max_failures)  # người có dòng: khoá qua `_check_threshold`
        preset = _row(env, "lan.dt").locked_until
        assert preset is not None
        preset += timedelta(hours=1)
        asyncio.run(store.set_locked_until(_row(env, "lan.dt").user_id, preset))
        store.calls.clear()
        env.clock.advance(timedelta(minutes=1))
        assert env.login("binh.tt").status_code == 200
        assert "count_failures" not in store.calls and "last_failure_at" not in store.calls  # binh.tt + lan.dt đều đã có dòng
        assert _row(env, "lan.dt").locked_until == preset


def test_q4a6e_verbatim_and_hashed_failures_sum(env: AuthEnv) -> None:
    """(e) 2 lần sai lưu NGUYÊN VĂN (bản ghi của code trước P2 — HMAC) + ngưỡng−2 lần lưu băm: nhánh ma chỉ thấy bản băm (không
    khoá); lúc tạo dòng đếm `IN (nguyên văn, băm)` = ngưỡng → khoá từ lần sai cuối."""
    cfg = _auth(env).config
    for _ in range(2):
        asyncio.run(env.sink.record("login_failed", username_attempted="lan.dt"))
        env.clock.advance(timedelta(minutes=1))
    last = _fail_spaced(env, "lan.dt", cfg.max_failures - 2)
    assert env.sink.of("account_locked") == []
    env.clock.advance(timedelta(minutes=1))
    assert env.login("binh.tt").status_code == 200
    assert _row(env, "lan.dt").locked_until == last + cfg.lockout
    _blocked_before_ad(env, "lan.dt")


# ---- khoá không lộ; không thêm truy vấn ở nhánh ma (P3) -----------------------------------------------------------------


def test_key_not_in_settings_service_or_signer_repr(env: AuthEnv) -> None:
    key = _key(env)
    auth: AuthService = env.app.state.auth
    assert env.settings.jwt_signing_key is not None
    signing = env.settings.jwt_signing_key.get_secret_value()
    texts = (repr(env.settings), str(env.settings), repr(auth), repr(vars(env.settings)), repr(auth.signer), str(auth.signer))
    for text in texts:
        assert key.hex() not in text and repr(key) not in text
        assert signing not in text and repr(signing.encode("utf-8")) not in text


class CountingStore(InMemoryAuthStore):
    def __init__(self, sink: RecordingSink) -> None:
        super().__init__(sink)
        self.calls: list[str] = []

    async def count_failures(self, usernames: tuple[str, ...], since: datetime) -> int:
        self.calls.append("count_failures")
        return await super().count_failures(usernames, since)

    async def last_failure_at(self, usernames: tuple[str, ...], since: datetime) -> datetime | None:
        self.calls.append("last_failure_at")
        return await super().last_failure_at(usernames, since)

    async def count_ip_failures(self, ip_prefix: str, since: datetime) -> int:
        self.calls.append("count_ip_failures")
        return await super().count_ip_failures(ip_prefix, since)

    async def get_user_by_username(self, username: str) -> Any:
        self.calls.append("get_user_by_username")
        return await super().get_user_by_username(username)


def test_p3_ghost_branch_adds_no_store_query() -> None:
    """P3: nhánh username ma gọi store ĐÚNG như 3e (ip → tra users → đếm khoá → ghi → đếm ngưỡng) — băm là CPU thuần, không
    thêm truy vấn (thời gian phản hồi không tách được username ma)."""
    clock = FakeClock(EPOCH)
    sink = RecordingSink(clock)
    store = CountingStore(sink)
    with auth_env(store=store, sink=sink, clock=clock) as env:
        env.login(GHOST, "sai")
    assert store.calls == ["count_ip_failures", "get_user_by_username", "count_failures", "count_failures"]
