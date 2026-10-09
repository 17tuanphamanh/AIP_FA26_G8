"""M9-B3 cụm 2 — `monitor/drift.py`: PSI, `DriftScore`, `score`, `score_shares`. Không DB.

Nguồn: issue #15 (PSI tay khớp, sai số ≤ 1e-6; bin rỗng dùng epsilon cố định), mặc định đã gửi ở issue #15: Q-M9-B3-5
(epsilon 1e-4 hai phía, không chuẩn hoá lại), Q-M9-B3-6 phương án A (một phía 0 mẫu → None), Q-M9-B3-8.
Mọi kỳ vọng là hằng tính tay (phép tính ghi cạnh hằng), không gọi hàm đang test để ra kỳ vọng.
Logarit dùng: ln 1,2 = 0,1823215568; ln 0,8 = −0,2231435513; ln 1000 = 6,9077552790; ln 3 = 1,0986122887;
ln 1,5 = 0,4054651081; ln(4/7) = −0,5596157879.
"""

import math
from decimal import Decimal
from typing import Any

import pytest
from app.monitor import drift
from app.monitor.drift import (
    MIN_BINS,
    MIN_SAMPLES_PER_BIN,
    PSI_EPS,
    DriftScore,
    psi,
    score,
    score_shares,
)

TOL = 1e-6  # issue #15: sai số ≤ 1e-6

# e = [0,5; 0,5], a = [0,6; 0,4]: 0,1·ln 1,2 + (−0,1)·ln 0,8 = 0,1·0,1823215568 + 0,1·0,2231435513
PSI_TWO_BINS = 0.0405465108
# e = [0,5; 0,5; 0], a = [0,5; 0,4; 0,1], ε = 1e-4: 0 + (−0,1)·ln 0,8 + (0,1 − 1e-4)·ln(0,1 / 1e-4)
#   = 0,0223143551 + 0,0999·6,9077552790 = 0,0223143551 + 0,6900847524
PSI_EMPTY_BIN = 0.7123991075
# e = [0,1; 0,2; 0,7], a = [0,3; 0,3; 0,4]: 0,2·ln 3 + 0,1·ln 1,5 + (−0,3)·ln(4/7)
#   = 0,2197224577 + 0,0405465108 + 0,1678847364
PSI_THREE_BINS = 0.4281537049


def test_constants() -> None:
    assert PSI_EPS == 1e-4  # Q-M9-B3-5
    assert MIN_SAMPLES_PER_BIN == 0  # Q-M9-B3-6 phương án A
    assert MIN_BINS == 2


# ---- psi: ca tính tay -------------------------------------------------------------------------------------------------


def test_psi_two_bins_hand() -> None:
    assert abs(psi([0.5, 0.5], [0.6, 0.4]) - PSI_TWO_BINS) <= TOL


def test_psi_empty_expected_bin() -> None:
    """Bin rỗng phía mốc (nhóm mới xuất hiện): 0 thay bằng ε → số hữu hạn, đủ lớn để báo."""
    assert abs(psi([0.5, 0.5, 0.0], [0.5, 0.4, 0.1]) - PSI_EMPTY_BIN) <= TOL


def test_psi_empty_actual_bin() -> None:
    """Bin rỗng phía đo (nhóm biến mất): số hạng (1e-4 − 0,1)·ln(1e-4 / 0,1) = (−0,0999)·(−6,9077552790) — cùng giá trị."""
    assert abs(psi([0.5, 0.4, 0.1], [0.5, 0.5, 0.0]) - PSI_EMPTY_BIN) <= TOL


def test_psi_empty_same_bin_both_sides() -> None:
    """Cùng bin rỗng hai phía: (ε − ε)·ln 1 = 0 → bằng ca hai bin. Chuẩn hoá lại sau khi thay ε sẽ ra 0,0405424566."""
    assert abs(psi([0.5, 0.5, 0.0], [0.6, 0.4, 0.0]) - PSI_TWO_BINS) <= TOL


def test_psi_identical_is_zero() -> None:
    assert psi([0.2, 0.3, 0.5], [0.2, 0.3, 0.5]) == 0.0


def test_psi_symmetric() -> None:
    e, a = [0.1, 0.2, 0.7], [0.3, 0.3, 0.4]
    assert abs(psi(e, a) - PSI_THREE_BINS) <= TOL
    assert abs(psi(a, e) - PSI_THREE_BINS) <= TOL


def test_psi_returns_python_float() -> None:
    assert type(psi([0.5, 0.5], [0.6, 0.4])) is float


