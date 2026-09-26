"""Sinh định danh. ticket_id/turn_id vừa cột VARCHAR(64) của P7; trace_id theo OpenTelemetry."""

from uuid import uuid4


def new_ticket_id() -> str:
    return str(uuid4())


def new_turn_id() -> str:
    return str(uuid4())


def new_trace_id() -> str:
    # 32 ký tự hex — định dạng trace-id của OpenTelemetry (P1 mục 9).
    return uuid4().hex
