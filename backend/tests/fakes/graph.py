"""Bản giả in-memory cho runtime graph (P1) — cùng hợp đồng với store SQL (`app/db/runtime.py`,
`app/audit/writer.py`) để test graph không cần Postgres. Bản SQL chạy lại các luồng chính trong
`tests/integration/test_graph_pg.py`.

`GraphHarness.restart()` dựng graph + runner MỚI trên cùng checkpointer và cùng "DB" giả — mô phỏng
khởi động lại backend (cổng 2).
"""

import asyncio
import importlib.util
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.approval.store import ApprovalRow
from app.audit.writer import check_audit_row
from app.core.clock import FakeClock
from app.db.escalations import QueueItem
from app.db.runtime import DueWait, OpenTurn, as_ref
from app.db.tickets import NewTicket, TicketRow
from app.domain.action import Action
from app.domain.final import FinalSummary
from app.graph.builder import build_graph, fake_nodes
from app.graph.checkpoint import make_serde
from app.graph.fakes import FakeScenario, NodeDeps
from app.graph.ports import SpanRecord, TicketBusy, ToolCaller
from app.graph.runner import Runner
from app.llm import LlmPort
from app.settings import get_escalation_templates, get_policy
from langgraph.checkpoint.memory import InMemorySaver
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.identity import (
    REQUESTER,
    SESSION,
    FakeAd,
    MemoryAlerts,
    MemoryIdentity,
    ad_user,
    fake_directory,
)
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag

LOCKOUT = timedelta(minutes=15)


class MemoryAudit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.drop = False  # True → mô phỏng INSERT không để lại dòng (kiểm cấm 4)
        self.crash_once: set[str] = set()  # event → process "chết" ngay TRƯỚC khi ghi dòng đó

    async def record(self, row: Mapping[str, Any]) -> bool:
        check_audit_row(row)
        if row["event"] in self.crash_once:
            self.crash_once.discard(row["event"])
            raise Crash(f"process chết trước khi ghi audit {row['event']}")
        key = row.get("idempotency_key")
        if self.drop:
            return False
        if key is None or all(r.get("idempotency_key") != key for r in self.rows):
            self.rows.append(dict(row))
        return True

    def events(self, ticket_id: str) -> list[tuple[str, str]]:
        return [(r["step"], r["event"]) for r in self.rows if r["ticket_id"] == ticket_id]

    def of(self, ticket_id: str, event: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["ticket_id"] == ticket_id and r["event"] == event]


class MemoryEffects:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def run_once(
        self, *, key: str, ticket_id: str, kind: str, step: str, turn_id: str,
        call: Callable[[], Awaitable[Any]],
    ) -> str | None:  # fmt: skip
        async with self._lock:  # giống transaction: lời gọi thứ hai chờ lời gọi đầu xong
            if key in self.rows:
                return self.rows[key]["result_ref"]
            ref = as_ref(await call())
            self.rows[key] = {"ticket_id": ticket_id, "kind": kind, "step": step,
                              "turn_id": turn_id, "result_ref": ref}  # fmt: skip
            return ref

    def count(self, ticket_id: str, kind: str) -> int:
        return sum(1 for r in self.rows.values() if r["ticket_id"] == ticket_id and r["kind"] == kind)


class MemorySpans:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []
        self.crash_once: set[str] = set()  # tên span → process "chết" khi node đã xong, trước checkpoint

    async def write(self, span: SpanRecord) -> None:
        if span.name in self.crash_once:
            self.crash_once.discard(span.name)
            raise Crash(f"process chết sau {span.name}, trước checkpoint")
        self.spans.append(span)


class MemoryTurns:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def start(
        self, *, turn_id: str, ticket_id: str, session_id: str | None, event_type: str, at: datetime
    ) -> None:
        assert turn_id not in self.rows, "turn_id là khoá chính"
        self.rows[turn_id] = {"ticket_id": ticket_id, "event_type": event_type,
                              "started_at": at, "ended_at": None}  # fmt: skip

    async def end(self, turn_id: str, at: datetime) -> None:
        if self.rows[turn_id]["ended_at"] is None:
            self.rows[turn_id]["ended_at"] = at

    async def is_open(self, turn_id: str) -> bool:
        return turn_id in self.rows and self.rows[turn_id]["ended_at"] is None

    async def bump_recover_attempts(self, turn_id: str) -> int | None:
        row = self.rows.get(turn_id)
        if row is None or row["ended_at"] is not None:
            return None
        row["recover_attempts"] = row.get("recover_attempts", 0) + 1
        return int(row["recover_attempts"])

    async def stale(self, before: datetime, limit: int) -> list[OpenTurn]:
        rows = sorted(
            (r["started_at"], t, r["ticket_id"]) for t, r in self.rows.items()
            if r["ended_at"] is None and r["started_at"] < before
        )  # fmt: skip
        return [OpenTurn(tid, t, at) for at, t, tid in rows[:limit]]

    def of(self, ticket_id: str) -> list[dict[str, Any]]:
        return [{"turn_id": t, **r} for t, r in self.rows.items() if r["ticket_id"] == ticket_id]


