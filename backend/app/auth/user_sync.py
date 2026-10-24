"""Đồng bộ bảng `users` từ AD — MỘT định nghĩa cho đăng nhập (`AuthService`) và B15 (người duyệt chưa từng đăng nhập, Q-4-N).

Tách từ `AuthService` (Phase 4 chặng 4b P5, phase4 4.10 #11): chuỗi quản lý ≤ 5 cấp upsert trước (FK `users.manager_id`), rồi
upsert chính người đó; dòng VỪA tạo (role cũ None — kết quả `INSERT … ON CONFLICT DO NOTHING RETURNING`, Q-4a-6) → mang khoá
trượt của username ma sang `locked_until` (`_carry_ghost_lock`); role đổi → tăng `token_version` + thu hồi phiên + `role_changed`;
disabled/terminated → thu hồi phiên. Không tạo phiên, không phát token.

Mọi đường tạo dòng `users` trong mã chạy thật đi qua `_upsert` ở đây (`SqlAuthStore.upsert_user` là câu INSERT duy nhất) — B15
`ensure` người duyệt cũng vậy, nên người duyệt từng bị khoá trượt khi còn là username ma vẫn bị khoá khi dòng được tạo.
`on_sessions_revoked`: tiến trình có cache phiên (API — `AuthService._evict_user`) xoá cache ngay; tiến trình khác (worker) không có
cache, phiên đã thu hồi hết hiệu lực ≤ `REVOCATION_CACHE_SECONDS` ở API (P6 "thu hồi ≤ 30 s").

`AuthApproverUsers` (Phase 4 4b, TQ-3) — port `graph.fakes.ApproverUsers` của B15: bọc `AdUserSync` (không định nghĩa thứ hai).
Thiếu `JWT_SIGNING_KEY` (không dẫn xuất được khoá HMAC username ma) → `available=False` (Q-4b-5: B15 ra E2 trước `ensure`).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.auth.models import INACTIVE_STATUSES, UserRecord, UserSync
from app.auth.ports import AdUser, AuthStore, SecurityEventSink
from app.auth.username_hash import failure_keys
from app.domain.context import Role, role_from_groups

log = logging.getLogger(__name__)

MAX_MANAGER_DEPTH = 5

type GetUser = Callable[[str], Awaitable[AdUser | None]]


@dataclass(frozen=True)
class LockPolicy:
    """Tham số khoá do dò mật khẩu — cùng giá trị với `AuthConfig` (`MAX_AUTH_FAILURES`, cửa sổ, thời gian khoá)."""

    failure_window: timedelta
    max_failures: int
    lockout: timedelta


def _no_cache(user_id: str) -> None:
    """Tiến trình không giữ cache phiên (worker, B15) — không có gì để xoá."""


class AdUserSync:
    def __init__(
        self,
        *,
        store: AuthStore,
        sink: SecurityEventSink,
        username_key: bytes,
        lock: LockPolicy,
        on_sessions_revoked: Callable[[str], None] = _no_cache,
    ) -> None:
        self.store = store
        self.sink = sink
        self.lock = lock
        self._username_key = username_key
        self._on_sessions_revoked = on_sessions_revoked

    async def sync_user_from_ad(self, get_user: GetUser, ad: AdUser, now: datetime) -> UserRecord | None:
        """Upsert `ad` (+ chuỗi quản lý qua `get_user`). Nhóm AD không ánh xạ được role → None, không ghi gì. Lỗi của
        `get_user` lan ra (đăng nhập → 503; B15 → E2)."""
        role = role_from_groups(ad.groups)
        if role is None:
            return None
        manager_id = (
            await self._ensure_manager(get_user, ad.manager_id, depth=1, seen={ad.user_id}, now=now)
            if ad.manager_id
            else None
        )
        return await self._upsert(ad, role, manager_id, now)

    async def _ensure_manager(
        self, get_user: GetUser, user_id: str, *, depth: int, seen: set[str], now: datetime
    ) -> str | None:
        """Upsert người quản lý trước (FK `users.manager_id`), sâu tối đa 5 cấp, chặn vòng.
        Không tìm thấy / không ánh xạ được role / quá sâu / vòng → NULL = "không biết" (không phải
        "không có sếp") — Phase 3–4 không được cho NULL khớp luật allow."""
        if depth > MAX_MANAGER_DEPTH or user_id in seen:
            log.warning("chuỗi quản lý dừng ở %s (vòng hoặc quá %d cấp)", user_id, MAX_MANAGER_DEPTH)
            return None
        ad = await get_user(user_id)
        if ad is None:
            log.warning("người quản lý %s không có trong AD — manager_id = NULL", user_id)
            return None
        role = role_from_groups(ad.groups)
        if role is None:
            log.warning("người quản lý %s không ánh xạ được role — manager_id = NULL", user_id)
            return None
        boss = (
            await self._ensure_manager(get_user, ad.manager_id, depth=depth + 1, seen=seen | {user_id}, now=now)
            if ad.manager_id
            else None
        )
        await self._upsert(ad, role, boss, now)
        return user_id

    async def _upsert(self, ad: AdUser, role: Role, manager_id: str | None, now: datetime) -> UserRecord:
        user, previous_role = await self.store.upsert_user(
            UserSync(
                user_id=ad.user_id,
                username=ad.username,
                full_name=ad.full_name,
                role=role,
                department=ad.department,
                manager_id=manager_id,
                employment_status=ad.employment_status,
                hired_at=ad.hired_at,
                is_privileged_account=ad.is_privileged_account,
                synced_at=now,
                email=getattr(ad, "email", None),  # notify-email: trường tuỳ chọn của AD (Protocol `AdUser` không bắt buộc)
            )
        )
        if previous_role is None:  # dòng VỪA tạo bởi chính lời gọi này (kết quả INSERT … ON CONFLICT — AuthStore.upsert_user)
            user = await self._carry_ghost_lock(user, now)
        if previous_role is not None and previous_role != user.role:
            # Role đổi trong AD → access token mang role cũ phải chết [Suy luận, đã duyệt].
            version = await self.store.bump_token_version(user.user_id)
            await self.store.revoke_user_sessions(user.user_id, "admin", now)
            self._on_sessions_revoked(user.user_id)
            await self.sink.record(
                "role_changed", user_id=user.user_id,
                detail={"from": previous_role, "to": user.role},
            )  # fmt: skip
            user = replace(user, token_version=version)
        if user.employment_status in INACTIVE_STATUSES:
            await self.store.revoke_user_sessions(user.user_id, "user_disabled", now)
            self._on_sessions_revoked(user.user_id)
        return user

    async def _carry_ghost_lock(self, user: UserRecord, now: datetime) -> UserRecord:
        """Q-4a-6: dòng `users` VỪA tạo cho username từng là "ma". Lần sai trong cửa sổ đếm như `_is_locked`/`_check_threshold`
        (`failure_keys` = nguyên văn + băm; cùng ngưỡng, cùng cửa sổ) đủ ngưỡng → `locked_until` = lần sai CUỐI + thời gian khoá
        — như thể dòng đã có từ lần sai đó (khoá của người có dòng tính từ lần sai chạm ngưỡng), không tính từ lúc tạo dòng.
        Chỉ chạy lúc tạo dòng (mỗi người một lần) — lượt của người đã có dòng không thêm truy vấn. `account_locked` + cảnh báo đã
        ghi lúc khoá trượt → không ghi lại."""
        since = now - self.lock.failure_window
        keys = failure_keys(user.username, known=True, key=self._username_key)
        failures = await self.store.count_failures(keys, since)
        if failures >= self.lock.max_failures:
            last = await self.store.last_failure_at(keys, since)
            # `last` None không xảy ra (đã đếm ≥ 1 dòng, bảng append-only) — nếu có: khoá từ now (fail-closed, không bỏ khoá)
            until = (last or now) + self.lock.lockout
            await self.store.set_locked_until(user.user_id, until)
            return replace(user, locked_until=until)
        return user


class AuthApproverUsers:
    """B15 `ensure` người duyệt/dự phòng (Q-4-N): cùng `AdUserSync.sync_user_from_ad` với đăng nhập — chuỗi quản lý qua `lookup`
    (hàm tra CÓ CACHE của node, registry bước `B15_APPROVER`), mang khoá trượt khi dòng vừa tạo. Không tạo phiên, không phát
    token; `token_version` chỉ đổi khi role đổi (như đăng nhập). `sync=None` = thiếu khoá HMAC → `available=False`."""

    def __init__(self, sync: AdUserSync | None) -> None:
        self._sync = sync

    @property
    def available(self) -> bool:
        return self._sync is not None

    async def ensure(self, ad_user: AdUser, lookup: GetUser, *, now: datetime) -> None:
        if self._sync is None:  # B15 kiểm `available` TRƯỚC (Q-4b-5) — tới đây là bug → E9
            raise RuntimeError("AuthApproverUsers.ensure khi thiếu khoá HMAC username ma")
        if await self._sync.sync_user_from_ad(lookup, ad_user, now) is None:  # B15 chỉ ensure người đã `valid` (ra role)
            raise RuntimeError(f"AuthApproverUsers.ensure: nhóm AD của {ad_user.user_id} không ra role")
