"""Gói 2b — chống spam (D-54 a): phần thuần của `db/rate_limits.py` + Settings ngưỡng. Viết TỪ ĐẶC TẢ trước code (không mở
`db/rate_limits.py`): đặc tả `claude/dac-ta-bat-2-model.md` 4.8 + PLAN-2B1 mục 3.3 (công thức `Retry-After`, 3 ví dụ số), bảng ca
U13–U15.

Công thức (4.8 "Khi vượt ngưỡng", PLAN 3.3): với mỗi cửa sổ đang vượt, `t` = giờ của request thứ (số đếm − ngưỡng + 1) tính từ cũ
nhất; `r = t + độ dài cửa sổ − now`; `Retry-After = max(1, ceil(max r))`. Dòng thuộc cửa sổ khi `created_at > now − độ dài` (chặt).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.db.rate_limits import (
    RATE_LIMITED,
    Counter,
    RateLimits,
    Window,
    event_detail,
    over_limit,
    retry_after,
    since,
)
from app.settings import Settings
from pydantic import ValidationError

RATE_ENV = ("TICKET_RATE_10MIN", "TICKET_RATE_HOUR", "MESSAGE_RATE_10MIN")
NINE = datetime(2030, 5, 1, 9, 0, tzinfo=UTC)  # 09:00:00 của các ví dụ PLAN 3.3


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def at(minutes: int = 0, seconds: float = 0) -> datetime:
    return NINE + timedelta(minutes=minutes, seconds=seconds)


W10_TICKETS = Window("10m", 600, 10)
W1H_TICKETS = Window("1h", 3600, 30)
W10_MESSAGES = Window("10m", 600, 30)


# ---- U13: hàm thuần --------------------------------------------------------------------------------------------------------------


def test_u13_example1_tickets_10min_retry_after_300() -> None:
    """U13 — PLAN 3.3 ví dụ 1: 10 ticket 09:00:00…09:04:30, request thứ 11 lúc 09:05:00 → k = 1, t = 09:00:00 → 300."""
    assert retry_after([(W10_TICKETS, at(0))], at(5)) == 300


def test_u13_example2_messages_leaked_rows_retry_after_244() -> None:
    """U13 — PLAN 3.3 ví dụ 2: 32 dòng (2 dòng lọt do song song), ngưỡng 30, dòng thứ 3 từ cũ nhất 09:00:03.4, request 09:06:00 →
    243,4 → làm tròn LÊN 244."""
    assert retry_after([(W10_MESSAGES, at(0, 3.4))], at(6)) == 244


def test_u13_example3_both_windows_take_max_916() -> None:
    """U13 — PLAN 3.3 ví dụ 3: hai cửa sổ cùng vượt, r_10m = 120, r_1h = 915,4 → lấy LỚN NHẤT rồi làm tròn lên → 916."""
    now = at(60)
    t10 = now - timedelta(seconds=600) + timedelta(seconds=120)
    t1h = now - timedelta(seconds=3600) + timedelta(seconds=915.4)
    assert retry_after([(W10_TICKETS, t10), (W1H_TICKETS, t1h)], now) == 916
    assert retry_after([(W1H_TICKETS, t1h), (W10_TICKETS, t10)], now) == 916  # không phụ thuộc thứ tự


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        pytest.param(timedelta(0), 1, id="r-bang-0-toi-thieu-1"),  # t = now − w: dòng vừa ra khỏi cửa sổ
        pytest.param(timedelta(seconds=0.2), 1, id="r-0.2-len-1"),
        pytest.param(timedelta(seconds=299.001), 300, id="lam-tron-len"),
        pytest.param(timedelta(seconds=300), 300, id="so-nguyen-giu-nguyen"),
        pytest.param(timedelta(seconds=-5), 1, id="r-am-toi-thieu-1"),
    ],
)  # fmt: skip
def test_u13_minimum_one_and_ceil(offset: timedelta, expected: int) -> None:
    """U13: tối thiểu 1 giây, làm tròn lên theo giây (4.8). `t = now − 600 + offset` → `r = offset`."""
    now = at(30)
    t = now - timedelta(seconds=600) + offset
    value = retry_after([(W10_MESSAGES, t)], now)
    assert value == expected and type(value) is int


def test_u13_window_boundary_strict() -> None:
    """U13: biên cửa sổ `since = now − w`; dòng thuộc cửa sổ khi `created_at > since` (chặt) — dòng đúng bằng `now − w` nằm NGOÀI."""
    now = at(10)
    assert since(W10_MESSAGES, now) == now - timedelta(seconds=600)
    assert since(W1H_TICKETS, now) == now - timedelta(seconds=3600)
    edge = now - timedelta(seconds=600)
    assert not edge > since(W10_MESSAGES, now)  # định nghĩa "thuộc cửa sổ" của đặc tả: chặt
    assert retry_after([(W10_MESSAGES, edge)], now) == 1


@pytest.mark.parametrize(("count", "over"), [(0, False), (9, False), (10, True), (11, True), (32, True)])
def test_u13_over_limit_is_count_ge_limit(count: int, over: bool) -> None:
    """U13 + 4.8 "≤ 10 ticket trong 10 phút": số đếm (chưa tính request này) đủ ngưỡng → vượt. Bắt mutation 11 (`>=` → `>`)."""
    assert over_limit(count, W10_TICKETS) is over


def test_u13_limits_from_settings_and_windows() -> None:
    """4.8 ngưỡng: A = 10 phút + 1 giờ, B = 10 phút; tên cửa sổ `10m`/`1h` (giá trị `detail.window`)."""
    s = _settings(ticket_rate_10min=7, ticket_rate_hour=21, message_rate_10min=13)
    limits = RateLimits.from_settings(s)
    assert limits == RateLimits(ticket_10min=7, ticket_hour=21, message_10min=13)
    assert limits.ticket_windows() == (Window("10m", 600, 7), Window("1h", 3600, 21))
    assert limits.message_window() == Window("10m", 600, 13)


@pytest.mark.parametrize(
    ("counter", "window", "detail"),
    [
        ("tickets", Window("10m", 600, 10), {"counter": "tickets", "window": "10m", "limit": 10}),
        ("tickets", Window("1h", 3600, 30), {"counter": "tickets", "window": "1h", "limit": 30}),
        ("messages", Window("10m", 600, 30), {"counter": "messages", "window": "10m", "limit": 30}),
    ],
)  # fmt: skip
def test_u13_event_detail_three_keys_only(counter: Counter, window: Window, detail: dict[str, object]) -> None:
    """4.8 "Sự kiện": `detail = {"counter", "window", "limit"}` — đúng 3 khoá, không chữ người dùng."""
    assert event_detail(counter, window) == detail
    assert RATE_LIMITED == "rate_limited"


# ---- U14: Settings ------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def no_rate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Xoá 3 biến mà `conftest.py` gốc đặt = 100000 (G9) — để thấy mặc định của `settings.py`."""
    for name in RATE_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_rate_env")
