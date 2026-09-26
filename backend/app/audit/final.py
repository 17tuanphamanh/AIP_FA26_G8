"""Tổng hợp kết quả cuối của ticket cho B20 (B20 mục 2 bước 1, 3; điểm log 8) — hàm thuần.

`resolution_path` (NGU-CANH 9.1: auto | approved | rejected | escalated | deflected) do B20 suy ra ở MỘT
chỗ (quyết định Q-A 2b-2), không do node đặt vào state: `TicketState` không có key này và LangGraph bỏ
im lặng key lạ (nay `check_state_keys` chặn thành lỗi).

| Trạng thái cuối | resolution_path |
|---|---|
| ticket cha (D-30) | NULL |
| S_ESCALATED | escalated (kể cả ca B17 đã chạy rồi người dùng báo "chưa ổn" → E8) |
| S_REJECTED | rejected |
| S_BLOCKED | NULL — không giá trị nào trong 5 giá trị mô tả "bị chặn"; CHECK cho qua NULL |
| S_RESOLVED | deflected nếu `need_type=info`; approved nếu `approval_result=approved`; còn lại auto |
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.domain.exit_codes import CloseReason
from app.domain.final import FinalSummary
from app.domain.states import S_BLOCKED, S_ESCALATED, S_REJECTED, S_RESOLVED

__all__ = ["FinalSummary", "resolution_path", "summarize_final"]


def resolution_path(state: Mapping[str, Any]) -> str | None:
    if state.get("is_parent"):
        return None
    status = state["status"]
    if status == S_ESCALATED:
        return "escalated"
    if status == S_REJECTED:
        return "rejected"
    if status == S_RESOLVED:
        if state.get("need_type") == "info":
            return "deflected"
        return "approved" if state.get("approval_result") == "approved" else "auto"
    if status == S_BLOCKED:
        return None
    raise ValueError(f"B20 chỉ nhận trạng thái kết thúc, gặp {status!r}")


def summarize_final(
    state: Mapping[str, Any], *, created_at: datetime, total_turns: int, now: datetime
) -> FinalSummary:
    close_reason = state.get("close_reason")
    return FinalSummary(
        final_state=state["status"],
        exit_code=state.get("exit_code"),
        block_reason=state.get("block_reason"),
        close_reason=close_reason,
        resolution_path=resolution_path(state),
        aggregate_status=state.get("aggregate_status"),
        auto_closed=close_reason == CloseReason.RESOLVED_AUTO_TIMEOUT_48H.value,
        intent=state.get("intent"),
        slots=dict(state["slots"]) if state.get("slots") else None,
        total_turns=total_turns,
        total_duration_seconds=max(0, int((now - created_at).total_seconds())),
        closed_at=now,
    )
