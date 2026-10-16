"""`ChildOps` — khởi động con và chuyển sự kiện xuống con, ở TẦNG RUNNER (Phase 5 T20b P4, P8; phase5 5.2.1; D-17, D-18, D-31).

Node cha (`parent_wait`, `parent_reply_wait`) gọi qua `current_run().children` — không qua `NodeDeps`. Runner dựng một `ChildOps` cho
chính nó và gắn vào mọi `RunContext`.

Lượt con chạy LỒNG trong lượt cha (cha đang giữ khoá cha): lấy khoá CON (thứ tự khoá luôn cha → con; không chỗ nào giữ khoá con rồi chờ
khoá cha), mở dòng `turns` của con, `RunContext` + hạn lượt MỚI của con (TQ-3), KHÔNG lấy thêm `Semaphore`, KHÔNG `after_turn` (cha tự
đối soát ngay sau — tránh deadlock 2b-Q7). Không chạy bên trong `effects.once` (lượt con không nằm trong transaction của `run_once` —
D-19): cha ghi `child_submit` / `child_event` qua `effects.once` SAU khi chạy, `peek` trước để không làm lại.

- `start_missing(cha)`: với từng `cid` trong `cha["children"]` (thứ tự `index`) — thread con đã có state → bỏ qua; chưa → lượt
  `turns(event_type="submit")` → `aupdate_state(seed + goto(...), as_node="b03_classify")` (khuôn `Runner._divert_bound(seed=True)`;
  `goto` từ `S_CLASSIFYING`: ý chạy được → `S_DIAGNOSING`/`b06_diagnose`, `event="child_started"`; ý E1 → `S_ESCALATED`/`b20_audit`,
  `event="child_not_runnable"`; `step="B5"`) → `ainvoke(None)` → đóng lượt. `requester_context` đọc từ state cha. Sau đó — CHỈ khi
  lần này thật sự khởi động — `effects.once("child_submit", sub=cid)` (`peek` trước: đã ghi ở lượt này → bỏ) — một dòng/con.
  `recorded` = con đã có dòng `child_submit` ở BẤT KỲ lượt nào (`tickets.started_children`, node cha đọc) → bỏ qua luôn. Con có thread
  mà CHƯA có dòng (chết giữa lượt lồng và lúc ghi) → ghi bù `child_submit` (Q-T20b-11 — P12 (a) vế 1 không đánh thức cha mãi).
- `deliver(cid, needs, payload)`: dưới khoá con — con đang đúng trạng thái + đúng node chờ (`answer` → `S_CLARIFYING`/`clarify_wait`;
  `confirm` → `S_CONFIRMING`/`confirm_wait`) → resume lồng → `"delivered"`; lệch (đã giao ở lần chạy trước, hoặc con đã đi tiếp) →
  `"skipped"`, KHÔNG `late_event`. `TicketBusy` → thử lại sau `busy_delay_s` × `busy_retries` rồi ném (E9 cha — hiếm).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from langgraph.types import Command, StateSnapshot
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.domain.exit_codes import ExitCode
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_DIAGNOSING, S_ESCALATED
from app.graph import effects
from app.graph.goto import goto
from app.graph.ports import TicketBusy
from app.graph.routing import AUDIT

if TYPE_CHECKING:
    from app.graph.runner import Runner

log = logging.getLogger(__name__)

type DeliverOutcome = Literal["delivered", "skipped"]
type StartOutcome = Literal["started", "exists", "busy", "failed"]
# Không lấy được khoá con: `TicketBusy` (khoá bị giữ quá `lock_timeout`) hoặc pool khoá hết chờ (`max_overflow=0` — mỗi cha đang chạy cần
# 2 kết nối khoá; nợ: tăng pool ở `settings.py` sau cổng 5 — Q-T20b-6 C)
LOCK_UNAVAILABLE: Final = (TicketBusy, PoolTimeout)


@dataclass
class StartReport:
    started: list[str] = field(default_factory=list)
    busy: list[str] = field(default_factory=list)  # khoá con bận / pool khoá hết chờ (Q-T20b-6)
    failed: list[str] = field(default_factory=list)  # lượt lồng lỗi trước checkpoint đầu của con (soát S10 B-ii)
type Sleep = Callable[[float], Awaitable[None]]

# `needs` của ý → (node chờ của con, trạng thái lúc chờ)
WAIT_OF_NEEDS: Final[Mapping[str, tuple[str, str]]] = {
    "answer": ("clarify_wait", S_CLARIFYING),
    "confirm": ("confirm_wait", S_CONFIRMING),
}
CLASSIFY: Final = "b03_classify"  # con được gieo như thể B3/B5 vừa chạy (khuôn `Runner._divert_bound(seed=True)`)
DIAGNOSE: Final = "b06_diagnose"
E1_FIELDS: Final = ("exit_code", "escalation_reason_detail")
E1_REASONS: Final = frozenset({"out_of_scope", "split_span_invalid", "intent_low_confidence", "intent_not_enabled"})  # bảng 5.2.2
BUSY_RETRIES: Final = 5
BUSY_DELAY_S: Final = 1.0


class ChildOps:
    def __init__(
        self, runner: "Runner", *, sleep: Sleep = asyncio.sleep, busy_retries: int = BUSY_RETRIES,
        busy_delay_s: float = BUSY_DELAY_S,
    ) -> None:  # fmt: skip
        self._runner = runner
        self._sleep = sleep
        self._busy_retries = busy_retries
        self._busy_delay_s = busy_delay_s

    async def start_missing(self, parent: Mapping[str, Any], *, recorded: Collection[str]) -> StartReport:
        """Khởi động mọi con chưa có thread (idempotent). `started` = con vừa khởi động ở lần gọi này; `busy` = con chưa khởi động được vì
        khoá con đang bị giữ / pool khoá hết chờ (Q-T20b-6 — bỏ qua, lần đối soát sau thử lại; cha ghi tên vào `audit_detail`).
        `recorded` = con đã có dòng `child_submit` (mọi lượt) — bỏ qua; con đã có thread mà chưa có dòng → ghi bù (Q-T20b-11)."""
        report = StartReport()
        seeds: Mapping[str, Mapping[str, Any]] = parent.get("child_seeds") or {}
        for cid in parent.get("children") or []:
            if cid in recorded or await effects.peek(parent, "child_submit", step="B5", sub=cid) is not None:
                continue  # đã khởi động + ghi (lượt trước, hoặc chạy lại cùng lượt — D-18)
            outcome = await self._start(parent, cid, seeds[cid])
            if outcome in ("started", "exists"):  # "exists" ở đây = có thread mà thiếu dòng `child_submit` → ghi bù (Q-T20b-11)
                if outcome == "started":
                    report.started.append(cid)
                await effects.once(parent, "child_submit", _started, cid, step="B5", sub=cid)
            elif outcome == "busy":
                report.busy.append(cid)
            elif outcome == "failed":
                report.failed.append(cid)
        return report

    async def _start(self, parent: Mapping[str, Any], cid: str, seed: Mapping[str, Any]) -> StartOutcome:
        runner = self._runner
        if (await runner.snapshot(cid)).values:  # KHÔNG lấy khoá con đã khởi động (con đang chạy lượt dài không chặn cha — soát S10 8a)
            return "exists"
        values = {**seed, "requester_context": parent["requester_context"]}
        e1: dict[str, Any] = {k: values[k] for k in E1_FIELDS if k in values}
        if e1 and (e1.get("exit_code") != ExitCode.E1.value or e1.get("escalation_reason_detail") not in E1_REASONS):
            raise ValueError(f"seed con {cid}: E1 lạ")  # seed chỉ mang hằng bảng 5.2.2 — lớp thứ hai (soát S10 B-i)
        try:
            async with runner.hold(cid):
                return await self._start_locked(cid, values, e1)
        except LOCK_UNAVAILABLE:  # chưa khởi động được lúc này — không ghi `child_submit`; lần chạy sau của cha / lưới worker thử lại
            log.warning("ticket con %s: không lấy được khoá (bận / pool khoá hết chờ) — để lần đối soát sau khởi động", cid)
            return "busy"

    async def _start_locked(self, cid: str, values: Mapping[str, Any], e1: Mapping[str, Any]) -> StartOutcome:
        runner = self._runner
        if (await runner.snapshot(cid)).values:
            return "exists"  # đã khởi động ở lần chạy trước (thread có state) — không chạy lại từ đầu

        async def work(turn_id: str) -> None:
            seeded = {**values, "turn_id": turn_id}
            if e1:  # ý không chạy được (bảng 5.2.2 #1–#4) → E1 ngay, không B6
                update = await goto(seeded, S_ESCALATED, next_node=AUDIT, step="B5", event="child_not_runnable", **e1)
            else:
                update = await goto(seeded, S_DIAGNOSING, next_node=DIAGNOSE, step="B5", event="child_started")
            await runner.graph.aupdate_state(runner.config(cid), {**seeded, **update}, as_node=CLASSIFY)
            await runner.invoke_bound(cid, None)

        await self._nested(cid, "submit", values.get("session_id"), work)
        # Lượt lồng lỗi TRƯỚC checkpoint đầu của con (thread vẫn rỗng) → chưa khởi động: không ghi `child_submit` (soát S10 B-ii)
        return "started" if (await runner.snapshot(cid)).values else "failed"

    async def deliver(self, child_id: str, needs: str, payload: Mapping[str, Any]) -> DeliverOutcome:
        """Chuyển một sự kiện (`user_reply` / `confirmed` / `unresolved` / `timeout`) xuống con đang chờ ý `needs`."""
        node, status = WAIT_OF_NEEDS[needs]
        runner = self._runner
        for attempt in range(self._busy_retries + 1):
            try:
                async with runner.hold(child_id):
                    snap = await runner.snapshot(child_id)
                    if snap.values.get("status") != status or snap.next != (node,):
                        return "skipped"  # đã giao ở lần chạy trước / con đã đi tiếp — KHÔNG late_event

                    async def work(turn_id: str) -> None:
                        await runner.invoke_bound(child_id, Command(resume=dict(payload), update={"turn_id": turn_id}))

                    before = _progress(snap)
                    try:
                        await runner.run_nested_locked(
                            child_id, event_type="resume", session_id=snap.values.get("session_id"), work=work
                        )
                    except Exception:
                        if _progress(await runner.snapshot(child_id)) == before:
                            raise  # con CHƯA nhận resume — không được báo "đã giao" (soát lượt 2 FAIL-1): cha E9, thấy được (Q-T20b-5)
                        log.exception("lượt lồng của ticket con %s lỗi SAU khi đã nhận sự kiện — lượt còn mở, worker phục hồi", child_id)
                    return "delivered"
            except LOCK_UNAVAILABLE:  # Q-T20b-6: cả pool khoá hết chờ — thử lại rồi ném (E9 cha, thấy được — Q-T20b-5)
                if attempt == self._busy_retries:
                    raise
                await self._sleep(self._busy_delay_s)
        raise AssertionError("không tới")  # vòng lặp luôn return/raise

    async def _nested(
        self, cid: str, event_type: str, session_id: str | None, work: Callable[[str], Awaitable[None]]
    ) -> None:
        """Lượt con lồng; `Exception` của con KHÔNG làm hỏng lượt cha (lượt con để mở → worker phục hồi, `after_turn` đánh thức cha)."""
        try:
            await self._runner.run_nested_locked(cid, event_type=event_type, session_id=session_id, work=work)
        except Exception:
            log.exception("lượt lồng của ticket con %s lỗi — để worker phục hồi", cid)


def _progress(snap: StateSnapshot) -> tuple[Any, tuple[str, ...], Any]:
    """Mốc "con đã nhận sự kiện chưa": `checkpoint_id` + `next` + `values.turn_id`. Đã kiểm với LangGraph 1.2: resume được nhận rồi node
    lỗi thì `checkpoint_id` GIỮ NGUYÊN (giá trị resume là write chờ trên checkpoint cũ) nhưng `next` đổi (`('confirm_wait',)` → `()` —
    khuôn `runner._pending`); DB lỗi NGAY SAU khi LangGraph ghi write NULL (`__resume__` + `turn_id` của lượt — `Command(update=…)`) mà
    trước write của task thì `checkpoint_id` và `next` đều không đổi, chỉ `values.turn_id` đổi (soát lượt 3 NGHI-1) — resume vẫn nằm chờ,
    worker recover sẽ tiêu nó; chưa nhận gì (lỗi trước `ainvoke`, vd `turns.start`) → cả ba không đổi."""
    return snap.config.get("configurable", {}).get("checkpoint_id"), tuple(snap.next), snap.values.get("turn_id")


def _started(cid: str) -> str:
    return f"started:{cid}"
