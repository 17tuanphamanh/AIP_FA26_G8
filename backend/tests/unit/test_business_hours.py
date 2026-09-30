"""h20 — `within_business_hours` (phase3 11.7 h20; định nghĩa ở 11.2: đổi `Clock.now()` sang `tz`; thứ ISO ∈ `weekdays`
và `start ≤ giờ < end`; không xét ngày lễ). Giờ lấy từ `config/policy.json` qua `get_policy().business_hours`.

Mốc: thứ Hai 28/09/2026 … thứ Sáu 02/10/2026, thứ Bảy 03/10, Chủ nhật 04/10 (giờ Asia/Ho_Chi_Minh). Không dùng đồng hồ thật.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from app.domain.policy import within_business_hours
from app.settings import get_policy

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _vn(month: int, day: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, month, day, hh, mm, ss, tzinfo=VN)


def _utc(month: int, day: int, hh: int, mm: int) -> datetime:
    return datetime(2026, month, day, hh, mm, tzinfo=UTC)


# 5 mốc bắt buộc của bảng 11.7 (h20) + Chủ nhật (lời giao 3h).
H20_BAT_BUOC = [
    pytest.param(_vn(9, 29, 7, 59), False, id="h20-thu-ba-07:59-F"),
    pytest.param(_vn(9, 29, 8, 0), True, id="h20-thu-ba-08:00-T"),
    pytest.param(_vn(9, 29, 17, 59), True, id="h20-thu-ba-17:59-T"),
    pytest.param(_vn(9, 29, 18, 0), False, id="h20-thu-ba-18:00-F"),
    pytest.param(_vn(10, 3, 10, 0), False, id="h20-thu-bay-10:00-F"),
    pytest.param(_vn(10, 4, 10, 0), False, id="h20-chu-nhat-10:00-F"),
]

# Suy từ định nghĩa 11.2: biên theo giây (start ≤ giờ < end), biên thứ trong weekdays [1..5], và đổi tz trước khi so.
H20_SUY_RA = [
    pytest.param(_vn(9, 29, 7, 59, 59), False, id="thu-ba-07:59:59-F"),
    pytest.param(_vn(9, 29, 17, 59, 59), True, id="thu-ba-17:59:59-T"),
    pytest.param(_vn(9, 28, 8, 0), True, id="thu-hai-08:00-T"),
    pytest.param(_vn(10, 2, 17, 59), True, id="thu-sau-17:59-T"),
    pytest.param(_vn(10, 3, 8, 0), False, id="thu-bay-08:00-F"),
    pytest.param(_vn(10, 4, 17, 59), False, id="chu-nhat-17:59-F"),
    pytest.param(_utc(9, 29, 3, 0), True, id="utc-thu-ba-03:00=vn-10:00-T"),
    pytest.param(_utc(9, 29, 0, 59), False, id="utc-thu-ba-00:59=vn-07:59-F"),
    pytest.param(_utc(9, 29, 1, 0), True, id="utc-thu-ba-01:00=vn-08:00-T"),
    pytest.param(_utc(9, 29, 11, 0), False, id="utc-thu-ba-11:00=vn-18:00-F"),  # 11:00 UTC "trong giờ" nếu quên đổi tz
    pytest.param(_utc(10, 2, 17, 30), False, id="utc-thu-sau-17:30=vn-thu-bay-00:30-F"),  # đổi tz đổi cả thứ
    pytest.param(_utc(10, 4, 23, 30), False, id="utc-chu-nhat-23:30=vn-thu-hai-06:30-F"),
    pytest.param(_utc(10, 5, 1, 0), True, id="utc-thu-hai-01:00=vn-thu-hai-08:00-T"),
]


@pytest.mark.parametrize(("now", "mong_doi"), H20_BAT_BUOC)
def test_h20_bien_gio_hanh_chinh(now: datetime, mong_doi: bool) -> None:
    """h20 (phase3 11.7): 07:59, 08:00, 17:59, 18:00 ngày thường, thứ Bảy → F, T, T, F, F; Chủ nhật → F."""
    assert within_business_hours(now, get_policy().business_hours) is mong_doi


@pytest.mark.parametrize(("now", "mong_doi"), H20_SUY_RA)
def test_h20_bien_suy_tu_dinh_nghia_11_2(now: datetime, mong_doi: bool) -> None:
    """h20 mở rộng (phase3 11.2): `end` không bao gồm (M-3h-4), thứ ISO 1–5, `now` UTC phải đổi sang Asia/Ho_Chi_Minh."""
    assert within_business_hours(now, get_policy().business_hours) is mong_doi


def test_h20_moc_ngay_dung_thu() -> None:
    """Quy ước 3.9: bảng không rỗng, đủ 6 mốc; tự kiểm mốc ngày đúng thứ ISO (tránh test đúng vì chọn sai ngày)."""
    assert len(H20_BAT_BUOC) >= 6 and len(H20_SUY_RA) >= 10
    assert _vn(9, 28, 0, 0).isoweekday() == 1
    assert _vn(9, 29, 0, 0).isoweekday() == 2
    assert _vn(10, 2, 0, 0).isoweekday() == 5
    assert _vn(10, 3, 0, 0).isoweekday() == 6
    assert _vn(10, 4, 0, 0).isoweekday() == 7
    assert _utc(10, 2, 17, 30).astimezone(VN).isoweekday() == 6
    assert _utc(10, 4, 23, 30).astimezone(VN).isoweekday() == 1
