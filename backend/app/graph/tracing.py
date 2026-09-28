"""traced() — span `node:<tên>` cho mỗi lần chạy node (P1 mục 9, huong-dan 17.1).

Trạng thái span: `ok`, `error` (exception lọt ra, hoặc boundary đánh dấu qua `mark_error`),
`interrupted` (node dừng chờ người — `GraphInterrupt`). Span con (LLM, tool, RAG) đọc `current_span()`
làm cha. Ghi span lỗi không được làm hỏng lượt chạy: lỗi ghi chỉ log.
"""

import functools
import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from langgraph.errors import GraphBubbleUp

from app.graph.context import current_run, run_or_none
from app.graph.ports import SpanRecord
from app.llm.ports import TraceParent

log = logging.getLogger(__name__)

type NodeFn = Callable[[Any], Awaitable[dict[str, Any]]]

TRACEBACK_LIMIT = 4096  # P1 mục 5.2: traceback rút gọn ≤ 4 KB
_SPAN: ContextVar[SpanRecord | None] = ContextVar("graph_span", default=None)


def current_span() -> SpanRecord | None:
    return _SPAN.get()


def trace_parent() -> TraceParent | None:
    """Lượt + span node đang chạy cho LLM gateway (`llm` không import `graph` — PLAN-3d Q-3d-2). Ngoài lượt → None."""
    run = run_or_none()
    if run is None:
        return None
    span = _SPAN.get()
    return TraceParent(run.turn_id, run.trace_id, span.span_id if span else None)


def short_traceback(exc: BaseException) -> str:
    text = "".join(traceback.format_exception(exc))
    return text if len(text) <= TRACEBACK_LIMIT else "…" + text[-(TRACEBACK_LIMIT - 1) :]


def mark_error(exc: BaseException) -> None:
    """Boundary gọi khi nuốt exception: span vẫn phải ghi `error` (P1 mục 5.2, huong-dan 17.1)."""
    span = _SPAN.get()
    if span is not None:
        span.status = "error"
        span.attributes["unhandled_exception"] = f"{type(exc).__name__}: {exc}"[:500]
        span.attributes["traceback"] = short_traceback(exc)


def traced(name: str, fn: NodeFn) -> NodeFn:
    @functools.wraps(fn)
    async def wrapped(state: Any) -> dict[str, Any]:
        run = current_run()
        parent = _SPAN.get()
        span = SpanRecord(
            span_id=uuid4().hex,
            trace_id=run.trace_id,
            turn_id=run.turn_id,
            span_type="node",
            name=f"node:{name}",
            started_at=run.clock.now(),
            parent_span_id=parent.span_id if parent else None,
        )
        token = _SPAN.set(span)
        t0 = time.perf_counter()
        try:
            return await fn(state)
        except GraphBubbleUp:
            span.status = "interrupted"
            raise
        except BaseException as exc:
            mark_error(exc)
            raise
        finally:
            span.duration_ms = int((time.perf_counter() - t0) * 1000)
            _SPAN.reset(token)
            try:
                await run.spans.write(span)
            except Exception:  # trace hỏng không được làm hỏng ticket
                log.exception("không ghi được span %s", span.name)

    wrapped.__dict__["traced"] = True
    return wrapped