def test_u14_defaults_10_30_30() -> None:
    """U14 — 4.8 ngưỡng [Chốt]: A ≤ 10 / 10 phút, ≤ 30 / giờ; B ≤ 30 / 10 phút."""
    s = _settings()
    assert (s.ticket_rate_10min, s.ticket_rate_hour, s.message_rate_10min) == (10, 30, 30)


@pytest.mark.usefixtures("no_rate_env")
@pytest.mark.parametrize("field", ["ticket_rate_10min", "ticket_rate_hour", "message_rate_10min"])
@pytest.mark.parametrize("value", [0, -1])
def test_u14_zero_or_negative_rejected(field: str, value: int) -> None:
    """U14 — 4.8 "Không có giá trị tắt": `Field(ge=1)` → 0 (hay số âm) là lỗi cấu hình."""
    with pytest.raises(ValidationError):
        _settings(**{field: value})
    assert getattr(_settings(**{field: 1}), field) == 1


@pytest.mark.usefixtures("no_rate_env")
@pytest.mark.parametrize("name", RATE_ENV)
def test_u14_env_zero_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """U14: biến môi trường `=0` cũng bị từ chối (không có đường "tắt" qua `.env`)."""
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.usefixtures("no_rate_env")
def test_u14_empty_env_means_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """U14 + G4: compose truyền `${X:-}` → chuỗi rỗng = chưa đặt = mặc định (`env_ignore_empty=True`)."""
    for name in RATE_ENV:
        monkeypatch.setenv(name, "")
    s = _settings()
    assert (s.ticket_rate_10min, s.ticket_rate_hour, s.message_rate_10min) == (10, 30, 30)


