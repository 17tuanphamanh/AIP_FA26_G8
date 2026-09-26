"""Bản giả cho auth (P6): AD, sink `security_events`, AuthStore in-memory.

`InMemoryAuthStore` chạy chung bộ test hợp đồng với `SqlAuthStore` (`tests/unit/auth_store_contract.py`)
để không lệch bản thật. `RecordingSink` dùng cùng `check_event` với writer thật.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.audit.security_events import check_event
from app.auth.models import SessionRecord, UserRecord, UserSync
from app.auth.ports import IdentityUnavailable
from app.core.clock import Clock
from app.db.models import AUTH_FAILURE_TYPES
from tests.fakes.demo import DEMO_PASSWORD


@dataclass(frozen=True)
class FakeAdUser:
    user_id: str
    username: str
    groups: list[str]
    manager_id: str | None = None
    department: str = "it"
    full_name: str = "Người thử"
    employment_status: str = "active"
    hired_at: date = date(2024, 1, 1)
    is_privileged_account: bool = False


def seed_ad_users() -> list[FakeAdUser]:
    """Tập nhỏ theo mock_services/seed.json: đủ 4 role, disabled, terminated, chuỗi quản lý."""
    return [
        FakeAdUser("it_mgr01", "quan.tm", ["IT-Users", "IT-Manager"]),
        FakeAdUser("l1_01", "ha.lt", ["IT-Users", "IT-L1"], "it_mgr01"),
        FakeAdUser("l1_02", "duc.pv", ["IT-Users", "IT-L1"], "it_mgr01"),
        FakeAdUser("l2_01", "long.nh", ["IT-Users", "IT-L2"], "it_mgr01"),
        FakeAdUser("fin_head", "lan.dt", ["IT-Users"], department="finance"),
        FakeAdUser("nv001", "an.nv", ["IT-Users"], "fin_head", department="finance"),
        FakeAdUser("nv002", "binh.tt", ["IT-Users"], "fin_head", department="finance"),
        FakeAdUser("nv004", "dung.dv", ["IT-Users"], "fin_head", employment_status="disabled"),
        FakeAdUser("nv006", "em.lv", ["IT-Users"], "fin_head", employment_status="terminated"),
    ]


class FakeIdentityProvider:
    def __init__(self, users: list[FakeAdUser] | None = None, password: str = DEMO_PASSWORD) -> None:
        self.users = {u.user_id: u for u in (users if users is not None else seed_ad_users())}
        self.password = password
        self.down = False
        self.authenticate_calls = 0

    def by_username(self, username: str) -> FakeAdUser | None:
        return next((u for u in self.users.values() if u.username == username), None)

    def set(self, user: FakeAdUser) -> None:
        self.users[user.user_id] = user

    async def authenticate(self, username: str, password: str) -> FakeAdUser | None:
        self.authenticate_calls += 1
        if self.down:
            raise IdentityUnavailable("AD giả đang tắt")
        user = self.by_username(username)
        return user if user is not None and password == self.password else None

    async def get_user(self, user_id: str) -> FakeAdUser | None:
        if self.down:
            raise IdentityUnavailable("AD giả đang tắt")
        return self.users.get(user_id)


@dataclass
class RecordedEvent:
    event_type: str
    occurred_at: datetime
    user_id: str | None
    username_attempted: str | None
    ip_prefix: str | None
    route: str | None
    ticket_id: str | None
    detail: dict[str, Any] = field(default_factory=dict)


class RecordingSink:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.events: list[RecordedEvent] = []

    async def record(
        self,
        event_type: str,
        *,
        user_id: str | None = None,
        username_attempted: str | None = None,
        ip_prefix: str | None = None,
        route: str | None = None,
        ticket_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        payload = dict(detail or {})
        check_event(event_type, payload)
        event = RecordedEvent(
            event_type, self.clock.now(), user_id, username_attempted, ip_prefix, route, ticket_id,
            payload,
        )  # fmt: skip
        self.events.append(event)

    def of(self, event_type: str) -> list[RecordedEvent]:
        return [e for e in self.events if e.event_type == event_type]


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC) if value is not None else None


def _user_out(user: UserRecord | None) -> UserRecord | None:
    """Như SqlAuthStore: mọi datetime trả về có tzinfo đúng là timezone.utc."""
    return replace(user, locked_until=_utc(user.locked_until)) if user is not None else None


def _session_out(s: SessionRecord | None) -> SessionRecord | None:
    if s is None:
        return None
    return replace(s, created_at=s.created_at.astimezone(UTC), expires_at=s.expires_at.astimezone(UTC),
                   revoked_at=_utc(s.revoked_at))  # fmt: skip


class InMemoryAuthStore:
    def __init__(self, sink: RecordingSink) -> None:
        self.sink = sink  # đọc `auth_failures` từ sự kiện đã ghi
        self.users: dict[str, UserRecord] = {}
        self.sessions: dict[str, SessionRecord] = {}
        self.created_at: dict[str, datetime] = {}

    # ---- users ----
    async def get_user(self, user_id: str) -> UserRecord | None:
        return _user_out(self.users.get(user_id))

    async def get_user_by_username(self, username: str) -> UserRecord | None:
        return _user_out(next((u for u in self.users.values() if u.username == username), None))

    async def upsert_user(self, sync: UserSync) -> tuple[UserRecord, str | None]:
        if sync.manager_id is not None and sync.manager_id not in self.users:
            raise ValueError(f"FK users.manager_id: {sync.manager_id} chưa có")  # như Postgres
        old = self.users.get(sync.user_id)
        clash = await self.get_user_by_username(sync.username)
        if clash is not None and clash.user_id != sync.user_id:
            raise ValueError("UNIQUE users.username")
        attrs = {
            "username": sync.username, "full_name": sync.full_name, "role": sync.role,
            "department": sync.department, "manager_id": sync.manager_id,
            "employment_status": sync.employment_status, "hired_at": sync.hired_at,
            "is_privileged_account": sync.is_privileged_account,
        }  # fmt: skip
        user = replace(old, **attrs) if old else UserRecord(user_id=sync.user_id, **attrs)
        self.users[sync.user_id] = user
        out = _user_out(user)
        assert out is not None
        return out, old.role if old else None

    async def bump_token_version(self, user_id: str) -> int:
        user = self.users[user_id]
        self.users[user_id] = replace(user, token_version=user.token_version + 1)
        return user.token_version + 1

    async def set_locked_until(self, user_id: str, until: datetime) -> None:
        self.users[user_id] = replace(self.users[user_id], locked_until=until)

    async def set_mfa_secret(self, user_id: str, secret_enc: bytes) -> None:
        self.users[user_id] = replace(self.users[user_id], mfa_secret_enc=secret_enc)

    # ---- auth_failures ----
    async def count_failures(self, username: str, since: datetime) -> int:
        return sum(
            1 for e in self.sink.events
            if e.event_type in AUTH_FAILURE_TYPES and e.username_attempted == username
            and e.occurred_at > since
        )  # fmt: skip

    async def count_ip_failures(self, ip_prefix: str, since: datetime) -> int:
        return sum(
            1 for e in self.sink.events
            if e.event_type in AUTH_FAILURE_TYPES and e.ip_prefix == ip_prefix
            and e.occurred_at > since
        )  # fmt: skip

    # ---- sessions ----
    async def create_session(self, session: SessionRecord) -> None:
        if session.session_id in self.sessions:
            raise ValueError("PK sessions")
        if any(s.refresh_token_hash == session.refresh_token_hash for s in self.sessions.values()):
            raise ValueError("UNIQUE sessions.refresh_token_hash")
        if session.user_id not in self.users:
            raise ValueError("FK sessions.user_id")
        self.sessions[session.session_id] = session

    async def get_session(self, session_id: str) -> SessionRecord | None:
        return _session_out(self.sessions.get(session_id))

    async def get_session_by_refresh_hash(self, refresh_hash: str) -> SessionRecord | None:
        return _session_out(
            next((s for s in self.sessions.values() if s.refresh_token_hash == refresh_hash), None)
        )

    async def rotate_session(self, old_session_id: str, new: SessionRecord, now: datetime) -> bool:
        # Không có `await` giữa kiểm và ghi → nguyên tử trong một event loop, như UPDATE có điều kiện.
        old = self.sessions.get(old_session_id)
        if old is None or old.revoked_at is not None:
            return False
        self.sessions[old_session_id] = replace(old, revoked_at=now, revoke_reason="rotated")
        await self.create_session(new)
        return True

    def _revoke_where(self, match: Any, reason: str, now: datetime) -> int:
        n = 0
        for sid, s in list(self.sessions.items()):
            if s.revoked_at is None and match(s):
                self.sessions[sid] = replace(s, revoked_at=now, revoke_reason=reason)
                n += 1
        return n

    async def revoke_session(self, session_id: str, reason: str, now: datetime) -> None:
        self._revoke_where(lambda s: s.session_id == session_id, reason, now)

    async def revoke_family(self, family_id: UUID, reason: str, now: datetime) -> int:
        return self._revoke_where(lambda s: s.token_family_id == family_id, reason, now)

    async def revoke_user_sessions(self, user_id: str, reason: str, now: datetime) -> int:
        return self._revoke_where(lambda s: s.user_id == user_id, reason, now)

    async def login_started_at(self, session_id: str) -> datetime | None:
        s = self.sessions.get(session_id)
        if s is None:
            return None
        started = min(x.created_at for x in self.sessions.values() if x.token_family_id == s.token_family_id)
        return _utc(started)


# Mốc FakeClock của test auth. PHẢI nằm xa trong tương lai: cookie jar của httpx/TestClient bỏ cookie
# theo GIỜ THẬT, còn cookie refresh hết hạn ở EPOCH + 8 giờ. Mốc cũ (26/09/2026 08:00 UTC) làm 8 test
# refresh/CSRF đỏ từ 16:00 UTC cùng ngày — mọi phép kiểm của app (JWT, phiên, khoá) vẫn theo FakeClock.
EPOCH = datetime(2099, 9, 26, 8, 0, tzinfo=UTC)
