"""P4 tuần 8 — `SqlEscalationStore.list_page` / `get` / `close` trên Postgres 16 thật (khuôn `test_override_pg`, `test_t20b_q5_pg`).

- `close`: MỘT transaction — `escalations` (closed_at, close_result, closed_by, close_note) + `tickets.close_reason` (chỉ khi `S_ESCALATED` và
  còn NULL; không khớp → giữ nguyên + log.info) + một dòng audit `B20`/`escalation_closed` (`detail` đúng 4 khoá, không nguyên văn ghi chú).
- Hai lần đóng đồng thời (hai kết nối) → đúng một thành công, một None (route → 409); một dòng audit; ghi chú của bên thắng.
- Lỗi giữa transaction (dòng audit trùng khoá; móc `reopen` ném lỗi) → KHÔNG đóng ca, `tickets` không đổi, không dòng audit.
- Móc `reopen` (cắm phương án (A) sau này) chạy TRONG transaction: id nó trả về thành `new_ticket_id`.
- `list_page`: keyset theo `priority, created_at, escalation_id` — > 200 dòng duyệt hết, không trùng / không sót, kể cả khi trùng
  (priority, created_at); `closed` liệt kê ca đã đóng kèm 4 cột đóng.

Mã/ghi chú GIẢ. Database riêng cho module (`fresh_database`). PG chờ Mac — chạy được bằng cụm PG16 cục bộ + plugin ngoài repo.
"""

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.db.escalations import (
    CLOSE_EVENT,
    CLOSE_STEP,
    CloseRequest,
    EscalationHead,
    QueueKey,
    SqlEscalationStore,
)
from app.db.tickets import NewTicket, SqlTicketStore
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration.graph_pg import APPROVER, REQUESTER, SESSION, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
SECRET_LIKE = "mat-khau-gia-7Qx"  # chuỗi giả — ghi chú đưa vào store luôn là bản ĐÃ che; audit không được chứa nguyên văn


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


async def _exec(rw: AsyncEngine, sql: str, **params: Any) -> None:
    async with rw.begin() as conn:
        await conn.execute(text(sql), params)


async def _one(rw: AsyncEngine, sql: str, **params: Any) -> dict[str, Any]:
    async with rw.connect() as conn:
        return dict((await conn.execute(text(sql), params)).mappings().one())


async def _escalated(rw: AsyncEngine, code: str = "E1", *, deny: bool = False, created_at: datetime = T0,
                     final_state: str | None = "S_ESCALATED", close_reason: str | None = None) -> tuple[str, int]:  # fmt: skip
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=T0),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    if final_state is not None:
        await _exec(rw, "UPDATE tickets SET final_state = :f, exit_code = :c, close_reason = :r, closed_at = :at, total_turns = 1, "
                        "total_duration_seconds = 60 WHERE ticket_id = :t",
                    f=final_state, c=code if final_state == "S_ESCALATED" else None, r=close_reason, at=T0, t=ticket)  # fmt: skip
    eid = await SqlEscalationStore(rw).create(ticket_id=ticket, exit_code=code, reason_detail=None,
                                              handoff_note={"request": "x"}, is_deny_case=deny, created_at=created_at)  # fmt: skip
    return ticket, int(eid)


def _req(eid: int, result: str = "completed", note: str = "đã xử lý [BÍ_MẬT_ĐÃ_ẨN]", **kw: Any) -> CloseRequest:
    base: dict[str, Any] = {"escalation_id": eid, "close_result": result, "closed_by": APPROVER, "close_note": note,
                            "close_reason": "resolved_after_escalation", "at": T0 + timedelta(hours=1)}  # fmt: skip
    return CloseRequest(**{**base, **kw})


async def _audit_rows(rw: AsyncEngine, ticket: str) -> list[dict[str, Any]]:
    async with rw.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT * FROM audit_logs WHERE ticket_id = :t AND step = :s AND event = :e ORDER BY log_id"
        ), {"t": ticket, "s": CLOSE_STEP, "e": CLOSE_EVENT})).mappings().all()  # fmt: skip
    return [dict(r) for r in rows]


# ---- close ---------------------------------------------------------------------------------------------------------------------


