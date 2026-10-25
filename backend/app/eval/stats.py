"""Bootstrap theo họ kịch bản (P8 §6.4) — khoảng tin cậy cho chỉ số và cho hiệu giữa hai phương án. S4 T29.

- Lấy mẫu lại HỌ (`PredictionRecord.family`), không lấy mẫu lại biến thể/lá: biến thể trong một họ gần như trùng nhau, lấy mẫu theo
  lá làm khoảng hẹp giả tạo (P8:379 — bản thân bootstrap theo họ là [Đề xuất] của P8). Mỗi họ được rút mang theo MỌI lá của nó.
- `BOOTSTRAP_N = 2000` (P8:379 "2.000 lần", P8:399 `BOOTSTRAP_N`), `SEED = 20260925` (P8:399 `SEED`) — hằng ở đây, truyền qua
  tham số được; không đưa vào `settings.py`.
- RNG: `numpy.random.default_rng(seed)` (PCG64; numpy đã là dependency của backend). Tên họ sắp tăng dần, lá trong họ sắp theo
  `ticket_id` trước khi rút → kết quả không phụ thuộc thứ tự đầu vào.
- Khoảng = phân vị (1−level)/2 và (1+level)/2 của các giá trị bootstrap (level 0,95 → 2,5 / 97,5 [Đề xuất — P8 chỉ ghi "95%"]),
  nội suy tuyến tính `numpy.percentile(method="linear")`: vị trí q·(N−1) trên dãy đã sắp.
- Lần rút mà thống kê trả `None` (mẫu số 0) → bỏ, đếm `n_undefined`; không coi là 0.
- Cận trên Clopper–Pearson một phía ở `decision_math` (D-37, `metrics.safety` import thẳng). Ở đây chỉ cận dưới và khoảng hai
  phía (P8 §2 `stats.py`, §6.1 "báo thêm hai phía"); cận trên của khoảng gọi lại `decision_math`, không viết lại.
- Dự phòng thiếu thời gian (P8:427): giữ Clopper–Pearson cho FNR, bỏ so sánh hiệu — `paired_family_bootstrap_diff` là phần có
  thể bỏ.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np
from scipy.stats import beta

from app.eval.predictions import PredictionRecord
from app.risk.decision_math import clopper_pearson_upper

type Records = Sequence[PredictionRecord]
type Statistic = Callable[[Sequence[PredictionRecord]], float | None]

BOOTSTRAP_N = 2000  # P8:379, P8:399
SEED = 20260925  # P8:399
LEVEL = 0.95


@dataclass(frozen=True)
class BootstrapCI:
    """`point` = thống kê trên dữ liệu gốc; `lo`, `hi` = khoảng phân vị trên `n_used` lần rút (None nếu n_used = 0)."""

    point: float | None
    lo: float | None
    hi: float | None
    n_boot: int
    n_used: int
    n_undefined: int
    n_families: int
    seed: int
    level: float


@dataclass(frozen=True)
class PairedDiffCI:
    """Hiệu stat(A) − stat(B), bootstrap ghép cặp theo họ (P8:380). `contains_zero` → "chưa đủ bằng chứng khác biệt",
    không ghi "tốt hơn"; None nếu không lần rút nào dùng được."""

    point: float | None
    lo: float | None
    hi: float | None
    contains_zero: bool | None
    n_boot: int
    n_used: int
    n_undefined: int
    n_families: int
    seed: int
    level: float


def _check_args(n_boot: object, seed: object, level: object) -> None:
    if isinstance(n_boot, bool) or not isinstance(n_boot, Integral) or n_boot < 1:
        raise ValueError("n_boot: phải là số nguyên ≥ 1")
    if isinstance(seed, bool) or not isinstance(seed, Integral):
        raise ValueError("seed: phải là số nguyên")  # noqa: TRY004 — P3: mọi lỗi đầu vào là ValueError (như decision_math)
    if isinstance(level, bool) or not isinstance(level, Real) or not (math.isfinite(float(level)) and 0.0 < float(level) < 1.0):
        raise ValueError("level: phải nằm trong khoảng mở (0, 1)")


def percentile_interval(values: Sequence[float], level: float = LEVEL) -> tuple[float, float]:
    """Phân vị (1−level)/2 và (1+level)/2, nội suy tuyến tính (numpy "linear"). Rỗng → ValueError."""
    if len(values) == 0:
        raise ValueError("values: rỗng")
    alpha = (1.0 - level) / 2.0
    lo, hi = np.percentile(np.asarray(values, dtype=float), [100.0 * alpha, 100.0 * (1.0 - alpha)], method="linear")
    return float(lo), float(hi)


def _family_units(records: Records) -> tuple[list[str], list[list[PredictionRecord]]]:
    """(tên họ đã sắp, lá của từng họ — sắp theo ticket_id). Rỗng → ValueError."""
    if len(records) == 0:
        raise ValueError("records: rỗng")
    groups: dict[str, list[PredictionRecord]] = {}
    for r in records:
        groups.setdefault(r.family, []).append(r)
    names = sorted(groups)
    return names, [sorted(groups[f], key=lambda r: r.ticket_id) for f in names]


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _take(units: list[list[PredictionRecord]], idx: np.ndarray) -> list[PredictionRecord]:
    return [r for i in idx for r in units[i]]


def _interval(values: list[float], level: float) -> tuple[float | None, float | None]:
    return percentile_interval(values, level) if values else (None, None)


def family_bootstrap_ci(
    records: Records, statistic: Statistic, *, n_boot: int = BOOTSTRAP_N, seed: int = SEED, level: float = LEVEL
) -> BootstrapCI:
    """Khoảng tin cậy `level` cho `statistic` (vd `lambda rs: safety(rs).fnr.value`) bằng bootstrap theo họ (P8:379): mỗi lần
    rút |họ| họ có lặp, ghép mọi lá của họ được rút, tính thống kê. Gọi `statistic` trên dữ liệu gốc TRƯỚC, rồi n_boot lần rút."""
    _check_args(n_boot, seed, level)
    names, units = _family_units(records)
    k = len(units)
    point = statistic(_take(units, np.arange(k)))
    rng = _rng(seed)
    values: list[float] = []
    undefined = 0
    for _ in range(n_boot):
        v = statistic(_take(units, rng.integers(0, k, size=k)))  # đơn vị lấy mẫu = họ
        if v is None:
            undefined += 1
        else:
            values.append(v)
    lo, hi = _interval(values, level)
    return BootstrapCI(point, lo, hi, n_boot, len(values), undefined, len(names), seed, level)


def paired_family_bootstrap_diff(
    records_a: Records,
    records_b: Records,
    statistic: Statistic,
    *,
    n_boot: int = BOOTSTRAP_N,
    seed: int = SEED,
    level: float = LEVEL,
) -> PairedDiffCI:
    """Hiệu stat(A) − stat(B) với bootstrap GHÉP CẶP theo họ (P8:380): mỗi lần rút dùng CÙNG một dãy họ cho A và B. Hai lần
    chạy phải cùng tập họ, cùng tập `scenario_id` (vd một lần rơi ticket → khác) và cùng `split` (review #42) → khác →
    ValueError. Lần mà một bên None → bỏ, đếm. Có thể bỏ (P8:427)."""
    _check_args(n_boot, seed, level)
    names_a, units_a = _family_units(records_a)
    names_b, units_b = _family_units(records_b)
    if names_a != names_b:
        raise ValueError("records_a, records_b: tập họ khác nhau — hai lần chạy phải trên cùng tập họ")
    if {r.scenario_id for r in records_a} != {r.scenario_id for r in records_b}:
        raise ValueError("records_a, records_b: tập scenario_id khác nhau — hai lần chạy phải trên cùng tập kịch bản")
    if {r.split for r in records_a} != {r.split for r in records_b}:
        raise ValueError("records_a, records_b: split khác nhau — không so hai lần chạy trên hai tập dữ liệu khác")
    k = len(names_a)
    pa, pb = statistic(_take(units_a, np.arange(k))), statistic(_take(units_b, np.arange(k)))
    point = pa - pb if pa is not None and pb is not None else None
    rng = _rng(seed)
    diffs: list[float] = []
    undefined = 0
    for _ in range(n_boot):
        idx = rng.integers(0, k, size=k)
        a = statistic(_take(units_a, idx))
        b = statistic(_take(units_b, idx))
        if a is None or b is None:
            undefined += 1
        else:
            diffs.append(a - b)
    lo, hi = _interval(diffs, level)
    contains_zero = lo <= 0.0 <= hi if lo is not None and hi is not None else None
    return PairedDiffCI(point, lo, hi, contains_zero, n_boot, len(diffs), undefined, k, seed, level)


# ---- Clopper–Pearson hai phía (G5) -------------------------------------------------------------------------------------


def clopper_pearson_lower(k: int, n: int, conf: float = LEVEL) -> float:
    """Cận dưới Clopper–Pearson MỘT PHÍA, đối xứng `decision_math.clopper_pearson_upper`: `beta.ppf(1 − conf, k, n−k+1)`;
    k = 0 → 0,0. n ≥ 1, 0 ≤ k ≤ n, conf ∈ (0, 1); sai → ValueError."""
    for value, name in ((k, "k"), (n, "n")):
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise ValueError(f"{name}: phải là số nguyên")  # noqa: TRY004 — P3: mọi lỗi đầu vào là ValueError
    if isinstance(conf, bool) or not isinstance(conf, Real) or not (math.isfinite(float(conf)) and 0.0 < float(conf) < 1.0):
        raise ValueError("conf: phải nằm trong khoảng mở (0, 1)")
    if n < 1:
        raise ValueError("n: phải ≥ 1")
    if not 0 <= k <= n:
        raise ValueError("k: phải thoả 0 ≤ k ≤ n")
    if k == 0:
        return 0.0
    return float(beta.ppf(1.0 - float(conf), int(k), int(n) - int(k) + 1))


def clopper_pearson_two_sided(k: int, n: int, level: float = LEVEL) -> tuple[float, float]:
    """Khoảng Clopper–Pearson HAI PHÍA `level` (P8 §6.1 "báo thêm hai phía"): mỗi phía (1 + level)/2 — cận dưới ở đây, cận trên
    `decision_math.clopper_pearson_upper`. level 0,95 → (beta.ppf(0,025, k, n−k+1), beta.ppf(0,975, k+1, n−k))."""
    if isinstance(level, bool) or not isinstance(level, Real) or not (math.isfinite(float(level)) and 0.0 < float(level) < 1.0):
        raise ValueError("level: phải nằm trong khoảng mở (0, 1)")
    c = (1.0 + level) / 2.0
    return clopper_pearson_lower(k, n, c), clopper_pearson_upper(k, n, c)