# ---- psi: đầu vào lỗi — thông điệp hằng, không mang giá trị ---------------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "actual", "exc", "message", "sentinel"),
    [
        ([0.5, 0.5], [0.2, 0.3, 0.5], ValueError, "psi: hai phân bố khác số bin", None),
        ([0.2, 0.3, 0.5], [0.5, 0.5], ValueError, "psi: hai phân bố khác số bin", None),
        ([], [], ValueError, "psi: cần ít nhất MIN_BINS bin", None),
        ([1.0], [1.0], ValueError, "psi: cần ít nhất MIN_BINS bin", None),
        # giá trị xấu phía mốc (expected)
        ([-0.123457, 1.123457], [0.5, 0.5], ValueError, "psi: tỉ lệ âm", "0.123457"),
        ([math.nan, 0.5], [0.5, 0.5], ValueError, "psi: giá trị không hữu hạn", "nan"),
        ([math.inf, 0.5], [0.5, 0.5], ValueError, "psi: giá trị không hữu hạn", "inf"),
        ([0.5, 0.4], [0.5, 0.5], ValueError, "psi: tổng tỉ lệ khác 1", "0.9"),
        ([0.0, 0.0], [0.5, 0.5], ValueError, "psi: tổng tỉ lệ khác 1", None),
        ([True, False], [0.5, 0.5], TypeError, "psi: phần tử không phải số thực", "True"),
        (["0.5", 0.5], [0.5, 0.5], TypeError, "psi: phần tử không phải số thực", "0.5"),
        ([None, 1.0], [0.5, 0.5], TypeError, "psi: phần tử không phải số thực", "None"),
        ([Decimal("0.25"), Decimal("0.75")], [0.5, 0.5], TypeError, "psi: phần tử không phải số thực", "0.25"),
        # giá trị xấu phía đo (actual), phía mốc hợp lệ — kiểm chỉ một phía thì các ca này đỏ
        ([0.5, 0.5], [-0.123457, 1.123457], ValueError, "psi: tỉ lệ âm", "0.123457"),
        ([0.5, 0.5], [math.nan, 0.5], ValueError, "psi: giá trị không hữu hạn", "nan"),
        ([0.5, 0.5], [-math.inf, 0.5], ValueError, "psi: giá trị không hữu hạn", "inf"),
        ([0.5, 0.5], [0.5, 0.4], ValueError, "psi: tổng tỉ lệ khác 1", "0.9"),
        ([0.5, 0.5], [0.0, 0.0], ValueError, "psi: tổng tỉ lệ khác 1", None),
        ([0.5, 0.5], [True, False], TypeError, "psi: phần tử không phải số thực", "True"),
        ([0.5, 0.5], ["0.5", 0.5], TypeError, "psi: phần tử không phải số thực", "0.5"),
    ],
    ids=[
        "lech_so_bin_moc_ngan", "lech_so_bin_do_ngan", "rong", "mot_bin",
        "am_moc", "nan_moc", "inf_moc", "tong_0_9_moc", "tong_0_moc", "bool_moc", "chuoi_moc", "none_moc", "decimal_moc",
        "am_do", "nan_do", "am_inf_do", "tong_0_9_do", "tong_0_do", "bool_do", "chuoi_do",
    ],
)  # fmt: skip
def test_psi_rejects(expected: Any, actual: Any, exc: type[Exception], message: str, sentinel: str | None) -> None:
    with pytest.raises(exc) as info:
        psi(expected, actual)
    assert str(info.value) == message
    if sentinel is not None:
        assert sentinel not in str(info.value)


# ---- score / score_shares ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "actual", "n"),
    [([50, 50], [60, 40], (100, 100)), ([1, 1], [3, 2], (2, 5))],
    ids=["100_100", "2_5"],
)
def test_score_counts_equal_shares(expected: Any, actual: Any, n: tuple[int, int]) -> None:
    """Số đếm chia tổng = ca tỉ lệ [0,5; 0,5] vs [0,6; 0,4] (50/100, 60/100; 1/2, 3/5)."""
    result = score(expected, actual)
    assert result is not None
    assert abs(result.psi - PSI_TWO_BINS) <= TOL
    assert (result.n_expected, result.n_actual) == n


def test_score_counts_empty_bin() -> None:
    result = score([50, 50, 0], [50, 40, 10])
    assert result is not None
    assert abs(result.psi - PSI_EMPTY_BIN) <= TOL
    assert (result.n_expected, result.n_actual) == (100, 100)


