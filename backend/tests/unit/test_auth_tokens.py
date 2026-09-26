"""JWT HS256 7 claim, kiểm hạn theo clock tiêm vào; refresh chỉ lưu SHA-256; CSRF double submit.

Bắt buộc (duyệt 26/09): exp quá hạn → từ chối; iat ở tương lai → từ chối; chỉ tắt kiểm thời gian
của pyjwt — chữ ký/thuật toán vẫn kiểm (`alg=none`, đổi alg → từ chối). Qua HTTP: 401.
"""

import base64
import hashlib
import json
import secrets
from datetime import timedelta

import jwt
import pytest
from app.auth.tokens import (
    CLAIMS,
    TokenError,
    TokenSigner,
    csrf_matches,
    hash_refresh_token,
    new_refresh_token,
)
from app.core.clock import FakeClock
from pydantic import SecretStr
from tests.fakes.auth import EPOCH
from tests.unit.auth_helpers import auth_env

KEY = secrets.token_urlsafe(32)


def _signer(clock: FakeClock, key: str = KEY) -> TokenSigner:
    return TokenSigner(SecretStr(key), timedelta(minutes=15), clock)


def _issue(signer: TokenSigner) -> str:
    return signer.issue(user_id="nv001", role="employee", session_id="s1", token_version=0)


def _b64(obj: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def test_exactly_seven_claims() -> None:
    clock = FakeClock(EPOCH)
    token = _issue(_signer(clock))
    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == set(CLAIMS) and len(CLAIMS) == 7
    assert claims["exp"] - claims["iat"] == 15 * 60
    assert jwt.get_unverified_header(token)["alg"] == "HS256"


def test_valid_token_verifies() -> None:
    clock = FakeClock(EPOCH)
    signer = _signer(clock)
    c = signer.verify(_issue(signer))
    assert (c.sub, c.role, c.sid, c.tv) == ("nv001", "employee", "s1", 0)


def test_key_shorter_than_32_bytes_rejected() -> None:
    with pytest.raises(ValueError, match="32"):
        _signer(FakeClock(EPOCH), key="x" * 31)


def test_expired_by_injected_clock() -> None:
    clock = FakeClock(EPOCH)
    signer = _signer(clock)
    token = _issue(signer)
    clock.advance(timedelta(minutes=15))
    with pytest.raises(TokenError, match="hết hạn"):
        signer.verify(token)


def test_iat_in_future_rejected() -> None:
    clock = FakeClock(EPOCH)
    future = _signer(FakeClock(EPOCH + timedelta(hours=1)))
    with pytest.raises(TokenError, match="tương lai"):
        _signer(clock).verify(_issue(future))


def test_alg_none_rejected() -> None:
    clock = FakeClock(EPOCH)
    claims = jwt.decode(_issue(_signer(clock)), options={"verify_signature": False})
    unsigned = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."
    with pytest.raises(TokenError):
        _signer(clock).verify(unsigned)


_HS512_WARNING = "ignore:The HMAC key is:UserWarning"  # token HS512 cố ý giả mạo trong test


@pytest.mark.filterwarnings(_HS512_WARNING)
def test_other_alg_with_same_key_rejected() -> None:
    clock = FakeClock(EPOCH)
    claims = jwt.decode(_issue(_signer(clock)), options={"verify_signature": False})
    hs512 = jwt.encode(claims, KEY.encode(), algorithm="HS512")
    with pytest.raises(TokenError):
        _signer(clock).verify(hs512)


def test_wrong_key_and_tampered_payload_rejected() -> None:
    clock = FakeClock(EPOCH)
    token = _issue(_signer(clock, key=secrets.token_urlsafe(32)))
    with pytest.raises(TokenError):
        _signer(clock).verify(token)
    head, _, sig = _issue(_signer(clock)).split(".")
    claims = jwt.decode(_issue(_signer(clock)), options={"verify_signature": False})
    forged = f"{head}.{_b64({**claims, 'role': 'manager'})}.{sig}"
    with pytest.raises(TokenError):
        _signer(clock).verify(forged)


def test_extra_or_missing_claim_rejected() -> None:
    clock = FakeClock(EPOCH)
    claims = jwt.decode(_issue(_signer(clock)), options={"verify_signature": False})
    with pytest.raises(TokenError):
        _signer(clock).verify(jwt.encode({**claims, "admin": True}, KEY.encode(), algorithm="HS256"))
    del claims["tv"]
    with pytest.raises(TokenError):
        _signer(clock).verify(jwt.encode(claims, KEY.encode(), algorithm="HS256"))


def test_refresh_token_256_bit_and_only_hash_stored() -> None:
    token = new_refresh_token()
    assert len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) == 32
    assert hash_refresh_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert new_refresh_token() != token


def test_csrf_matches() -> None:
    assert csrf_matches("abc", "abc")
    assert not csrf_matches("abc", "abd")
    assert not csrf_matches(None, "abc") and not csrf_matches("abc", None)
    assert not csrf_matches("", "")


# ---- qua HTTP: các token xấu đều 401 -----------------------------------------------------------


@pytest.mark.filterwarnings(_HS512_WARNING)
def test_http_rejects_bad_tokens_with_401() -> None:
    with auth_env() as env:
        good = env.token("an.nv")
        claims = jwt.decode(good, options={"verify_signature": False})
        key = env.settings.jwt_signing_key
        assert key is not None
        raw_key = key.get_secret_value().encode()
        bad = {
            "none": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}.",
            "hs512": jwt.encode(claims, raw_key, algorithm="HS512"),
            "future_iat": jwt.encode({**claims, "iat": claims["iat"] + 3600}, raw_key, algorithm="HS256"),
            "garbage": "abc.def.ghi",
        }
        for name, token in bad.items():
            r = env.client.get("/api/auth/me", headers=env.bearer(token))
            assert r.status_code == 401, name
        assert env.client.get("/api/auth/me", headers=env.bearer(good)).status_code == 200
        env.clock.advance(timedelta(minutes=15))  # exp quá hạn theo FakeClock
        assert env.client.get("/api/auth/me", headers=env.bearer(good)).status_code == 401
