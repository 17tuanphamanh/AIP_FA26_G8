"""`executor/txlog.SqlTxLog` + `SqlApprovals.get_status` trên Postgres 16 thật (phase3 11.4 bước 1, 4; PLAN-3h S9, S11).

- `begin` commit NGAY trong transaction riêng — kết nối KHÁC thấy dòng `begun` trước khi tool ghi được gọi (bằng chứng duy nhất
  còn lại nếu process chết sau lời gọi ghi). Chạy dưới role `app_rw` (quyền CRUD `transaction_log` từ 0001).
- `has_begun` theo ticket (MỌI lượt — chốt DỪNG 2, NGHI-2); `undone` / `undo_failed` + `detail`; CHECK trạng thái chỉ nhận
  begun/undone/undo_failed.
- Chuỗi đầy đủ: `VpnExecutor` thật + txlog PG + ghi VPN giả — `begun` có trước lời gọi; chạy lại cùng lượt → `ExecutionInterrupted`.
- `get_status`: phiếu pending/approved; không có → None (B17 "đã duyệt" đọc BẢNG — P8).
Database riêng cho module (dòng append-only không xoá được giữa các test).
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.approval.store import SqlApprovals
from app.core.clock import FakeClock
from app.db.tickets import NewTicket, SqlTicketStore
from app.domain.action import Action
from app.executor.errors import ExecutionInterrupted
from app.executor.txlog import SqlTxLog
from app.executor.vpn import VpnExecutor
from app.settings import get_action_metadata, get_policy
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.executor import FakeVpnWrites
from tests.integration.graph_pg import APPROVER, REQUESTER, SESSION, scalar, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


async def _ticket(rw: AsyncEngine) -> str:
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=NOW),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    return ticket


def _action() -> Action:
    meta = get_action_metadata().root["vpn"]["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target="device:LAP-0342", requested_for="nv001", scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params={"device_id": "LAP-0342"},
        facts={"device_registered": True, "device_owner_is_requester": True},
    )  # fmt: skip


async def test_begin_is_committed_immediately_and_visible(rw: AsyncEngine, db: PgUrls) -> None:
    ticket = await _ticket(rw)
    log = SqlTxLog(rw, FakeClock(NOW))
    assert not await log.has_begun(ticket)
    await log.begin(ticket, "T1", "renew_vpn_cert")
    other = create_async_engine(db.role("app_rw"))  # kết nối khác hẳn — thấy ngay, không cần transaction của ai
    try:
        assert await scalar(other, "SELECT count(*) FROM transaction_log WHERE ticket_id=:t AND turn_id='T1' "
                                   "AND status='begun' AND step_name='renew_vpn_cert' AND created_at=:n",
                            t=ticket, n=NOW) == 1  # fmt: skip
    finally:
        await other.dispose()
    assert await log.has_begun(ticket)  # mọi lượt của ticket (NGHI-2) — trước DỪNG 2 test này khẳng định lượt khác không chặn
    assert not await log.has_begun(await _ticket(rw))  # ticket khác không bị chặn


async def test_undone_and_undo_failed_rows(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    log = SqlTxLog(rw, FakeClock(NOW))
    await log.undone(ticket, "T1", "renew_vpn_cert")
    await log.undo_failed(ticket, "T1", "reissue_vpn_access", "UNDO_FAILED: http_5xx")
    assert await scalar(rw, "SELECT string_agg(step_name || ':' || status || ':' || coalesce(detail, '-'), ',' "
                            "ORDER BY log_id) FROM transaction_log WHERE ticket_id=:t", t=ticket) == (
        "renew_vpn_cert:undone:-,reissue_vpn_access:undo_failed:UNDO_FAILED: http_5xx")  # fmt: skip
    assert not await log.has_begun(ticket)  # undone/undo_failed không phải begun


async def test_status_check_constraint(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    log = SqlTxLog(rw, FakeClock(NOW))
    with pytest.raises(IntegrityError):
        await log._insert(ticket, "T1", "renew_vpn_cert", "committed", None)  # không thêm trạng thái mới


async def test_executor_with_pg_txlog_begun_then_interrupted(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    clock = FakeClock(NOW)
    writes = FakeVpnWrites(clock)
    ex = VpnExecutor(writes.registry(), SqlTxLog(rw, clock), clock, tz=get_policy().business_hours.tz)
    assert (await ex.execute(ticket, "T1", _action())).success
    assert await scalar(rw, "SELECT count(*) FROM transaction_log WHERE ticket_id=:t AND status='begun'", t=ticket) == 1
    with pytest.raises(ExecutionInterrupted):  # "recover" cùng lượt
        await ex.execute(ticket, "T1", _action())
    with pytest.raises(ExecutionInterrupted):  # lượt khác của cùng ticket (NGHI-2)
        await ex.execute(ticket, "T2", _action())
    assert writes.calls == {"renew_vpn_cert": 1}


async def test_get_status_reads_table(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    store = SqlApprovals(rw)
    aid = await store.create(ticket, APPROVER, NOW + timedelta(minutes=30), "h" * 64, backup_approver_id=None, conflict_detected=False, conflict_type=None)
    assert await store.get_status(aid) == "pending"
    await store.close(aid, "approved", NOW, decided_by=APPROVER, note=None)
    assert await store.get_status(aid) == "approved"
    assert await store.get_status("999999999") is None
    assert await store.get_status("khong-phai-so") is None
