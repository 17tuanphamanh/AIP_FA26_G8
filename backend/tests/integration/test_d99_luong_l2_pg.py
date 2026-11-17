"""D-99 (17/11/2026) trên Postgres 16 thật — migration 0018 + `SqlEscalationStore.claim/raise_tier/close/handling_of/set_new_ticket` +
`SqlNotificationSource` bốn nhánh.

- CHECK của 0018: `tier` ∈ {2, 3}; `assigned_to`/`assigned_at` cùng NULL hoặc cùng có; cấp 3 ⇔ đủ 4 cột chuyển cấp; `raise_target` ∈
  {it_manager, vendor}; `user_message` 1–500 ký tự.
- `claim`: một `UPDATE` có điều kiện — người đầu thắng, người sau `taken`, bấm lại `claimed` không thêm audit; ca đóng `closed`; sai cấp
  `wrong_tier`. `raise_tier`: chỉ từ cấp 2, bỏ người nhận cũ, một dòng audit; lần hai `already_raised`.
- `close` chỉ đóng đúng cấp; ghi `user_message`; ca chưa ai nhận → người đóng thành người nhận (cùng lúc đóng → KHÔNG sinh thông báo
  "đã nhận").
- Thông báo: người gửi thấy đã nhận → đã chuyển cấp → đã đóng (kèm lời nhắn); người khác không thấy gì.

Mã/ghi chú GIẢ. Database riêng cho module.
"""

from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.db.escalations import (
    CLAIM_EVENT,
    FLOW_STEP,
    RAISE_EVENT,
    ClaimRequest,
    CloseRequest,
    RaiseRequest,
    SqlEscalationStore,
)
from app.db.notifications import SqlNotificationSource
from app.db.tickets import NewTicket, SqlTicketStore
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import APPROVER, REQUESTER, SESSION, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)
L2 = APPROVER  # role l1 trong seed — người xử lý cấp 2
OTHER = "l2-fake"
MANAGER = "mgr-fake"


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"INSERT INTO users (user_id, username, role) VALUES ('{OTHER}', 'graph.l2', 'l2'), ('{MANAGER}', 'graph.mgr', 'manager') "
            "ON CONFLICT DO NOTHING"
        ))  # fmt: skip
    yield engine
    await engine.dispose()


async def _exec(rw: AsyncEngine, sql: str, **params: Any) -> None:
    async with rw.begin() as conn:
        await conn.execute(text(sql), params)


async def _one(rw: AsyncEngine, sql: str, **params: Any) -> dict[str, Any]:
    async with rw.connect() as conn:
        return dict((await conn.execute(text(sql), params)).mappings().one())


async def _escalated(rw: AsyncEngine, code: str = "E1") -> tuple[str, int]:
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=T0),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    await _exec(rw, "UPDATE tickets SET final_state = 'S_ESCALATED', exit_code = :c, closed_at = :at, total_turns = 1, "
                    "total_duration_seconds = 60 WHERE ticket_id = :t", c=code, at=T0, t=ticket)  # fmt: skip
    eid = await SqlEscalationStore(rw).create(ticket_id=ticket, exit_code=code, reason_detail=None, handoff_note={"request": "x"},
                                              is_deny_case=False, created_at=T0)  # fmt: skip
    return ticket, int(eid)


def _close(eid: int, by: str, *, tier: int = 2, at: datetime = T0 + timedelta(hours=3), msg: str | None = None,
           result: str = "completed") -> CloseRequest:  # fmt: skip
    return CloseRequest(escalation_id=eid, close_result=result, closed_by=by, close_note="đã xử lý",  # type: ignore[arg-type]
                        close_reason="resolved_after_escalation", at=at, tier=tier, user_message=msg)  # fmt: skip


async def _flow_audit(rw: AsyncEngine, ticket: str) -> list[str]:
    async with rw.connect() as conn:
        rows: Sequence[str] = (await conn.execute(text(
            "SELECT event FROM audit_logs WHERE ticket_id = :t AND step = :s ORDER BY log_id"
        ), {"t": ticket, "s": FLOW_STEP})).scalars().all()  # fmt: skip
    return list(rows)


