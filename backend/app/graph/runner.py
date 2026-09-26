"""Runner — submit / resume / recover (P1 mục 2, 7).

1. Khoá ticket (D-19) — `submit`/`resume`/`recover` tự lấy; `*_locked` dành cho `deliver_event` đã
   giữ khoá.
2. `Semaphore(GRAPH_CONCURRENCY)` mỗi process.
3. submit/resume: `turn_id` mới + dòng `turns`; recover GIỮ `turn_id` cũ (D-18) — khoá idempotent của
   audit/side effect trùng với lần chạy hỏng. `turn_id` là khoá chính của `turns` nên recover chỉ
   đóng dòng cũ (không dùng `event_type='recover'`).
4. `ainvoke(input | Command(resume=…) | None)`, `recursion_limit` (lưới cuối sau MAX_LOOPS).

Đã kiểm với LangGraph 1.2: giá trị resume được ghi vào checkpoint trước khi node chạy, nên process
chết giữa lượt resume thì `ainvoke(None)` chạy lại node chờ với đúng giá trị đó.

**Worker không có SVC_EXECUTOR_TOKEN** (quyết định 26/09/2026): `Runner(can_execute=False)` — recover
mà bước kế tiếp là `b17_execute` thì KHÔNG thực thi (không biết hệ thống ngoài đang ở trạng thái nào),
chuyển `S_ESCALATED` E7 "thực thi bị gián đoạn" rồi chạy B20.

**Giới hạn phục hồi** (2b-Q6, Q-B; migration 0005): `recover` tăng `turns.recover_attempts` TRƯỚC khi
chạy lại (dưới khoá ticket) — process chết giữa lượt vẫn bị tính. Vượt `max_recover_attempts` (3):
lượt kẹt ở B20 → audit `finalize_failed_permanent` + đóng lượt (M9 Phase 7 có luật cảnh báo); kẹt ở
node khác → `S_ESCALATED` E9 `recover_exhausted` rồi chạy B20.

**`wake_parent` sau khi nhả khoá** (2b-Q7, lệch mã giả B20): thread con kết thúc → runner đánh thức cha
khi KHÔNG còn giữ khoá con (gọi trong B20 có thể deadlock: con giữ khoá con chờ khoá cha, cha chuyển sự
kiện xuống con). Chỉ là tín hiệu (D-17): lỗi thì log, cha tự đối soát ở `parent_wait` (Phase 5 thêm job
đối soát cha khi mọi con đã có `final_state`).
"""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, StateSnapshot

from app.core.clock import Clock
from app.core.ids import new_trace_id, new_turn_id
from app.domain.exit_codes import ExitCode
from app.domain.states import S_ESCALATED, S_NEW
from app.graph.builder import Graph
from app.graph.context import RunContext, bind_run
from app.graph.goto import audit_key, goto
from app.graph.ports import AuditSink, EffectStore, SpanSink, TicketLock, TurnStore
from app.graph.routing import AUDIT

log = logging.getLogger(__name__)

EXECUTE_NODE = "b17_execute"
PARENT_WAIT = "parent_wait"
INTERRUPTED_NOTE = "Thực thi bị gián đoạn — cần L2 kiểm tra trạng thái thật trên hệ thống ngoài"
FINALIZE_FAILED = "finalize_failed_permanent"
RECOVER_EXHAUSTED = "recover_exhausted"


@dataclass(frozen=True)
class RunResult:
    ticket_id: str
    turn_id: str
    status: str | None
    waiting_at: str | None  # node đang dừng chờ; None = thread đã kết thúc
    values: Mapping[str, Any]


