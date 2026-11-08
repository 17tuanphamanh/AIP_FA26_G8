"""B10 thật trên Postgres THẬT (phase3 mục 10.5 g1, g2; chốt Q-3g-3 3g): store SQL, `AsyncPostgresSaver`, `effects.once`
và `lineage` ghi cùng transaction với audit. Graph `nodes="real"`: B1 → B2 → B3 → B6 (VPN giả) → B8 → B10 (`FixtureRag` =
chunk KB fixture thật + `expand` thật), ScriptedLLM `vpn_scripts(need="info")`.

- g2: process chết SAU khi goto của B10 đã commit (audit + lineage), TRƯỚC checkpoint → worker chạy lại B10 trong CÙNG lượt:
  đúng 1 tin (`side_effects` notify_user), đúng 1 dòng `lineage`, 1 dòng audit `deflected_info_only`.
- g1: resume `confirm_wait` hai lần (lần đầu chết trước audit của B19 → recover) → vẫn 1 `notify_user` của B10, 1 câu trả
  lời trong `conversation`.

Mỗi ca một người gửi RIÊNG (`seed_requester`): DB `migrated` dùng chung cả phiên pytest, còn B3 báo trùng (M1) gửi thêm một tin
`duplicate` nếu người gửi có ticket vpn còn mở do ca khác để lại — đếm "1 tin B10" / "1 notify_user" mới đo đúng B10.
"""

from collections.abc import AsyncIterator, Mapping
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from app.audit.writer import AuditWriter
from app.core.clock import FakeClock
from app.db.tickets import NewTicket, SqlTicketStore
from app.domain.states import S_CONFIRMING, S_RESOLVED
from app.graph.late_event import deliver_event
from app.graph.worker_jobs import WorkerJobs
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.graph import Crash
from tests.fakes.kb_index import KBV, fixture_rag
from tests.fakes.llm import make_gateway
from tests.fixtures.llm.vpn import vpn_scripts
from tests.integration.graph_pg import (
    OwnRequester,
    open_pg_runtime,
    scalar,
    seed_requester,
    seed_users,
)
from tests.integration.pg import PgUrls

pytestmark = pytest.mark.asyncio

QUESTION = "VPN công ty dùng cổng nào?"


