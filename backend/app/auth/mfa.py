"""MFA TOTP (P6 mục 4) + CLI vận hành đăng ký/đặt lại.

    python -m app.auth.mfa enroll <username> --by <operator> --reason <text>
    python -m app.auth.mfa reset  <username> --by <operator> --reason <text>

- Bắt buộc với `manager`, tùy chọn với l1/l2 (đã enroll thì đăng nhập phải có OTP).
- Chỉ đăng ký qua CLI này (kênh vận hành), không qua màn hình đăng nhập.
- Secret mã hoá AES-256-GCM bằng `MFA_ENC_KEY` (base64 của 32 byte), AAD = user_id: bản mã của
  người này chép sang dòng người khác thì không giải được.
- Enroll/reset ghi `security_events` (`mfa_enrolled`/`mfa_reset`), `detail` CHỈ có `by`, `reason`.
  Secret và URI otpauth chỉ in ra stdout cho người vận hành — không log, không ghi DB dạng rõ.
- Reset: secret mới + tăng `token_version` + thu hồi mọi phiên (phiên cũ chết).
"""

import argparse
import asyncio
import base64
import binascii
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import pyotp
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from app.auth.ports import AuthStore, SecurityEventSink

ISSUER = "ServiceDesk"
_NONCE_BYTES = 12


class MfaError(Exception):
    """Lỗi thao tác MFA (user chưa đồng bộ, đã enroll…) — thông báo an toàn để in ra."""


class MfaCipher:
    def __init__(self, key: SecretStr) -> None:
        try:
            raw = base64.b64decode(key.get_secret_value(), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("MFA_ENC_KEY phải là base64 của 32 byte") from None
        if len(raw) != 32:
            raise ValueError("MFA_ENC_KEY phải là base64 của 32 byte (AES-256-GCM)")
        self._aead = AESGCM(raw)

    def encrypt(self, user_id: str, secret: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, secret.encode("ascii"), user_id.encode("utf-8"))

    def decrypt(self, user_id: str, blob: bytes) -> str:
        try:
            plain = self._aead.decrypt(
                blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], user_id.encode("utf-8")
            )
        except InvalidTag:
            raise MfaError("không giải mã được secret MFA (sai khoá hoặc sai người)") from None
        return plain.decode("ascii")


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify_totp(secret: str, otp: str, at: datetime) -> bool:
    """Chấp nhận mã của bước hiện tại ± 1 bước (30 giây) để bù lệch đồng hồ điện thoại."""
    code = otp.strip()
    if not (code.isdigit() and len(code) == 6):
        return False
    return pyotp.TOTP(secret).verify(code, for_time=at, valid_window=1)


@dataclass(frozen=True)
class Enrollment:
    username: str
    secret: str
    uri: str


async def enroll(
    store: AuthStore, sink: SecurityEventSink, cipher: MfaCipher, *, username: str, by: str,
    reason: str,
) -> Enrollment:  # fmt: skip
    detail = _detail(by, reason)
    user = await store.get_user_by_username(username)
    if user is None:
        raise MfaError(f"{username} chưa có trong bảng users — người đó phải đăng nhập một lần trước")
    if user.mfa_secret_enc is not None:
        raise MfaError(f"{username} đã đăng ký MFA — muốn cấp secret mới thì dùng `reset`")
    secret = new_secret()
    await store.set_mfa_secret(user.user_id, cipher.encrypt(user.user_id, secret))
    await sink.record("mfa_enrolled", user_id=user.user_id, detail=detail)
    return Enrollment(username, secret, provisioning_uri(secret, username))


async def reset(
    store: AuthStore, sink: SecurityEventSink, cipher: MfaCipher, *, username: str, by: str,
    reason: str, now: datetime,
) -> Enrollment:  # fmt: skip
    detail = _detail(by, reason)
    user = await store.get_user_by_username(username)
    if user is None:
        raise MfaError(f"{username} chưa có trong bảng users")
    secret = new_secret()
    await store.set_mfa_secret(user.user_id, cipher.encrypt(user.user_id, secret))
    await store.bump_token_version(user.user_id)
    await store.revoke_user_sessions(user.user_id, "admin", now)
    await sink.record("mfa_reset", user_id=user.user_id, detail=detail)
    return Enrollment(username, secret, provisioning_uri(secret, username))


def _detail(by: str, reason: str) -> dict[str, str]:
    by, reason = by.strip(), reason.strip()
    if not by or not reason:
        raise MfaError("--by và --reason không được rỗng")
    return {"by": by, "reason": reason}


# ---- CLI --------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.auth.mfa", description="Đăng ký / đặt lại MFA")
    p.add_argument("command", choices=("enroll", "reset"))
    p.add_argument("username")
    p.add_argument("--by", required=True, help="người vận hành thực hiện")
    p.add_argument("--reason", required=True, help="lý do (ghi vào security_events)")
    return p


async def _run(args: argparse.Namespace) -> Enrollment:
    # Điểm nối (composition root) giống main.create_app: CLI chạy riêng nên tự dựng store + writer.
    # Import muộn để module auth không phụ thuộc audit ở mức import (01 mục 4.2).
    from app.audit.security_events import SecurityEventWriter
    from app.auth.store import SqlAuthStore
    from app.core.clock import SystemClock
    from app.db.session import create_engines
    from app.settings import Settings

    settings = Settings()
    if settings.mfa_enc_key is None:
        raise MfaError("MFA_ENC_KEY chưa cấu hình")
    cipher = MfaCipher(settings.mfa_enc_key)
    clock = SystemClock()
    engines = create_engines(settings)
    try:
        store = SqlAuthStore(engines.main)
        sink = SecurityEventWriter(engines.main, clock)
        if args.command == "enroll":
            return await enroll(store, sink, cipher, username=args.username, by=args.by,
                                reason=args.reason)  # fmt: skip
        return await reset(store, sink, cipher, username=args.username, by=args.by,
                           reason=args.reason, now=clock.now())  # fmt: skip
    finally:
        await engines.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except (MfaError, ValueError) as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 2
    # Chỉ stdout, cho người vận hành chuyển cho người dùng qua kênh an toàn. Không log.
    print(f"Đã {'đăng ký' if args.command == 'enroll' else 'đặt lại'} MFA cho {result.username}.")
    print(f"Secret: {result.secret}")
    print(f"URI: {result.uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
