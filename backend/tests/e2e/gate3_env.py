"""Môi trường e2e cổng 3 (phase3 mục 11.5; PLAN-3h S14) — dùng chung bởi `test_gate3_vpn.py`.

Chạy THẬT: `create_app` (auth qua AD của mock, guard regex mặc định, route ticket/duyệt), runtime ghép bằng CHÍNH
`graph.wiring._open` (store SQL, `AsyncPostgresSaver`, `PgTicketLock`, node thật), registry đọc (svc_agent) + registry GHI
(svc_executor) + `PlanExecutor` tới mock THẬT (subprocess, `seed.json`), `Retriever` thật trên Qdrant (testcontainer) với KB
fixture ingest thật, worker = runtime thứ hai `can_execute=False` + `WorkerJobs`. Giả: `FakeMlService` (ml-service),
ScriptedLLM (`vpn_scripts`) sau gateway thật (`SqlLlmStore` → `llm_calls`), FakeClock.

`open_runtime` không dùng được nguyên khối (tự dựng `MlClient` HTTP + LLM theo preset tĩnh) — `_open` là phần sau các bước
kiểm khởi động; phần trước (`check_*`) đã có test riêng. Đếm lời gọi ghi ở NƠI NHẬN: `GET /_admin/calls` của mock (3.9).

Crash (h15/h15b): `CrashAfterWrite` bọc registry ghi — lời gọi cấp chứng chỉ ĐÃ tới mock rồi process "chết" (`Crash` là
`BaseException`, xuyên qua boundary E9) TRƯỚC checkpoint của B17; dòng `begun` đã commit riêng.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from app.core.clock import Clock, FakeClock
from app.db.session import Engines, create_engines
from app.executor.plan_executor import PlanExecutor
from app.executor.txlog import SqlTxLog
from app.executor.wiring import build_write_registry
from app.graph.fakes import FakeScenario, RefusingExecutor
from app.graph.ports import ToolCaller
from app.graph.tracing import trace_parent
from app.graph.wiring import Runtime, _open, fake_approver
from app.graph.worker_jobs import WorkerJobs
from app.llm.providers.scripted import Script
from app.llm.store import SqlLlmStore
from app.main import create_app
from app.rag.bm25 import load_lexicon
from app.rag.ingest.config import ALIAS
from app.rag.ingest.kbversion import pipeline_sha
from app.rag.retriever import RagConfig, Retriever
from app.rag.vector_store import QdrantIndex
from app.settings import Settings, get_policy
from app.tools.registry import ToolResult
from app.tools.wiring import build_read_registry
from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.e2e.mock_server import MockServer
from tests.fakes.demo import DEMO_PASSWORD
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import Crash
from tests.fakes.kb import copy_kb
from tests.fakes.llm import Gateway, make_gateway
from tests.integration.pg import PgUrls
from tests.integration.test_rag_ingest_pg import _env
from tests.unit.auth_helpers import BASE_URL, auth_settings

APPROVER = "ha.lt"  # l1_01 = FAKE_APPROVER_ID — đăng nhập TRƯỚC khi ticket tới B15 (dòng users, 2b-3-Q4)
ISSUE_TOOLS = frozenset({"renew_vpn_cert", "reissue_vpn_access"})
WRITES = "/vpn/"  # mọi endpoint ghi VPN là POST dưới /vpn/ (đọc là GET)


def at_ict(hour: int, minute: int = 0) -> FakeClock:
    """Thứ Tư 30/09/2026, giờ Việt Nam (UTC+7) — `hour=10` trong giờ hành chính, `hour=20` ngoài giờ (R18)."""
    return FakeClock(datetime(2026, 9, 30, hour - 7, minute, tzinfo=UTC))


def ingest_kb(pg: PgUrls, qdrant_url: str, tmp: Path) -> None:
    """KB fixture ingest THẬT (như `test_rag_query_qdrant.env`) vào Qdrant/PG của phiên e2e — một lần (alias đã có → bỏ)."""

    async def run() -> None:
        async with _env(qdrant_url, pg) as env:
            if await env.index.alias_target(ALIAS) is not None:
                return
            r = await env.run(copy_kb(tmp, with_eval=False), allow_unevaluated=True)
            assert r.code == 0, r.err

    asyncio.run(run())


@dataclass
class CrashSwitch:
    armed: bool = False


class CrashAfterWrite:
    """Registry ghi thật; khi `switch.armed`, lời gọi CẤP chứng chỉ đầu tiên tới mock xong thì process "chết"."""

    def __init__(self, inner: Any, switch: CrashSwitch) -> None:
        self._inner = inner
        self._switch = switch

    async def call(self, name: str, args: Mapping[str, Any], *, caller_step: str) -> ToolResult:
        result: ToolResult = await self._inner.call(name, args, caller_step=caller_step)
        if self._switch.armed and name in ISSUE_TOOLS:
            self._switch.armed = False
            raise Crash(f"SIGKILL sau lời gọi ghi {name}, trước checkpoint của B17")
        return result


@dataclass
class Parts:
    """Những gì SỐNG QUA lần khởi động lại API trong một test: DB, mock, đồng hồ, LLM kịch bản, ml giả."""

    pg: PgUrls
    qdrant_url: str
    mock: MockServer
    clock: FakeClock
    gw: Gateway
    rw: AsyncEngine
    ml: FakeMlService = field(default_factory=FakeMlService)
    crash: CrashSwitch = field(default_factory=CrashSwitch)
    proactive: bool = True
    qdrant_override: str | None = None  # h8: Qdrant "tắt" = URL không ai nghe

    def settings(self) -> Settings:
        return auth_settings(
            database_url=self.pg.role("app_rw"), mock_url=self.mock.url, svc_agent_token=self.mock.agent,
            svc_executor_token=self.mock.executor, fake_approver_id="l1_01",
            qdrant_url=self.qdrant_override or self.qdrant_url, enable_proactive_diagnosis=self.proactive,
        )  # fmt: skip


@asynccontextmanager
async def open_gate3_runtime(
    parts: Parts, settings: Settings, engines: Engines, clock: Clock, *, can_execute: bool,
    directory: ToolCaller | None,
) -> AsyncIterator[Runtime]:  # fmt: skip
    """Như `main._default_runtime` + `graph.wiring.open_runtime`, chỉ thay ml/LLM bằng bản giả. API: `PlanExecutor` (registry
    ghi svc_executor); worker: `RefusingExecutor` — đúng P7."""
    async with AsyncExitStack() as stack:
        qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=int(settings.rag_qdrant_timeout_s),
                                   check_compatibility=False)  # fmt: skip
        stack.push_async_callback(qdrant.close)
        ml = parts.ml.client(clock)
        rag = Retriever(
            QdrantIndex(qdrant), ml, RagConfig.from_settings(settings),
            threshold=get_policy().constants.RETRIEVAL_THRESHOLD, pipeline_sha=pipeline_sha(settings.config_dir),
            lexicon=load_lexicon(settings.config_dir), clock=clock,
        )  # fmt: skip
        if directory is None:
            registry, read_http = build_read_registry(settings, clock)
            stack.push_async_callback(read_http.aclose)
            directory = registry
        txlog = SqlTxLog(engines.main, clock)
        if can_execute:
            write_registry, write_http = build_write_registry(settings, clock)
            stack.push_async_callback(write_http.aclose)
            executor: Any = PlanExecutor(CrashAfterWrite(write_registry, parts.crash), txlog, clock,
                                        tz=get_policy().business_hours.tz)  # fmt: skip
        else:
            executor = RefusingExecutor(txlog)
        rt = await stack.enter_async_context(_open(
            settings, engines, clock, can_execute=can_execute, directory=directory,
            approver_id=fake_approver(settings), scenario=FakeScenario(), ml=ml, rag=rag, llm=parts.gw.client,
            executor=executor,
        ))  # fmt: skip
        yield rt


@dataclass
class Api:
    parts: Parts
    app: FastAPI
    client: httpx.AsyncClient
    tokens: dict[str, dict[str, str]] = field(default_factory=dict)

    async def drain(self) -> None:
        await self.app.state.background.drain()

    async def login(self, username: str) -> dict[str, str]:
        r = await self.client.post("/api/auth/login", json={"username": username, "password": DEMO_PASSWORD})
        assert r.status_code == 200, (username, r.status_code, r.text)
        self.tokens[username] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return self.tokens[username]

    async def create(self, username: str, text_: str) -> str:
        """Người duyệt đăng nhập trước (dòng `users` cho khoá ngoại phiếu duyệt), rồi người gửi tạo ticket; chờ lượt nền."""
        if APPROVER not in self.tokens:
            await self.login(APPROVER)
        headers = self.tokens.get(username) or await self.login(username)
        r = await self.client.post("/api/tickets", json={"text": text_}, headers=headers)
        assert r.status_code == 202, r.text
        await self.drain()
        return str(r.json()["ticket_id"])

    async def post(self, path: str, body: Mapping[str, Any], username: str) -> httpx.Response:
        headers = self.tokens.get(username) or await self.login(username)
        r = await self.client.post(path, json=dict(body), headers=headers)
        await self.drain()
        return r

    async def confirm(self, ticket: str, username: str, confirmed: bool, note: str | None = None) -> httpx.Response:
        body: dict[str, Any] = {"confirmed": confirmed, **({"note": note} if note is not None else {})}
        return await self.post(f"/api/tickets/{ticket}/confirm", body, username)

    async def view(self, ticket: str, username: str) -> dict[str, Any]:
        headers = self.tokens.get(username) or await self.login(username)
        r = await self.client.get(f"/api/tickets/{ticket}", headers=headers)
        assert r.status_code == 200, r.text
        return dict(r.json())

    async def state(self, ticket: str) -> Mapping[str, Any]:
        return (await self.app.state.desk.runner.snapshot(ticket)).values  # type: ignore[no-any-return]


@asynccontextmanager
async def api(parts: Parts) -> AsyncIterator[Api]:
    """Một "process" API. Mở lại (trong cùng test) = khởi động lại backend: engine, registry, runtime mới; DB/mock giữ."""
    settings = parts.settings()

    @asynccontextmanager
    async def factory(s: Settings, engines: Engines, clock: Clock, directory: ToolCaller | None) -> AsyncIterator[Runtime]:
        async with open_gate3_runtime(parts, s, engines, clock, can_execute=True, directory=directory) as rt:
            yield rt

    app = create_app(settings, health_checks={}, clock=parts.clock, runtime=factory)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.30", 50000))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        assert app.state.runtime_status == "up"
        yield Api(parts, app, client)
        await app.state.background.drain()


@asynccontextmanager
async def worker(parts: Parts) -> AsyncIterator[WorkerJobs]:
    """Worker (`app.worker`): runtime `can_execute=False` + `RefusingExecutor`, registry đọc svc_agent, cùng DB/đồng hồ."""
    settings = parts.settings()
    engines = create_engines(settings)
    try:
        async with open_gate3_runtime(parts, settings, engines, parts.clock, can_execute=False, directory=None) as rt:
            yield WorkerJobs(rt.runner, rt.deadlines, rt.turns, stale_after=timedelta(minutes=2))
    finally:
        await engines.dispose()


@asynccontextmanager
async def gate3(
    pg: PgUrls, qdrant_url: str, mock: MockServer, *, clock: FakeClock, scripts: dict[str, Script],
    proactive: bool = True, qdrant_override: str | None = None, ml: FakeMlService | None = None,
) -> AsyncIterator[Parts]:  # fmt: skip
    """`ml`: ml-service giả riêng (vd `FakeMlService(rerank_score=0.05)` — Phase 4 s8 ép điểm truy hồi thấp)."""
    rw = create_async_engine(pg.role("app_rw"))
    gw = make_gateway(scripts, clock=clock, store=SqlLlmStore(rw), trace=trace_parent,  # type: ignore[arg-type]
                      cache_mode="bypass")  # fmt: skip
    try:
        yield Parts(pg, qdrant_url, mock, clock, gw, rw, ml=ml or FakeMlService(), proactive=proactive,
                    qdrant_override=qdrant_override)  # fmt: skip
    finally:
        await rw.dispose()


# ---- đọc ở NƠI NHẬN / trong DB ---------------------------------------------------------------------------------------


async def calls(mock: MockServer, prefix: str = WRITES, method: str | None = "POST") -> int:
    """Số lời gọi mock đã NHẬN (kể cả bị bơm lỗi) — `GET /_admin/calls`."""
    params = {"path_prefix": prefix, **({"method": method} if method else {})}
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{mock.url}/_admin/calls", params=params)
    r.raise_for_status()
    return int(r.json()["count"])


async def admin(mock: MockServer, path: str, body: Mapping[str, Any] | None = None) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(f"{mock.url}/_admin/{path}", json=dict(body) if body is not None else None)
    r.raise_for_status()


async def scalar(rw: AsyncEngine, sql: str, **params: Any) -> Any:
    async with rw.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def rows(rw: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with rw.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def audit_events(rw: AsyncEngine, ticket: str) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in await rows(
        rw, "SELECT step, event FROM audit_logs WHERE ticket_id = :t ORDER BY log_id", t=ticket)]  # fmt: skip


async def audit_detail(rw: AsyncEngine, ticket: str, step: str, event: str) -> dict[str, Any]:
    [row] = await rows(rw, "SELECT detail FROM audit_logs WHERE ticket_id = :t AND step = :s AND event = :e",
                       t=ticket, s=step, e=event)  # fmt: skip
    return dict(row[0] or {})


async def escalation(rw: AsyncEngine, ticket: str) -> tuple[str, str | None, dict[str, Any]]:
    """(exit_code, reason_detail, handoff_note 4 phần) — đúng một dòng `escalations`."""
    [row] = await rows(rw, "SELECT exit_code, reason_detail, handoff_note FROM escalations WHERE ticket_id = :t", t=ticket)
    return str(row[0]), row[1], dict(row[2])


async def open_turn(rw: AsyncEngine, ticket: str) -> str:
    [row] = await rows(rw, "SELECT turn_id FROM turns WHERE ticket_id = :t AND ended_at IS NULL", t=ticket)
    return str(row[0])