@pytest_asyncio.fixture
async def arw(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def who(arw: AsyncEngine) -> OwnRequester:
    return await seed_requester(arw)


class DieAfterAudit(AuditWriter):
    """Audit (+ lineage) của goto B10 `deflected_info_only` ĐÃ commit rồi process chết — checkpoint của B10 chưa ghi."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.armed = True

    async def record(self, row: Mapping[str, Any], *, lineage: Mapping[str, Any] | None = None) -> bool:
        present = await super().record(row, lineage=lineage)
        if self.armed and row["step"] == "B10" and row["event"] == "deflected_info_only":
            self.armed = False
            raise Crash("SIGKILL sau goto B10, trước checkpoint")
        return present


class DieBeforeConfirmAudit(AuditWriter):
    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.armed = True

    async def record(self, row: Mapping[str, Any], *, lineage: Mapping[str, Any] | None = None) -> bool:
        if self.armed and row["event"] == "user_confirmed":
            self.armed = False
            raise Crash("SIGKILL trong confirm_wait, trước audit + checkpoint")
        return await super().record(row, lineage=lineage)


async def _ticket(rw: AsyncEngine, clock: FakeClock, who: OwnRequester) -> tuple[str, str]:
    ticket, turn = f"b10-{uuid4().hex[:10]}", f"turn-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=who.user_id, requester_role="employee", requester_dept="it",
                  session_id=who.session_id, redacted_request=QUESTION, created_at=clock.now()),
        turn_id=turn,
    )  # fmt: skip
    return ticket, turn


async def _count(rw: AsyncEngine, sql: str, ticket: str) -> int:
    return int(await scalar(rw, sql, t=ticket))


def _answers(values: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [m for m in values.get("conversation") or [] if m.get("kind") == "answer"]


async def test_g2_crash_after_b10_goto_rerun_same_turn_single_notice_single_lineage_pg(
    migrated: PgUrls, arw: AsyncEngine, who: OwnRequester
) -> None:
    clock = FakeClock()
    url = migrated.role("app_rw")
    ticket, turn = await _ticket(arw, clock, who)
    rag = await fixture_rag(["KB-VPN-001#v1#1", "KB-VPN-003#v1#0"], clock)
    llm = make_gateway(vpn_scripts(need="info"), clock=clock).client  # type: ignore[arg-type]
    async with open_pg_runtime(url, clock=clock, nodes="real", llm=llm, rag=rag, ad=who.ad(),
                               audit=DieAfterAudit(arw)) as rt:  # fmt: skip
        with pytest.raises(Crash):
            await rt.runner.run_new(ticket, turn)
        first_sends = rt.notifier.count(ticket)
    assert first_sends == 1
    assert await _count(arw, "SELECT count(*) FROM lineage WHERE ticket_id = :t", ticket) == 1  # commit cùng audit

    clock.advance(timedelta(minutes=3))
    async with open_pg_runtime(url, clock=clock, nodes="real", llm=llm, rag=rag, ad=who.ad(), can_execute=False) as rt:
        assert await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns() >= 1
        values = (await rt.runner.snapshot(ticket)).values
        second_sends = rt.notifier.count(ticket)
    assert values["status"] == S_CONFIRMING and second_sends == 0  # chạy lại B10: effects.once trả ref cũ
    assert len(_answers(values)) == 1
    assert await _count(arw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t AND kind = 'notify_user' "
                             "AND step = 'B10'", ticket) == 1  # fmt: skip
    assert await _count(arw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t AND kind = 'deadline_set' "
                             "AND step = 'B10'", ticket) == 1  # fmt: skip
    assert await _count(arw, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t AND step = 'B10' "
                             "AND event = 'deflected_info_only'", ticket) == 1  # fmt: skip
    # Q-3g-3: chạy lại node trong cùng lượt → vẫn ĐÚNG 1 dòng lineage (NOT EXISTS), commit_sha NULL ở Phase 3
    assert await _count(arw, "SELECT count(*) FROM lineage WHERE ticket_id = :t", ticket) == 1
    row = await scalar(arw, "SELECT concat_ws('|', turn_id, step, prompt_id, prompt_version, kb_version, "
                            "coalesce(commit_sha, 'NULL')) FROM lineage WHERE ticket_id = :t", t=ticket)  # fmt: skip
    assert row == f"{turn}|B10|b10_answer|2|{KBV}|NULL"


async def test_g1_resume_confirm_wait_twice_single_b10_notice_pg(
    migrated: PgUrls, arw: AsyncEngine, who: OwnRequester
) -> None:
    clock = FakeClock()
    url = migrated.role("app_rw")
    ticket, turn = await _ticket(arw, clock, who)
    rag = await fixture_rag(["KB-VPN-001#v1#1"], clock)
    llm = make_gateway(vpn_scripts(need="info"), clock=clock).client  # type: ignore[arg-type]
    async with open_pg_runtime(url, clock=clock, nodes="real", llm=llm, rag=rag, ad=who.ad()) as rt:
        assert (res := await rt.runner.run_new(ticket, turn)) is not None and res.status == S_CONFIRMING
    async with open_pg_runtime(url, clock=clock, nodes="real", llm=llm, rag=rag, ad=who.ad(),
                               audit=DieBeforeConfirmAudit(arw)) as rt:  # fmt: skip
        with pytest.raises(Crash):
            await deliver_event(rt.runner, ticket, S_CONFIRMING, {"kind": "confirmed"})
    clock.advance(timedelta(minutes=3))
    async with open_pg_runtime(url, clock=clock, nodes="real", llm=llm, rag=rag, ad=who.ad(), can_execute=False) as rt:
        assert await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns() >= 1
        values = (await rt.runner.snapshot(ticket)).values
    assert values["status"] == S_RESOLVED
    assert len(_answers(values)) == 1
    assert await _count(arw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t AND kind = 'notify_user' "
                             "AND step = 'B10'", ticket) == 1  # fmt: skip
    assert await _count(arw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t AND kind = 'notify_user'",
                        ticket) == 1  # B19 → S_RESOLVED: B20 không gửi thêm (không exit_code)  # fmt: skip


async def test_q3g3_audit_insert_fails_lineage_rolled_back_pg(arw: AsyncEngine, who: OwnRequester) -> None:
    """Chốt DỪNG 1: dòng audit INSERT lỗi (vi phạm CHECK `exit_code`) → rollback CẢ transaction → 0 dòng lineage — audit và
    lineage của một bước cùng có hoặc cùng không."""
    from app.db.lineage import LINEAGE_COLUMNS
    from sqlalchemy.exc import IntegrityError

    clock = FakeClock()
    ticket, turn = await _ticket(arw, clock, who)
    row = {"ticket_id": ticket, "turn_id": turn, "loop_seq": 0, "idempotency_key": f"k-{uuid4().hex}", "step": "B10",
           "event": "deflected_info_only", "from_status": "S_RETRIEVING", "to_status": "S_CONFIRMING",
           "created_at": clock.now(), "detail": {}, "exit_code": "E99"}  # fmt: skip
    lineage = {"ticket_id": ticket, "turn_id": turn, "step": "B10", "created_at": clock.now(),
               "prompt_id": "b10_answer", "prompt_version": "1", "model": "scripted", "kb_version": KBV}  # fmt: skip
    assert set(lineage) <= LINEAGE_COLUMNS
    with pytest.raises(IntegrityError):
        await AuditWriter(arw).record(row, lineage=lineage)
    assert await _count(arw, "SELECT count(*) FROM lineage WHERE ticket_id = :t", ticket) == 0
    assert await _count(arw, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t AND step = 'B10'", ticket) == 0
    # đối chứng: cùng dòng với exit_code hợp lệ → cả hai được ghi
    await AuditWriter(arw).record({**row, "exit_code": None}, lineage=lineage)
    assert await _count(arw, "SELECT count(*) FROM lineage WHERE ticket_id = :t", ticket) == 1