async def test_pg_close_one_transaction_writes_three_tables(rw: AsyncEngine) -> None:
    ticket, eid = await _escalated(rw)
    store = SqlEscalationStore(rw)
    assert await store.get(eid) == EscalationHead(escalation_id=eid, ticket_id=ticket, exit_code="E1", is_deny_case=False,
                                                  closed_at=None)  # fmt: skip
    closed = await store.close(_req(eid))
    assert closed is not None
    assert (closed.ticket_id, closed.close_result, closed.close_reason, closed.closed_by, closed.new_ticket_id) == (
        ticket, "completed", "resolved_after_escalation", APPROVER, None)
    esc = await _one(rw, "SELECT closed_at, close_result, closed_by, close_note, new_ticket_id FROM escalations "
                         "WHERE escalation_id = :i", i=eid)  # fmt: skip
    assert esc == {"closed_at": T0 + timedelta(hours=1), "close_result": "completed", "closed_by": APPROVER,
                   "close_note": "đã xử lý [BÍ_MẬT_ĐÃ_ẨN]", "new_ticket_id": None}  # fmt: skip
    assert (await _one(rw, "SELECT close_reason FROM tickets WHERE ticket_id = :t", t=ticket))["close_reason"] == \
        "resolved_after_escalation"  # fmt: skip
    [row] = await _audit_rows(rw, ticket)
    assert row["detail"] == {"escalation_id": eid, "close_result": "completed", "closed_by": APPROVER,
                             "note_length": len("đã xử lý [BÍ_MẬT_ĐÃ_ẨN]")}  # fmt: skip
    assert row["idempotency_key"] == hashlib.sha256(f"escalation_close:{eid}".encode()).hexdigest()
    assert row["note"] is None and row["close_reason"] is None  # điểm 8 của ca nằm ở ("B20","closed"), không ở dòng này
    assert (await store.get(eid)).closed_at is not None  # type: ignore[union-attr]


async def test_pg_note_never_copied_to_audit(rw: AsyncEngine) -> None:
    ticket, eid = await _escalated(rw)
    assert await SqlEscalationStore(rw).close(_req(eid, note=f"ghi chú {SECRET_LIKE}")) is not None
    assert SECRET_LIKE not in str(await _audit_rows(rw, ticket))


async def test_pg_second_close_returns_none_nothing_changes(rw: AsyncEngine) -> None:
    ticket, eid = await _escalated(rw)
    store = SqlEscalationStore(rw)
    assert await store.close(_req(eid)) is not None
    assert await store.close(_req(eid, "confirmed_denial", "lần hai")) is None
    esc = await _one(rw, "SELECT close_result, close_note FROM escalations WHERE escalation_id = :i", i=eid)
    assert esc == {"close_result": "completed", "close_note": "đã xử lý [BÍ_MẬT_ĐÃ_ẨN]"}
    assert len(await _audit_rows(rw, ticket)) == 1


async def test_pg_concurrent_close_exactly_one_wins(rw: AsyncEngine, db: PgUrls) -> None:
    """Hai engine (hai kết nối thật) — UPDATE … WHERE closed_at IS NULL: bên chờ khoá hàng thấy hàng đã đóng → None."""
    ticket, eid = await _escalated(rw)
    other = create_async_engine(db.role("app_rw"))
    try:
        results = await asyncio.gather(
            SqlEscalationStore(rw).close(_req(eid, "completed", "bên A")),
            SqlEscalationStore(other).close(_req(eid, "confirmed_denial", "bên B")),
        )
    finally:
        await other.dispose()
    winners = [r for r in results if r is not None]
    assert len(winners) == 1 and results.count(None) == 1
    esc = await _one(rw, "SELECT close_result, close_note FROM escalations WHERE escalation_id = :i", i=eid)
    assert (esc["close_result"], esc["close_note"]) == (winners[0].close_result, winners[0].close_note)
    assert len(await _audit_rows(rw, ticket)) == 1


@pytest.mark.parametrize(
    ("final_state", "close_reason"), [("S_ESCALATED", "resolved_user_confirmed"), ("S_RESOLVED", "resolved_user_confirmed"), (None, None)]
)
async def test_pg_close_reason_skipped_logs_info(
    rw: AsyncEngine, caplog: pytest.LogCaptureFixture, final_state: str | None, close_reason: str | None
) -> None:
    ticket, eid = await _escalated(rw, final_state=final_state, close_reason=close_reason)
    with caplog.at_level(logging.INFO, logger="app.db.escalations"):
        closed = await SqlEscalationStore(rw).close(_req(eid))
    assert closed is not None and closed.close_reason == close_reason  # giá trị THẬT, không đè
    assert (await _one(rw, "SELECT close_reason FROM tickets WHERE ticket_id = :t", t=ticket))["close_reason"] == close_reason
    assert any("bỏ qua cập nhật close_reason" in r.getMessage() for r in caplog.records)
    assert len(await _audit_rows(rw, ticket)) == 1  # ca vẫn đóng


async def test_pg_deny_review_reason(rw: AsyncEngine) -> None:
    _, eid = await _escalated(rw, "E5", deny=True)
    closed = await SqlEscalationStore(rw).close(_req(eid, "confirmed_denial", close_reason="resolved_after_deny_review"))
    assert closed is not None and closed.close_reason == "resolved_after_deny_review"


async def _state(rw: AsyncEngine, ticket: str, eid: int) -> tuple[Any, ...]:
    esc = await _one(rw, "SELECT closed_at, close_result, close_note, new_ticket_id FROM escalations WHERE escalation_id = :i", i=eid)
    t = await _one(rw, "SELECT close_reason FROM tickets WHERE ticket_id = :t", t=ticket)
    return tuple(esc.values()) + (t["close_reason"], len(await _audit_rows(rw, ticket)))


