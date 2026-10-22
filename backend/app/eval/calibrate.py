"""Hiệu chỉnh, ngưỡng và chọn biến thể xác suất — theo TỪNG PHẦN và TỪNG PHƯƠNG ÁN có lớp LLM (P8 v1.4 §5.3; việc G4 + N18).

`fit_fold(train, …)` nhận các ca của phần huấn luyện (4 phần còn lại) của MỘT phương án, rồi với mỗi biến thể xác suất
(`with_evidence`, `no_evidence`, `max` — G10): fit Platt riêng (`app.risk.calibrator.fit_platt`) → chọn ngưỡng theo chi phí
(`decision_math.select_thresholds`, ma trận mặc định 10:1) → ép ngưỡng trên = `T_HIGH_MAX` khi thiếu ca L2 / AUC L2 thấp → chấm bằng
chi phí kỳ vọng trên phần huấn luyện → chọn biến thể rẻ nhất. Không nhìn phần đo. Toán và hiệu chỉnh gọi lại `app.risk.*` (D-37), không
viết bản thứ hai.

Quy ước đã chốt (N18, 22–23/10):
1. Ca đi lớp LLM (`FoldCase.llm`) do `offline.py` quyết theo P8 §5.4; ở đây chỉ nhận cờ. Ca không đi lớp LLM mang `fixed_route`
   (route của luật, hoặc ESCALATE_L2 do không tới điểm log 4).
2. `expected_cost_on` tính CẢ ca không đi lớp LLM (theo `fixed_route`); ca LLM hạ AUTO → HITL khi `kb_gap` (D-34). `kb_gap` là của ca
   (bằng chứng GỐC), dùng chung cho mọi biến thể — biến thể `no_evidence` không bị coi là "thiếu căn cứ" chỉ vì trích đoạn rỗng.
3. Hoà chi phí → thứ tự `VARIANT_ORDER` (with_evidence > no_evidence > max).
4. `t_high = T_HIGH_MAX` (1,01) nghĩa là lớp LLM KHÔNG BAO GIỜ đưa ca sang L2 (p ≤ 1 < 1,01) — không phải "mọi ca đi L2". "Không bao giờ
   AUTO" (D-38) = ngưỡng DƯỚI bằng 0 (`UNCALIBRATED_T_LOW`), không phải ngưỡng trên.
5. Phần huấn luyện có dưới `MIN_L2_CASES` ca L2 trong số ca ĐI LỚP LLM → không tính AUC, ngưỡng trên = `T_HIGH_MAX`. Đủ ca L2: AUC của p
   đã hiệu chỉnh tách "gold = ESCALATE_L2" < `AUC_L2_MIN`, hoặc không tính được (một lớp) → cũng `T_HIGH_MAX` (lý do `auc_undefined`).
6. Biến thể mà `fit_platt` ném `ValueError` (< 10 mẫu, một lớp, a ≤ 0, không hội tụ) bị loại khỏi so sánh trong phần đó và ghi log. Cả
   ba bị loại → phần đó CHƯA HIỆU CHỈNH (D-38): `route_for(raw, 0, policy_t_high)` — raw > ngưỡng trên của policy → L2, còn lại HITL.
7. So sánh biến thể trong phần chỉ trên ca đi lớp LLM có ĐỦ mọi biến thể (G10 có thể bỏ `no_evidence`/`max` của ca gọi lỗi).

Giới hạn (ghi trong báo cáo): Platt thường, KHÔNG làm mượt nhãn (P8 §5.3 tuỳ chọn; F3 không làm) → phần huấn luyện tách hẳn một lớp
thì biến thể bị loại thay vì được làm mượt. `select_thresholds` không biết `kb_gap` (decision_math không đổi) nên ngưỡng chọn không
tính việc hạ AUTO; phần điểm chi phí thì có. Khi ép ngưỡng trên = 1,01, ngưỡng dưới giữ nguyên như giả mã P8.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from app.risk.calibrator import Calibrator, LabeledSample, LeakageError, fit_platt
from app.risk.decision_math import (
    DEFAULT_COST,
    T_HIGH_MAX,
    CostMatrix,
    Route,
    auc,
    route_for,
    select_thresholds,
    sensitivity,
    t_low_star,
)

log = logging.getLogger(__name__)

type Variant = Literal["with_evidence", "no_evidence", "max"]
VARIANT_ORDER: Final[tuple[Variant, ...]] = ("with_evidence", "no_evidence", "max")  # thứ tự khi hoà chi phí (chốt 3)
UNCALIBRATED_VARIANT: Final[Variant] = "with_evidence"  # chưa hiệu chỉnh: đọc p thô của chính stack
UNCALIBRATED_T_LOW: Final = 0.0  # D-38: "không bao giờ AUTO" = ngưỡng dưới 0 (p < 0 không xảy ra)
MIN_L2_CASES: Final = 10  # P8 §5.3 "thiếu ca L2" = dưới số này ca gold ESCALATE_L2 trong số ca đi lớp LLM của phần huấn luyện
AUC_L2_MIN: Final = 0.7  # P8 §5.3: AUC tách "gold = ESCALATE_L2" dưới mức này → bỏ đường LLM → L2
SENSITIVITY_RATIOS: Final = (5.0, 10.0, 20.0)  # P8 §5.3 độ nhạy tỉ lệ bỏ sót/duyệt
type UpperReason = Literal["too_few_l2", "auc_below_min", "auc_undefined"]


@dataclass(frozen=True)
class FoldCase:
    """Một ca (lá đã nhãn, có trong mẫu) của một phương án. `split` = vai trò trong phần đang xét: "calibration" cho phần huấn luyện,
    "test" cho phần đo — `fit_fold` KHÔNG lọc, thấy "test" là `LeakageError`."""

    scenario_id: str
    family: str
    split: Literal["calibration", "test"]
    gold: Route
    llm: bool  # có đi lớp LLM của phương án (P8 §5.4)
    fixed_route: Route | None  # ca không đi lớp LLM; `llm = True` ⇒ None
    probs: Mapping[Variant, float]  # xác suất thô từng biến thể (G10); thiếu = biến thể bị bỏ ở ca này
    kb_gap: bool  # bằng chứng GỐC của ca

    def __post_init__(self) -> None:
        if self.llm == (self.fixed_route is not None):
            raise ValueError("FoldCase: llm=True ⇔ fixed_route=None")
        if any(not 0.0 <= p <= 1.0 for p in self.probs.values()):
            raise ValueError("FoldCase: xác suất thô phải nằm trong [0, 1]")


@dataclass(frozen=True)
class VariantTrial:
    variant: Variant
    status: Literal["ok", "dropped"]
    reason: str | None = None  # lý do loại (status = dropped)
    n_fit: int = 0
    train_cost: float | None = None
    t_low: float | None = None
    t_high: float | None = None
    upper_disabled: UpperReason | None = None
    auc_l2: float | None = None
    calibrator_version: str | None = None


@dataclass(frozen=True)
class FoldFit:
    mode: Literal["calibrated", "uncalibrated"]
    variant: Variant | None  # None khi chưa hiệu chỉnh
    calibrator: Calibrator | None
    thresholds: tuple[float, float]  # (t_low, t_high) áp dụng; chưa hiệu chỉnh: (0, policy_t_high)
    upper_disabled: UpperReason | None  # chỉ khi calibrated
    trials: tuple[VariantTrial, ...]
    n_train: int
    n_llm: int  # ca đi lớp LLM của phần huấn luyện
    n_l2: int  # trong số đó, gold ESCALATE_L2
    n_incomplete: int  # ca LLM thiếu ≥ 1 biến thể → ngoài so sánh
    t_low_star: float
    sensitivity: Mapping[str, Mapping[str, float]] | None
    log: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        cal = self.calibrator
        return {
            "mode": self.mode, "variant": self.variant,
            "calibrator_version": cal.params.version if cal is not None else None,
            "thresholds": {"t_low": self.thresholds[0], "t_high": self.thresholds[1]},
            "upper_disabled": self.upper_disabled, "t_low_star": self.t_low_star,
            "n_train": self.n_train, "n_llm": self.n_llm, "n_l2": self.n_l2, "n_incomplete": self.n_incomplete,
            "sensitivity": self.sensitivity,
            "trials": [t.__dict__ for t in self.trials], "log": list(self.log),
        }  # fmt: skip


def llm_route(raw: float, cal: Calibrator | None, th: tuple[float, float], kb_gap: bool, policy_t_high: float) -> Route:
    """Route của MỘT ca đi lớp LLM. Chưa hiệu chỉnh (D-38): `route_for(raw, 0, policy_t_high)` — không bao giờ AUTO nhờ ngưỡng dưới 0.
    Đã hiệu chỉnh: `route_for(cal.transform(raw), *th)`; `kb_gap` ∧ AUTO → HITL (D-34, như `strategy._llm_decision`)."""
    if cal is None:
        return route_for(raw, UNCALIBRATED_T_LOW, policy_t_high)
    route = route_for(cal.transform(raw), th[0], th[1])
    if kb_gap and route == "AUTO":
        return "HITL"
    return route


def expected_cost_on(
    cases: Sequence[FoldCase], variant: Variant, cal: Calibrator | None, th: tuple[float, float], policy_t_high: float,
    cost: CostMatrix = DEFAULT_COST,
) -> float:  # fmt: skip
    """Chi phí kỳ vọng/ca trên MỌI ca của `cases`: ca LLM theo `llm_route` với p của `variant`, ca còn lại theo `fixed_route`."""
    if not cases:
        raise ValueError("cases: rỗng")
    total = 0.0
    for c in cases:
        if c.llm:
            route = llm_route(c.probs[variant], cal, th, c.kb_gap, policy_t_high)
        else:
            assert c.fixed_route is not None  # __post_init__ bảo đảm
            route = c.fixed_route
        total += cost.costs[c.gold][route]
    return total / len(cases)


def _upper(n_l2: int, p_cal: Sequence[float], golds: Sequence[Route]) -> tuple[UpperReason | None, float | None]:
    """Quy tắc "bỏ đường LLM → L2" (P8 §5.3): (lý do ép ngưỡng trên = T_HIGH_MAX hoặc None, AUC L2 nếu tính được)."""
    if n_l2 < MIN_L2_CASES:
        return "too_few_l2", None
    try:
        a = auc(p_cal, [g == "ESCALATE_L2" for g in golds])
    except ValueError:  # trong tập so sánh chỉ một lớp
        return "auc_undefined", None
    return ("auc_below_min" if a < AUC_L2_MIN else None), a


def fit_fold(
    train: Sequence[FoldCase], *, now: datetime, policy_t_high: float, variants: Sequence[Variant] = VARIANT_ORDER,
    cost: CostMatrix = DEFAULT_COST,
) -> FoldFit:  # fmt: skip
    """Fit + chọn ngưỡng + chọn biến thể trên PHẦN HUẤN LUYỆN của một phương án. Có ca `split != "calibration"` → `LeakageError`
    (kiểm trước mọi tính toán, cả ca không đi lớp LLM). `now` đi vào `version` của calibrator (tái lập: truyền giờ cố định)."""
    if any(c.split != "calibration" for c in train):
        raise LeakageError(f"{sum(c.split != 'calibration' for c in train)} ca không thuộc split calibration — chỉ được fit trên calibration")
    if not 0.0 <= policy_t_high <= 1.0:
        raise ValueError("policy_t_high: phải nằm trong [0, 1]")
    if not variants or len(set(variants)) != len(variants):
        raise ValueError("variants: rỗng hoặc trùng")
    lines: list[str] = []
    llm = [c for c in train if c.llm]
    n_l2 = sum(c.gold == "ESCALATE_L2" for c in llm)  # "thiếu ca L2" đếm trên MỌI ca đi lớp LLM của phần (chốt 6)
    common = [c for c in llm if all(v in c.probs for v in variants)]  # chốt Q5: chỉ so trên ca đủ biến thể
    common_ids = {c.scenario_id for c in common}
    scored = [c for c in train if not c.llm or c.scenario_id in common_ids]
    trials: list[VariantTrial] = []
    best: tuple[tuple[float, int], Variant, Calibrator, tuple[float, float], UpperReason | None] | None = None
    for rank, v in enumerate(variants):
        samples = [LabeledSample(split=c.split, family=c.family, raw_prob=c.probs[v], y=c.gold != "AUTO") for c in common]
        try:
            cal = fit_platt(samples, now=now)
        except ValueError as e:  # < 10 mẫu, một lớp, a ≤ 0, không hội tụ → loại biến thể (chốt 7)
            trials.append(VariantTrial(v, "dropped", reason=str(e), n_fit=len(samples)))
            lines.append(f"biến thể {v} bị loại: {e}")
            continue
        p_cal = [cal.transform(c.probs[v]) for c in common]
        golds = [c.gold for c in common]
        th = select_thresholds(p_cal, golds, cost)
        reason, a = _upper(n_l2, p_cal, golds)
        final = (th.t_low, T_HIGH_MAX if reason is not None else th.t_high)
        score = expected_cost_on(scored, v, cal, final, policy_t_high, cost)
        trials.append(VariantTrial(v, "ok", n_fit=len(samples), train_cost=score, t_low=final[0], t_high=final[1],
                                   upper_disabled=reason, auc_l2=a, calibrator_version=cal.params.version))  # fmt: skip
        if reason is not None:
            lines.append(f"biến thể {v}: ngưỡng trên = {T_HIGH_MAX} ({reason}); số ca L2 trong ca đi lớp LLM = {n_l2}")
        key = (round(score, 12), rank)  # hoà chi phí → thứ tự `variants` (chốt 3)
        if best is None or key < best[0]:
            best = (key, v, cal, final, reason)
    t_star = t_low_star(cost)
    n_train, n_llm, n_incomplete = len(train), len(llm), len(llm) - len(common)
    if best is None:
        lines.append("cả các biến thể đều bị loại → phần này CHƯA HIỆU CHỈNH (D-38): raw > ngưỡng trên của policy → L2, còn lại HITL")
        for line in lines:
            log.info(line)
        return FoldFit("uncalibrated", None, None, (UNCALIBRATED_T_LOW, policy_t_high), None, tuple(trials),
                       n_train, n_llm, n_l2, n_incomplete, t_star, None, tuple(lines))  # fmt: skip
    _, v, cal, final, reason = best
    sens = sensitivity([cal.transform(c.probs[v]) for c in common], [c.gold for c in common], SENSITIVITY_RATIOS)
    sens_json = {
        str(int(r)): {"t_low_star": ts, "t_low": ch.t_low, "t_high": ch.t_high, "expected_cost": ch.expected_cost}
        for r, (ts, ch) in sens.items()
    }  # fmt: skip
    lines.append(f"chọn biến thể {v} (chi phí huấn luyện {best[0][0]:.6f})")
    for line in lines:
        log.info(line)
    return FoldFit("calibrated", v, cal, final, reason, tuple(trials), n_train, n_llm, n_l2, n_incomplete, t_star, sens_json,
                   tuple(lines))  # fmt: skip
