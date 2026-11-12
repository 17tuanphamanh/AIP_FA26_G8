"""MFA TOTP (P6 mục 4) + CLI vận hành đăng ký/đặt lại.

    python -m app.auth.mfa enroll <username> [--user-id <mã AD>] --by <operator> --reason <text>
    python -m app.auth.mfa reset  <username> --by <operator> --reason <text>

- Bắt buộc với `manager`, tùy chọn với l1/l2 (đã enroll thì đăng nhập phải có OTP).
- Chỉ đăng ký qua CLI này (kênh vận hành), không qua màn hình đăng nhập.
- Secret mã hoá AES-256-GCM bằng `MFA_ENC_KEY` (base64 của 32 byte), AAD = user_id: bản mã của
  người này chép sang dòng người khác thì không giải được.
- Enroll/reset ghi `security_events` (`mfa_enrolled`/`mfa_reset`), `detail` CHỈ có `by`, `reason`.
  Secret và URI otpauth chỉ in ra stdout cho người vận hành — không log, không ghi DB dạng rõ.
- Reset: secret mới + tăng `token_version` + thu hồi mọi phiên (phiên cũ chết).
- Enroll trên DB mới (O2, 12/11): người chưa có dòng `users` → `--user-id` đồng bộ từ AD qua `AdUserSync` (cùng đường với đăng
  nhập/B15) rồi mới enroll. AD chỉ tra theo `user_id`, nên tên đăng nhập trong AD phải khớp username gõ vào; không có trong AD,
  lệch tên, AD không trả lời, nhóm không ra role, tài khoản đã nghỉ → `MfaError`, không ghi secret, không ghi sự kiện.
"""

import argparse
import asyncio
import base64
import binascii
import hmac
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import pyotp
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from app.auth.models import INACTIVE_STATUSES, UserRecord
from app.auth.ports import (
    AuthStore,
    IdentityProvider,
    IdentityUnavailable,
    SecurityEventSink,
)
from app.auth.user_sync import AdUserSync

if TYPE_CHECKING:
    from app.core.clock import Clock
    from app.settings import Settings

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


TOTP_STEP_SECONDS = 30


def totp_step(secret: str, otp: str, at: datetime) -> int | None:
    """Bước TOTP (counter = floor(unix/30)) mà mã khớp trong cửa sổ ±1 bước (bù lệch đồng hồ điện thoại); sai dạng / không khớp → None.

    Lô Q7 / A4 (migration 0016): trả BƯỚC (không chỉ đúng/sai) để `AuthStore.accept_totp_step` từ chối mã của bước đã dùng. So sánh hằng
    thời gian; luôn tính đủ 3 bước (không thoát sớm theo kết quả)."""
    code = otp.strip()
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(at.timestamp()) // TOTP_STEP_SECONDS
    matched: int | None = None
    for step in (now_step - 1, now_step, now_step + 1):
        if hmac.compare_digest(totp.generate_otp(step), code) and matched is None:
            matched = step
    return matched


def verify_totp(secret: str, otp: str, at: datetime) -> bool:
    """Chấp nhận mã của bước hiện tại ± 1 bước (30 giây) để bù lệch đồng hồ điện thoại. Không chống dùng lại — đăng nhập dùng
    `totp_step` + `AuthStore.accept_totp_step` (A4)."""
    return totp_step(secret, otp, at) is not None


@dataclass(frozen=True)
class Enrollment:
    username: str
    secret: str
    uri: str


@dataclass(frozen=True)
class AdSource:
    """Nguồn AD cho enroll trên DB mới (O2): `user_id` người vận hành khai (`--user-id`), AD đọc, `AdUserSync` ghi `users`."""

    user_id: str
    identity: IdentityProvider
    sync: AdUserSync
    now: datetime


