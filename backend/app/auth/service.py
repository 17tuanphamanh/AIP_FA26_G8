"""Nghiệp vụ xác thực (P6 mục 4) — không biết HTTP hay SQL; route ở `api/auth.py`.

Đăng nhập 8 bước:
 1 giới hạn theo dải IP (lượt thất bại)                → 429
 2 username đang khoá                                   → 401 chung + account_locked(still_locked)
 3 idp.authenticate: sai → login_failed; đủ ngưỡng → khoá + account_locked(threshold) + 1 dòng
                    `alerts` (P9 luật 3, idempotent theo người + đợt khoá) → 401 chung
                    AD lỗi → 503 (không đếm)
 4 đồng bộ users (role từ nhóm AD, chuỗi quản lý ≤ 5 cấp) — role đổi → role_changed + phiên cũ chết
 5 disabled/terminated                                  → 401 chung (mọi phiên bị thu hồi)
 6 cần MFA? (manager, hoặc đã enroll): thiếu OTP → 401 mfa_required; sai → mfa_failed;
   manager chưa enroll → mfa_failed(not_enrolled) → 401 (fail-closed)
 7 tạo phiên (refresh hash, họ token), phát access + refresh + csrf
 8 login_success

Khoá theo username [Suy luận, đã duyệt]: user có dòng `users` → `locked_until` (15 phút). Username
chưa có dòng (không tồn tại, hoặc người AD chưa đăng nhập lần nào) → không có chỗ đặt khoá, coi
"≥ MAX_AUTH_FAILURES lỗi trong cửa sổ" là đang khoá (cửa sổ trượt). Hai trường hợp trả phản hồi
GIỐNG HỆT nhau — không dò được username nào tồn tại.

Username ma (Phase 4 P2–P3, Q-3e-14 + Q-4-S): username KHÔNG có dòng `users` (tra một lần ở bước 2 — `existing`) được lưu
`stored_username(…, known=False)` = `"h:" + HMAC` ở MỌI chỗ ghi `username_attempted` và trong cảnh báo dò mật khẩu; đếm/khoá
(`count_failures`) dùng CÙNG giá trị. Khoá HMAC tính một lần ở `__init__` từ signer — không thêm truy vấn, không thêm nhánh
chỉ riêng username ma (thời gian phản hồi giữ như 3e).
Chuyển tiếp (Q-4a-5): username ma có dòng `users` giữa cửa sổ (chính người đó đăng nhập, hoặc `_ensure_manager` khi cấp dưới
đăng nhập) → đếm `IN (nguyên văn, bản băm)` trong CÙNG một câu SQL (`_failure_keys`) — các lần sai lưu băm trước đó không mất.
Q-4a-6: username ma ĐÃ khoá theo cửa sổ trượt rồi mới có dòng → `_upsert` khi dòng VỪA tạo mang khoá sang `locked_until`
(`_carry_ghost_lock`) — lần kế tiếp bị chặn ở bước 2, không tới AD. Phase 4 4b P5: bước 4 (`_ensure_manager`, `_upsert`,
`_carry_ghost_lock`) nằm ở `auth/user_sync.AdUserSync` — dùng chung với B15 (người duyệt chưa đăng nhập).
"""

import ipaddress
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.auth.mfa import MfaCipher, MfaError, verify_totp
from app.auth.models import (
    IssuedTokens,
    Principal,
    SessionRecord,
    UserRecord,
)
from app.auth.permissions import permissions_of
from app.auth.ports import (
    AdUser,
    AlertSink,
    AuthStore,
    IdentityProvider,
    IdentityUnavailable,
    SecurityEventSink,
)
from app.auth.tokens import (
    TokenError,
    TokenSigner,
    hash_refresh_token,
    hash_user_agent,
    new_csrf_token,
    new_refresh_token,
)
from app.auth.user_sync import AdUserSync, LockPolicy
from app.auth.username_hash import failure_keys, stored_username
from app.core.clock import Clock
from app.domain.alerts import bruteforce_alert
from app.settings import PolicyConstants, Settings

