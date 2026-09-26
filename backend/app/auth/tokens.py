"""Access token (JWT HS256, đúng 7 claim), refresh token, CSRF (P6 mục 4).

- Khoá ký ≥ 32 byte (256 bit). Chỉ chấp nhận HS256: `alg=none` hay alg khác đều bị từ chối.
- `exp`/`iat` kiểm theo clock tiêm vào (FakeClock tua được), KHÔNG theo giờ máy của pyjwt — chỉ tắt
  phần kiểm thời gian của pyjwt; chữ ký, thuật toán, claim bắt buộc pyjwt vẫn kiểm.
- Refresh token 256 bit ngẫu nhiên; DB chỉ lưu SHA-256 (lộ DB cũng không dùng lại được).
- CSRF double submit: cookie `csrf` + header `X-CSRF-Token` phải khớp ở `/api/auth/refresh`.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, get_args
from uuid import uuid4

import jwt
from pydantic import SecretStr

from app.core.clock import Clock
from app.domain.context import Role

ALGORITHM = "HS256"
MIN_KEY_BYTES = 32
CLAIMS = ("sub", "role", "sid", "tv", "iat", "exp", "jti")  # P6 mục 4 — đúng 7, không thêm
_ROLES = frozenset(get_args(Role))


class TokenError(Exception):
    """Access token không dùng được (sai chữ ký/thuật toán, hết hạn, claim sai). Không kèm token."""


@dataclass(frozen=True)
class AccessClaims:
    sub: str
    role: Role
    sid: str
    tv: int
    iat: int
    exp: int
    jti: str


class TokenSigner:
    def __init__(self, key: SecretStr, ttl: timedelta, clock: Clock) -> None:
        raw = key.get_secret_value().encode("utf-8")
        if len(raw) < MIN_KEY_BYTES:
            raise ValueError(f"JWT_SIGNING_KEY phải dài ≥ {MIN_KEY_BYTES} byte (HS256, P6)")
        self._key = raw
        self._ttl = ttl
        self._clock = clock

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    def issue(self, *, user_id: str, role: Role, session_id: str, token_version: int) -> str:
        iat = int(self._clock.now().timestamp())
        claims: dict[str, Any] = {
            "sub": user_id,
            "role": role,
            "sid": session_id,
            "tv": token_version,
            "iat": iat,
            "exp": iat + self.ttl_seconds,
            "jti": uuid4().hex,
        }
        return jwt.encode(claims, self._key, algorithm=ALGORITHM)

    def verify(self, token: str) -> AccessClaims:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=[ALGORITHM],
                options={
                    "verify_signature": True,
                    "verify_exp": False,  # kiểm dưới đây theo clock tiêm vào
                    "verify_iat": False,
                    "verify_nbf": False,
                    "require": list(CLAIMS),
                },
            )
        except jwt.PyJWTError as e:
            raise TokenError(type(e).__name__) from None
        if set(claims) != set(CLAIMS):
            raise TokenError("claim thừa hoặc thiếu")
        ints = ("tv", "iat", "exp")
        strs = ("sub", "sid", "jti")
        if not all(type(claims[k]) is int for k in ints) or not all(
            isinstance(claims[k], str) and claims[k] for k in strs
        ):
            raise TokenError("claim sai kiểu")
        if claims["role"] not in _ROLES:
            raise TokenError("role lạ")
        now = self._clock.now().timestamp()
        if claims["iat"] > now:
            raise TokenError("iat ở tương lai")
        if claims["exp"] <= now:
            raise TokenError("hết hạn")
        return AccessClaims(**claims)


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bit


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie: str | None, header: str | None) -> bool:
    if not cookie or not header:
        return False
    return hmac.compare_digest(cookie.encode("utf-8"), header.encode("utf-8"))


def hash_user_agent(user_agent: str | None) -> str | None:
    return hashlib.sha256(user_agent.encode("utf-8")).hexdigest() if user_agent else None
