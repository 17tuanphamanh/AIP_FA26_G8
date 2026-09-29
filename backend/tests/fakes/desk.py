"""Bản giả cho test HTTP của route ticket / duyệt (2b-3).

- `harness_runtime(h)`: factory runtime cho `create_app(runtime=…)` dựng từ `GraphHarness` (InMemorySaver,
  store in-memory) — cùng graph, cùng node giả, cùng runner như test runtime.
- `StoreIdentity`: B1 đọc phiên (theo họ token) + `locked_until` từ CHÍNH `InMemoryAuthStore` mà route
  đăng nhập ghi — đăng nhập thật qua HTTP rồi tạo ticket là đi đúng đường B1.
- `MaskingGuard`: che `SECRET` → `[BÍ_MẬT_ĐÃ_ẨN]`, đếm số lần gọi (kiểm guard chạy SAU kiểm quyền).
- `desk_env`: app + client httpx async (ASGITransport) + lifespan chạy tay — test giữ được task nền
  bằng `asyncio.Event` (không `sleep`) và đợi hết task nền bằng `drain()`.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from app.api.background import BackgroundRuns
from app.core.clock import FakeClock
from app.db.identity import LiveSession
from app.db.session import Engines
from app.graph.ports import ToolCaller
from app.graph.wiring import Runtime
from app.guard.privacy import RedactionResult
from app.main import create_app
from app.settings import Settings
from fastapi import FastAPI
from tests.fakes.auth import (
    DEMO_PASSWORD,
    EPOCH,
    FakeAdUser,
    FakeIdentityProvider,
    InMemoryAuthStore,
    RecordingSink,
    seed_ad_users,
)
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, MemoryIdentity, ad_user
from tests.unit.auth_helpers import BASE_URL, auth_settings

# Chuỗi canary: không được xuất hiện ở bất kỳ đâu sau guard. Ghép lúc chạy — viết liền thì gitleaks
# (generic-api-key) coi là khoá thật và hook pre-commit chặn.
_CANARY_PARTS = ("SECRET", "7f3a9c")
SECRET = "-".join(_CANARY_PARTS)
MASK = "[BÍ_MẬT_ĐÃ_ẨN]"
APPROVER = "l1_01"  # ha.lt — người duyệt giả (FAKE_APPROVER_ID) trong test HTTP

type RuntimeFactory = Callable[
    [Settings, Engines, Any, ToolCaller | None], AbstractAsyncContextManager[Runtime]
]


def harness_runtime(h: GraphHarness) -> RuntimeFactory:
    @asynccontextmanager
    async def factory(*_: Any) -> AsyncIterator[Runtime]:
        yield Runtime(runner=h.runner, deadlines=h.deadlines, turns=h.turns, tickets=h.tickets,
                      approvals=h.approvals)  # fmt: skip

    return factory


class StoreIdentity(MemoryIdentity):
    def __init__(self, store: InMemoryAuthStore) -> None:
        super().__init__()
        self._store = store

    async def active_session(self, session_id: str, now: datetime) -> LiveSession | None:
        origin = self._store.sessions.get(session_id)
        if origin is None:
            return None
        alive = any(
            s.token_family_id == origin.token_family_id and s.revoked_at is None and s.expires_at > now
            for s in self._store.sessions.values()
        )
        return LiveSession(session_id, origin.user_id) if alive else None

    async def locked_until(self, user_id: str) -> datetime | None:
        user = self._store.users.get(user_id)
        return user.locked_until if user else None


class MaskingGuard:
    def __init__(self) -> None:
        self.calls = 0

    async def redact(self, text: str) -> RedactionResult:
        self.calls += 1
        found = text.count(SECRET)
        return RedactionResult(text=text.replace(SECRET, MASK), secrets_found=found,
                               pii_map_id=None, notices=[])  # fmt: skip


def ad_directory(users: list[FakeAdUser]) -> FakeAd:
    return FakeAd(*(
        ad_user(u.user_id, username=u.username, groups=tuple(u.groups), department=u.department,
                manager_id=u.manager_id, employment_status=u.employment_status, hired_at=u.hired_at)
        for u in users
    ))  # fmt: skip


@dataclass
class DeskEnv:
    app: FastAPI
    client: httpx.AsyncClient
    h: GraphHarness
    clock: FakeClock
    sink: RecordingSink
    store: InMemoryAuthStore
    guard: Any  # MaskingGuard (mặc định) hoặc guard thật `RegexPrivacyGuard` (3e)
    idp: FakeIdentityProvider
    settings: Settings

    @property
    def background(self) -> BackgroundRuns:
        return self.app.state.background  # type: ignore[no-any-return]

    async def drain(self) -> None:
        await self.background.drain()

    async def login(self, username: str, password: str = DEMO_PASSWORD) -> httpx.Response:
        return await self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    async def token(self, username: str) -> dict[str, str]:
        r = await self.login(username)
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def create(self, headers: dict[str, str], text: str = "VPN không vào được") -> str:
        r = await self.client.post("/api/tickets", json={"text": text}, headers=headers)
        assert r.status_code == 202, r.text
        return str(r.json()["ticket_id"])

    async def ticket(self, ticket_id: str, headers: dict[str, str]) -> dict[str, Any]:
        r = await self.client.get(f"/api/tickets/{ticket_id}", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]

    def denied(self) -> int:
        return len(self.sink.of("permission_denied"))

    def late(self, ticket_id: str) -> list[dict[str, Any]]:
        return self.h.audit.of(ticket_id, "late_event")

    def approval_of(self, ticket_id: str) -> str:
        [aid] = [a for a, row in self.h.approvals._table.items() if row["ticket_id"] == ticket_id]
        return aid


@asynccontextmanager
async def desk_env(
    *,
    plan: dict[str, str | list[str]] | None = None,
    lock_timeout: float = 5.0,
    guard: Any = None,
    runtime: RuntimeFactory | None = None,
    **settings_over: Any,
) -> AsyncIterator[DeskEnv]:
    """`plan`: kết quả node giả cho MỌI ticket tạo qua API (`FakeScenario.plan_all`)."""
    clock = FakeClock(EPOCH)
    sink = RecordingSink(clock)
    store = InMemoryAuthStore(sink)
    idp = FakeIdentityProvider()
    h = GraphHarness(clock=clock, identity=StoreIdentity(store), ad=ad_directory(seed_ad_users()),
                     approver_id=APPROVER, lock_timeout=lock_timeout)  # fmt: skip
    h.scenario.plan_all(**(plan or {}))
    guard = guard or MaskingGuard()
    settings = auth_settings(**settings_over)
    app = create_app(
        settings, health_checks={}, idp=idp, store=store, sink=sink, alerts=h.alerts,
        runtime=runtime or harness_runtime(h), guard=guard, clock=clock,
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 50000))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        yield DeskEnv(app, client, h, clock, sink, store, guard, idp, settings)
        await app.state.background.drain()


async def wait_for(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), 5)
