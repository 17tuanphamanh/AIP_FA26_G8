"""M9 A0 — cửa sổ thời gian (hợp đồng mục 3; Q-M9-2: ngày/tuần theo giờ VN, mốc trả về kiểu UTC)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from app.monitor.window import VN_TZ, bucket_start, day_start, hour_start, week_start


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0, us: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, us, tzinfo=UTC)


def test_day_boundary_vn() -> None:
    # 23:59:59 và 00:00:00 giờ VN (UTC+7) rơi vào hai ngày VN khác nhau
    before = day_start(utc(2026, 9, 29, 16, 59, 59))
    after = day_start(utc(2026, 9, 29, 17, 0, 0))
    assert before == utc(2026, 9, 28, 17, 0)  # 29/09 00:00 VN
    assert after == utc(2026, 9, 29, 17, 0)  # 30/09 00:00 VN
    assert before != after
    assert before.utcoffset() == after.utcoffset() == UTC.utcoffset(None)


def test_day_start_accepts_non_utc_input() -> None:
    ts = utc(2026, 9, 29, 16, 59, 59)
    assert day_start(ts.astimezone(VN_TZ)) == day_start(ts)


def test_week_start_is_monday_vn() -> None:
    assert week_start(utc(2026, 9, 30, 3, 0)) == utc(2026, 9, 27, 17, 0)  # thứ Tư → thứ Hai 28/09 00:00 VN
    last_second = week_start(utc(2026, 10, 4, 16, 59, 59))  # Chủ nhật 23:59:59 VN
    new_week = week_start(utc(2026, 10, 4, 17, 0, 0))  # thứ Hai 05/10 00:00 VN
    assert last_second == utc(2026, 9, 27, 17, 0)
    assert new_week == utc(2026, 10, 4, 17, 0)
    for ws in (last_second, new_week):
        local = ws.astimezone(VN_TZ)
        assert (local.weekday(), local.hour, local.minute) == (0, 0, 0)


def test_day_and_week_start_honor_tz_argument() -> None:
    # X3: tham số `tz` phải được dùng — Tokyo (UTC+9) khác giờ VN (UTC+7) 2 tiếng
    tokyo = ZoneInfo("Asia/Tokyo")
    ts = utc(2026, 9, 30, 15, 30)  # 30/09 22:30 VN, 01/10 00:30 Tokyo
    assert day_start(ts, tz=tokyo) == utc(2026, 9, 30, 15, 0)  # 01/10 00:00 Tokyo
    assert day_start(ts) == utc(2026, 9, 29, 17, 0)  # 30/09 00:00 VN
    sunday_tokyo = utc(2026, 10, 4, 15, 30)  # Chủ nhật 22:30 VN, thứ Hai 05/10 00:30 Tokyo
    assert week_start(sunday_tokyo, tz=tokyo) == utc(2026, 10, 4, 15, 0)  # thứ Hai 05/10 00:00 Tokyo
    assert week_start(sunday_tokyo) == utc(2026, 9, 27, 17, 0)  # thứ Hai 28/09 00:00 VN
    local = week_start(sunday_tokyo, tz=tokyo).astimezone(tokyo)
    assert (local.weekday(), local.hour, local.minute) == (0, 0, 0)


def test_hour_start_truncates() -> None:
    assert hour_start(datetime(2026, 9, 30, 10, 59, 59, 999000, tzinfo=UTC)) == utc(2026, 9, 30, 10, 0)


def test_bucket_start_5_minutes() -> None:
    assert bucket_start(utc(2026, 9, 30, 10, 7, 31), 5) == utc(2026, 9, 30, 10, 5)
    assert bucket_start(utc(2026, 9, 30, 10, 5, 0), 5) == utc(2026, 9, 30, 10, 5)
    assert bucket_start(datetime(2026, 9, 30, 10, 4, 59, 999999, tzinfo=UTC), 5) == utc(2026, 9, 30, 10, 0)
    with pytest.raises(ValueError):
        bucket_start(utc(2026, 9, 30, 10, 7), 0)


def test_naive_datetime_rejected() -> None:
    naive = datetime(2026, 9, 30, 10, 7)  # noqa: DTZ001 — cố ý naive
    for call in (
        lambda: day_start(naive),
        lambda: hour_start(naive),
        lambda: week_start(naive),
        lambda: bucket_start(naive, 5),
    ):
        with pytest.raises(ValueError):
            call()
