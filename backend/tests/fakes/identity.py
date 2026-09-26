"""Bản giả cho B1 (phụ thuộc `identity`, `directory`, `alerts` của `NodeDeps`).

- `FakeAd` là **handler HTTP giả** của `ad_get_user`, gắn vào `ToolRegistry` THẬT (`fake_directory`)
  — B1 đi đúng đường retry + breaker + validate schema như khi gọi mock AD.
- `MemoryIdentity`: `sessions` theo họ token (giống `db/identity.SqlIdentityReads`) + `locked_until`.
- `MemoryAlerts`: cùng khoá chống trùng `(rule_id, subject, window_start)` như `audit/alerts.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
from app.audit.alerts import check_alert
from app.core.clock import Clock
from app.db.identity import LiveSession
from app.domain.alerts import AlertDraft
from app.tools.breaker import BreakerBoard
from app.tools.models import UserIn
from app.tools.registry import ToolRegistry

REQUESTER = "nv-fake"
SESSION = "s1"


def ad_user(
    user_id: str = REQUESTER,
    *,
    username: str | None = None,
    groups: tuple[str, ...] = ("IT-Users",),
    department: str = "finance",
    manager_id: str | None = "fin_head",
    employment_status: str = "active",
    hired_at: date = date(2024, 1, 1),
) -> dict[str, Any]:
    """JSON người dùng như mock AD trả (`GET /ad/users/{id}`)."""
    return {
        "user_id": user_id, "username": username or f"{user_id}.user", "full_name": user_id,
        "title": "NV", "department": department, "groups": list(groups), "manager_id": manager_id,
        "employment_status": employment_status, "hired_at": hired_at.isoformat(),
        "is_privileged_account": False,
        "account": {"account_type": "ad", "enabled": employment_status not in ("disabled", "terminated"),
                    "locked": False, "lock_reason": None,
                    "password_last_set": "2026-01-01T00:00:00Z"},
    }  # fmt: skip


def _status(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://mock.test/ad/users/x")
    return httpx.HTTPStatusError(str(code), request=request, response=httpx.Response(code, request=request))


class FakeAd:
    """`down=True` → mọi lần gọi timeout (hết retry → B1 E2). Không có user → 404. `crash` → ném đúng
    exception đó (BaseException như `Crash` = process bị giết giữa B1, boundary không bắt)."""

    def __init__(self, *users: Mapping[str, Any]) -> None:
        self.users: dict[str, dict[str, Any]] = {u["user_id"]: dict(u) for u in users}
        self.down = False
        self.crash: BaseException | None = None  # process "chết" giữa lời gọi AD (không phải lỗi AD)
        self.calls = 0

    async def ad_get_user(self, inp: UserIn, timeout: float) -> object:
        self.calls += 1
        if self.crash is not None:
            raise self.crash
        if self.down:
            raise httpx.ConnectTimeout("AD không trả lời")
        user = self.users.get(inp.user_id)
        if user is None:
            raise _status(404)
        return user


def fake_directory(ad: FakeAd, clock: Clock) -> ToolRegistry:
    breakers = BreakerBoard(clock, failure_threshold=5, window_seconds=60, open_seconds=30)
    return ToolRegistry({"ad_get_user": ad.ad_get_user}, breakers=breakers, clock=clock)


@dataclass
class _Session:
    user_id: str
    family: str
    expires_at: datetime
    revoked: bool = False


class MemoryIdentity:
    def __init__(self) -> None:
        self.sessions: dict[str, _Session] = {}
        self.locked: dict[str, datetime] = {}
        self.fail: Exception | None = None  # lỗi chưa lường trước (→ E9 qua boundary)

    def add_session(
        self, session_id: str, user_id: str, *, expires_at: datetime, family: str | None = None
    ) -> None:
        self.sessions[session_id] = _Session(user_id, family or session_id, expires_at)

    async def active_session(self, session_id: str, now: datetime) -> LiveSession | None:
        if self.fail is not None:
            raise self.fail
        origin = self.sessions.get(session_id)
        if origin is None:
            return None
        alive = any(
            s.family == origin.family and not s.revoked and s.expires_at > now
            for s in self.sessions.values()
        )
        return LiveSession(session_id, origin.user_id) if alive else None

    async def locked_until(self, user_id: str) -> datetime | None:
        return self.locked.get(user_id)


class MemoryAlerts:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, datetime], AlertDraft] = {}

    async def raise_once(self, draft: AlertDraft) -> bool:
        check_alert(draft)
        key = (draft.rule_id, draft.subject, draft.window_start)
        if key in self.rows:
            return False
        self.rows[key] = draft
        return True

    def of(self, rule_id: str) -> list[AlertDraft]:
        return [a for a in self.rows.values() if a.rule_id == rule_id]
