"""Hiệu chỉnh kiểm tra chéo 5 phần theo họ (D-58, `eval/folds.csv`) — CÙNG loại calibrator T37: Platt `app.risk.calibrator.fit_platt`
(calibrator RQ1 gọi ở `app/eval/calibrate.py:184-186`). Nhãn = nhãn của calibrator RQ1: `y = gold.expected_route != "AUTO"`
(`calibrate.py:184`, `risk/calibrator.py:53`).

Với từng phần k: fit trên các lá có p ở 4 phần còn lại (`LabeledSample.split = "calibration"`), biến đổi lá của phần k, gộp 5 phần.
Chống rò rỉ: (1) một họ nằm ở > 1 phần → `LeakageError` trước mọi tính toán; (2) mẫu fit dựng từ lá có `fold != k` — lá phần k không
bao giờ vào `fit_platt` (mà `fit_platt` vẫn tự từ chối mẫu `split != "calibration"`). `fit_platt` ném `ValueError` (< 10 mẫu, một lớp,
a ≤ 0, không hội tụ) → lá phần k KHÔNG có p hiệu chỉnh (ghi lý do), không lấy p thô thay vào.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.eval.predictions import CV_K
from app.risk.calibrator import LabeledSample, LeakageError, fit_platt


@dataclass(frozen=True)
class CalRow:
    ticket_id: str
    family: str
    fold: int
    y: bool


@dataclass(frozen=True)
class FoldInfo:
    fold: int
    n_train: int
    n_test: int
    status: str  # "ok" | "fit_failed"
    reason: str | None
    calibrator_version: str | None
    a: float | None
    b: float | None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def check_families(rows: Sequence[CalRow]) -> None:
    folds: dict[str, set[int]] = {}
    for r in rows:
        folds.setdefault(r.family, set()).add(r.fold)
    bad = sum(1 for f in folds.values() if len(f) > 1)
    if bad:
        raise LeakageError(f"{bad} họ nằm ở nhiều phần — chia phần phải theo họ")
    if any(not 1 <= r.fold <= CV_K for r in rows):
        raise ValueError(f"fold ngoài 1..{CV_K}")


def cross_fit(
    rows: Sequence[CalRow], prob: Callable[[CalRow], float | None], *, now: datetime, k: int = CV_K
) -> tuple[dict[str, float | None], list[FoldInfo]]:
    """p hiệu chỉnh ngoài phần cho mọi lá có p thô (lá không có p thô → vắng khỏi kết quả)."""
    check_families(rows)
    out: dict[str, float | None] = {}
    infos: list[FoldInfo] = []
    for fold in range(1, k + 1):
        train = [r for r in rows if r.fold != fold and prob(r) is not None]
        test = [r for r in rows if r.fold == fold and prob(r) is not None]
        samples = [LabeledSample(split="calibration", family=r.family, raw_prob=_p(prob, r), y=r.y) for r in train]
        try:
            cal = fit_platt(samples, now=now)
        except ValueError as e:
            infos.append(FoldInfo(fold, len(train), len(test), "fit_failed", str(e), None, None, None))
            out.update(dict.fromkeys((r.ticket_id for r in test), None))
            continue
        for r in test:
            out[r.ticket_id] = cal.transform(_p(prob, r))
        prm = cal.params
        infos.append(FoldInfo(fold, len(train), len(test), "ok", None, prm.version, prm.a, prm.b))
    return out, infos


def _p(prob: Callable[[CalRow], float | None], r: CalRow) -> float:
    p = prob(r)
    assert p is not None
    return p
