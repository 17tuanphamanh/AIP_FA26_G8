"""A4 (bn-a, 08/11, migration 0016 — dời từ 0015) — TOTP không dùng lại được (test viết trước, DỪNG 1).

Hợp đồng (PLAN bn-a mục A4):
- `auth.mfa.totp_step(secret, otp, at) -> int | None`: bước (counter = floor(unix/30)) mà mã khớp trong cửa sổ ±1 bước như
  `verify_totp` cũ; sai dạng / không khớp → None. So sánh hằng thời gian.
- `AuthStore.accept_totp_step(user_id, step) -> bool`: NGUYÊN TỬ — True và ghi `users.mfa_last_step = step` khi chưa có bước nào hoặc bước
  cũ < `step`; False (không ghi) khi `step` ≤ bước đã chấp nhận. Bản SQL: một câu `UPDATE … WHERE mfa_last_step IS NULL OR mfa_last_step <
  :step RETURNING` (test PG: hai đăng nhập đồng thời cùng mã → đúng một True).
- Đăng nhập: mã đúng nhưng bước ≤ bước đã chấp nhận → 401 thông báo chung + `mfa_failed {"reason": "otp_replayed"}` + tính vào ngưỡng
  khoá như `invalid_otp`.
- `set_mfa_secret` (enroll/reset) xoá bước đã chấp nhận (secret mới — bước cũ không còn nghĩa).
Thời gian từ `FakeClock` (không đồng hồ thật).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from app.auth.service import GENERIC_LOGIN_ERROR as GENERIC
from tests.unit.auth_helpers import AuthEnv, auth_env

T0 = datetime(2099, 9, 26, 8, 0, 10, tzinfo=UTC)  # giây 10 của một bước 30 s (unix chia hết cho 30 ở :00)

CHO_0016 = pytest.mark.xfail(strict=True, reason="CHỜ migration 0016 — gỡ cờ khi hiện thực")


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env() as e:
        e.clock.set(T0)
        yield e


def _enrolled_manager(env: AuthEnv) -> str:
    assert env.login("quan.tm").status_code == 401  # tạo dòng users
    return env.enroll_mfa("quan.tm")


def _code(secret: str, at: datetime) -> str:
    return pyotp.TOTP(secret).at(at)


# ---- hàm thuần -----------------------------------------------------------------------------------------------------------------


@CHO_0016


def test_a4_totp_step_returns_matched_counter_within_window() -> None:
    # A4: `totp_step` có khi hiện thực (chờ 0016) — gỡ ignore
    from app.auth.mfa import totp_step  # type: ignore[attr-defined]

    secret = pyotp.random_base32()
    step = int(T0.timestamp()) // 30
    assert totp_step(secret, _code(secret, T0), T0) == step
    assert totp_step(secret, _code(secret, T0 - timedelta(seconds=30)), T0) == step - 1  # lệch đồng hồ ±1 bước như cũ
    assert totp_step(secret, _code(secret, T0 + timedelta(seconds=30)), T0) == step + 1
    assert totp_step(secret, _code(secret, T0 - timedelta(seconds=60)), T0) is None  # ngoài cửa sổ
    for bad in ("", "12345", "1234567", "abcdef", " 12 34 "):
        assert totp_step(secret, bad, T0) is None


# ---- luồng đăng nhập -----------------------------------------------------------------------------------------------------------


@CHO_0016


def test_a4_same_code_twice_in_same_step_rejected_as_replay(env: AuthEnv) -> None:
    secret = _enrolled_manager(env)
    code = _code(secret, env.clock.now())
    assert env.login("quan.tm", otp=code).status_code == 200
    env.clock.advance(timedelta(seconds=5))  # vẫn cùng bước
    r = env.login("quan.tm", otp=code)
    assert (r.status_code, r.json()) == (401, {"detail": GENERIC})
    assert env.sink.of("mfa_failed")[-1].detail == {"reason": "otp_replayed"}


@CHO_0016


def test_a4_previous_step_code_rejected_after_current_step_accepted(env: AuthEnv) -> None:
    """Cửa sổ ±1 vẫn nhận mã bước trước KHI CHƯA dùng bước nào mới hơn; đã nhận bước t thì mã bước t−1 (còn trong cửa sổ) bị từ chối."""
    secret = _enrolled_manager(env)
    now = env.clock.now()
    assert env.login("quan.tm", otp=_code(secret, now)).status_code == 200
    r = env.login("quan.tm", otp=_code(secret, now - timedelta(seconds=30)))
    assert r.status_code == 401
    assert env.sink.of("mfa_failed")[-1].detail == {"reason": "otp_replayed"}


def test_a4_next_step_code_accepted(env: AuthEnv) -> None:
    secret = _enrolled_manager(env)
    assert env.login("quan.tm", otp=_code(secret, env.clock.now())).status_code == 200
    env.clock.advance(timedelta(seconds=30))
    assert env.login("quan.tm", otp=_code(secret, env.clock.now())).status_code == 200


@CHO_0016


def test_a4_replay_counts_toward_lockout(env: AuthEnv) -> None:
    """`otp_replayed` là một lần thất bại như `invalid_otp` (view `auth_failures` đếm `mfa_failed`) — dò lại mã cũ vẫn bị khoá."""
    secret = _enrolled_manager(env)
    code = _code(secret, env.clock.now())
    assert env.login("quan.tm", otp=code).status_code == 200
    before = len(env.sink.of("mfa_failed"))
    for _ in range(3):
        env.login("quan.tm", otp=code)
    assert len(env.sink.of("mfa_failed")) == before + 3
    assert all(e.detail == {"reason": "otp_replayed"} for e in env.sink.of("mfa_failed")[before:])


def test_a4_reset_clears_accepted_step(env: AuthEnv) -> None:
    """Reset MFA (secret mới) trong CÙNG bước: mã của secret mới ở bước hiện tại phải được nhận (bước cũ thuộc secret cũ)."""
    import asyncio

    from app.auth.mfa import MfaCipher, reset

    secret = _enrolled_manager(env)
    assert env.login("quan.tm", otp=_code(secret, env.clock.now())).status_code == 200
    key = env.settings.mfa_enc_key
    assert key is not None
    fresh = asyncio.run(reset(env.store, env.sink, MfaCipher(key), username="quan.tm", by="ops", reason="test",
                              now=env.clock.now())).secret  # fmt: skip
    assert env.login("quan.tm", otp=_code(fresh, env.clock.now())).status_code == 200
