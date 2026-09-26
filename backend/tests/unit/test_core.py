"""core: ids, clock, errors, logging JSON."""

import json
import logging
import re
from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.core.clock import FakeClock, SystemClock
from app.core.errors import DomainError, ExternalSystemError, LLMSchemaError
from app.core.ids import new_ticket_id, new_trace_id, new_turn_id
from app.core.logging import JsonFormatter, bind_log_context


def test_ids_unique_and_fit_varchar64() -> None:
    ids = {new_ticket_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) <= 64 for i in ids)
    assert new_turn_id() != new_turn_id()


def test_trace_id_is_otel_format() -> None:
    assert re.fullmatch(r"[0-9a-f]{32}", new_trace_id())


def test_system_clock_is_utc_aware() -> None:
    assert SystemClock().now().tzinfo is not None


def test_fake_clock_advance_and_set() -> None:
    clock = FakeClock(datetime(2026, 9, 25, 8, 0, tzinfo=UTC))
    clock.advance(timedelta(hours=24))
    assert clock.now() == datetime(2026, 9, 26, 8, 0, tzinfo=UTC)
    clock.set(datetime(2026, 9, 25, 15, 0, tzinfo=timezone(timedelta(hours=7))))
    assert clock.now() == datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
    assert clock.now().tzinfo == UTC


def test_fake_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 9, 25))  # noqa: DTZ001 — cố ý truyền datetime không múi giờ


def test_errors_are_distinct() -> None:
    # E2 ≠ E3: lỗi hệ thống ngoài không được lẫn với lỗi nghiệp vụ.
    assert not issubclass(ExternalSystemError, DomainError)
    assert not issubclass(LLMSchemaError, DomainError)


def _format(msg: str) -> dict[str, object]:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, None, None)
    parsed: dict[str, object] = json.loads(JsonFormatter().format(record))
    return parsed


def test_json_log_carries_context() -> None:
    with bind_log_context(ticket_id="t-1", trace_id="abc"), bind_log_context(turn_id="turn-2"):
        out = _format("Đã xác thực")
    assert out["msg"] == "Đã xác thực"
    assert out["level"] == "INFO"
    assert (out["ticket_id"], out["trace_id"], out["turn_id"]) == ("t-1", "abc", "turn-2")


def test_json_log_context_resets_after_block() -> None:
    with bind_log_context(ticket_id="t-1"):
        pass
    assert _format("x")["ticket_id"] is None


def test_json_log_rejects_unknown_context_key() -> None:
    with pytest.raises(ValueError), bind_log_context(raw_request="..."):
        pass


@pytest.mark.asyncio
async def test_fake_clock_sleep_advances_without_waiting() -> None:
    clock = FakeClock(datetime(2026, 9, 25, 8, 0, tzinfo=UTC))
    await clock.sleep(1)
    await clock.sleep(2)
    assert clock.sleeps == [1, 2]
    assert clock.now() == datetime(2026, 9, 25, 8, 0, 3, tzinfo=UTC)
