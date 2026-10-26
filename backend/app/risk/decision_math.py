"""Toán quyết định của M5 (phase6 mục 4.2) — hàm thuần, NGUỒN DUY NHẤT cho M5 lúc vận hành và cho T27, T29 (D-37: `app.eval`
import lại từ đây, không viết lại CP, ECE, Brier, AUC, ngưỡng từ chi phí).

- Route = đúng `RiskDecision.route` (P2). Ngưỡng: p < t_low → AUTO; p > t_high → ESCALATE_L2; còn lại HITL (bằng ngưỡng = HITL).
- Chi phí `costs[gold][pred]`, đơn vị = một lượt duyệt; `DEFAULT_COST` = bảng 7.3 [Chốt Q9, 10:1] — hằng trong code (P4),
  đóng băng sâu (Q-6A-2 = A): dùng chung nhiều người, sửa nhầm một ô là sai số âm thầm.
- Mọi hàm kiểm đầu vào (P3) → `ValueError`; thông điệp nêu TÊN tham số + loại vi phạm, KHÔNG in giá trị dữ liệu.
- Nhãn `labels`: 1/True = "cần người" (gold ≠ AUTO). Chỉ nhận bool/int (Q-6A-1 = A — float, kể cả 0.0/1.0, là lỗi: chặn nhầm
  p ↔ nhãn).
"""

import math
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from types import MappingProxyType
from typing import Literal

import numpy as np
from pydantic import BaseModel, field_serializer, field_validator
from scipy.stats import beta, rankdata

type Route = Literal["AUTO", "HITL", "ESCALATE_L2"]
ROUTES: tuple[Route, ...] = ("AUTO", "HITL", "ESCALATE_L2")

type _Floats = Sequence[float] | np.ndarray
type _Golds = Sequence[Route] | Sequence[str] | np.ndarray
type _Labels = Sequence[bool] | Sequence[int] | np.ndarray

T_HIGH_MAX = 1.01  # t_high = 1,01 = lớp LLM không bao giờ đưa ca sang L2 (p ≤ 1 < 1,01; P8 §5.3, B12-B14 §5.2 mục 5)
_GRID = np.arange(101) / 100  # P7: {i/100 : i = 0…100} — phép chia IEEE, bằng đúng `i / 100` của Python


class CostMatrix(BaseModel, frozen=True, extra="forbid", hide_input_in_errors=True):
    """`costs[gold][pred]` — đủ 3×3, hữu hạn, ≥ 0; thiếu/thừa ô → ValueError."""

    costs: Mapping[Route, Mapping[Route, float]]

    @field_validator("costs", mode="after")
    @classmethod
    def _full_finite_frozen(cls, costs: Mapping[Route, Mapping[Route, float]]) -> Mapping[Route, Mapping[Route, float]]:
        if set(costs) != set(ROUTES) or any(set(row) != set(ROUTES) for row in costs.values()):
            raise ValueError("costs: phải đủ 3×3 ô theo ROUTES")
        if any(not math.isfinite(v) or v < 0 for row in costs.values() for v in row.values()):
            raise ValueError("costs: mỗi ô phải hữu hạn và không âm")
        return MappingProxyType({g: MappingProxyType({p: float(costs[g][p]) for p in ROUTES}) for g in ROUTES})

    @field_serializer("costs")
    def _plain_dict(self, costs: Mapping[Route, Mapping[Route, float]]) -> dict[Route, dict[Route, float]]:
        return {g: dict(row) for g, row in costs.items()}  # mappingproxy → dict: pydantic không tự serialize mappingproxy

    def matrix(self) -> np.ndarray:
        """Mảng 3×3 theo thứ tự ROUTES (hàng = gold, cột = pred)."""
        return np.array([[self.costs[g][p] for p in ROUTES] for g in ROUTES], dtype=float)


