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
- Clopper–Pearson KHÔNG ở đây: `metrics.safety` import từ `decision_math` (D-37).
- Dự phòng thiếu thời gian (P8:427): giữ Clopper–Pearson cho FNR, bỏ so sánh hiệu — `paired_family_bootstrap_diff` là phần có
  thể bỏ.

Đồng thuận giữa 2 người gán nhãn (G9, P8:130 "Cohen's κ trên nhãn tình huống ≥ 0,6"; khớp script của phiên D). Nhãn theo thứ tự
`AUTO < HITL < ESCALATE_L2` (`KAPPA_LABELS`), k = 3, n cặp, n_ij = số ca A gán i và B gán j:
- po = Σ_i n_ii / n; p_A(c), p_B(c) = tỉ lệ biên của từng người; pe = Σ_c p_A(c)·p_B(c).
- κ Cohen không trọng số = (po − pe)/(1 − pe); pe = 1 → None, lý do `pe_bang_1` (không chia cho 0).
- κ trọng số tuyến tính (tham khảo): w_ij = 1 − |i−j|/(k−1); po_w = Σ w_ij·n_ij / n; pe_w = Σ w_ij·p_A(i)·p_B(j);
  κ_w = (po_w − pe_w)/(1 − pe_w); 1 − pe_w = 0 → None, lý do `mau_so_trong_so_bang_0`.
- PABAK = (k·po − 1)/(k − 1).
- Kết luận: κ None → `khong_xac_dinh`; κ ≥ 0,6 → `DAT`; còn lại `KHONG_DAT`.
Tính bằng `Fraction` trên số đếm nguyên → so ngưỡng chính xác (κ = 3/5 đúng biên không thành 0,5999…). n = 0, độ dài khác nhau, nhãn
ngoài tập → `ValueError`.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from numbers import Integral, Real
from typing import Literal

import numpy as np

from app.eval.predictions import PredictionRecord

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


# ---- Đồng thuận người gán nhãn (G9) ----------------------------------------------------------------------------------

KAPPA_LABELS: tuple[str, ...] = ("AUTO", "HITL", "ESCALATE_L2")  # thứ tự dùng cho κ_w
KAPPA_PASS = Fraction(3, 5)  # P8:130

type Verdict = Literal["DAT", "KHONG_DAT", "khong_xac_dinh"]
type Weights = list[list[Fraction]]


@dataclass(frozen=True)
class Kappa:
    """`exact` = κ dạng phân số, `value` = float của nó; cả hai None khi mẫu số 0 (`reason`). `po`, `pe` theo trọng số của hàm."""

    value: float | None
    exact: Fraction | None
    po: Fraction
    pe: Fraction
    reason: str | None


@dataclass(frozen=True)
class Agreement:
    n: int
    po: Fraction
    pe: Fraction
    kappa: Kappa
    kappa_w: Kappa
    pabak: Fraction
    verdict: Verdict


def _table(a: Sequence[str], b: Sequence[str], labels: Sequence[str]) -> tuple[int, list[list[int]]]:
    """(n, bảng n_ij) — hàng = A, cột = B, theo thứ tự `labels`."""
    if len(labels) < 2 or len(set(labels)) != len(labels):
        raise ValueError("labels: cần ≥ 2 nhãn khác nhau")
    if len(a) != len(b):
        raise ValueError("a, b: độ dài khác nhau")
    if not a:
        raise ValueError("a, b: rỗng (n = 0)")
    idx = {c: i for i, c in enumerate(labels)}
    if any(x not in idx for x in (*a, *b)):
        raise ValueError("a, b: có nhãn ngoài tập")  # không in giá trị
    t = [[0] * len(labels) for _ in labels]
    for x, y in zip(a, b, strict=True):
        t[idx[x]][idx[y]] += 1
    return len(a), t


def _kappa(n: int, t: list[list[int]], w: Weights, reason: str) -> Kappa:
    k = len(t)
    row = [sum(t[i]) for i in range(k)]
    col = [sum(t[i][j] for i in range(k)) for j in range(k)]
    po = sum((w[i][j] * t[i][j] for i in range(k) for j in range(k)), Fraction(0)) / n
    pe = sum((w[i][j] * Fraction(row[i] * col[j], n * n) for i in range(k) for j in range(k)), Fraction(0))
    if pe == 1:
        return Kappa(None, None, po, pe, reason)
    exact = (po - pe) / (1 - pe)
    return Kappa(float(exact), exact, po, pe, None)


def cohen_kappa(a: Sequence[str], b: Sequence[str], labels: Sequence[str] = KAPPA_LABELS) -> Kappa:
    """κ Cohen không trọng số; pe = 1 → None, lý do `pe_bang_1`."""
    n, t = _table(a, b, labels)
    k = len(labels)
    w = [[Fraction(int(i == j)) for j in range(k)] for i in range(k)]
    return _kappa(n, t, w, "pe_bang_1")


def weighted_kappa_linear(a: Sequence[str], b: Sequence[str], labels: Sequence[str] = KAPPA_LABELS) -> Kappa:
    """κ trọng số tuyến tính theo thứ tự `labels`: w_ij = 1 − |i−j|/(k−1). `po`, `pe` của kết quả là po_w, pe_w."""
    n, t = _table(a, b, labels)
    k = len(labels)
    w = [[1 - Fraction(abs(i - j), k - 1) for j in range(k)] for i in range(k)]
    return _kappa(n, t, w, "mau_so_trong_so_bang_0")


def pabak(a: Sequence[str], b: Sequence[str], labels: Sequence[str] = KAPPA_LABELS) -> Fraction:
    """PABAK = (k·po − 1)/(k − 1), k = số nhãn."""
    n, t = _table(a, b, labels)
    k = len(labels)
    po = Fraction(sum(t[i][i] for i in range(k)), n)
    return (k * po - 1) / (k - 1)


def kappa_verdict(kappa: Kappa) -> Verdict:
    if kappa.exact is None:
        return "khong_xac_dinh"
    return "DAT" if kappa.exact >= KAPPA_PASS else "KHONG_DAT"


def agreement(a: Sequence[str], b: Sequence[str], labels: Sequence[str] = KAPPA_LABELS) -> Agreement:
    """Mọi chỉ số đồng thuận của 2 dãy nhãn đã ghép cặp (cùng thứ tự ca)."""
    kappa = cohen_kappa(a, b, labels)
    return Agreement(len(a), kappa.po, kappa.pe, kappa, weighted_kappa_linear(a, b, labels), pabak(a, b, labels),
                     kappa_verdict(kappa))  # fmt: skip