@pytest.mark.parametrize(
    ("expected", "actual"), [([0, 0], [3, 1]), ([3, 1], [0, 0]), ([0, 0], [0, 0])], ids=["mốc_0", "đo_0", "hai_0"]
)
def test_score_one_side_empty_is_none(expected: Any, actual: Any) -> None:
    """Q-M9-B3-6 phương án A: một phía 0 mẫu → None (không đo được), KHÔNG phải DriftScore(0.0, …)."""
    assert score(expected, actual) is None


def test_score_one_sample_side_is_measured() -> None:
    """Ranh giới mặc định (phương án A, ngưỡng max(1, 0 × 2) = 1): một phía đúng 1 mẫu → ĐO ĐƯỢC, không None.
    [1, 0] → e = [1; 0] → e' = [1; 1e-4]; [3, 1] → a = [0,75; 0,25]:
    (0,75 − 1)·ln(0,75 / 1) + (0,25 − 1e-4)·ln(0,25 / 1e-4) = (−0,25)·(−0,2876820725) + 0,2499·7,8240460109
    = 0,0719205181 + 1,9552290981 = 2,0271496162."""
    result = score([1, 0], [3, 1])
    assert result is not None
    assert abs(result.psi - 2.0271496162) <= TOL
    assert (result.n_expected, result.n_actual) == (1, 4)


def test_score_min_samples_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đổi một hằng là đủ chuyển sang phương án B: 2 bin × 20 = 40 mẫu tối thiểu mỗi phía."""
    monkeypatch.setattr(drift, "MIN_SAMPLES_PER_BIN", 20)
    assert score([20, 19], [20, 20]) is None  # 39 < 40
    assert score([20, 20], [20, 19]) is None
    assert score([20, 20], [20, 20]) == DriftScore(0.0, 40, 40)  # đúng 40 → đo được; hai phía giống nhau → PSI 0


def test_score_shares_unknown_n() -> None:
    result = score_shares([0.5, 0.5], [0.6, 0.4])
    assert abs(result.psi - PSI_TWO_BINS) <= TOL
    assert (result.n_expected, result.n_actual) == (None, None)


@pytest.mark.parametrize(
    ("expected", "actual", "exc", "message"),
    [
        ([1.0, 1], [1, 1], TypeError, "score: số đếm không phải số nguyên"),
        ([True, 1], [1, 1], TypeError, "score: số đếm không phải số nguyên"),
        ([-7, 10], [1, 1], ValueError, "score: số đếm âm"),
        ([1, 1], [1.0, 1], TypeError, "score: số đếm không phải số nguyên"),
        ([1, 1], [True, 1], TypeError, "score: số đếm không phải số nguyên"),
        ([1, 1], [-7, 10], ValueError, "score: số đếm âm"),
        ([1, 1], [1, 1, 1], ValueError, "score: hai phân bố khác số bin"),
        ([1, 1, 1], [1, 1], ValueError, "score: hai phân bố khác số bin"),
        ([5], [5], ValueError, "score: cần ít nhất MIN_BINS bin"),
    ],
    ids=[
        "float_moc", "bool_moc", "am_moc", "float_do", "bool_do", "am_do", "lech_so_bin_moc_ngan",
        "lech_so_bin_do_ngan", "mot_bin",
    ],
)  # fmt: skip
def test_score_rejects(expected: Any, actual: Any, exc: type[Exception], message: str) -> None:
    with pytest.raises(exc) as info:
        score(expected, actual)
    assert str(info.value) == message


_BAD_PSI = "DriftScore: psi phải hữu hạn và không âm"
_BAD_N = "DriftScore: số mẫu phải là số nguyên không âm"


@pytest.mark.parametrize(
    ("value", "n_expected", "n_actual", "message"),
    [
        (math.nan, 1, 1, _BAD_PSI),
        (-0.1, 1, 1, _BAD_PSI),
        (math.inf, 1, 1, _BAD_PSI),
        ("0.1", 1, 1, _BAD_PSI),
        (None, 1, 1, _BAD_PSI),
        (0.1, -1, 1, _BAD_N),
        (0.1, 1, -1, _BAD_N),
        (0.1, True, 1, _BAD_N),
        (0.1, 1, True, _BAD_N),
        (0.1, 1.5, 1, _BAD_N),
        (0.1, 1, 1.5, _BAD_N),
    ],
    ids=[
        "nan", "am", "inf", "psi_chuoi", "psi_none", "n_moc_am", "n_do_am", "n_moc_bool", "n_do_bool", "n_moc_thuc",
        "n_do_thuc",
    ],
)  # fmt: skip
def test_drift_score_rejects_bad(value: Any, n_expected: Any, n_actual: Any, message: str) -> None:
    with pytest.raises(ValueError) as info:
        DriftScore(value, n_expected, n_actual)
    assert str(info.value) == message