DEFAULT_COST = CostMatrix(
    costs={
        "AUTO": {"AUTO": 0, "HITL": 1, "ESCALATE_L2": 3},
        "HITL": {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
        "ESCALATE_L2": {"AUTO": 20, "HITL": 6, "ESCALATE_L2": 3},
    }
)


# ---- kiểm đầu vào (P3) -----------------------------------------------------------------------------------------------


def _finite_real(x: object, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(float(x)):
        raise ValueError(f"{name}: phải là số thực hữu hạn")
    return float(x)


def _vector(values: object, name: str) -> np.ndarray:
    arr = np.asarray(values)
    if arr.ndim != 1:
        raise ValueError(f"{name}: phải là dãy một chiều")
    if arr.size == 0:
        raise ValueError(f"{name}: rỗng")
    return arr


def _floats(values: object, name: str, *, unit: bool) -> np.ndarray:
    arr = _vector(values, name)
    if arr.dtype.kind not in "iuf":  # bool ('b'), chuỗi, object → lỗi
        raise ValueError(f"{name}: phải là dãy số thực")
    out = arr.astype(float)
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{name}: có phần tử không hữu hạn")
    if unit and not np.all((out >= 0.0) & (out <= 1.0)):
        raise ValueError(f"{name}: có phần tử ngoài đoạn [0, 1]")
    return out


def _labels(values: object, n: int, name: str = "labels") -> np.ndarray:
    arr = _vector(values, name)
    if arr.dtype.kind not in "biu":  # Q-6A-1 = A: float (kể cả 0.0/1.0) → lỗi
        raise ValueError(f"{name}: phải là bool hoặc số nguyên")
    if arr.size != n:
        raise ValueError(f"{name}: độ dài khác dãy xác suất/điểm")
    if not np.all((arr == 0) | (arr == 1)):
        raise ValueError(f"{name}: chỉ nhận nhãn không/một hoặc False/True")
    return arr.astype(bool)


def _golds(values: object, n: int) -> np.ndarray:
    """Chỉ số gold theo ROUTES (0 = AUTO, 1 = HITL, 2 = ESCALATE_L2)."""
    arr = _vector(values, "golds")
    if arr.size != n:
        raise ValueError("golds: độ dài khác probs")
    index = {r: i for i, r in enumerate(ROUTES)}
    if arr.dtype.kind not in "UO" or not all(isinstance(g, str) and g in index for g in arr.tolist()):
        raise ValueError("golds: có phần tử không phải route hợp lệ")
    return np.array([index[g] for g in arr.tolist()], dtype=np.intp)


def _thresholds(t_low: object, t_high: object) -> tuple[float, float]:
    lo, hi = _finite_real(t_low, "t_low"), _finite_real(t_high, "t_high")
    if not 0.0 <= lo <= hi <= T_HIGH_MAX:
        raise ValueError("t_low, t_high: phải thoả 0 ≤ t_low ≤ t_high ≤ 1,01")
    return lo, hi


def _require_cost(cost: object) -> CostMatrix:
    if not isinstance(cost, CostMatrix):
        raise ValueError("cost: phải là CostMatrix")  # noqa: TRY004 — P3: mọi lỗi đầu vào là ValueError
    return cost


# ---- ngưỡng ----------------------------------------------------------------------------------------------------------


def cost_matrix_for_ratio(ratio: float) -> CostMatrix:
    """Độ nhạy tỉ lệ bỏ sót/duyệt ∈ {5, 10, 20} [Chốt]: HITL→AUTO = ratio; L2→AUTO = 2·ratio (giữ tỉ lệ 2:1 của bảng gốc);
    các ô khác như DEFAULT_COST. ratio = 10 → bằng DEFAULT_COST."""
    r = _finite_real(ratio, "ratio")
    if r <= 0:
        raise ValueError("ratio: phải dương")
    rows = {g: dict(DEFAULT_COST.costs[g]) for g in ROUTES}
    rows["HITL"]["AUTO"] = r
    rows["ESCALATE_L2"]["AUTO"] = 2 * r
    return CostMatrix(costs=rows)


def t_low_star(cost: CostMatrix = DEFAULT_COST) -> float:
    """t_low* = c_review / c_miss, c_review = cost[AUTO][HITL], c_miss = cost[HITL][AUTO] [Chốt B12 §5.2]. Trả đúng tỉ số
    (không kẹp vào [0, 1]); c_miss = 0 → ValueError."""
    c = _require_cost(cost).costs
    c_review, c_miss = c["AUTO"]["HITL"], c["HITL"]["AUTO"]
    if c_miss <= 0:
        raise ValueError("cost: ô HITL→AUTO (c_miss) phải dương")
    return c_review / c_miss


def route_for(p: float, t_low: float, t_high: float) -> Route:
    """p < t_low → AUTO; p > t_high → ESCALATE_L2; còn lại HITL (bằng ngưỡng = HITL).
    Ràng buộc 0 ≤ t_low ≤ t_high ≤ 1,01 (1,01 = lớp LLM không bao giờ đưa ca sang L2: p ≤ 1 < 1,01; P8 §5.3)."""
    x = _finite_real(p, "p")
    if not 0.0 <= x <= 1.0:
        raise ValueError("p: phải nằm trong đoạn [0, 1]")
    lo, hi = _thresholds(t_low, t_high)
    if x < lo:
        return "AUTO"
    if x > hi:
        return "ESCALATE_L2"
    return "HITL"


def expected_cost(probs: _Floats, golds: _Golds, t_low: float, t_high: float, cost: CostMatrix = DEFAULT_COST) -> float:
    """Trung bình `cost[gold][route_for(p, t_low, t_high)]` — định nghĩa chuẩn; `select_thresholds` báo chi phí qua hàm này."""
    p = _floats(probs, "probs", unit=True)
    g = _golds(golds, p.size)
    _thresholds(t_low, t_high)
    c = _require_cost(cost).costs
    total = sum(c[ROUTES[gi]][route_for(float(pi), t_low, t_high)] for pi, gi in zip(p, g, strict=True))
    return total / p.size


class ThresholdChoice(BaseModel, frozen=True, extra="forbid", hide_input_in_errors=True):
    t_low: float
    t_high: float
    expected_cost: float


def select_thresholds(probs: _Floats, golds: _Golds, cost: CostMatrix = DEFAULT_COST) -> ThresholdChoice:
    """P7 — quét lưới t_low, t_high ∈ {i/100}, t_high ≥ t_low; chọn khoá `(round(chi phí, 12), t_low, t_high)` nhỏ nhất (hoà →
    t_low nhỏ nhất: ít tự làm hơn, ưu tiên giảm FN; rồi t_high nhỏ nhất).

    Tìm bằng numpy (không lặp 5 151 × n): sắp p một lần; số ca AUTO (p < t_low) theo từng lớp gold = `searchsorted(left)`, số ca
    L2 (p > t_high) = n_g − `searchsorted(right)`; chi phí mọi cặp từ số đếm nguyên. Chi phí trả về của cặp thắng tính lại bằng
    `expected_cost` — một nguồn ngữ nghĩa biên (B1).

    Chỉ truyền dữ liệu thuộc split calibration (P8 bất biến 10); người gọi (T27 calibrate.py) tự gọi require_calibration_split
    trên LabeledSample trước khi tách mảng."""
    p = _floats(probs, "probs", unit=True)
    g = _golds(golds, p.size)
    m = _require_cost(cost).matrix()
    n = p.size
    total = np.zeros((_GRID.size, _GRID.size))
    for gi in range(len(ROUTES)):
        pg = np.sort(p[g == gi])
        n_auto = np.searchsorted(pg, _GRID, side="left").astype(float)  # theo t_low
        n_l2 = pg.size - np.searchsorted(pg, _GRID, side="right").astype(float)  # theo t_high
        # HITL = n_g − AUTO − L2 (t_high ≥ t_low → hai tập rời nhau)
        total += (n_auto * (m[gi, 0] - m[gi, 1]))[:, None] + (n_l2 * (m[gi, 2] - m[gi, 1]))[None, :] + pg.size * m[gi, 1]
    lo_idx, hi_idx = np.triu_indices(_GRID.size)  # mọi cặp t_high ≥ t_low
    key_cost = np.round(total[lo_idx, hi_idx] / n, 12)
    best = np.lexsort((_GRID[hi_idx], _GRID[lo_idx], key_cost))[0]
    t_low, t_high = float(_GRID[lo_idx[best]]), float(_GRID[hi_idx[best]])
    return ThresholdChoice(t_low=t_low, t_high=t_high, expected_cost=expected_cost(p, golds, t_low, t_high, cost))


def sensitivity(
    probs: _Floats, golds: _Golds, ratios: Sequence[float] = (5, 10, 20)
) -> dict[float, tuple[float, ThresholdChoice]]:
    """ratio → (t_low* của ratio, ngưỡng chọn với cost_matrix_for_ratio(ratio)).

    Chỉ truyền dữ liệu thuộc split calibration (P8 bất biến 10); người gọi (T27 calibrate.py) tự gọi require_calibration_split
    trên LabeledSample trước khi tách mảng."""
    if len(ratios) == 0:
        raise ValueError("ratios: rỗng")
    out: dict[float, tuple[float, ThresholdChoice]] = {}
    for ratio in ratios:
        cm = cost_matrix_for_ratio(ratio)
        out[float(ratio)] = (t_low_star(cm), select_thresholds(probs, golds, cm))
    return out


# ---- chỉ số ----------------------------------------------------------------------------------------------------------


def clopper_pearson_upper(k: int, n: int, conf: float = 0.95) -> float:
    """Cận trên Clopper–Pearson MỘT PHÍA (P6, P8 §6.1): `beta.ppf(conf, k+1, n−k)`; k = n → 1,0. n ≥ 1, 0 ≤ k ≤ n."""
    for value, name in ((k, "k"), (n, "n")):
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise ValueError(f"{name}: phải là số nguyên")  # noqa: TRY004 — P3: mọi lỗi đầu vào là ValueError
    c = _finite_real(conf, "conf")
    if not 0.0 < c < 1.0:
        raise ValueError("conf: phải nằm trong khoảng mở (0, 1)")
    if n < 1:
        raise ValueError("n: phải ≥ 1")
    if not 0 <= k <= n:
        raise ValueError("k: phải thoả 0 ≤ k ≤ n")
    if k == n:
        return 1.0
    return float(beta.ppf(c, int(k) + 1, int(n) - int(k)))


def ece(probs: _Floats, labels: _Labels, n_bins: int = 10) -> float:
    """Expected calibration error, `n_bins` bin đều (P5): Σ (n_b/N)·|mean p_b − mean y_b|, bin rỗng bỏ qua. Chỉ số bin
    `k = min(floor(round(p·n_bins, 9)), n_bins − 1)` — làm tròn 9 chữ số để `0.7 − 0.4 = 0.29999999999999993` vẫn vào bin 3;
    p = 1 vào bin cuối."""
    if isinstance(n_bins, bool) or not isinstance(n_bins, Integral) or n_bins < 1:
        raise ValueError("n_bins: phải là số nguyên ≥ 1")
    p = _floats(probs, "probs", unit=True)
    y = _labels(labels, p.size).astype(float)
    k = np.minimum(np.floor(np.round(p * n_bins, 9)), n_bins - 1).astype(int)
    count = np.bincount(k, minlength=n_bins)
    sum_p = np.bincount(k, weights=p, minlength=n_bins)
    sum_y = np.bincount(k, weights=y, minlength=n_bins)
    used = count > 0
    return float(np.sum(np.abs(sum_p[used] - sum_y[used])) / p.size)  # (n_b/N)·|Σp/n_b − Σy/n_b| = |Σp − Σy|/N


def brier(probs: _Floats, labels: _Labels) -> float:
    """mean((p − y)²)."""
    p = _floats(probs, "probs", unit=True)
    y = _labels(labels, p.size).astype(float)
    return float(np.mean((p - y) ** 2))


def auc(scores: _Floats, labels: _Labels) -> float:
    """AUC = thống kê Mann–Whitney (hạng trung bình → cặp hoà tính 0,5); thiếu một lớp → ValueError. `scores` chỉ cần hữu
    hạn (AUC theo hạng — không bắt ∈ [0, 1])."""
    s = _floats(scores, "scores", unit=False)
    y = _labels(labels, s.size)
    n_pos = int(y.sum())
    n_neg = y.size - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("labels: phải có cả hai lớp")
    ranks = rankdata(s)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))
