"""Chỉ số RQ2 — dùng lại `app.risk.decision_math` (`ece` 10 ngăn đều, `brier`) và `app.eval.stats` (`family_bootstrap_ci`).

- ECE 10 ngăn đều = `decision_math.ece(p, y, 10)` (cùng hàm `metrics.calibration_scores` của RQ1).
- ECE 5 ngăn cùng số mẫu (viết mới — không có trên tag): sắp lá theo `(p, ticket_id)`, chia `numpy.array_split` thành 5 nhóm liên tiếp
  (cỡ chênh nhau ≤ 1; nhóm rỗng khi N < 5 bị bỏ), ECE = Σ_b |Σp_b − Σy_b| / N (= Σ (n_b/N)·|p̄_b − ȳ_b|). Các lá cùng một mức p có thể
  rơi vào 2 ngăn kề nhau — với (b) chỉ có 6 mức p nên đây là chủ ý: giữ 5 ngăn cùng cỡ thay vì gộp mức.
- Độ phân giải: số mức p khác nhau (so sau làm tròn 12 chữ số) + tỉ lệ lá dồn vào 2 mức đông nhất.
- Bootstrap: `family_bootstrap_ci` (lấy mẫu lại HỌ, P8 §6.4) với `n_boot = 1000` (đặc tả Phase 11; P8 dùng `BOOTSTRAP_N = 2000`),
  seed `stats.SEED` = 20260925, KTC 95% phân vị. Hàm chỉ đọc `.family`, `.ticket_id` của bản ghi (`stats._family_units`) — bản ghi RQ2
  đưa vào qua `cast` vì chữ ký khai `PredictionRecord`.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

import numpy as np

from app.eval.stats import LEVEL, SEED, BootstrapCI, family_bootstrap_ci
from app.risk.decision_math import brier, ece

N_BOOT: Final = 1000
ECE_BINS_UNIFORM: Final = 10
ECE_BINS_MASS: Final = 5
LEVEL_DIGITS: Final = 12


@dataclass(frozen=True)
class Point:
    """Một lá trong phép tính: p (thô hoặc đã hiệu chỉnh), nhãn, họ."""

    ticket_id: str
    family: str
    p: float
    y: bool


def ece_uniform(points: Sequence[Point], n_bins: int = ECE_BINS_UNIFORM) -> float:
    return ece([q.p for q in points], [q.y for q in points], n_bins)


def ece_equal_mass(points: Sequence[Point], n_bins: int = ECE_BINS_MASS) -> float:
    if not points:
        raise ValueError("points: rỗng")
    if n_bins < 1:
        raise ValueError("n_bins: phải ≥ 1")
    ordered = sorted(points, key=lambda q: (q.p, q.ticket_id))
    total = 0.0
    for group in np.array_split(np.arange(len(ordered)), n_bins):
        if group.size == 0:
            continue
        total += abs(sum(ordered[i].p for i in group) - sum(float(ordered[i].y) for i in group))
    return total / len(ordered)


def brier_score(points: Sequence[Point]) -> float:
    return brier([q.p for q in points], [q.y for q in points])


@dataclass(frozen=True)
class Resolution:
    n: int
    n_levels: int
    top2_share: float
    levels: dict[str, int]  # mức p (chuỗi, 12 chữ số) → số lá


def resolution(ps: Sequence[float]) -> Resolution:
    if not ps:
        raise ValueError("ps: rỗng")
    counts = Counter(round(float(p), LEVEL_DIGITS) for p in ps)
    top2 = sum(c for _, c in counts.most_common(2))
    return Resolution(len(ps), len(counts), top2 / len(ps), {repr(k): v for k, v in sorted(counts.items())})


type Stat = Callable[[Sequence[Point]], float]
STATS: Final[dict[str, Stat]] = {"ece10": ece_uniform, "ece5_mass": ece_equal_mass, "brier": brier_score}


def bootstrap(points: Sequence[Point], stat: Stat, *, n_boot: int = N_BOOT, seed: int = SEED, level: float = LEVEL) -> BootstrapCI:
    def statistic(rs: Sequence[Any]) -> float | None:
        return stat(cast(Sequence[Point], rs)) if rs else None

    return family_bootstrap_ci(cast(Any, list(points)), statistic, n_boot=n_boot, seed=seed, level=level)


@dataclass(frozen=True)
class Bin:
    lo: float
    hi: float
    n: int
    mean_p: float | None
    frac_pos: float | None


def reliability_bins(points: Sequence[Point], n_bins: int = ECE_BINS_UNIFORM) -> list[Bin]:
    """Ngăn đều như `decision_math.ece` (chỉ số ngăn `min(floor(round(p·n, 9)), n−1)`) — dữ liệu cho reliability diagram."""
    groups: list[list[Point]] = [[] for _ in range(n_bins)]
    for q in points:
        groups[min(int(np.floor(round(q.p * n_bins, 9))), n_bins - 1)].append(q)
    out = []
    for i, g in enumerate(groups):
        mean_p = sum(q.p for q in g) / len(g) if g else None
        frac = sum(q.y for q in g) / len(g) if g else None
        out.append(Bin(i / n_bins, (i + 1) / n_bins, len(g), mean_p, frac))
    return out