# ---- CHECK của 0018 -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE escalations SET tier = 4 WHERE escalation_id = :e",
        "UPDATE escalations SET tier = 3 WHERE escalation_id = :e",  # thiếu 4 cột chuyển cấp
        "UPDATE escalations SET assigned_to = 'l1-fake' WHERE escalation_id = :e",  # thiếu assigned_at
        "UPDATE escalations SET raise_target = 'ceo' WHERE escalation_id = :e",
        "UPDATE escalations SET user_message = repeat('x', 501) WHERE escalation_id = :e",
        "UPDATE escalations SET user_message = '' WHERE escalation_id = :e",
    ],
)
async def test_0018_checks(rw: AsyncEngine, sql: str) -> None:
    _, eid = await _escalated(rw)
    with pytest.raises(IntegrityError):
        await _exec(rw, sql, e=eid)


async def test_old_rows_default_tier2_unassigned(rw: AsyncEngine) -> None:
    _, eid = await _escalated(rw)
    row = await _one(rw, "SELECT tier, assigned_to, assigned_at, raised_at, user_message FROM escalations WHERE escalation_id = :e", e=eid)
    assert row == {"tier": 2, "assigned_to": None, "assigned_at": None, "raised_at": None, "user_message": None}


# ---- nhận ca, chuyển cấp, đóng ---------------------------------------------------------------------------------------------------


async def test_claim_first_wins_reclaim_noop_and_misses(rw: AsyncEngine) -> None:
    store = SqlEscalationStore(rw)
    ticket, eid = await _escalated(rw)
    assert await store.claim(ClaimRequest(eid, L2, 2, T0 + timedelta(minutes=5))) == "claimed"
    assert await store.claim(ClaimRequest(eid, L2, 2, T0 + timedelta(minutes=6))) == "claimed"  # bấm lại
    assert await store.claim(ClaimRequest(eid, OTHER, 2, T0 + timedelta(minutes=7))) == "taken"
    assert await store.claim(ClaimRequest(eid, MANAGER, 3, T0 + timedelta(minutes=7))) == "wrong_tier"
    assert await store.claim(ClaimRequest(999_999, L2, 2, T0)) == "not_found"
    row = await _one(rw, "SELECT assigned_to, assigned_at FROM escalations WHERE escalation_id = :e", e=eid)
    assert row == {"assigned_to": L2, "assigned_at": T0 + timedelta(minutes=5)}
    assert await _flow_audit(rw, ticket) == [CLAIM_EVENT]
    assert await store.close(_close(eid, L2)) is not None
    assert await store.claim(ClaimRequest(eid, OTHER, 2, T0 + timedelta(hours=4))) == "closed"


async def test_raise_then_l3_queue_close_and_tier_guard(rw: AsyncEngine) -> None:
    store = SqlEscalationStore(rw)
    ticket, eid = await _escalated(rw, "E5")
    await store.claim(ClaimRequest(eid, L2, 2, T0 + timedelta(minutes=5)))
    raise_req = RaiseRequest(eid, L2, "it_manager", "Cần ngoại lệ [BÍ_MẬT_ĐÃ_ẨN]", T0 + timedelta(minutes=30))
    assert await store.raise_tier(raise_req) == "raised"
    assert await store.raise_tier(raise_req) == "already_raised"
    row = await _one(rw, "SELECT tier, assigned_to, assigned_at, raised_by, raise_target FROM escalations WHERE escalation_id = :e", e=eid)
    assert row == {"tier": 3, "assigned_to": None, "assigned_at": None, "raised_by": L2, "raise_target": "it_manager"}
    l2_ids = {i.escalation_id for i in await store.list_page("open", 500, None, tier=2)}
    l3 = {i.escalation_id: i for i in await store.list_page("open", 500, None, tier=3)}
    assert eid not in l2_ids and l3[eid].raise_target == "it_manager" and l3[eid].raised_at == T0 + timedelta(minutes=30)
    assert await store.close(_close(eid, L2, tier=2)) is None  # L2 không đóng được ca đã lên cấp 3
    closed = await store.close(_close(eid, MANAGER, tier=3, msg="Đã duyệt ngoại lệ, bạn thử lại nhé.", result="confirmed_denial"))
    assert closed is not None and closed.user_message == "Đã duyệt ngoại lệ, bạn thử lại nhé."
    row = await _one(rw, "SELECT assigned_to, assigned_at, user_message, closed_by FROM escalations WHERE escalation_id = :e", e=eid)
    assert (row["assigned_to"], row["closed_by"]) == (MANAGER, MANAGER)  # chưa ai nhận ở cấp 3 → người đóng
    assert await _flow_audit(rw, ticket) == [CLAIM_EVENT, RAISE_EVENT]
    async with rw.connect() as conn:
        detail: dict[str, Any] = (await conn.execute(text(
            "SELECT detail FROM audit_logs WHERE ticket_id = :t AND event = :e"), {"t": ticket, "e": RAISE_EVENT})).scalar_one()  # fmt: skip
    assert detail == {"escalation_id": eid, "by": L2, "target": "it_manager", "note_length": len(raise_req.note)}