async def _sync_from_ad(username: str, src: AdSource) -> UserRecord:
    try:
        ad = await src.identity.get_user(src.user_id)
        if ad is None:
            raise MfaError(f"{src.user_id} không có trong AD — kiểm lại mã người dùng")
        if ad.username != username:
            raise MfaError(f"mã AD {src.user_id} không thuộc tài khoản {username}")
        if ad.employment_status in INACTIVE_STATUSES:
            raise MfaError(f"{username} không còn hoạt động trong AD — không đăng ký MFA")
        user = await src.sync.sync_user_from_ad(src.identity.get_user, ad, src.now)
    except IdentityUnavailable:
        raise MfaError("AD không trả lời — chưa đồng bộ được, thử lại sau") from None
    if user is None:
        raise MfaError(f"nhóm AD của {username} không ánh xạ được role — không đồng bộ")
    return user


async def enroll(
    store: AuthStore, sink: SecurityEventSink, cipher: MfaCipher, *, username: str, by: str,
    reason: str, from_ad: AdSource | None = None,
) -> Enrollment:  # fmt: skip
    detail = _detail(by, reason)
    user = await store.get_user_by_username(username)
    if user is not None and from_ad is not None and user.user_id != from_ad.user_id:
        raise MfaError(f"--user-id {from_ad.user_id} không khớp dòng users của {username}")
    if user is None and from_ad is not None:
        user = await _sync_from_ad(username, from_ad)
    if user is None:
        raise MfaError(
            f"{username} chưa có trong bảng users — người đó đăng nhập một lần, "
            "hoặc chạy lại với --user-id <mã AD> để đồng bộ từ AD"
        )
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
    p.add_argument("--user-id", help="enroll: mã người dùng trong AD — chưa có dòng users (DB mới) thì đồng bộ từ AD trước")
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
    user_id = getattr(args, "user_id", None)
    if user_id is not None and args.command != "enroll":
        raise MfaError("--user-id chỉ dùng với enroll")
    if user_id is not None and settings.svc_agent_token is None:
        raise MfaError("SVC_AGENT_TOKEN chưa cấu hình — không đọc được AD để đồng bộ")
    clock = SystemClock()
    engines = create_engines(settings)
    try:
        store = SqlAuthStore(engines.main)
        sink = SecurityEventWriter(engines.main, clock)
        if args.command == "reset":
            return await reset(store, sink, cipher, username=args.username, by=args.by,
                               reason=args.reason, now=clock.now())  # fmt: skip
        if user_id is None:
            return await enroll(store, sink, cipher, username=args.username, by=args.by,
                                reason=args.reason)  # fmt: skip
        return await _enroll_from_ad(settings, clock, store, sink, cipher, args, user_id)
    finally:
        await engines.dispose()


async def _enroll_from_ad(
    settings: "Settings", clock: "Clock", store: AuthStore, sink: SecurityEventSink, cipher: MfaCipher,
    args: argparse.Namespace, user_id: str,
) -> Enrollment:  # fmt: skip
    """Dựng nguồn AD như `main.create_app` (đọc qua registry `ad_get_user`) + `AdUserSync` như B15 (`graph.wiring.approver_users`)."""
    from app.auth.service import auth_config, lock_policy
    from app.auth.username_hash import resolve_key
    from app.settings import get_policy
    from app.tools.adapters.ad_read import AdIdentityProvider
    from app.tools.specs import READ_TIMEOUT_S
    from app.tools.wiring import build_read_registry

    key = resolve_key(settings.jwt_signing_key, settings.username_hmac_key)
    if key is None:
        raise MfaError("thiếu JWT_SIGNING_KEY / USERNAME_HMAC_KEY — không đồng bộ được users từ AD")
    registry, http = build_read_registry(settings, clock)
    try:
        identity = AdIdentityProvider(http, registry, timeout=READ_TIMEOUT_S, unavailable=IdentityUnavailable)
        sync = AdUserSync(store=store, sink=sink, username_key=key,
                          lock=lock_policy(auth_config(settings, get_policy().constants)))  # fmt: skip
        src = AdSource(user_id=user_id, identity=identity, sync=sync, now=clock.now())
        return await enroll(store, sink, cipher, username=args.username, by=args.by, reason=args.reason,
                            from_ad=src)  # fmt: skip
    finally:
        await http.aclose()


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