class MemoryDeadlines:
    """`wait_deadlines` + phần `approvals` worker đọc (hạn duyệt)."""

    def __init__(self) -> None:
        self.waits: list[dict[str, Any]] = []
        self.approvals: dict[str, dict[str, Any]] = {}

    async def set(self, ticket_id: str, kind: str, deadline: datetime, created_turn: str) -> str:
        for w in self.waits:
            if w["ticket_id"] == ticket_id and w["kind"] == kind and w["fired_at"] is None:
                w["fired_at"] = deadline  # bị thay (giá trị giả, chỉ cần khác None)
        self.waits.append({"ticket_id": ticket_id, "kind": kind, "deadline": deadline,
                           "created_turn": created_turn, "fired_at": None, "is_parent": False})  # fmt: skip
        return created_turn

    async def due(self, now: datetime, limit: int) -> list[DueWait]:
        out = [DueWait(w["ticket_id"], w["kind"], w["created_turn"], w["is_parent"])
               for w in sorted(self.waits, key=lambda w: w["deadline"])
               if w["fired_at"] is None and w["deadline"] < now]  # fmt: skip
        out += [DueWait(a["ticket_id"], "approval", aid) for aid, a in self.approvals.items()
                if a["status"] == "pending" and a["deadline"] < now]  # fmt: skip
        return out[:limit]

    async def mark_fired(self, due: DueWait, at: datetime) -> None:
        if due.kind == "approval":
            if self.approvals[due.ref]["status"] == "pending":
                self.approvals[due.ref]["status"] = "timeout"
            return
        for w in self.waits:
            if (w["ticket_id"], w["kind"], w["created_turn"]) == (due.ticket_id, due.kind, due.ref):
                w["fired_at"] = w["fired_at"] or at


class MemoryApprovals:
    """Port approvals giả, ghi vào cùng bảng `approvals` giả mà worker đọc hạn. `lock_row` khoá
    theo phiếu như `SELECT … FOR UPDATE` (giữ suốt khối `async with`)."""

    def __init__(self, deadlines: MemoryDeadlines) -> None:
        self._table = deadlines.approvals
        self.notified: list[tuple[str, str]] = []
        self._row_locks: dict[str, asyncio.Lock] = {}
        self.crash_on_create = False  # process "chết" ở lần tạo phiếu kế tiếp (chưa ghi gì)

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str:
        if self.crash_on_create:
            self.crash_on_create = False
            raise Crash(f"process chết khi tạo phiếu cho {ticket_id}")
        approval_id = str(len(self._table) + 1)
        self._table[approval_id] = {"ticket_id": ticket_id, "approver_id": approver_id,
                                    "deadline": deadline, "status": "pending",
                                    "action_plan_hash": action_plan_hash}  # fmt: skip
        return approval_id

    async def notify_approver(self, approval_id: str, approver_id: str) -> str:
        self.notified.append((approval_id, approver_id))
        return f"n{len(self.notified)}"

    async def close(
        self, approval_id: str, result: str, at: datetime, *, decided_by: str | None = None,
        note: str | None = None,
    ) -> None:  # fmt: skip
        row = self._table[approval_id]
        if row["status"] == "pending":
            if result == "rejected" and note is None:
                raise ValueError("CHECK rejected_needs_note")  # như Postgres
            row.update(status=result, decided_at=at, decided_by=decided_by, note=note)

    def _row(self, approval_id: str) -> ApprovalRow | None:
        a = self._table.get(approval_id)
        if a is None:
            return None
        return ApprovalRow(
            approval_id=approval_id, ticket_id=a["ticket_id"], approver_id=a["approver_id"],
            status=a["status"], deadline=a["deadline"], decided_by=a.get("decided_by"),
            note=a.get("note"), first_viewed_at=a.get("first_viewed_at"),
        )  # fmt: skip

    async def get(self, approval_id: str) -> ApprovalRow | None:
        return self._row(approval_id)

    @asynccontextmanager
    async def lock_row(self, approval_id: str) -> AsyncIterator[ApprovalRow | None]:
        lock = self._row_locks.setdefault(approval_id, asyncio.Lock())
        async with lock:
            yield self._row(approval_id)

    def status(self, approval_id: str) -> str:
        return str(self._table[approval_id]["status"])

    def count(self, ticket_id: str) -> int:
        return sum(1 for a in self._table.values() if a["ticket_id"] == ticket_id)


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.crash_once: set[str] = set()  # ticket → process "chết" giữa lúc gửi (chưa gửi được)

    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
        if ticket_id in self.crash_once:
            self.crash_once.discard(ticket_id)
            raise Crash(f"process chết khi gửi tin cho {ticket_id}")
        self.sent.append((ticket_id, text, needs))
        return f"m{len(self.sent)}"

    def count(self, ticket_id: str) -> int:
        return sum(1 for t, _, _ in self.sent if t == ticket_id)


