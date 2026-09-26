"""P5 mục 6 / mục 8 "Breaker": 5 lỗi → mở; lời gọi thứ 6 không chạm hệ thống; sau 30s → half-open."""

from datetime import timedelta

from app.core.clock import FakeClock
from app.settings import Settings
from app.tools.breaker import BreakerBoard, CircuitBreaker

S = Settings(_env_file=None)  # type: ignore[call-arg]


def _breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker("ad", clock, S.breaker_failure_threshold, S.breaker_window_seconds,
                          S.breaker_open_seconds)  # fmt: skip


def _fail(b: CircuitBreaker, n: int) -> None:
    for _ in range(n):
        assert b.allow()
        b.record_failure()


def test_defaults_match_spec() -> None:
    assert (S.breaker_failure_threshold, S.breaker_window_seconds, S.breaker_open_seconds) == (5, 60, 30)


def test_opens_after_threshold_and_rejects() -> None:
    b = _breaker(FakeClock())
    _fail(b, 4)
    assert b.state == "closed"
    _fail(b, 1)
    assert b.state == "open" and not b.allow()


def test_success_resets_consecutive_count() -> None:
    b = _breaker(FakeClock())
    _fail(b, 4)
    b.allow()
    b.record_success()
    _fail(b, 4)
    assert b.state == "closed"


def test_failures_outside_window_do_not_count() -> None:
    clock = FakeClock()
    b = _breaker(clock)
    _fail(b, 4)
    clock.advance(timedelta(seconds=61))
    _fail(b, 1)
    assert b.state == "closed"


def test_half_open_after_open_period_single_probe() -> None:
    clock = FakeClock()
    b = _breaker(clock)
    _fail(b, 5)
    clock.advance(timedelta(seconds=29))
    assert not b.allow()
    clock.advance(timedelta(seconds=1))
    assert b.allow() and b.state == "half_open"
    assert not b.allow()  # chỉ đúng 1 lời gọi thử


def test_probe_success_closes_probe_failure_reopens() -> None:
    clock = FakeClock()
    b = _breaker(clock)
    _fail(b, 5)
    clock.advance(timedelta(seconds=30))
    assert b.allow()
    b.record_failure()
    assert b.state == "open" and not b.allow()
    clock.advance(timedelta(seconds=30))
    assert b.allow()
    b.record_success()
    assert b.state == "closed" and b.allow()


def test_board_one_breaker_per_system() -> None:
    board = BreakerBoard(FakeClock(), 5, 60, 30)
    assert board["ad"] is board["ad"] and board["ad"] is not board["vpn"]
