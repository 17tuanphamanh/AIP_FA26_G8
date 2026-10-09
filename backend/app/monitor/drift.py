"""Drift M9 (luật 8, chặng B3 — issue #15) — PSI giữa phân bố tuần mốc và tuần đo; THUẦN: không I/O, không đồng hồ,
không log.

Chỉ phần toán. Bin, tên phân bố, cửa sổ tuần và SQL đếm thuộc cụm 3 (chờ chốt Q-M9-B3-1…3); luật 8 nhận `DriftScore` đã
tính và chỉ so ngưỡng (Q-M9-B3-8) — test "bằng đúng 0,2" làm được trên số PSI, không dựng nổi phân bố cho PSI đúng 0,2.

- `psi(expected, actual)`: hai dãy TỈ LỆ (tổng 1) → PSI.
- `score(expected_counts, actual_counts)`: hai dãy SỐ ĐẾM → `DriftScore` (kèm số mẫu), hoặc `None` khi không đủ mẫu.
- `score_shares(expected, actual)`: phân bố chỉ có tỉ lệ, không có số đếm (vd escalation từ `escalation_rate_raw` của A1,
  cụm 3 dựng `[p, 1 − p]`) → `DriftScore` với số mẫu `None`. `p` là `None` (0 lá) thì cụm 3 gán `None` cho phân bố, không
  gọi hàm này.

Kiểm đầu vào TRƯỚC khi đưa vào numpy: numpy ép chuỗi lỗi thì in nguyên giá trị vào thông điệp. Thông điệp lỗi chỉ là
hằng, không mang dữ liệu (test AST `test_monitor_rules_event.py::test_error_messages_carry_no_data`). Không gọi `float(…)`
— kết quả numpy đổi về `float` Python bằng `.item()`.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np

# Q-M9-B3-5: tỉ lệ ĐÚNG BẰNG 0 (cả hai phía) thay bằng hằng này, không kẹp số nhỏ, KHÔNG chuẩn hoá lại. ln 0 không xác
# định; với 1e-4, một nhóm mới chiếm 10% cho PSI ≈ 0,69 (vẫn báo) mà không nổ vô cực. Không chuẩn hoá để số tay dễ kiểm.
PSI_EPS = 1e-4
# Q-M9-B3-6 phương án A: chỉ bỏ khi một phía 0 mẫu. Phương án B (N = 20 × số bin mỗi phía) → đổi hằng này thành 20.
MIN_SAMPLES_PER_BIN = 0
SHARE_SUM_TOL = 1e-9  # tổng tỉ lệ được lệch 1 tối đa chừng này (sai số làm tròn của c/n, của p và 1 − p)
MIN_BINS = 2  # 1 bin thì PSI luôn 0 → luật không bao giờ báo (bỏ sót im lặng) → coi là lỗi cấu hình


def _is_real(value: object) -> bool:
    """`int`, `float`, số thực numpy; không `bool` (`True` là `int`), không `str`, `None`, `Decimal`."""
    return isinstance(value, Real) and not isinstance(value, bool)


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    """PSI của hai phân bố cho dưới dạng TỈ LỆ (mỗi phía tổng 1, cùng số bin, ≥ `MIN_BINS` bin):

        e'_i = PSI_EPS nếu e_i = 0, ngược lại e_i        (a'_i tương tự)
        PSI  = Σ_i (a'_i − e'_i) · ln(a'_i / e'_i)       (ln tự nhiên; không chuẩn hoá lại sau khi thay)

    Mọi số hạng ≥ 0 (hai thừa số cùng dấu) và `psi(e, a) == psi(a, e)`. Sai kiểu → `TypeError`; khác số bin, ít bin,
    không hữu hạn, âm, tổng lệch 1 quá `SHARE_SUM_TOL` → `ValueError`."""
    if not all(_is_real(v) for v in (*expected, *actual)):
        raise TypeError("psi: phần tử không phải số thực")
    if len(expected) != len(actual):
        raise ValueError("psi: hai phân bố khác số bin")
    if len(expected) < MIN_BINS:
        raise ValueError("psi: cần ít nhất MIN_BINS bin")
    if not all(math.isfinite(v) for v in (*expected, *actual)):
        raise ValueError("psi: giá trị không hữu hạn")
    if any(v < 0 for v in (*expected, *actual)):
        raise ValueError("psi: tỉ lệ âm")
    if abs(math.fsum(expected) - 1) > SHARE_SUM_TOL or abs(math.fsum(actual) - 1) > SHARE_SUM_TOL:
        raise ValueError("psi: tổng tỉ lệ khác 1")
    e = np.asarray(expected, dtype=np.float64)
    a = np.asarray(actual, dtype=np.float64)
    e = np.where(e == 0, PSI_EPS, e)
    a = np.where(a == 0, PSI_EPS, a)
    return np.sum((a - e) * np.log(a / e)).item()


@dataclass(frozen=True)
class DriftScore:
    """PSI của một phân bố + số mẫu hai phía; `None` = không biết số mẫu (phân bố chỉ có tỉ lệ, `score_shares`).

    `psi` phải hữu hạn và ≥ 0: luật so `psi > ngưỡng`, mà `NaN > 0,2` là False → không báo im lặng (bỏ sót)."""

    psi: float
    n_expected: int | None
    n_actual: int | None

    def __post_init__(self) -> None:
        if not _is_real(self.psi) or not math.isfinite(self.psi) or self.psi < 0:
            raise ValueError("DriftScore: psi phải hữu hạn và không âm")
        for n in (self.n_expected, self.n_actual):
            if n is not None and (isinstance(n, bool) or not isinstance(n, Integral) or n < 0):
                raise ValueError("DriftScore: số mẫu phải là số nguyên không âm")


def score(expected_counts: Sequence[int], actual_counts: Sequence[int]) -> DriftScore | None:
    """Hai dãy SỐ ĐẾM theo bin → `DriftScore(psi(c / n_e, c / n_a), n_e, n_a)`.

    Một phía có ít hơn `max(1, MIN_SAMPLES_PER_BIN × số bin)` mẫu → `None` (không đo được, không phải lỗi). Không trả
    0.0: 0 nghĩa là "đã đo, không lệch" — sai sự thật. Phần tử không phải số nguyên (gồm `bool`, `float`) → `TypeError`;
    âm, khác số bin, ít bin → `ValueError`."""
    if not all(isinstance(c, Integral) and not isinstance(c, bool) for c in (*expected_counts, *actual_counts)):
        raise TypeError("score: số đếm không phải số nguyên")
    if len(expected_counts) != len(actual_counts):
        raise ValueError("score: hai phân bố khác số bin")
    if len(expected_counts) < MIN_BINS:
        raise ValueError("score: cần ít nhất MIN_BINS bin")
    if any(c < 0 for c in (*expected_counts, *actual_counts)):
        raise ValueError("score: số đếm âm")
    n_expected, n_actual = sum(expected_counts), sum(actual_counts)
    if min(n_expected, n_actual) < max(1, MIN_SAMPLES_PER_BIN * len(expected_counts)):
        return None
    value = psi([c / n_expected for c in expected_counts], [c / n_actual for c in actual_counts])
    return DriftScore(value, n_expected, n_actual)


def score_shares(expected: Sequence[float], actual: Sequence[float]) -> DriftScore:
    """Hai dãy TỈ LỆ (không có số đếm) → `DriftScore(psi(expected, actual), None, None)`. Không áp `MIN_SAMPLES_PER_BIN`
    vì không biết số mẫu."""
    return DriftScore(psi(expected, actual), None, None)
