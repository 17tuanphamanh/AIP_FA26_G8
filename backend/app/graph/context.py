"""Ngữ cảnh một lượt chạy graph, do runner gắn qua contextvar (P1 mục 2).

`goto`, `effects.once`, `traced` đọc từ đây nên chữ ký giữ đúng như đặc tả (`goto(state, S_X, …)`,
`once(state, kind, fn, …)`) mà không phải truyền store vào từng node. asyncio chép context khi tạo
task, nên node LangGraph thấy giá trị runner đặt trước `ainvoke` (đã kiểm với LangGraph 1.2).

`turn_id` ở đây là NGUỒN của mọi khoá idempotent (không đọc `state["turn_id"]`): recover giữ đúng
turn_id cũ kể cả khi process chết trước checkpoint đầu tiên của lượt resume (D-18).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.core.clock import Clock
from app.graph.ports import AuditSink, EffectStore, SpanSink


@dataclass(frozen=True)
class RunContext:
    turn_id: str
    trace_id: str
    audit: AuditSink
    effects: EffectStore
    spans: SpanSink
    clock: Clock
    rediagnose_on_new_slot: bool = False  # D-20, cờ tắt mặc định


_RUN: ContextVar[RunContext | None] = ContextVar("graph_run", default=None)


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