async def test_pg_failure_mid_transaction_rolls_back_everything(rw: AsyncEngine) -> None:
    """Dòng audit đóng ca đã có (trùng khoá idempotency) → INSERT lỗi ở bước CUỐI → ca vẫn mở, `tickets` không đổi."""
    ticket, eid = await _escalated(rw)
    key = hashlib.sha256(f"escalation_close:{eid}".encode()).hexdigest()
    await _exec(rw, "INSERT INTO audit_logs (ticket_id, step, event, loop_seq, idempotency_key, created_at, detail) "
                    "VALUES (:t, 'X', 'chan', 0, :k, :c, '{}'::jsonb)", t=ticket, k=key, c=T0)  # fmt: skip
    with pytest.raises(IntegrityError):
        await SqlEscalationStore(rw).close(_req(eid))
    assert await _state(rw, ticket, eid) == (None, None, None, None, None, 0)


async def test_pg_reopen_hook_runs_in_same_transaction(rw: AsyncEngine) -> None:
    """Chỗ cắm (A): móc tạo ticket mới bằng CHÍNH kết nối của transaction → `new_ticket_id`; móc lỗi → không gì được ghi."""
    ticket, eid = await _escalated(rw)
    new_id = f"tk-{uuid4().hex[:8]}"

    async def reopen(conn: AsyncConnection, head: EscalationHead, req: CloseRequest) -> str:
        assert head.ticket_id == ticket and req.close_result == "reopened_as_new"
        await conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, created_at) "
                                "VALUES (:t, :r, 'employee', :q, :c)"), {"t": new_id, "r": REQUESTER, "q": req.close_note, "c": req.at})  # fmt: skip
        return new_id

    async def broken(conn: AsyncConnection, head: EscalationHead, req: CloseRequest) -> str:
        await reopen(conn, head, req)
        raise RuntimeError("tạo ticket mới lỗi giữa chừng")

    store = SqlEscalationStore(rw)
    with pytest.raises(RuntimeError):
        await store.close(_req(eid, "reopened_as_new"), reopen=broken)
    assert await _state(rw, ticket, eid) == (None, None, None, None, None, 0)
    async with rw.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM tickets WHERE ticket_id = :t"), {"t": new_id})).scalar() == 0
    closed = await store.close(_req(eid, "reopened_as_new"), reopen=reopen)
    assert closed is not None and closed.new_ticket_id == new_id
    assert (await _state(rw, ticket, eid))[3] == new_id
    _, other = await _escalated(rw)
    closed = await store.close(_req(other, "confirmed_denial"), reopen=reopen)  # móc chỉ chạy cho reopened_as_new
    assert closed is not None and closed.new_ticket_id is None


async def test_pg_close_note_check_constraint(rw: AsyncEngine) -> None:
    """Lớp chặn DB (CHECK 0013): ghi chú > 1000 không vào được — route đã 422 trước đó."""
    ticket, eid = await _escalated(rw)
    with pytest.raises(IntegrityError):
        await SqlEscalationStore(rw).close(_req(eid, note="x" * 1001))
    assert await _state(rw, ticket, eid) == (None, None, None, None, None, 0)


# ---- list_page ------------------------------------------------------------------------------------------------------------------


async def _walk(store: SqlEscalationStore, status: Any, limit: int, mine: set[int]) -> list[int]:
    ids: list[int] = []
    after: QueueKey | None = None
    while True:
        rows = await store.list_page(status, limit + 1, after)
        page = rows[:limit]
        ids += [r.escalation_id for r in page if r.escalation_id in mine]
        if len(rows) <= limit:
            return ids
        last = page[-1]
        after = QueueKey(last.priority, last.created_at, last.escalation_id)


async def test_pg_more_than_200_rows_keyset_no_dup_no_gap(rw: AsyncEngine) -> None:
    mine: dict[int, tuple[int, datetime, int]] = {}
    store = SqlEscalationStore(rw)
    for i in range(230):  # trùng (priority, created_at) nhiều — phá hoà bằng escalation_id
        _, eid = await _escalated(rw, ("E1", "E7", "E9")[i % 3], created_at=T0 + timedelta(minutes=i % 3))
        head = await _one(rw, "SELECT priority, created_at FROM escalations WHERE escalation_id = :i", i=eid)
        mine[eid] = (head["priority"], head["created_at"], eid)
    ids = await _walk(store, "open", 100, set(mine))
    assert len(ids) == len(set(ids)) == 230
    assert ids == sorted(mine, key=lambda e: mine[e])


async def test_pg_closed_page_has_close_columns(rw: AsyncEngine) -> None:
    ticket, eid = await _escalated(rw, "E2")
    store = SqlEscalationStore(rw)
    assert eid not in await _walk(store, "closed", 100, {eid})
    assert await store.close(_req(eid, note="ghi chú đã che")) is not None
    assert eid not in await _walk(store, "open", 100, {eid})
    [item] = [i for i in await store.list_page("closed", 10_000, None) if i.escalation_id == eid]
    assert (item.ticket_id, item.close_result, item.closed_by, item.close_note) == (ticket, "completed", APPROVER, "ghi chú đã che")
    assert item.closed_at == T0 + timedelta(hours=1)
