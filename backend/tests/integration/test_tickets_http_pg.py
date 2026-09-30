"""Route ticket / duyệt trên Postgres 16 thật (2b-3): `create_app` + auth SQL + runtime SQL
(`AsyncPostgresSaver`, `pg_advisory_lock`), AD giả, FakeClock. Kiểm dữ liệu ghi xuống bảng.

Cổng 2 qua HTTP: tạo → chờ duyệt → ĐÓNG app, mở app mới cùng DB → quyết định → xác nhận → S_RESOLVED.
Database riêng (dòng audit/security_events append-only, không xoá được giữa các test).
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.runtime import SqlDeadlineStore, SqlTurnStore
from app.db.tickets import NewTicket, SqlTicketStore, TicketRow
from app.domain.states import (
    S_CLARIFYING,
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_RESOLVED,
)
from app.graph.fakes import FakeScenario
from app.graph.worker_jobs import WorkerJobs
from app.main import create_app
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.auth import EPOCH, FakeIdentityProvider, seed_ad_users
from tests.fakes.desk import MASK, SECRET, MaskingGuard, ad_directory
from tests.fakes.graph import Crash
from tests.fakes.identity import FakeAd, ad_user
from tests.integration import _crash_after_ticket_create
from tests.integration.graph_pg import (
    REQUESTER,
    SESSION,
    open_pg_runtime,
    pg_runtime_factory,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.integration.scan import scannable_columns, tables_containing
from tests.unit.auth_helpers import BASE_URL, auth_settings

SLA = timedelta(minutes=30)
CANARY = "CANARY-khong-bi-che"  # chuỗi KHÔNG phải bí mật: phép quét phải thấy nó (đối chứng)


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    yield engine
    await engine.dispose()


@dataclass
class PgDesk:
    app: FastAPI
    client: httpx.AsyncClient
    clock: FakeClock

    async def token(self, username: str) -> dict[str, str]:
        r = await self.client.post("/api/auth/login", json={"username": username, "password": "Demo@2026!"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def drain(self) -> None:
        await self.app.state.background.drain()

    async def create(self, headers: dict[str, str], text_: str = "VPN lỗi") -> str:
        r = await self.client.post("/api/tickets", json={"text": text_}, headers=headers)
        assert r.status_code == 202, r.text
        await self.drain()
        return str(r.json()["ticket_id"])

    async def status(self, ticket: str, headers: dict[str, str]) -> Any:
        r = await self.client.get(f"/api/tickets/{ticket}", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    def worker(self, engine: AsyncEngine) -> WorkerJobs:
        runner = self.app.state.desk.runner
        return WorkerJobs(runner, SqlDeadlineStore(engine), SqlTurnStore(engine))


@asynccontextmanager
async def pg_desk(
    db: PgUrls, clock: FakeClock, *, scenario: FakeScenario | None = None,
    approver_id: str | None = "l1_01",
) -> AsyncIterator[PgDesk]:  # fmt: skip
    url = db.role("app_rw")
    settings = auth_settings(database_url=url, fake_approver_id=approver_id)
    ad = ad_directory(seed_ad_users())
    app = create_app(
        settings, health_checks={}, idp=FakeIdentityProvider(), clock=clock, guard=MaskingGuard(),
        runtime=pg_runtime_factory(url, clock=clock, ad=ad, scenario=scenario, approver_id=approver_id),
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        assert app.state.runtime_status == "up"
        yield PgDesk(app, client, clock)
        await app.state.background.drain()


async def _late_rows(rw: AsyncEngine, ticket: str) -> list[Any]:
    async with rw.connect() as conn:
        rows = await conn.execute(
            text("SELECT detail FROM audit_logs WHERE ticket_id=:t AND event='late_event'"), {"t": ticket}
        )
        return [r.detail for r in rows]


# ---- Cổng 2 qua HTTP + created_at từ Clock (S2) ----------------------------------------------


@pytest.mark.asyncio
async def test_full_flow_restart_duration_300s_pg(db: PgUrls, rw: AsyncEngine) -> None:
    clock = FakeClock(EPOCH)
    async with pg_desk(db, clock) as d:
        l1 = await d.token("ha.lt")  # người duyệt giả phải có dòng users (Q4)
        an = await d.token("an.nv")
        ticket = await d.create(an)
        assert (await d.status(ticket, an))["status"] == S_PENDING_APPROVAL
    assert await scalar(rw, "SELECT created_at = :e FROM tickets WHERE ticket_id=:t", t=ticket, e=EPOCH)

    clock.advance(timedelta(seconds=300))
    async with pg_desk(db, clock) as d:  # "khởi động lại backend": app + runtime mới, cùng DB
        l1, an = await d.token("ha.lt"), await d.token("an.nv")
        aid = await scalar(rw, "SELECT approval_id FROM approvals WHERE ticket_id=:t", t=ticket)
        r = await d.client.post(f"/api/approvals/{aid}/decision", json={"decision": "approved"}, headers=l1)
        assert r.status_code == 202
        await d.drain()
        assert (await d.status(ticket, an))["status"] == S_CONFIRMING
        r = await d.client.post(f"/api/tickets/{ticket}/confirm", json={"confirmed": True}, headers=an)
        assert r.status_code == 202
        await d.drain()
        assert (await d.status(ticket, an))["status"] == S_RESOLVED
    async with rw.connect() as conn:
        row = (await conn.execute(text(
            "SELECT final_state, close_reason, total_duration_seconds FROM tickets WHERE ticket_id=:t"),
            {"t": ticket})).one()  # fmt: skip
        approval = (await conn.execute(text(
            "SELECT status, decided_by FROM approvals WHERE ticket_id=:t"), {"t": ticket})).one()  # fmt: skip
        point8 = await conn.execute(text(
            "SELECT total_duration_seconds FROM audit_logs WHERE ticket_id=:t AND event='closed'"),
            {"t": ticket})  # fmt: skip
    assert tuple(row) == (S_RESOLVED, "resolved_user_confirmed", 300)
    assert tuple(approval) == ("approved", "l1_01")
    assert [p[0] for p in point8] == [300]


# ---- Sự kiện muộn ở 3 trạng thái chờ ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("plan", "route", "body", "status"), [
    ({}, "messages", {"text": "x"}, S_PENDING_APPROVAL),
    ({"b11_slots": "missing"}, "confirm", {"confirmed": True}, S_CLARIFYING),
    ({"b12_assess": "auto"}, "messages", {"text": "x"}, S_CONFIRMING),
])  # fmt: skip
async def test_late_events_pg(
    db: PgUrls, rw: AsyncEngine, plan: dict[str, str], route: str, body: Any, status: str
) -> None:
    clock = FakeClock(EPOCH)
    async with pg_desk(db, clock, scenario=FakeScenario().plan_all(**plan)) as d:
        await d.token("ha.lt")
        an = await d.token("an.nv")
        ticket = await d.create(an)
        assert (await d.status(ticket, an))["status"] == status
        r = await d.client.post(f"/api/tickets/{ticket}/{route}", json=body, headers=an)
        assert r.status_code == 409
        assert (await d.status(ticket, an))["status"] == status
    [late] = await _late_rows(rw, ticket)
    assert (late["actual_status"], late["source"]) == (status, "user")


# ---- Bấm muộn trước chu kỳ quét (Q2, S5) ----------------------------------------------------


@pytest.mark.asyncio
async def test_late_click_before_scan_pg(db: PgUrls, rw: AsyncEngine) -> None:
    clock = FakeClock(EPOCH)
    async with pg_desk(db, clock) as d:
        await d.token("ha.lt")
        an = await d.token("an.nv")
        ticket = await d.create(an)
        aid = await scalar(rw, "SELECT approval_id FROM approvals WHERE ticket_id=:t", t=ticket)
        clock.advance(SLA + timedelta(seconds=1))
        l1 = await d.token("ha.lt")
        r = await d.client.post(f"/api/approvals/{aid}/decision", json={"decision": "approved"}, headers=l1)
        assert r.status_code == 409
        [late] = await _late_rows(rw, ticket)
        assert (late["reason"], late["approval_id"], late["clicked_by"]) == ("expired", str(aid), "l1_01")
        assert await scalar(rw, "SELECT status FROM approvals WHERE approval_id=:a", a=aid) == "pending"
        report = await d.worker(rw).scan_deadlines()
        # DB dùng chung cả module: phiếu pending của test khác cũng quá hạn → không đếm tổng, kiểm
        # đúng ticket/phiếu của test này ở dưới
        assert report.delivered >= 1 and report.failed == 0
    assert await scalar(rw, "SELECT status FROM approvals WHERE approval_id=:a", a=aid) == "timeout"
    assert await scalar(rw, "SELECT exit_code FROM tickets WHERE ticket_id=:t", t=ticket) == "E6"


# ---- IDOR (S6) -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_idor_pg(db: PgUrls) -> None:
    async with pg_desk(db, FakeClock(EPOCH)) as d:
        await d.token("ha.lt")
        an, binh = await d.token("an.nv"), await d.token("binh.tt")
        ticket = await d.create(an)
        own = await d.create(binh)
        other = await d.client.get(f"/api/tickets/{ticket}", headers=binh)
        missing = await d.client.get(f"/api/tickets/{uuid4()}", headers=binh)
        assert (other.status_code, other.json()) == (missing.status_code, missing.json()) == (
            404, {"detail": "not_found"})  # fmt: skip
        # mỗi người đọc được ĐÚNG ticket của mình (bắt cả `get` trả nhầm dòng)
        for who, tid in ((an, ticket), (binh, own)):
            r = await d.client.get(f"/api/tickets/{tid}", headers=who)
            assert (r.status_code, r.json()["ticket_id"]) == (200, tid)


# ---- Guard: quét MỌI cột text/jsonb/bytea của MỌI bảng + checkpoint ---------------------------


@pytest.mark.asyncio
async def test_secret_nowhere_in_db_after_ticket_and_message_pg(db: PgUrls, rw: AsyncEngine) -> None:
    scenario = FakeScenario().plan_all(b11_slots=["missing", "complete"])
    async with pg_desk(db, FakeClock(EPOCH), scenario=scenario) as d:
        await d.token("ha.lt")
        an = await d.token("an.nv")
        ticket = await d.create(an, f"{CANARY} mật khẩu là {SECRET}")
        assert (await d.status(ticket, an))["status"] == S_CLARIFYING
        r = await d.client.post(f"/api/tickets/{ticket}/messages",
                                json={"text": f"máy LAP-1 {CANARY}-2 pass {SECRET}"}, headers=an)  # fmt: skip
        assert r.status_code == 202
        await d.drain()
    # không xanh oan vì danh sách quét rỗng / lọc sai schema: 22 bảng nghiệp vụ (P7) + 4 bảng checkpoint
    scanned = {table for table, _, _ in await scannable_columns(rw)}
    assert len(scanned) >= 22, sorted(scanned)
    assert {"tickets", "audit_logs", "turns", "side_effects", "checkpoints", "checkpoint_blobs",
            "checkpoint_writes"} <= scanned  # fmt: skip
    assert await tables_containing(rw, SECRET) == []
    # đối chứng: phép quét thấy chuỗi không bị che — cả ở tickets lẫn blob checkpoint
    seen = await tables_containing(rw, f"{CANARY}-2")
    assert any(h.startswith("checkpoint") for h in seen), seen
    assert "tickets.redacted_request" in await tables_containing(rw, CANARY)
    assert await tables_containing(rw, MASK)


# ---- Q4: người duyệt giả chưa có dòng users → E9 ---------------------------------------------


@pytest.mark.asyncio
async def test_fake_approver_without_users_row_goes_e9_pg(db: PgUrls, rw: AsyncEngine) -> None:
    async with pg_desk(db, FakeClock(EPOCH), approver_id="l1_chua_dang_nhap") as d:
        an = await d.token("an.nv")
        ticket = await d.create(an)
        view = await d.status(ticket, an)
    assert (view["status"], view["exit_code"]) == (S_ESCALATED, "E9")
    assert await scalar(rw, "SELECT count(*) FROM approvals WHERE ticket_id=:t", t=ticket) == 0


# ---- Giết process thật giữa commit INSERT và submit (chốt g, S8) ------------------------------


@pytest.mark.asyncio
async def test_kill_between_insert_and_submit(db: PgUrls, rw: AsyncEngine) -> None:
    await seed_users(rw)
    ticket, turn = f"tk-{uuid4().hex[:8]}", f"turn-{uuid4().hex[:8]}"
    env = {**os.environ, "APP_ENV_FILE": "", "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    proc = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, _crash_after_ticket_create.__file__, db.role("app_rw"), ticket, turn],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert proc.returncode == _crash_after_ticket_create.EXIT_CODE, proc.stderr[-2000:]
    assert await scalar(rw, "SELECT count(*) FROM checkpoints WHERE thread_id=:t", t=ticket) == 0
    assert await scalar(rw, "SELECT ended_at IS NULL FROM turns WHERE turn_id=:u", u=turn)

    clock = FakeClock()
    clock.advance(timedelta(minutes=3))
    scenario = FakeScenario().plan(ticket, b12_assess="deny")  # chạy tới đóng (E5) để có final_state
    async with open_pg_runtime(db.role("app_rw"), clock=clock, scenario=scenario, can_execute=False) as rt:
        assert await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns() >= 1
    assert await scalar(rw, "SELECT final_state FROM tickets WHERE ticket_id=:t", t=ticket) == S_ESCALATED
    assert await scalar(rw, "SELECT count(DISTINCT thread_id) FROM checkpoints WHERE thread_id=:t",
                        t=ticket) == 1  # fmt: skip
    assert await scalar(rw, "SELECT string_agg(turn_id, ',') FROM turns WHERE ticket_id=:t", t=ticket) == turn
    assert await scalar(rw, "SELECT ended_at IS NOT NULL FROM turns WHERE turn_id=:u", u=turn)
    assert await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id=:t "
                            "AND event='identity_established'", t=ticket) == 1  # fmt: skip


# ---- Cạn lượt phục hồi: không bao giờ bỏ rơi ticket (2b-Q6, L27) ------------------------------


class DyingTickets(SqlTicketStore):
    """`get` "chết" N lần đầu — bước ngay trước khi runner chạy state đầu (chưa có checkpoint)."""

    def __init__(self, engine: AsyncEngine, deaths: int) -> None:
        super().__init__(engine)
        self.deaths = deaths

    async def get(self, ticket_id: str) -> TicketRow | None:
        if self.deaths > 0:
            self.deaths -= 1
            raise Crash("SIGKILL trước checkpoint đầu")
        return await super().get(ticket_id)


async def _die_four_times_pg(db: PgUrls, ticket: str, turn: str, **runtime: Any) -> None:
    """Lượt đầu + 3 lần worker phục hồi đều "chết"; mỗi lần là một runtime MỚI (process mới)."""
    url, clock = db.role("app_rw"), FakeClock()
    async with open_pg_runtime(url, clock=clock, **runtime) as rt:
        with pytest.raises(Crash):
            await rt.runner.run_new(ticket, turn)
    for _ in range(3):
        clock.advance(timedelta(minutes=3))
        async with open_pg_runtime(url, clock=clock, can_execute=False, **runtime) as rt:
            with pytest.raises(Crash):
                await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns()
    clock.advance(timedelta(minutes=3))
    async with open_pg_runtime(url, clock=clock, can_execute=False, **runtime) as rt:
        assert await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns() >= 1


async def _assert_e9_once_pg(rw: AsyncEngine, ticket: str, turn: str) -> Any:
    async with rw.connect() as conn:
        final = (await conn.execute(text(
            "SELECT final_state, exit_code FROM tickets WHERE ticket_id=:t"), {"t": ticket})).one()  # fmt: skip
        escs = (await conn.execute(text(
            "SELECT exit_code, reason_detail FROM escalations WHERE ticket_id=:t"), {"t": ticket})).all()  # fmt: skip
        turns = (await conn.execute(text(
            "SELECT turn_id, recover_attempts, ended_at IS NOT NULL FROM turns WHERE ticket_id=:t"),
            {"t": ticket})).all()  # fmt: skip
        [detail] = cast(list[Any], (await conn.execute(text(
            "SELECT detail FROM audit_logs WHERE ticket_id=:t AND event='recover_exhausted'"),
            {"t": ticket})).scalars().all())  # fmt: skip
    assert tuple(final) == (S_ESCALATED, "E9")
    assert [tuple(e) for e in escs] == [("E9", "recover_exhausted")]
    assert [tuple(t) for t in turns] == [(turn, 4, True)]
    return detail


async def _new_ticket(rw: AsyncEngine) -> tuple[str, str]:
    await seed_users(rw)
    ticket, turn = f"tk-{uuid4().hex[:8]}", f"turn-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee",
                  requester_dept="it", session_id=SESSION, redacted_request="VPN lỗi",
                  created_at=FakeClock().now()),
        turn_id=turn,
    )  # fmt: skip
    return ticket, turn


@pytest.mark.asyncio
async def test_killed_in_b1_every_time_goes_e9_pg(db: PgUrls, rw: AsyncEngine) -> None:
    ticket, turn = await _new_ticket(rw)
    ad = FakeAd(ad_user(REQUESTER))
    ad.crash = Crash("SIGKILL giữa B1")
    await _die_four_times_pg(db, ticket, turn, ad=ad)
    detail = await _assert_e9_once_pg(rw, ticket, turn)
    assert detail["node"] == "b01_identity" and "no_checkpoint" not in detail


@pytest.mark.asyncio
async def test_killed_before_first_checkpoint_every_time_goes_e9_pg(db: PgUrls, rw: AsyncEngine) -> None:
    ticket, turn = await _new_ticket(rw)
    dying = DyingTickets(rw, deaths=4)
    await _die_four_times_pg(db, ticket, turn, tickets=dying)
    detail = await _assert_e9_once_pg(rw, ticket, turn)
    assert detail["no_checkpoint"] is True and detail["recover_attempts"] == 3
