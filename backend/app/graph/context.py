"""Ngữ cảnh một lượt chạy graph, do runner gắn qua contextvar (P1 mục 2).

`goto`, `effects.once`, `traced` đọc từ đây nên chữ ký giữ đúng như đặc tả (`goto(state, S_X, …)`,
`once(state, kind, fn, …)`) mà không phải truyền store vào từng node. asyncio chép context khi tạo
task, nên node LangGraph thấy giá trị runner đặt trước `ainvoke` (đã kiểm với LangGraph 1.2).

`turn_id` ở đây là NGUỒN của mọi khoá idempotent (không đọc `state["turn_id"]`): recover giữ đúng
turn_id cũ kể cả khi process chết trước checkpoint đầu tiên của lượt resume (D-18).
"""

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.clock import Clock
from app.executor.txlog import TxLog
from app.graph.ports import AuditSink, EffectStore, SpanSink


class StartLike(Protocol):
    """`graph.children.StartReport` theo cấu trúc: con vừa khởi động / chưa khởi động được vì khoá (Q-T20b-6)."""

    @property
    def started(self) -> list[str]: ...

    @property
    def busy(self) -> list[str]: ...

    @property
    def failed(self) -> list[str]: ...


class ChildPort(Protocol):
    """`graph.children.ChildOps` theo cấu trúc (Phase 5 T20b P4, P8) — khai báo ở đây để `context` không import `children`/`runner`
    (node import `context`; import-linter "graph.nodes.* không import lẫn nhau" đếm cả import TYPE_CHECKING)."""

    async def start_missing(self, parent: Mapping[str, Any], *, recorded: Collection[str]) -> "StartLike": ...

    async def deliver(self, child_id: str, needs: str, payload: Mapping[str, Any]) -> str: ...


@dataclass(frozen=True)
class RunContext:
    turn_id: str
    trace_id: str
    audit: AuditSink
    effects: EffectStore
    spans: SpanSink
    clock: Clock
    # BẮT BUỘC (không mặc định "chưa có gì" — fail-open): boundary hỏi `begun` theo ticket trước khi hạ lỗi xuống E9/E2
    # (Việc treo 21, 3h DỪNG 3b)
    txlog: TxLog
    rediagnose_on_new_slot: bool = False  # D-20, cờ tắt mặc định
    # Phase 5 T20b (P4, P8): khởi động con / chuyển sự kiện xuống con — runner gắn; node cha đọc `current_run().children`
    children: ChildPort | None = None


_RUN: ContextVar[RunContext | None] = ContextVar("graph_run", default=None)


def run_or_none() -> RunContext | None:
    """Như `current_run` nhưng trả None ngoài lượt (LLM gateway hỏi xem có lượt để ghi trace không, 3d)."""
    return _RUN.get()


def current_run() -> RunContext:
    run = _RUN.get()
    if run is None:
        raise RuntimeError("Chưa có RunContext — node chỉ chạy được qua runner (graph/runner.py)")
    return run


@contextmanager
def bind_run(run: RunContext) -> Iterator[RunContext]:
    token = _RUN.set(run)
    try:
        yield run
    finally:
        _RUN.reset(token)
