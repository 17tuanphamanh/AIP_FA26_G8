"""B20 trên Postgres 16 thật (B20 mục 11 — phần Phase 2): E0–E9 → đúng 1 dòng `escalations`, priority
lấy từ `exit_code_priority` (seed), `handoff_note` JSONB 4 phần; điểm log 8 qua CHECK của DB; B20 chạy
lại → không trùng, audit khớp `tickets` (Q-C); `finalize_once` không đè; hàng đợi L2 sắp đúng, bỏ ticket
cha; giới hạn phục hồi với `turns.recover_attempts` thật (migration 0005, Q-B)."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.escalations import SqlEscalationStore
from app.db.tickets import SqlTicketStore
from app.domain.final import FinalSummary
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL
from app.graph.late_event import deliver_event
from app.graph.runner import FINALIZE_FAILED
from app.graph.worker_jobs import WorkerJobs
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.graph import Crash
from tests.integration.graph_pg import (
    SESSION,
    PgRuntime,
    create_ticket,
    open_pg_runtime,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database

NOW = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)
# B20 mục 4.1 — đối chiếu với seed thật trong DB (test đầu tiên).
EXPECTED_RANK = {"E7": 1, "E0": 2, "E6": 3, "E2": 4, "E9": 4, "E5": 5, "E1": 6, "E3": 6, "E4": 6, "E8": 6}
PLANS: dict[str, dict[str, str]] = {
    "E0": {"b02_screen": "injection"}, "E1": {"b03_classify": "out_of_scope"},
    "E2": {"b06_diagnose": "tool_error"}, "E3": {"b08_retrieve": "no_evidence"},
    "E4": {"b11_slots": "missing"}, "E5": {"b12_assess": "deny"}, "E6": {},
    "E7": {"b12_assess": "auto", "b17_execute": "fail"}, "E8": {"b12_assess": "auto"},
    "E9": {"b06_diagnose": "raise"},
}  # fmt: skip
THEN: dict[str, tuple[str, dict[str, str]]] = {
    "E4": (S_CLARIFYING, {"kind": "timeout"}), "E6": (S_PENDING_APPROVAL, {"kind": "timeout"}),
    "E8": (S_CONFIRMING, {"kind": "unresolved"}),
}  # fmt: skip


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
    """`created_at = NOW` (mốc FakeClock): thời lượng đo được thật, không bị kẹp về 0 vì lệch với
    `now()` của Postgres — bản đầu của test chạy lại xanh oan dưới mutation vì lý do này."""
    ticket = f"b20-{uuid4().hex[:12]}"
    await create_ticket(rw, ticket, created_at=NOW)
    return ticket


async def _submit(rt: PgRuntime, ticket: str, **plan: str) -> Any:
    rt.scenario.plan(ticket, **plan)
    return await rt.runner.submit(ticket, session_id=SESSION, redacted_request="Yêu cầu đã che")


async def _rows(rw: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with rw.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


class FailingTickets(SqlTicketStore):
    """`finalize_once` luôn hỏng: Exception (bug) hoặc `Crash` (process bị giết, không kịp ghi gì)."""

    def __init__(self, engine: AsyncEngine, error: BaseException) -> None:
        super().__init__(engine)
        self.error = error
        self.calls = 0

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        self.calls += 1
        # Bản MỚI mỗi lần: ném lại cùng một đối tượng thì traceback cộng dồn qua các lần thử.
        raise type(self.error)(*self.error.args)


class CrashAfterFinalize(SqlTicketStore):
    """`finalize_once` THẬT (commit xuống DB) rồi process "chết" ngay — trước điểm log 8 (Q-C)."""

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        await super().finalize_once(ticket_id, summary)
        raise Crash("process chết sau finalize_once, trước điểm log 8")


# ---- seed + E0–E9 -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_priority_matches_b20_4_1(rw: AsyncEngine) -> None:
    rows = await _rows(rw, "SELECT exit_code, rank FROM exit_code_priority")
    assert {code: rank for code, rank in rows} == EXPECTED_RANK


@pytest.mark.asyncio
@pytest.mark.parametrize("code", sorted(EXPECTED_RANK))
async def test_each_exit_code_one_escalation_row(db: PgUrls, rw: AsyncEngine, code: str) -> None:
    ticket = await _ticket(rw)
    async with open_pg_runtime(db.role("app_rw"), clock=FakeClock(NOW)) as rt:
        await _submit(rt, ticket, **PLANS[code])
        if code in THEN:
            status, event = THEN[code]
            await deliver_event(rt.runner, ticket, status, event)
    [(exit_code, priority, deny, note)] = await _rows(
        rw, "SELECT exit_code, priority, is_deny_case, handoff_note FROM escalations "
        "WHERE ticket_id=:t", t=ticket,
    )  # fmt: skip
    assert (exit_code, priority, deny) == (code, EXPECTED_RANK[code], code == "E5")
    assert set(note) == {"request", "done_so_far", "why_escalated", "next_for_l2"}
    assert note["request"] == "Yêu cầu đã che"
    [final] = await _rows(
        rw, "SELECT final_state, exit_code, total_turns, total_duration_seconds, closed_at "
        "FROM tickets WHERE ticket_id=:t", t=ticket,
    )  # fmt: skip
    [point8] = await _rows(
        rw, "SELECT final_state, exit_code, total_turns, total_duration_seconds FROM audit_logs "
        "WHERE ticket_id=:t AND step='B20' AND event='closed'", t=ticket,
    )  # fmt: skip
    assert final.exit_code == code and final.closed_at is not None
    assert tuple(point8) == tuple(final)[:4]  # điểm log 8 == dòng tickets (Q-C)
    kinds = await scalar(rw, "SELECT string_agg(kind, ',' ORDER BY kind) FROM side_effects "
                             "WHERE ticket_id=:t AND step='B20'", t=ticket)  # fmt: skip
    assert kinds == "escalation_create,notify_user"


# ---- chạy lại / ghi một lần -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b20_rerun_no_duplicates_and_audit_matches_ticket(db: PgUrls, rw: AsyncEngine) -> None:
    """Process chết giữa lúc gửi tin (sau `finalize_once` + `escalation_create` đã commit) → recover
    5 phút sau: vẫn 1 escalation, 1 tin, 1 điểm log 8; thời lượng trong audit = trong tickets (lần 1)."""
    ticket = await _ticket(rw)
    clock = FakeClock(NOW)
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        rt.notifier.crash_once.add(ticket)
        with pytest.raises(Crash):
            await _submit(rt, ticket, b12_assess="deny")
    turn = await scalar(rw, "SELECT turn_id FROM turns WHERE ticket_id=:t AND ended_at IS NULL", t=ticket)
    clock.advance(timedelta(minutes=5))
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        r = await rt.runner.recover(ticket, turn)
        assert r is not None and r.waiting_at is None and len(rt.notifier.sent) == 1
    assert await scalar(rw, "SELECT count(*) FROM escalations WHERE ticket_id=:t", t=ticket) == 1
    assert await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id=:t AND event='closed'",
                        t=ticket) == 1  # fmt: skip
    [(audit_dur, ticket_dur)] = await _rows(
        rw, "SELECT a.total_duration_seconds, t.total_duration_seconds FROM audit_logs a "
        "JOIN tickets t USING (ticket_id) WHERE a.ticket_id=:t AND a.event='closed'", t=ticket,
    )  # fmt: skip
    # Lần đầu ghi lúc NOW (0 giây); lần chạy lại 5 phút sau mà đè thì tickets = 300 ≠ audit.
    assert (audit_dur, ticket_dur) == (0, 0)


@pytest.mark.asyncio
async def test_crash_between_finalize_and_point8_audit_uses_stored_row(
    db: PgUrls, rw: AsyncEngine
) -> None:
    """Ca cốt lõi của Q-C trên SQL thật: lần 1 ghi `tickets` (0 giây) rồi chết TRƯỚC điểm log 8; recover
    5 phút sau → điểm log 8 phải lấy từ dòng `finalize_once` đọc lại trong DB (0), không phải bản tính
    lại (300). Không có dòng audit nào từ lần 1 — lần chạy lại là lần DUY NHẤT ghi điểm log 8."""
    ticket = await _ticket(rw)
    clock = FakeClock(NOW)
    async with open_pg_runtime(
        db.role("app_rw"), clock=clock, tickets=CrashAfterFinalize(rw)
    ) as rt:  # fmt: skip
        with pytest.raises(Crash):
            await _submit(rt, ticket, b12_assess="deny")
    assert await scalar(rw, "SELECT total_duration_seconds FROM tickets WHERE ticket_id=:t", t=ticket) == 0
    assert await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id=:t AND event='closed'",
                        t=ticket) == 0  # fmt: skip
    turn = await scalar(rw, "SELECT turn_id FROM turns WHERE ticket_id=:t AND ended_at IS NULL", t=ticket)
    clock.advance(timedelta(minutes=5))
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:  # process mới, store thật
        r = await rt.runner.recover(ticket, turn)
        assert r is not None and r.waiting_at is None
    [(audit_dur, ticket_dur, audit_closed, ticket_closed)] = await _rows(
        rw, "SELECT a.total_duration_seconds, t.total_duration_seconds, a.final_state, t.final_state "
        "FROM audit_logs a JOIN tickets t USING (ticket_id) WHERE a.ticket_id=:t AND a.event='closed'",
        t=ticket,
    )  # fmt: skip
    assert (audit_dur, ticket_dur) == (0, 0)  # audit lấy dòng đã lưu, không phải 300 của lần chạy lại
    assert audit_closed == ticket_closed == "S_ESCALATED"
    assert await scalar(rw, "SELECT count(*) FROM escalations WHERE ticket_id=:t", t=ticket) == 1


@pytest.mark.asyncio
async def test_finalize_once_never_overwrites(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    store = SqlTicketStore(rw)
    first = FinalSummary("S_ESCALATED", "E2", None, None, "escalated", None, False, None, None, 1, 10, NOW)
    later = FinalSummary("S_RESOLVED", None, None, "resolved_user_confirmed", "auto", None, False,
                         "vpn", {"a": 1}, 3, 99, NOW + timedelta(hours=1))  # fmt: skip
    assert await store.finalize_once(ticket, first) == first
    assert await store.finalize_once(ticket, later) == first  # trả dòng đang có, không đè


# ---- hàng đợi L2 ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_sorted_by_seed_priority_without_parents(rw: AsyncEngine) -> None:
    """Chèn XÁO TRỘN (E1 đầu, E7 cuối). E2/E9 cùng hạng 4: E9 chèn TRƯỚC (id nhỏ hơn) nhưng
    `created_at` MUỘN hơn → sắp đúng phải ra E2 trước E9 (theo created_at, không theo id)."""
    store = SqlEscalationStore(rw)
    ours: dict[str, str] = {}
    created = {"E9": NOW + timedelta(seconds=10)}
    for code in ("E1", "E5", "E9", "E2", "E6", "E0", "E7"):
        ours[code] = await _ticket(rw)
        await store.create(ticket_id=ours[code], exit_code=code, reason_detail=None,
                           handoff_note={"request": "x"}, is_deny_case=False,
                           created_at=created.get(code, NOW))  # fmt: skip
    parent = await _ticket(rw)
    async with rw.begin() as conn:  # scalar() không commit — UPDATE phải trong transaction riêng
        await conn.execute(text("UPDATE tickets SET is_parent = true WHERE ticket_id=:t"), {"t": parent})
    await store.create(ticket_id=parent, exit_code="E7", reason_detail=None,
                       handoff_note={"request": "x"}, is_deny_case=False, created_at=NOW)  # fmt: skip
    queue = [i for i in await store.list_open(1000) if i.ticket_id in {*ours.values(), parent}]
    assert [i.exit_code for i in queue] == ["E7", "E0", "E6", "E2", "E9", "E5", "E1"]
    assert parent not in {i.ticket_id for i in queue}
    assert queue[0].label == "Rất cao" and queue[0].created_at == NOW


# ---- giới hạn phục hồi (migration 0005) -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("bug cố định"), Crash("SIGKILL")], ids=["bug", "killed"])
async def test_recover_limit_on_postgres(db: PgUrls, rw: AsyncEngine, error: BaseException) -> None:
    ticket = await _ticket(rw)
    clock = FakeClock(NOW)
    tickets = FailingTickets(rw, error)
    async with open_pg_runtime(db.role("app_rw"), clock=clock, tickets=tickets) as rt:
        with pytest.raises(type(error)):
            await _submit(rt, ticket, b12_assess="deny")
        jobs = WorkerJobs(rt.runner, rt.deadlines, rt.turns)
        for _ in range(3):
            clock.advance(timedelta(minutes=3))
            if isinstance(error, Crash):
                with pytest.raises(Crash):
                    await jobs.scan_stale_turns()
            else:
                await jobs.scan_stale_turns()
        clock.advance(timedelta(minutes=3))
        await jobs.scan_stale_turns()  # lần 4: ngừng thử
        clock.advance(timedelta(minutes=3))
        await jobs.scan_stale_turns()  # lượt đã đóng: không đụng tới
    assert tickets.calls == 4  # lượt gốc + 3 lần worker
    [(attempts, ended)] = await _rows(
        rw, "SELECT recover_attempts, ended_at IS NOT NULL FROM turns WHERE ticket_id=:t", t=ticket
    )
    assert (attempts, ended) == (4, True)
    [detail] = await _rows(rw, "SELECT detail FROM audit_logs WHERE ticket_id=:t AND event=:e",
                           t=ticket, e=FINALIZE_FAILED)  # fmt: skip
    assert detail[0]["recover_attempts"] == 3 and detail[0]["node"] == "b20_audit"