@pytest.mark.usefixtures("no_rate_env")
def test_u14_env_values_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """4.8: tên biến `TICKET_RATE_10MIN`, `TICKET_RATE_HOUR`, `MESSAGE_RATE_10MIN`."""
    for name, value in zip(RATE_ENV, ("4", "5", "6"), strict=True):
        monkeypatch.setenv(name, value)
    s = _settings()
    assert (s.ticket_rate_10min, s.ticket_rate_hour, s.message_rate_10min) == (4, 5, 6)


# ---- U15: conftest -----------------------------------------------------------------------------------------------------------------


def test_u15_conftest_makes_test_settings_loose() -> None:
    """U15 — 4.8 "test: Settings dùng trong test mặc định số lớn": `Settings` dựng trong test (không truyền ngưỡng) có cả 3 ≥ 100000."""
    s = _settings()
    assert min(s.ticket_rate_10min, s.ticket_rate_hour, s.message_rate_10min) >= 100000
    limits = RateLimits.from_settings(s)
    assert min(w.limit for w in (*limits.ticket_windows(), limits.message_window())) >= 100000


# ---- U22: cảnh báo lúc khởi động khi ngưỡng bị nới ngoài dev/test (Q-2B1-8) ---------------------------------------------------


_DEFAULTS = {"ticket_rate_10min": 10, "ticket_rate_hour": 30, "message_rate_10min": 30}


def _warnings(caplog: pytest.LogCaptureFixture, **over: Any) -> list[str]:
    from app.main import create_app
    from tests.fakes.runtime import no_runtime
    from tests.unit.auth_helpers import auth_settings

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.main"):
        create_app(auth_settings(**{**_DEFAULTS, **over}), health_checks={}, runtime=no_runtime)
    return [r.getMessage() for r in caplog.records if r.name == "app.main" and "429" in r.getMessage()]


def test_u22_loose_rates_outside_dev_test_warn_names_only(caplog: pytest.LogCaptureFixture) -> None:
    """U22 (Q-2B1-8): APP_ENV không phải dev/test + ngưỡng > mặc định → MỘT WARNING nêu TÊN biến (không giá trị), app vẫn dựng."""
    [msg] = _warnings(caplog, app_env="staging", ticket_rate_10min=100000, message_rate_10min=31)
    assert "TICKET_RATE_10MIN" in msg and "MESSAGE_RATE_10MIN" in msg and "TICKET_RATE_HOUR" not in msg
    assert "100000" not in msg and "31" not in msg
    [msg] = _warnings(caplog, app_env=None, ticket_rate_hour=31)  # thiếu APP_ENV = môi trường thật
    assert "TICKET_RATE_HOUR" in msg


@pytest.mark.parametrize("over", [
    {"app_env": "dev", "ticket_rate_10min": 100000}, {"app_env": "test", "message_rate_10min": 100000},
    {"app_env": "staging"}, {"app_env": "staging", "ticket_rate_10min": 5},
])  # fmt: skip
def test_u22_no_warning_in_dev_test_or_at_or_below_default(caplog: pytest.LogCaptureFixture, over: dict[str, Any]) -> None:
    """U22: dev/test được nới (cổng, đo); bằng hoặc thấp hơn mặc định thì không cảnh báo."""
    assert _warnings(caplog, **over) == []
