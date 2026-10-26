"""SQL `SqlApprovals.parent_deadline` (TicketView.deadline của ticket CHA) trên Postgres 16 thật: hạn chờ riêng chưa bắn của cha thắng;
không có → `min(approvals.deadline)` phiếu `pending` của CON (không tính phiếu đã đóng, phiếu của chính cha, con của cha khác); không có → None."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.approval.store import SqlApprovals
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration.pg import PgUrls, alembic_config, fresh_database

T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        sync = create_engine(fresh.role("app_rw"))
        with sync.begin() as c:
            c.execute(text("INSERT INTO users (user_id, username, role) VALUES ('nv-p','p.nv','employee'), ('l1-p','p.l1','l1')"))
            for tid, parent, is_parent in (
                ("P1", None, True), ("P1-1", "P1", False), ("P1-2", "P1", False), ("P2", None, True), ("P2-1", "P2", False),
                ("P3", None, True), ("P3-1", "P3", False), ("P4", None, True),
            ):  # fmt: skip
                c.execute(text(
                    "INSERT INTO tickets (ticket_id, parent_ticket_id, requester_id, requester_role, redacted_request, is_parent) "
                    "VALUES (:t, :p, 'nv-p', 'employee', 'x', :ip)"), {"t": tid, "p": parent, "ip": is_parent})  # fmt: skip

            def approval(ticket: str, minutes: int, status: str = "pending") -> None:
                decided = status != "pending"
                c.execute(text(
                    "INSERT INTO approvals (ticket_id, approver_id, deadline, action_plan_hash, status, decided_by, decided_at, note) "
                    "VALUES (:t, 'l1-p', :d, :h, :s, :db, :da, :n)"),
                    {"t": ticket, "d": T0 + timedelta(minutes=minutes), "h": "h" * 64, "s": status,
                     "db": "l1-p" if decided else None, "da": T0 if decided else None, "n": "x" if status == "rejected" else None})  # fmt: skip

            approval("P1-1", 50)
            approval("P1-2", 20)
            approval("P1-2", 5, "approved")  # đã đóng: không tính
            approval("P1", 1)  # phiếu của chính cha: không tính
            approval("P2-1", 30)
            approval("P3-1", 10)
            c.execute(text("INSERT INTO wait_deadlines (ticket_id, kind, deadline, created_turn) VALUES ('P2', 'confirm', :d, 'tr')"),
                      {"d": T0 + timedelta(hours=24)})  # P2: hạn riêng (sớm hơn? không — muộn hơn con) vẫn thắng
            c.execute(text("INSERT INTO wait_deadlines (ticket_id, kind, deadline, created_turn, fired_at) VALUES ('P3', 'clarify', :d, 'tr', now())"),
                      {"d": T0 + timedelta(hours=1)})  # P3: hạn riêng đã bắn → bỏ qua
        sync.dispose()
        yield fresh


@pytest_asyncio.fixture
async def store(db: PgUrls):  # type: ignore[no-untyped-def]
    engine = create_async_engine(db.role("app_rw"))
    yield SqlApprovals(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_parent_deadline_precedence(store: SqlApprovals) -> None:
    assert await store.parent_deadline("P1") == T0 + timedelta(minutes=20)  # không hạn riêng: phiếu con pending sớm nhất
    assert await store.parent_deadline("P2") == T0 + timedelta(hours=24)  # hạn riêng thắng dù con chờ duyệt sớm hơn
    assert await store.parent_deadline("P3") == T0 + timedelta(minutes=10)  # hạn riêng đã bắn → quay về con
    assert await store.parent_deadline("P4") is None  # không gì cả
    assert await store.parent_deadline("khong-co") is None
    got = await store.parent_deadline("P1")
    assert got is not None and got.tzinfo is not None
