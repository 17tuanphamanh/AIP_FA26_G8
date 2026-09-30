"""Cửa sổ thời gian của M9 (hợp đồng A0 mục 3; Q-M9-2: "ngày"/"tuần" theo giờ Việt Nam).

Mọi hàm nhận datetime CÓ múi giờ (naive → ValueError) và trả mốc biên kiểu UTC — lưu và so sánh vẫn UTC,
chỉ ranh giới ngày/tuần tính theo `tz`. `hour_start`, `bucket_start` cắt theo UTC: múi giờ VN lệch nguyên giờ nên
trùng với biên giờ VN.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # Q-M9-2
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("cần datetime có múi giờ")
    return ts


def day_start(ts: datetime, tz: ZoneInfo = VN_TZ) -> datetime:
    """00:00 theo `tz` của ngày chứa `ts`, kiểu UTC."""
    local = _aware(ts).astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def hour_start(ts: datetime) -> datetime:
    return _aware(ts).astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def week_start(ts: datetime, tz: ZoneInfo = VN_TZ) -> datetime:
    """Thứ Hai 00:00 theo `tz` của tuần chứa `ts`, kiểu UTC."""
    local = _aware(ts).astimezone(tz)
    monday = local - timedelta(days=local.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def bucket_start(ts: datetime, minutes: int) -> datetime:
    """Đầu khung `minutes` phút chứa `ts` (khung tính từ epoch; luật 10 dùng 5 phút), kiểu UTC."""
    if minutes <= 0:
        raise ValueError("minutes phải > 0")
    step = timedelta(minutes=minutes)
    return _EPOCH + ((_aware(ts).astimezone(UTC) - _EPOCH) // step) * step
