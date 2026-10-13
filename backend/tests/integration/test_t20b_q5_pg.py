"""T20b Q-T20b-5 trên Postgres 16 thật — agent chính viết (sửa theo duyệt MẪU B DỪNG 1). Chỉ chạy ở verify/CI (testcontainers).

- (ii) `SqlEscalationStore.list_open`: `is_parent = false OR tickets.exit_code IS NOT NULL` — cha lỗi (E9 đã finalize) HIỆN; cha đóng
  bình thường (không `exit_code`) và cha chưa finalize KHÔNG hiện; ticket lá như cũ.
- (iii) `SqlDeadlineStore.orphan_children` (DỪNG 2 — `CHO_DUNG2`): con chờ người dùng mà notice ĐÃ gửi + cha đã kết thúc → chọn (`needs`
  của notice `needs≠none` mới nhất); con đang có phiếu duyệt `pending` → bỏ.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from app.db.escalations import SqlEscalationStore
from app.db.runtime import OrphanChild, SqlDeadlineStore
from app.db.tickets import SqlTicketStore
from app.domain.final import FinalSummary
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import APPROVER, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.integration.test_t20b_pg import NOW, _children, _final, _notice, _parent

pytestmark = pytest.mark.asyncio

CHO_DUNG2 = frozenset({"test_q5_iii_orphan_children_includes_delivered_notice_skips_pending_approval"})


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.originalname in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError), reason="T20b DỪNG 2"))


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


def _parent_e9() -> FinalSummary:
    return FinalSummary("S_ESCALATED", "E9", None, None, None, None, False, None, None, 1, 10, NOW)


async def _escalate(store: SqlEscalationStore, ticket: str, code: str) -> None:
    await store.create(ticket_id=ticket, exit_code=code, reason_detail=None, handoff_note={"request": "x"}, is_deny_case=False,
                       created_at=NOW)  # fmt: skip


async def test_q5_ii_list_open_shows_failed_parent_only(rw: AsyncEngine) -> None:
    tickets, esc = SqlTicketStore(rw), SqlEscalationStore(rw)
    failed = await _parent(rw)
    [f1] = await _children(rw, failed, 1)
    await tickets.finalize_once(failed, _parent_e9())
    await _escalate(esc, failed, "E9")
    await tickets.finalize_once(f1, _final("S_ESCALATED"))
    await _escalate(esc, f1, "E1")
    unfinished = await _parent(rw)  # cha có dòng escalation nhưng chưa finalize (exit_code NULL) → không hiện (khuôn test_b20_pg)
    await _children(rw, unfinished, 1)
    await _escalate(esc, unfinished, "E7")
    normal = await _parent(rw)
    [n1] = await _children(rw, normal, 1)
    await tickets.finalize_once(normal, _final("S_ESCALATED", parent=True))
    queue = {i.ticket_id for i in await esc.list_open(1000)}
    assert {failed, f1} <= queue
    assert unfinished not in queue and normal not in queue and n1 not in queue


async def test_q5_iii_orphan_children_includes_delivered_notice_skips_pending_approval(rw: AsyncEngine) -> None:
    tickets = SqlTicketStore(rw)
    parent = await _parent(rw)
    waiting, approving = await _children(rw, parent, 2)
    await _notice(rw, waiting, "B11", "answer")
    await _notice(rw, approving, "B11", "answer")
    async with rw.begin() as conn:  # digest vòng 1 đã gửi cả hai notice
        await conn.execute(text("UPDATE child_notices SET delivered_round = 1, delivered_at = now() WHERE parent_ticket_id = :p"),
                           {"p": parent})  # fmt: skip
        await conn.execute(text("INSERT INTO approvals (ticket_id, approver_id, deadline, status, action_plan_hash) "
                                "VALUES (:t, :u, now() + interval '30 minutes', 'pending', :h)"),
                           {"t": approving, "u": APPROVER, "h": "a" * 64})  # fmt: skip
    await tickets.finalize_once(parent, _parent_e9())
    orphans = [o for o in await SqlDeadlineStore(rw).orphan_children(1000) if o.ticket_id in (waiting, approving)]
    assert orphans == [OrphanChild(waiting, "answer")]


async def test_nghi_children_view_final_with_open_turn_not_ended(rw: AsyncEngine) -> None:
    """Soát lượt 2 NGHI "notice bị nuốt": con có `final_state` nhưng còn lượt `turns` mở (B20 chưa xong) → `children_view` coi CHƯA kết
    thúc; đóng lượt → kết thúc."""
    tickets = SqlTicketStore(rw)
    parent = await _parent(rw)
    [c1] = await _children(rw, parent, 1)  # `_children` mở một lượt cho con (còn mở)
    await tickets.finalize_once(c1, _final("S_ESCALATED"))
    [view] = await tickets.children_view(parent, [c1])
    assert view.final_state is None
    async with rw.begin() as conn:
        await conn.execute(text("UPDATE turns SET ended_at = now() WHERE ticket_id = :t"), {"t": c1})
    [view] = await tickets.children_view(parent, [c1])
    assert view.final_state == "S_ESCALATED"