log = logging.getLogger(__name__)

GENERIC_LOGIN_ERROR = "Tên đăng nhập hoặc mật khẩu không đúng"  # P6 mục 4: luôn cùng một câu
LOGIN_ROUTE = "/api/auth/login"


class AuthError(Exception):
    """Lỗi trả cho client: `status` + `detail` an toàn (không lộ lý do nội bộ)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _invalid_login() -> AuthError:
    return AuthError(401, GENERIC_LOGIN_ERROR)


def _unauthorized() -> AuthError:
    return AuthError(401, "unauthorized")


@dataclass(frozen=True)
class AuthConfig:
    access_ttl: timedelta
    refresh_ttl: timedelta
    lockout: timedelta
    max_failures: int
    failure_window: timedelta
    ip_failure_limit: int
    ip_failure_window: timedelta
    reauth_window: timedelta
    cache_ttl: timedelta


@dataclass(frozen=True)
class LoginResult:
    tokens: IssuedTokens
    user: UserRecord


@dataclass(frozen=True)
class _Cached:
    session: SessionRecord
    user: UserRecord
    fetched_at: datetime


def ip_prefix(host: str | None) -> str | None:
    """Che phần host của IP: IPv4 /24, IPv6 /48 (P7 2.2)."""
    if not host:
        return None
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None
    bits = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{bits}", strict=False))


class AuthService:
    def __init__(
        self,
        *,
        store: AuthStore,
        idp: IdentityProvider,
        sink: SecurityEventSink,
        alerts: AlertSink,
        clock: Clock,
        signer: TokenSigner,
        cipher: MfaCipher | None,
        config: AuthConfig,
    ) -> None:
        self.store = store
        self.idp = idp
        self.sink = sink
        self.alerts = alerts
        self.clock = clock
        self.signer = signer
        self.cipher = cipher
        self.config = config
        self._cache: dict[str, _Cached] = {}
        self._username_key = signer.username_key()  # P2: một lần lúc dựng service; không log, không vào Settings
        self._sync = AdUserSync(
            store=store, sink=sink, username_key=self._username_key,
            lock=LockPolicy(config.failure_window, config.max_failures, config.lockout),
            on_sessions_revoked=self._evict_user,
        )  # fmt: skip

    def _stored(self, username: str, user: UserRecord | None) -> str:
        """Giá trị lưu/đếm của username: có dòng `users` → nguyên văn; không → `"h:" + HMAC` (P2–P3)."""
        return stored_username(username, known=user is not None, key=self._username_key)

    def _failure_keys(self, username: str, user: UserRecord | None) -> tuple[str, ...]:
        """Giá trị đếm lỗi (view `auth_failures`, MỘT câu `IN`): username ma → (bản băm,); có dòng `users` → (nguyên văn,
        bản băm) — lần sai ghi lúc CHƯA có dòng vẫn được đếm sau khi dòng được tạo (Q-4a-5)."""
        return failure_keys(username, known=user is not None, key=self._username_key)

    # ---- đăng nhập -------------------------------------------------------------------------

    async def login(
        self, username: str, password: str, otp: str | None, *, ip: str | None,
        user_agent: str | None = None,
    ) -> LoginResult:  # fmt: skip
        now = self.clock.now()
        cfg = self.config
        # 1. giới hạn theo dải IP
        if ip is not None:
            ip_failures = await self.store.count_ip_failures(ip, now - cfg.ip_failure_window)
            if ip_failures >= cfg.ip_failure_limit:
                raise AuthError(429, "too_many_attempts")

        # 2. đang khoá?
        existing = await self.store.get_user_by_username(username)
        if await self._is_locked(username, existing, now):
            await self._event("account_locked", existing, username, ip, reason="still_locked")
            raise _invalid_login()

        # 3. hỏi AD
        try:
            ad = await self.idp.authenticate(username, password)
        except IdentityUnavailable:
            log.warning("đăng nhập: AD không trả lời — 503, không đếm lần sai")
            raise AuthError(503, "identity_unavailable") from None
        if ad is None:
            await self._event("login_failed", existing, username, ip)
            await self._check_threshold(username, existing, ip, now)
            raise _invalid_login()

        # 4. đồng bộ users
        try:
            user = await self._sync_login_user(ad, now)
        except IdentityUnavailable:
            raise AuthError(503, "identity_unavailable") from None
        if user is None:  # nhóm AD không ánh xạ được role → fail-closed
            await self.sink.record(
                "permission_denied", username_attempted=self._stored(username, existing), ip_prefix=ip,
                route=LOGIN_ROUTE, detail={"reason": "role_unmappable"},
            )  # fmt: skip
            raise _invalid_login()

        # 5. tài khoản bị vô hiệu hoá / nghỉ việc
        if not user.active:  # _upsert đã thu hồi mọi phiên của người này
            await self._event("login_failed", user, username, ip, reason="account_inactive")
            raise _invalid_login()

        # 6. MFA
        await self._check_mfa(user, otp, username, ip, now)

        # 7. phiên mới + token
        session = SessionRecord(
            session_id=uuid4().hex,
            user_id=user.user_id,
            token_family_id=uuid4(),
            refresh_token_hash="",  # đặt trong _issue
            created_at=now,
            expires_at=now + cfg.refresh_ttl,
            ip_prefix=ip,
            user_agent_hash=hash_user_agent(user_agent),
        )
        session, tokens = self._issue(session, user)
        await self.store.create_session(session)

        # 8.
        await self.sink.record(  # `user` vừa đồng bộ ở bước 4 → có dòng `users` → nguyên văn
            "login_success", user_id=user.user_id, username_attempted=self._stored(username, user), ip_prefix=ip
        )
        return LoginResult(tokens, user)

    async def _is_locked(self, username: str, user: UserRecord | None, now: datetime) -> bool:
        if user is not None:
            return user.locked_until is not None and user.locked_until > now
        since = now - self.config.failure_window
        return await self.store.count_failures(self._failure_keys(username, user), since) >= self.config.max_failures

    async def _check_threshold(
        self, username: str, user: UserRecord | None, ip: str | None, now: datetime
    ) -> None:
        """Sau mỗi lần thất bại: đủ MAX_AUTH_FAILURES trong cửa sổ → khoá + account_locked + cảnh báo
        Trưởng BP (P9 luật 3; khoá cảnh báo tính giống B1 — `domain.alerts.bruteforce_alert`)."""
        failures = await self.store.count_failures(
            self._failure_keys(username, user), now - self.config.failure_window
        )
        if failures < self.config.max_failures:
            return
        if user is not None:
            await self.store.set_locked_until(user.user_id, now + self.config.lockout)
        await self._event("account_locked", user, username, ip, reason="threshold",
                          failures=failures)  # fmt: skip
        await self.alerts.raise_once(
            bruteforce_alert(user_id=user.user_id if user else None, username=self._stored(username, user),
                             lock_start=now, source="login")
        )  # fmt: skip

    async def _event(
        self, event_type: str, user: UserRecord | None, username: str, ip: str | None,
        **detail: Any,
    ) -> None:  # fmt: skip
        await self.sink.record(
            event_type,
            user_id=user.user_id if user else None,
            username_attempted=self._stored(username, user),
            ip_prefix=ip,
            detail=detail,
        )

    async def _check_mfa(
        self, user: UserRecord, otp: str | None, username: str, ip: str | None, now: datetime
    ) -> None:
        required = user.role == "manager" or user.mfa_secret_enc is not None
        if not required:
            return
        if user.mfa_secret_enc is None:  # manager chưa enroll → fail-closed
            await self._event("mfa_failed", user, username, ip, reason="not_enrolled")
            await self._check_threshold(username, user, ip, now)
            raise AuthError(401, "mfa_not_enrolled")
        if self.cipher is None:
            log.error("MFA_ENC_KEY chưa cấu hình — không kiểm được OTP")
            raise AuthError(503, "mfa_unavailable")
        if not otp:  # bước 1 của form 2 bước: chưa phải lần thử sai
            raise AuthError(401, "mfa_required")
        try:
            secret = self.cipher.decrypt(user.user_id, user.mfa_secret_enc)
        except MfaError:
            log.error("không giải mã được secret MFA của %s", user.user_id)
            raise AuthError(503, "mfa_unavailable") from None
        if not verify_totp(secret, otp, now):
            await self._event("mfa_failed", user, username, ip, reason="invalid_otp")
            await self._check_threshold(username, user, ip, now)
            raise _invalid_login()

    # ---- đồng bộ users ---------------------------------------------------------------------

    async def _sync_login_user(self, ad: AdUser, now: datetime) -> UserRecord | None:
        """Bước 4: `AdUserSync` (Phase 4 4b P5 — MỘT định nghĩa `_upsert`/`_carry_ghost_lock` với B15)."""
        return await self._sync.sync_user_from_ad(self.idp.get_user, ad, now)

    # ---- phiên ------------------------------------------------------------------------------

    def _issue(self, session: SessionRecord, user: UserRecord) -> tuple[SessionRecord, IssuedTokens]:
        refresh = new_refresh_token()
        session = replace(session, refresh_token_hash=hash_refresh_token(refresh))
        access = self.signer.issue(
            user_id=user.user_id, role=user.role, session_id=session.session_id,
            token_version=user.token_version,
        )  # fmt: skip
        return session, IssuedTokens(
            access_token=access,
            refresh_token=refresh,
            csrf_token=new_csrf_token(),
            expires_in=self.signer.ttl_seconds,
            refresh_expires_at=session.expires_at,
        )

    async def refresh(self, refresh_token: str, *, ip: str | None) -> LoginResult:
        """Xoay vòng (P6 mục 4). Token đã xoay bị trình lại → thu hồi cả họ + refresh_reuse_detected.
        Hai request đồng thời cùng token (2 tab): request thứ hai bị coi là reuse — hành vi đã biết,
        frontend xử lý ở Phase 7."""
        now = self.clock.now()
        old = await self.store.get_session_by_refresh_hash(hash_refresh_token(refresh_token))
        if old is None:
            raise _unauthorized()
        if old.revoked_at is not None:
            if old.revoke_reason == "rotated":
                await self._reuse_detected(old, ip, now)
            raise _unauthorized()
        if now >= old.expires_at:
            await self.store.revoke_session(old.session_id, "expired", now)
            raise _unauthorized()
        user = await self.store.get_user(old.user_id)
        if user is None or not user.active:
            await self.store.revoke_user_sessions(old.user_id, "user_disabled", now)
            self._evict_user(old.user_id)
            raise _unauthorized()
        new = SessionRecord(
            session_id=uuid4().hex,
            user_id=user.user_id,
            token_family_id=old.token_family_id,
            refresh_token_hash="",
            created_at=now,
            expires_at=old.expires_at,  # hạn tuyệt đối từ lúc đăng nhập, không trượt
            ip_prefix=ip,
            user_agent_hash=old.user_agent_hash,
        )
        new, tokens = self._issue(new, user)
        if not await self.store.rotate_session(old.session_id, new, now):
            await self._reuse_detected(old, ip, now)  # request khác vừa xoay token này
            raise _unauthorized()
        self._cache.pop(old.session_id, None)
        await self.sink.record("token_refreshed", user_id=user.user_id, ip_prefix=ip)
        return LoginResult(tokens, user)

    async def _reuse_detected(self, session: SessionRecord, ip: str | None, now: datetime) -> None:
        revoked = await self.store.revoke_family(session.token_family_id, "reuse_detected", now)
        self._evict_user(session.user_id)
        await self.sink.record(
            "refresh_reuse_detected", user_id=session.user_id, ip_prefix=ip,
            detail={"revoked_sessions": revoked},
        )  # fmt: skip

    async def logout(self, principal: Principal) -> None:
        now = self.clock.now()
        await self.store.revoke_session(principal.session_id, "logout", now)
        self._cache.pop(principal.session_id, None)
        await self.sink.record("logout", user_id=principal.user_id, detail={"scope": "session"})

    async def logout_all(self, principal: Principal) -> None:
        now = self.clock.now()
        await self.store.bump_token_version(principal.user_id)
        await self.store.revoke_user_sessions(principal.user_id, "logout", now)
        self._evict_user(principal.user_id)
        await self.sink.record("logout", user_id=principal.user_id, detail={"scope": "all"})

    async def revoke_user(self, admin: Principal, user_id: str) -> bool:
        """Thu hồi mọi phiên của một người (P6 mục 8). False = không có user này."""
        if await self.store.get_user(user_id) is None:
            return False
        now = self.clock.now()
        await self.store.bump_token_version(user_id)
        revoked = await self.store.revoke_user_sessions(user_id, "admin", now)
        self._evict_user(user_id)
        await self.sink.record(
            "session_revoked", user_id=user_id,
            detail={"by": admin.user_id, "revoked_sessions": revoked},
        )  # fmt: skip
        return True

    async def recently_logged_in(self, principal: Principal) -> bool:
        """Xác nhận lại (P6 mục 4): đăng nhập (min created_at của họ token) trong 10 phút gần nhất."""
        started = await self.store.login_started_at(principal.session_id)
        return started is not None and self.clock.now() - started <= self.config.reauth_window

    # ---- kiểm access token mỗi request -----------------------------------------------------

    async def validate_access(self, token: str) -> Principal:
        """Tầng 1: chữ ký + hạn (clock), phiên chưa thu hồi, `tv` và role khớp `users`, tài khoản
        không disabled/terminated. Tra DB được cache theo phiên ≤ 30 giây (P6: thu hồi ≤ 30 giây)."""
        try:
            claims = self.signer.verify(token)
        except TokenError:
            raise _unauthorized() from None
        now = self.clock.now()
        entry = self._cache.get(claims.sid)
        if entry is None or now - entry.fetched_at >= self.config.cache_ttl:
            session = await self.store.get_session(claims.sid)
            user = await self.store.get_user(claims.sub) if session is not None else None
            if session is None or user is None:
                self._cache.pop(claims.sid, None)
                raise _unauthorized()
            entry = _Cached(session, user, now)
            self._cache[claims.sid] = entry
        session, user = entry.session, entry.user
        if (
            not session.usable(now)
            or session.user_id != claims.sub
            or user.token_version != claims.tv
            or user.role != claims.role
            or not user.active
        ):
            raise _unauthorized()
        return Principal(
            user_id=user.user_id,
            role=user.role,
            session_id=session.session_id,
            token_version=user.token_version,
            permissions=permissions_of(user.role),
        )

    def _evict_user(self, user_id: str) -> None:
        for sid in [sid for sid, e in self._cache.items() if e.user.user_id == user_id]:
            del self._cache[sid]


def auth_config(settings: Settings, policy_constants: PolicyConstants) -> AuthConfig:
    """Gom tham số: TTL/khoá/IP/re-auth/cache từ env (`Settings`); MAX_AUTH_FAILURES + cửa sổ từ
    `config/policy.json` [Chốt] — một nguồn cho mỗi hằng số."""
    return AuthConfig(
        access_ttl=timedelta(minutes=settings.access_ttl_minutes),
        refresh_ttl=timedelta(hours=settings.refresh_ttl_hours),
        lockout=timedelta(minutes=settings.lockout_minutes),
        max_failures=policy_constants.MAX_AUTH_FAILURES,
        failure_window=timedelta(minutes=policy_constants.AUTH_FAILURE_WINDOW_MINUTES),
        ip_failure_limit=settings.ip_failure_limit,
        ip_failure_window=timedelta(minutes=settings.ip_failure_window_minutes),
        reauth_window=timedelta(minutes=settings.reauth_minutes),
        cache_ttl=timedelta(seconds=settings.revocation_cache_seconds),
    )

