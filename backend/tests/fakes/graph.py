"""Bản giả in-memory cho runtime graph (P1) — cùng hợp đồng với store SQL (`app/db/runtime.py`,
`app/audit/writer.py`) để test graph không cần Postgres. Bản SQL chạy lại các luồng chính trong
`tests/integration/test_graph_pg.py`.

`GraphHarness.restart()` dựng graph + runner MỚI trên cùng checkpointer và cùng "DB" giả — mô phỏng
khởi động lại backend (cổng 2).
"""

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.audit.writer import check_audit_row
from app.core.clock import FakeClock
from app.db.runtime import DueWait, OpenTurn, as_ref
from app.domain.action import Action
from app.graph.builder import build_graph, fake_nodes
from app.graph.checkpoint import make_serde
from app.graph.fakes import FakeScenario, NodeDeps
from app.graph.ports import SpanRecord, TicketBusy
from app.graph.runner import Runner
from app.settings import get_policy
from langgraph.checkpoint.memory import InMemorySaver


class MemoryAudit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.drop = False  # True → mô phỏng INSERT không để lại dòng (kiểm cấm 4)

    async def record(self, row: Mapping[str, Any]) -> bool:
        check_audit_row(row)
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

    async def write(self, span: SpanRecord) -> None:
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
    """Port approvals giả, ghi vào cùng bảng `approvals` giả mà worker đọc hạn."""

    def __init__(self, deadlines: MemoryDeadlines) -> None:
        self._table = deadlines.approvals
        self.notified: list[tuple[str, str]] = []

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str:
        approval_id = str(len(self._table) + 1)
        self._table[approval_id] = {"ticket_id": ticket_id, "approver_id": approver_id,
                                    "deadline": deadline, "status": "pending",
                                    "action_plan_hash": action_plan_hash}  # fmt: skip
        return approval_id

    async def notify_approver(self, approval_id: str, approver_id: str) -> str:
        self.notified.append((approval_id, approver_id))
        return f"n{len(self.notified)}"

    async def record_result(self, approval_id: str, result: str, at: datetime) -> None:
        if self._table[approval_id]["status"] == "pending":
            self._table[approval_id]["status"] = result

    def count(self, ticket_id: str) -> int:
        return sum(1 for a in self._table.values() if a["ticket_id"] == ticket_id)


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
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
    approvals: MemoryApprovals = field(init=False)
    lock: MemoryTicketLock = field(init=False)
    runner: Runner = field(init=False)

    def __post_init__(self) -> None:
        self.approvals = MemoryApprovals(self.deadlines)
        self.lock = MemoryTicketLock(self.lock_timeout)
        self.runner = self._make_runner()

    def deps(self) -> NodeDeps:
        return NodeDeps(
            notifier=self.notifier, approvals=self.approvals, executor=self.executor,
            deadlines=self.deadlines, constants=get_policy().constants, scenario=self.scenario,
        )  # fmt: skip

    def _make_runner(self) -> Runner:
        return Runner(
            build_graph(fake_nodes(self.deps()), self.saver), lock=self.lock, turns=self.turns,
            audit=self.audit, effects=self.effects, spans=self.spans, clock=self.clock,
            concurrency=self.concurrency, can_execute=self.can_execute,
            rediagnose_on_new_slot=self.rediagnose_on_new_slot,
            recursion_limit=self.recursion_limit,
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
        return await self.runner.submit(ticket_id, session_id="s1", redacted_request="yêu cầu")
