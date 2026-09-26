"""MFA: AES-GCM (AAD = user_id), TOTP theo clock, enroll/reset ghi sự kiện không lộ secret."""

import base64
import secrets
from datetime import timedelta

import pyotp
import pytest
from app.auth.mfa import MfaCipher, MfaError, enroll, main, reset, verify_totp
from app.auth.models import SessionRecord, UserSync
from app.core.clock import FakeClock
from pydantic import SecretStr
from tests.fakes.auth import EPOCH, InMemoryAuthStore, RecordingSink


def _key() -> SecretStr:
    return SecretStr(base64.b64encode(secrets.token_bytes(32)).decode())


def test_cipher_round_trip_bound_to_user() -> None:
    cipher = MfaCipher(_key())
    blob = cipher.encrypt("nv001", "JBSWY3DPEHPK3PXP")
    assert b"JBSWY3DPEHPK3PXP" not in blob
    assert cipher.decrypt("nv001", blob) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(MfaError):  # bản mã chép sang người khác → không giải được
        cipher.decrypt("nv002", blob)
    with pytest.raises(MfaError):
        MfaCipher(_key()).decrypt("nv001", blob)


@pytest.mark.parametrize("bad", ["không-phải-base64", base64.b64encode(b"x" * 16).decode()])
def test_cipher_rejects_bad_key(bad: str) -> None:
    with pytest.raises(ValueError, match="32 byte"):
        MfaCipher(SecretStr(bad))


def test_totp_uses_given_time() -> None:
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).at(EPOCH)
    assert verify_totp(secret, code, EPOCH)
    assert verify_totp(secret, code, EPOCH + timedelta(seconds=30))  # ± 1 bước
    assert not verify_totp(secret, code, EPOCH + timedelta(minutes=5))
    assert not verify_totp(secret, "12345", EPOCH) and not verify_totp(secret, "abcdef", EPOCH)


async def _store_with_manager(clock: FakeClock) -> tuple[InMemoryAuthStore, RecordingSink]:
    sink = RecordingSink(clock)
    store = InMemoryAuthStore(sink)
    await store.upsert_user(
        UserSync("it_mgr01", "quan.tm", "Q", "manager", "it", None, "active", None, False, EPOCH)
    )
    return store, sink


@pytest.mark.asyncio
async def test_enroll_records_event_without_secret() -> None:
    clock = FakeClock(EPOCH)
    store, sink = await _store_with_manager(clock)
    cipher = MfaCipher(_key())
    result = await enroll(store, sink, cipher, username="quan.tm", by="ops.an", reason="cấp mới")
    user = await store.get_user("it_mgr01")
    assert user is not None and user.mfa_secret_enc is not None
    assert cipher.decrypt("it_mgr01", user.mfa_secret_enc) == result.secret
    assert result.uri.startswith("otpauth://totp/")
    [event] = sink.of("mfa_enrolled")
    assert event.detail == {"by": "ops.an", "reason": "cấp mới"}  # canary: chỉ 2 khoá này
    assert result.secret not in repr(sink.events) and "otpauth" not in repr(sink.events)
    with pytest.raises(MfaError, match="reset"):  # enroll lần 2 → phải dùng reset
        await enroll(store, sink, cipher, username="quan.tm", by="ops.an", reason="lại")


@pytest.mark.asyncio
async def test_reset_new_secret_kills_sessions() -> None:
    from uuid import uuid4

    clock = FakeClock(EPOCH)
    store, sink = await _store_with_manager(clock)
    cipher = MfaCipher(_key())
    first = await enroll(store, sink, cipher, username="quan.tm", by="ops", reason="cấp")
    await store.create_session(
        SessionRecord("s1", "it_mgr01", uuid4(), "h" * 64, EPOCH, EPOCH + timedelta(hours=8))
    )
    second = await reset(store, sink, cipher, username="quan.tm", by="ops", reason="mất máy",
                         now=clock.now())  # fmt: skip
    user = await store.get_user("it_mgr01")
    assert user is not None and user.token_version == 1
    assert second.secret != first.secret
    session = await store.get_session("s1")
    assert session is not None and session.revoke_reason == "admin"
    [event] = sink.of("mfa_reset")
    assert event.detail == {"by": "ops", "reason": "mất máy"}
    assert second.secret not in repr(sink.events)


@pytest.mark.asyncio
async def test_enroll_unknown_user_or_empty_reason_fails_before_writing() -> None:
    clock = FakeClock(EPOCH)
    store, sink = await _store_with_manager(clock)
    cipher = MfaCipher(_key())
    with pytest.raises(MfaError, match="chưa có"):
        await enroll(store, sink, cipher, username="ai.do", by="ops", reason="x")
    with pytest.raises(MfaError, match="rỗng"):
        await enroll(store, sink, cipher, username="quan.tm", by="ops", reason="  ")
    user = await store.get_user("it_mgr01")
    assert user is not None and user.mfa_secret_enc is None
    assert sink.events == []


def test_cli_requires_by_and_reason(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["enroll", "quan.tm"])
    assert "--by" in capsys.readouterr().err


def test_cli_without_mfa_key_fails_cleanly(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MFA_ENC_KEY", raising=False)
    assert main(["enroll", "quan.tm", "--by", "ops", "--reason", "x"]) == 2
    assert "MFA_ENC_KEY" in capsys.readouterr().err