async def test_handling_and_set_new_ticket(rw: AsyncEngine) -> None:
    store = SqlEscalationStore(rw)
    ticket, eid = await _escalated(rw)
    [h] = await store.handling_of([ticket])
    assert (h.escalation_id, h.tier, h.assigned_at, h.closed_at) == (eid, 2, None, None)
    await store.set_new_ticket(eid, ticket)  # chưa đóng bằng reopened_as_new → không ghi
    assert (await _one(rw, "SELECT new_ticket_id FROM escalations WHERE escalation_id = :e", e=eid))["new_ticket_id"] is None
    assert await store.close(_close(eid, L2, result="reopened_as_new")) is not None
    new_ticket, _ = await _escalated(rw)
    await store.set_new_ticket(eid, new_ticket)
    [h] = await store.handling_of([ticket])
    assert (h.close_result, h.new_ticket_id) == ("reopened_as_new", new_ticket)
    assert await store.handling_of([]) == []


# ---- thông báo -------------------------------------------------------------------------------------------------------------------


async def test_notifications_follow_each_step_only_for_requester(rw: AsyncEngine) -> None:
    store, source = SqlEscalationStore(rw), SqlNotificationSource(rw)
    ticket, eid = await _escalated(rw)
    _, quiet = await _escalated(rw)  # đóng không qua nhận ca → không có thông báo "đã nhận"
    await store.claim(ClaimRequest(eid, L2, 2, T0 + timedelta(minutes=5)))
    await store.raise_tier(RaiseRequest(eid, L2, "vendor", "Cần thay linh kiện", T0 + timedelta(minutes=10)))
    await store.claim(ClaimRequest(eid, MANAGER, 3, T0 + timedelta(minutes=20)))
    await store.close(_close(eid, MANAGER, tier=3, msg="Linh kiện về thứ Hai."))
    await store.close(_close(quiet, L2))
    mine = [r for r in await source.page(REQUESTER, 50, None) if r.ticket_id == ticket or r.id.endswith(f":{quiet}")]
    kinds = [(r.id.split(":")[0], r.kind, r.result) for r in mine if r.id.endswith(f":{eid}")]
    assert kinds == [("esc", "escalation_closed", "completed"), ("escc", "escalation_claimed", "in_progress"),
                     ("escr", "escalation_raised", "raised")]  # fmt: skip
    by_kind = {r.kind: r for r in mine if r.id.endswith(f":{eid}")}
    assert by_kind["escalation_closed"].user_message == "Linh kiện về thứ Hai."
    assert (by_kind["escalation_claimed"].tier, by_kind["escalation_raised"].raise_target) == (3, "vendor")
    assert [r.kind for r in mine if r.id.endswith(f":{quiet}")] == ["escalation_closed"]
    assert await source.page(OTHER, 50, None) == []