class Crash(BaseException):
    """Mô phỏng process chết giữa chừng: không phải Exception nên boundary E9 không bắt, LangGraph
    không kịp ghi checkpoint của node đang chạy."""


class CountingExecutor:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.crash_once: set[str] = set()  # ticket sẽ "chết" giữa lần thực thi đầu

    async def execute(self, ticket_id: str, action: Action | None) -> bool:
        self.calls[ticket_id] += 1
        if ticket_id in self.crash_once:
            self.crash_once.discard(ticket_id)
            raise Crash(f"process chết khi đang thực thi {ticket_id}")
        return True


def seed_priority() -> dict[str, tuple[int, str]]:
    """Rank + nhãn E0–E9 đọc từ CHÍNH seed của migration 0001 (nguồn duy nhất, B20 5.1)."""
    path = Path(__file__).resolve().parents[2] / "app/db/alembic/versions/0001_init_22_bang_role_trigger.py"
    spec = importlib.util.spec_from_file_location("_mig_0001", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {r["exit_code"]: (r["rank"], r["label"]) for r in module.EXIT_CODE_PRIORITY}


class MemoryTickets:
    """`tickets` giả: ghi kết quả cuối MỘT lần (`WHERE final_state IS NULL`), trả dòng đang có.
    `fail` tiêm lỗi vào `finalize_once`: Exception (bug → boundary) hoặc `Crash` (process chết, không
    kịp ghi gì); `fail_times` None = mãi mãi."""

    def __init__(self, turns: MemoryTurns) -> None:
        self._turns = turns
        self.rows: dict[str, dict[str, Any]] = {}
        self.fail: BaseException | None = None
        self.fail_times: int | None = None
        self.finalize_calls: Counter[str] = Counter()

    def register(
        self, ticket_id: str, created_at: datetime, *, is_parent: bool = False,
        requester_id: str = REQUESTER, session_id: str | None = SESSION,
        redacted_request: str = "yêu cầu", parent_ticket_id: str | None = None,
        requester_role: str = "employee", requester_dept: str | None = None,
    ) -> None:  # fmt: skip
        self.rows.setdefault(ticket_id, {
            "created_at": created_at, "final": None, "is_parent": is_parent,
            "requester_id": requester_id, "session_id": session_id,
            "redacted_request": redacted_request, "parent_ticket_id": parent_ticket_id,
            "requester_role": requester_role, "requester_dept": requester_dept,
        })  # fmt: skip

    async def create(self, ticket: NewTicket, *, turn_id: str) -> None:
        """Như SQL: dòng `tickets` + lượt `submit` trong MỘT transaction (lượt lỗi → không ticket)."""
        if ticket.ticket_id in self.rows:
            raise ValueError("PK tickets")
        if turn_id in self._turns.rows:
            raise ValueError("PK turns")
        self.register(
            ticket.ticket_id, ticket.created_at, requester_id=ticket.requester_id,
            session_id=ticket.session_id, redacted_request=ticket.redacted_request,
            requester_role=ticket.requester_role, requester_dept=ticket.requester_dept,
        )  # fmt: skip
        await self._turns.start(turn_id=turn_id, ticket_id=ticket.ticket_id,
                                session_id=ticket.session_id, event_type="submit",
                                at=ticket.created_at)  # fmt: skip

    async def get(self, ticket_id: str) -> TicketRow | None:
        r = self.rows.get(ticket_id)
        if r is None:
            return None
        final: FinalSummary | None = r["final"]
        return TicketRow(
            ticket_id=ticket_id, requester_id=r["requester_id"], session_id=r["session_id"],
            redacted_request=r["redacted_request"], parent_ticket_id=r["parent_ticket_id"],
            is_parent=r["is_parent"], final_state=final.final_state if final else None,
            exit_code=final.exit_code if final else None,
            close_reason=final.close_reason if final else None, created_at=r["created_at"],
            closed_at=final.closed_at if final else None,
        )  # fmt: skip

    async def created_at(self, ticket_id: str) -> datetime:
        return self.rows[ticket_id]["created_at"]  # type: ignore[no-any-return]

    async def count_turns(self, ticket_id: str) -> int:
        return len(self._turns.of(ticket_id))

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        self.finalize_calls[ticket_id] += 1
        if self.fail is not None and (self.fail_times is None or self.fail_times > 0):
            if self.fail_times is not None:
                self.fail_times -= 1
            raise self.fail
        row = self.rows[ticket_id]
        if row["final"] is None:
            row["final"] = summary
        return row["final"]  # type: ignore[no-any-return]

    def final(self, ticket_id: str) -> FinalSummary | None:
        return self.rows[ticket_id]["final"]  # type: ignore[no-any-return]


class MemoryEscalations:
    def __init__(self, tickets: MemoryTickets) -> None:
        self._tickets = tickets
        self._priority = seed_priority()
        self.rows: list[dict[str, Any]] = []

    async def create(
        self, *, ticket_id: str, exit_code: str, reason_detail: str | None,
        handoff_note: Mapping[str, Any], is_deny_case: bool, created_at: datetime,
    ) -> str:  # fmt: skip
        rank, _ = self._priority[exit_code]
        self.rows.append({"escalation_id": len(self.rows) + 1, "ticket_id": ticket_id,
                          "exit_code": exit_code, "priority": rank, "reason_detail": reason_detail,
                          "handoff_note": dict(handoff_note), "is_deny_case": is_deny_case,
                          "created_at": created_at, "closed_at": None, "assigned_to": None})  # fmt: skip
        return str(len(self.rows))

    def of(self, ticket_id: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["ticket_id"] == ticket_id]

    async def list_open(self, limit: int) -> list[QueueItem]:
        rows = [r for r in self.rows if r["closed_at"] is None
                and not self._tickets.rows.get(r["ticket_id"], {}).get("is_parent")]  # fmt: skip
        rows.sort(key=lambda r: (r["priority"], r["created_at"], r["escalation_id"]))
        return [
            QueueItem(
                escalation_id=r["escalation_id"], ticket_id=r["ticket_id"], exit_code=r["exit_code"],
                priority=r["priority"], label=self._priority[r["exit_code"]][1],
                reason_detail=r["reason_detail"], is_deny_case=r["is_deny_case"],
                handoff_note=r["handoff_note"], assigned_to=None, created_at=r["created_at"],
            )
            for r in rows[:limit]
        ]


class MemoryTicketLock:
    def __init__(self, timeout: float = 5.0) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._timeout = timeout

    @asynccontextmanager
    async def hold(self, ticket_id: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(ticket_id, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), self._timeout)
        except TimeoutError as exc:
            raise TicketBusy(ticket_id) from exc
        try:
            yield
        finally:
            lock.release()


@dataclass
class GraphHarness:
    """Toàn bộ runtime trên bản giả. Trường `saver`, store… giữ nguyên qua `restart()`."""

    clock: FakeClock = field(default_factory=FakeClock)
    scenario: FakeScenario = field(default_factory=FakeScenario)
    can_execute: bool = True
    rediagnose_on_new_slot: bool = False
    recursion_limit: int = 60
    concurrency: int = 8
    lock_timeout: float = 5.0
    saver: InMemorySaver = field(default_factory=lambda: InMemorySaver(serde=make_serde()))
    audit: MemoryAudit = field(default_factory=MemoryAudit)
    effects: MemoryEffects = field(default_factory=MemoryEffects)
    spans: MemorySpans = field(default_factory=MemorySpans)
    turns: MemoryTurns = field(default_factory=MemoryTurns)
    deadlines: MemoryDeadlines = field(default_factory=MemoryDeadlines)
    notifier: RecordingNotifier = field(default_factory=RecordingNotifier)
    executor: CountingExecutor = field(default_factory=CountingExecutor)
    # B1 thật: phiên `s1` của `nv-fake` còn sống, AD có `nv-fake` (employee)
    identity: MemoryIdentity = field(default_factory=MemoryIdentity)
    ad: FakeAd = field(default_factory=lambda: FakeAd(ad_user()))
    alerts: MemoryAlerts = field(default_factory=MemoryAlerts)
    directory: ToolCaller | None = None  # None = registry thật trên `FakeAd`; e2e gắn registry tới mock
    max_recover_attempts: int = 3
    approver_id: str | None = "l1-fake"  # B15 giả (FAKE_APPROVER_ID)
    ml: FakeMlService = field(default_factory=FakeMlService)  # ml-service giả (3a), đếm ở nơi nhận
    rag: FakeRag = field(default_factory=FakeRag)  # RAG giả (3c) — b08 thật dùng khi `nodes="real"`
    # LLM gateway THẬT + ScriptedLLM rỗng (3d): node gọi LLM mà test chưa cấp kịch bản → ScriptExhausted → E9
    llm: LlmPort = field(default_factory=lambda: make_gateway().client)
    tickets: MemoryTickets = field(init=False)
    escalations: MemoryEscalations = field(init=False)
    approvals: MemoryApprovals = field(init=False)
    lock: MemoryTicketLock = field(init=False)
    runner: Runner = field(init=False)

    def __post_init__(self) -> None:
        self.approvals = MemoryApprovals(self.deadlines)
        self.tickets = MemoryTickets(self.turns)
        self.escalations = MemoryEscalations(self.tickets)
        self.lock = MemoryTicketLock(self.lock_timeout)
        if isinstance(self.identity, MemoryIdentity):
            self.identity.add_session(
                SESSION, REQUESTER, expires_at=self.clock.now() + timedelta(days=365)
            )
        self.runner = self._make_runner()

    def deps(self) -> NodeDeps:
        """Mỗi lần gọi = một "process": registry (và breaker) mới, như khởi động lại backend."""
        return NodeDeps(
            notifier=self.notifier, approvals=self.approvals, executor=self.executor,
            deadlines=self.deadlines, constants=get_policy().constants,
            identity=self.identity, directory=self.directory or fake_directory(self.ad, self.clock),
            alerts=self.alerts, lockout=LOCKOUT, tickets=self.tickets,
            escalations=self.escalations, templates=get_escalation_templates(), ml=self.ml.client(self.clock),
            rag=self.rag, llm=self.llm, scenario=self.scenario, approver_id=self.approver_id,
        )  # fmt: skip

    def _make_runner(self) -> Runner:
        return Runner(
            build_graph(fake_nodes(self.deps()), self.saver), lock=self.lock, turns=self.turns,
            audit=self.audit, effects=self.effects, spans=self.spans, clock=self.clock,
            concurrency=self.concurrency, can_execute=self.can_execute,
            rediagnose_on_new_slot=self.rediagnose_on_new_slot,
            recursion_limit=self.recursion_limit, max_recover_attempts=self.max_recover_attempts,
            tickets=self.tickets,
        )  # fmt: skip

    def restart(self, *, can_execute: bool | None = None) -> Runner:
        """Graph + runner mới (process mới) trên cùng checkpoint và cùng DB giả."""
        if can_execute is not None:
            self.can_execute = can_execute
        self.lock = MemoryTicketLock(self.lock_timeout)
        self.runner = self._make_runner()
        return self.runner

    async def submit(self, ticket_id: str, **plan: str | list[str]) -> Any:
        if plan:
            self.scenario.plan(ticket_id, **plan)
        return await self.submit_as(ticket_id, SESSION)

    async def submit_as(
        self, ticket_id: str, session_id: str | None, text: str = "yêu cầu",
        parent_ticket_id: str | None = None,
    ) -> Any:  # fmt: skip
        """Như API (2b-3): có dòng `tickets` trước, rồi mới submit graph."""
        self.tickets.register(ticket_id, self.clock.now())
        return await self.runner.submit(
            ticket_id, session_id=session_id, redacted_request=text,
            parent_ticket_id=parent_ticket_id,
        )  # fmt: skip

