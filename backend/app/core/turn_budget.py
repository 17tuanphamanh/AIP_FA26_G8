"""Hạn cho cả lượt (phase3 mục 9.0 — chốt Q-3e-12, PLAN-3f S0).

Runner đặt hạn TUYỆT ĐỐI khi nhận lượt (`bind_turn_deadline`, trước semaphore) — contextvar, KHÔNG vào state/checkpoint
(chạy lại lượt thì hạn mới). Mọi lời gọi ra ngoài (ToolRegistry, MlClient, LLMClient, Retriever) lấy timeout =
`cap_timeout(timeout riêng)` = min(timeout riêng, còn lại − biên an toàn) và không ngủ backoff vượt phần còn lại
(`check_sleep`). Còn lại ≤ biên → `TurnBudgetExceeded` TRƯỚC khi gửi: node/boundary đưa về E2 `turn_budget_exceeded`
(không cho qua, không E3). Ngoài lượt (đăng nhập, CLI ingest…) không có hạn → không cắt.

Ở `core` vì tools/ml/llm/rag không được import `graph` (.importlinter 6–8).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from app.core.clock import Clock


class TurnBudgetExceeded(Exception):
    """Lượt hết hạn — không phải lỗi hệ thống ngoài, không phải bug: E2 `turn_budget_exceeded`. Thông điệp chỉ có tên
    điểm gọi và số giây — không có dữ liệu người dùng."""


@dataclass(frozen=True)
class TurnDeadline:
    at: datetime  # thời điểm tuyệt đối (clock của runner) lượt phải xong phần gọi ra ngoài
    margin_s: float  # SAFETY_MARGIN_S: phần dành cho việc sau lời gọi (goto, audit, B20)


_TURN: ContextVar[TurnDeadline | None] = ContextVar("turn_deadline", default=None)


@contextmanager
def bind_turn_deadline(deadline: TurnDeadline) -> Iterator[TurnDeadline]:
    token = _TURN.set(deadline)
    try:
        yield deadline
    finally:
        _TURN.reset(token)


def current_deadline() -> TurnDeadline | None:
    return _TURN.get()


def usable_s(clock: Clock) -> float | None:
    """Giây còn dùng được cho lời gọi ra ngoài = còn lại − biên an toàn; None = ngoài lượt (không có hạn)."""
    deadline = _TURN.get()
    if deadline is None:
        return None
    return (deadline.at - clock.now()).total_seconds() - deadline.margin_s


def cap_timeout(timeout_s: float, clock: Clock, *, what: str, full: bool = False) -> float:
    """Timeout cho MỘT lần gọi. `full=True` (tool ghi): không đủ trọn `timeout_s` → không gửi — gửi với timeout rút ngắn
    để lại trạng thái "đã ghi hay chưa" ở hệ thống ngoài."""
    left = usable_s(clock)
    if left is None:
        return timeout_s
    if left <= 0 or (full and left < timeout_s):
        raise TurnBudgetExceeded(f"{what}: còn {max(left, 0.0):.1f}s dùng được, cần {timeout_s:g}s")
    return min(timeout_s, left)


def check_sleep(seconds: float, clock: Clock, *, what: str) -> None:
    """Trước khi ngủ backoff: ngủ xong không còn thời gian gọi lại → dừng ngay (không ngủ vô ích tới hết hạn)."""
    left = usable_s(clock)
    if left is not None and seconds >= left:
        raise TurnBudgetExceeded(f"{what}: backoff {seconds:g}s ≥ còn {max(left, 0.0):.1f}s dùng được")


def window(limit_s: float, clock: Clock, *, what: str) -> tuple[float, bool]:
    """Khung thời gian cho một KHỐI nhiều lời gọi đã có deadline riêng (RAG `rag_deadline_s`, LLM `deadline_s`):
    `(giây, bị_hạn_lượt_chặn)`. `True` → hết khung là hết hạn lượt: bên gọi ném `TurnBudgetExceeded`, không đổi thành lỗi
    hệ thống của chính nó (E2 `rag_system_error`/`LLMUnavailable`)."""
    left = usable_s(clock)
    if left is None:
        return limit_s, False
    if left <= 0:
        raise TurnBudgetExceeded(f"{what}: còn {max(left, 0.0):.1f}s dùng được")
    return (left, True) if left < limit_s else (limit_s, False)
