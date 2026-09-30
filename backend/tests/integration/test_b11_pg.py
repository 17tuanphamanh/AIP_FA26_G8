"""g23 (PLAN-3g, chốt P5): 3 lượt hỏi B11 trên Postgres THẬT — notifier nhận đúng 3 câu hỏi; `side_effects` có đúng 3 dòng
`notify_user` của B11, KHÁC khoá (khoá theo lượt: `turn_id` + `sub=f"q{n}"`); chạy lại lượt hỏi thứ 2 (process chết sau khi
goto của B11 đã commit, trước checkpoint → worker recover) KHÔNG gửi thêm.

Graph `nodes="real"`, người gửi `nv-graph` (không có máy trong seed → B6 không suy được máy), ScriptedLLM `vpn_scripts`
không gợi ý hành động → thiếu cả `device_id` lẫn `action`. Trả lời: lạc đề → "PC-0977" → lạc đề → E4 `clarification_exhausted`.
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
from app.domain.states import S_CLARIFYING, S_ESCALATED
from app.graph.late_event import deliver_event
from app.graph.worker_jobs import WorkerJobs
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.graph import Crash
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts
from tests.integration.graph_pg import (
    REQUESTER,
    SESSION,
    open_pg_runtime,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls
from tests.unit.test_b11_slots import _rag

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def arw(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


class DieAfterSecondAsk(AuditWriter):
    """Audit của goto B11 `asked` ở lượt hỏi THỨ HAI đã commit (cùng `side_effects` notify/hạn) rồi process chết."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.asked = 0

    async def record(self, row: Mapping[str, Any], *, lineage: Mapping[str, Any] | None = None) -> bool:
        present = await super().record(row, lineage=lineage)
        if row["step"] == "B11" and row["event"] == "asked":
            self.asked += 1
            if self.asked == 2:
                raise Crash("SIGKILL sau goto B11 lượt hỏi 2, trước checkpoint")
        return present


def _asks(sent: list[tuple[str, str, str]], ticket: str) -> int:
    """Câu hỏi B11 (needs=answer) CỦA ticket này. DB PG dùng chung cả phiên test: `scan_stale_turns` còn phục hồi lượt treo
    của ticket test KHÁC (file chạy trước) và chúng cũng gửi tin qua cùng notifier → đếm chung thì sai."""
    return len([s for s in sent if s[0] == ticket and s[2] == "answer"])


async def test_g23_three_questions_three_distinct_effects_rerun_sends_nothing_pg(
    migrated: PgUrls, arw: AsyncEngine
) -> None:
    clock = FakeClock()
    url = migrated.role("app_rw")
    ticket, turn = f"b11-{uuid4().hex[:10]}", f"turn-{uuid4().hex[:8]}"
    await SqlTicketStore(arw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN không vào được", created_at=clock.now()),
        turn_id=turn,
    )  # fmt: skip
    llm = make_gateway(vpn_scripts(action=None), clock=clock).client  # type: ignore[arg-type]
    rag: FakeRag = _rag()
    sent: list[tuple[str, str, str]] = []
    async with open_pg_runtime(url, clock=clock, nodes="real", llm=llm, rag=rag, audit=DieAfterSecondAsk(arw)) as rt:
        assert (res := await rt.runner.run_new(ticket, turn)) is not None and res.status == S_CLARIFYING  # hỏi lượt 1
        with pytest.raises(Crash):
            await deliver_event(rt.runner, ticket, S_CLARIFYING, {"kind": "user_reply", "text": "hôm nay trời đẹp quá"})
        sent += rt.notifier.sent
    assert _asks(sent, ticket) == 2  # lượt 2 đã gửi rồi mới "chết"

    clock.advance(timedelta(minutes=3))
    async with open_pg_runtime(url, clock=clock, nodes="real", llm=llm, rag=rag, can_execute=False) as rt:
        assert await WorkerJobs(rt.runner, rt.deadlines, rt.turns).scan_stale_turns() >= 1  # chạy lại lượt 2
        assert (await rt.runner.snapshot(ticket)).values["clarification_turns"] == 2
        await deliver_event(rt.runner, ticket, S_CLARIFYING, {"kind": "user_reply", "text": "PC-0977"})
        values = (await deliver_event(rt.runner, ticket, S_CLARIFYING,
                                      {"kind": "user_reply", "text": "không biết nữa"})).values  # fmt: skip
        sent += rt.notifier.sent
    assert (values["status"], values["exit_code"], values["escalation_reason_detail"]) == (
        S_ESCALATED, "E4", "clarification_exhausted",
    )  # fmt: skip
    assert _asks(sent, ticket) == 3  # đo ở NƠI NHẬN: đúng 3 câu hỏi, chạy lại không gửi thêm
    assert len([m for m in values["conversation"] if m.get("kind") == "question"]) == 3
    keys = await scalar(arw, "SELECT count(DISTINCT effect_key) FROM side_effects WHERE ticket_id = :t "
                             "AND kind = 'notify_user' AND step = 'B11'", t=ticket)  # fmt: skip
    rows = await scalar(arw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t AND kind = 'notify_user' "
                             "AND step = 'B11'", t=ticket)  # fmt: skip
    assert (rows, keys) == (3, 3)
    waits = await scalar(arw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t AND kind = 'deadline_set' "
                              "AND step = 'B11'", t=ticket)  # fmt: skip
    assert waits == 3
    assert await scalar(arw, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t AND step = 'B11' "
                             "AND event = 'asked'", t=ticket) == 3  # fmt: skip