class Runner:
    def __init__(
        self,
        graph: Graph,
        *,
        lock: TicketLock,
        turns: TurnStore,
        audit: AuditSink,
        effects: EffectStore,
        spans: SpanSink,
        clock: Clock,
        concurrency: int = 8,
        can_execute: bool = True,
        rediagnose_on_new_slot: bool = False,
        recursion_limit: int = 60,
        max_recover_attempts: int = 3,
    ) -> None:
        self.graph = graph
        self.audit = audit
        self.clock = clock
        self._lock = lock
        self._turns = turns
        self._effects = effects
        self._spans = spans
        self._sem = asyncio.Semaphore(concurrency)
        self._can_execute = can_execute
        self._rediagnose = rediagnose_on_new_slot
        self._recursion_limit = recursion_limit
        self._max_recover = max_recover_attempts

    # ---- tiện ích -----------------------------------------------------------------------------

    def config(self, ticket_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": ticket_id}, "recursion_limit": self._recursion_limit}

    def hold(self, ticket_id: str) -> Any:
        return self._lock.hold(ticket_id)

    async def snapshot(self, ticket_id: str) -> StateSnapshot:
        return await self.graph.aget_state(self.config(ticket_id))

    def _context(self, turn_id: str) -> RunContext:
        return RunContext(
            turn_id=turn_id, trace_id=new_trace_id(), audit=self.audit, effects=self._effects,
            spans=self._spans, clock=self.clock, rediagnose_on_new_slot=self._rediagnose,
        )  # fmt: skip

    async def _result(self, ticket_id: str, turn_id: str) -> RunResult:
        snap = await self.snapshot(ticket_id)
        return RunResult(
            ticket_id=ticket_id, turn_id=turn_id, status=snap.values.get("status"),
            waiting_at=snap.next[0] if snap.next else None, values=snap.values,
        )  # fmt: skip

    # ---- API ----------------------------------------------------------------------------------

    async def submit(
        self,
        ticket_id: str,
        *,
        session_id: str | None,
        redacted_request: str,
        parent_ticket_id: str | None = None,
    ) -> RunResult:
        async with self._lock.hold(ticket_id):
            turn_id = new_turn_id()
            await self._turns.start(
                turn_id=turn_id, ticket_id=ticket_id, session_id=session_id,
                event_type="submit", at=self.clock.now(),
            )  # fmt: skip
            initial: dict[str, Any] = {
                "ticket_id": ticket_id, "parent_ticket_id": parent_ticket_id, "is_parent": False,
                "children": [], "session_id": session_id, "turn_id": turn_id,
                "redacted_request": redacted_request, "conversation": [], "status": S_NEW,
                "clarification_turns": 0, "reasoning_loops": 0, "off_topic_streak": 0,
            }  # fmt: skip
            result = await self._run(ticket_id, turn_id, initial)
        await self.after_turn(result)
        return result

    async def resume(
        self, ticket_id: str, event: Mapping[str, Any], *, session_id: str | None = None
    ) -> RunResult:
        async with self._lock.hold(ticket_id):
            result = await self.resume_locked(ticket_id, event, session_id=session_id)
        await self.after_turn(result)
        return result

    async def resume_locked(
        self, ticket_id: str, event: Mapping[str, Any], *, session_id: str | None = None
    ) -> RunResult:
        turn_id = new_turn_id()
        await self._turns.start(
            turn_id=turn_id, ticket_id=ticket_id, session_id=session_id, event_type="resume",
            at=self.clock.now(),
        )  # fmt: skip
        return await self._run(
            ticket_id, turn_id, Command(resume=dict(event), update={"turn_id": turn_id})
        )

    async def recover(self, ticket_id: str, turn_id: str) -> RunResult | None:
        """Chạy tiếp lượt dở dang từ checkpoint cuối, giữ `turn_id`. Lượt đã đóng → None.

        Tăng `recover_attempts` TRƯỚC khi chạy (dưới khoá) — vượt giới hạn thì `_give_up`."""
        async with self._lock.hold(ticket_id):
            if not await self._turns.is_open(turn_id):
                return None  # lượt kia đã xong trong lúc ta chờ khoá
            attempts = await self._turns.bump_recover_attempts(turn_id)
            if attempts is None:
                return None
            snap = await self.snapshot(ticket_id)
            if not snap.next:  # thread đã kết thúc, chỉ chưa kịp đóng turn
                await self._turns.end(turn_id, self.clock.now())
                result = await self._result(ticket_id, turn_id)
            elif attempts > self._max_recover:
                result = await self._give_up(ticket_id, turn_id, snap, attempts)
            elif not self._can_execute and EXECUTE_NODE in snap.next:
                result = await self._divert(
                    ticket_id, turn_id, snap, as_node=EXECUTE_NODE, step="B17",
                    event="execution_interrupted", exit_code=ExitCode.E7.value,
                    escalation_note=INTERRUPTED_NOTE,
                    escalation_reason_detail="execution_interrupted",
                )  # fmt: skip
            else:
                result = await self._run(ticket_id, turn_id, None)
        await self.after_turn(result)
        return result

    async def _give_up(
        self, ticket_id: str, turn_id: str, snap: StateSnapshot, attempts: int
    ) -> RunResult:
        node = snap.next[0]
        log.error("ticket %s: lượt %s kẹt ở %s sau %d lần phục hồi — ngừng thử",
                  ticket_id, turn_id, node, attempts - 1)  # fmt: skip
        if node != AUDIT:
            return await self._divert(
                ticket_id, turn_id, snap, as_node=node, step="runner", event=RECOVER_EXHAUSTED,
                exit_code=ExitCode.E9.value, escalation_reason_detail=RECOVER_EXHAUSTED,
                escalation_note=f"Phục hồi lượt thất bại {attempts - 1} lần tại {node}",
                audit_detail={"recover_attempts": attempts - 1, "node": node},
            )  # fmt: skip
        status = snap.values.get("status")
        loop_seq = int(snap.values.get("reasoning_loops", 0) or 0)
        await self.audit.record({
            "ticket_id": ticket_id, "turn_id": turn_id, "loop_seq": loop_seq,
            "idempotency_key": audit_key(ticket_id, "B20", FINALIZE_FAILED, turn_id, loop_seq),
            "step": "B20", "event": FINALIZE_FAILED, "from_status": status, "to_status": status,
            "exit_code": snap.values.get("exit_code"), "created_at": self.clock.now(),
            "detail": {
                "recover_attempts": attempts - 1, "max_recover_attempts": self._max_recover,
                "node": node, "hint": "xem audit unhandled_exception / span node:b20_audit cùng turn_id",
            },
        })  # fmt: skip
        await self._turns.end(turn_id, self.clock.now())
        return await self._result(ticket_id, turn_id)

    # ---- ticket con → cha (D-17) --------------------------------------------------------------

    async def after_turn(self, result: RunResult) -> None:
        """Gọi SAU khi nhả khoá ticket (2b-Q7). Thread con đã kết thúc → đánh thức cha."""
        parent = result.values.get("parent_ticket_id")
        if result.waiting_at is not None or not parent:
            return
        try:
            await self.wake_parent(parent)
        except Exception:  # chỉ là tín hiệu — cha tự đối soát ở parent_wait
            log.exception("không đánh thức được ticket cha %s", parent)

    async def wake_parent(self, parent_id: str) -> RunResult | None:
        """Chỉ là tín hiệu (D-17): cha đang ở `parent_wait` → đánh thức; không thì không làm gì và
        KHÔNG ghi `late_event` — cha tự đối soát từ DB khi tới `parent_wait`."""
        async with self._lock.hold(parent_id):
            snap = await self.snapshot(parent_id)
            if snap.next != (PARENT_WAIT,):
                return None
            result = await self.resume_locked(parent_id, {"kind": "wake"})
        await self.after_turn(result)
        return result

    # ---- lõi ----------------------------------------------------------------------------------

    async def _run(self, ticket_id: str, turn_id: str, graph_input: Any) -> RunResult:
        cfg = self.config(ticket_id)
        async with self._sem:
            with bind_run(self._context(turn_id)):
                try:
                    await self.graph.ainvoke(graph_input, cfg)
                except GraphRecursionError:
                    log.error("ticket %s vượt recursion_limit → E9", ticket_id)
                    snap = await self.graph.aget_state(cfg)
                    await self._divert_bound(
                        ticket_id, snap, as_node=snap.next[0] if snap.next else AUDIT,
                        step="runner", event="recursion_limit", exit_code=ExitCode.E9.value,
                        escalation_note="Vượt giới hạn số bước của graph (recursion_limit)",
                    )  # fmt: skip
        await self._turns.end(turn_id, self.clock.now())
        return await self._result(ticket_id, turn_id)

    async def _divert(
        self, ticket_id: str, turn_id: str, snap: StateSnapshot, **kwargs: Any
    ) -> RunResult:
        async with self._sem:
            with bind_run(self._context(turn_id)):
                await self._divert_bound(ticket_id, snap, **kwargs)
        await self._turns.end(turn_id, self.clock.now())
        return await self._result(ticket_id, turn_id)

    async def _divert_bound(
        self, ticket_id: str, snap: StateSnapshot, *, as_node: str, step: str, event: str,
        audit_detail: Mapping[str, Any] | None = None, **fields: Any,
    ) -> None:  # fmt: skip
        """Bẻ luồng sang S_ESCALATED → B20 mà không chạy node kế tiếp. Vẫn qua goto() (audit)."""
        cfg = self.config(ticket_id)
        update = await goto(
            snap.values, S_ESCALATED, next_node=AUDIT, step=step, event=event,
            audit_detail=audit_detail, **fields,
        )  # fmt: skip
        await self.graph.aupdate_state(cfg, update, as_node=as_node)
        await self.graph.ainvoke(None, cfg)
