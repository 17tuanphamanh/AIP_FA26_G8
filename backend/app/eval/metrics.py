"""Công thức chỉ số M8 (P8 §6) — hàm thuần trên `PredictionRecord` (hợp đồng v1, `predictions.py`). S2: §6.1; S3: §6.2.

Quy ước (chốt #32, 13/10):
- Danh sách bản ghi rỗng → `ValueError` (như `decision_math`). Mẫu số con = 0 → `None`, không trả 0 giả.
- §6.1 chỉ tính trên lá có điểm log 4 (`route ≠ None`, P8:342); "cần người" = `expected_route ≠ AUTO` (P8:346).
- §6.2 tính trên MỌI lá (P8:342), kể cả lá không tới M5 (Q7).
- CP, ECE, Brier, ma trận chi phí IMPORT từ `app.risk.decision_math` — không viết lại (D-37).
- Tỉ lệ trả `Rate(k, n)` để báo cáo và tính tay; `value = k/n`.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

import numpy as np

from app.db.models import EXIT_CODES
from app.domain.states import S_RESOLVED
from app.eval.predictions import PredictionRecord
from app.risk.decision_math import (
    DEFAULT_COST,
    ROUTES,
    CostMatrix,
    Route,
    brier,
    clopper_pearson_upper,
    ece,
)

type Records = Sequence[PredictionRecord]


@dataclass(frozen=True)
class Rate:
    """Tỉ lệ k/n; n = 0 → `value` None."""

    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None


@dataclass(frozen=True)
class Mean:
    """Trung bình total/n; n = 0 → `value` None."""

    total: float
    n: int

    @property
    def value(self) -> float | None:
        return self.total / self.n if self.n else None


@dataclass(frozen=True)
class SafetyMetrics:
    """P8 §6.1 trên `n_m5` lá có điểm log 4. `confusion[gold][pred]` theo ROUTES; `f1_by_class` None = lớp vắng."""

    n_m5: int
    fnr: Rate
    fnr_upper95: float | None
    fpr: Rate
    accuracy: Rate
    confusion: Mapping[Route, Mapping[Route, int]]
    f1_by_class: Mapping[Route, float | None]
    macro_f1: float | None
    cost: Mean


@dataclass(frozen=True)
class CalibrationScores:
    """ECE (10 bin) + Brier trên `n` ca `decided_by = llm` có p; `which` = cột p đã dùng."""

    which: Literal["raw", "calibrated"]
    n: int
    p_method: str | None
    ece: float
    brier: float


@dataclass(frozen=True)
class DecidedByDistribution:
    """P8:356 — mẫu số = lá có điểm log 4. `missing` = lá tới M5 mà `decided_by` None [Đề xuất]."""

    rule: Rate
    llm: Rate
    missing: Rate


def _require(records: Records) -> None:
    if len(records) == 0:
        raise ValueError("records: rỗng")


def _pairs(records: Records) -> list[tuple[Route, Route]]:
    """(gold, pred) của lá có điểm log 4 (P8:342)."""
    return [(r.expected_route, r.route) for r in records if r.route is not None]


def _confusion(pairs: list[tuple[Route, Route]]) -> dict[Route, dict[Route, int]]:
    counts = {g: dict.fromkeys(ROUTES, 0) for g in ROUTES}
    for gold, pred in pairs:
        counts[gold][pred] += 1
    return counts


def _f1_by_class(counts: dict[Route, dict[Route, int]]) -> dict[Route, float | None]:
    """F1 lớp = 2·TP/(#pred + #gold) (= 2PR/(P+R); TP = 0 → 0). Vắng cả gold lẫn pred → None (loại khỏi trung bình);
    P hoặc R = 0/0 → 0 [Đề xuất, duyệt #32]."""
    out: dict[Route, float | None] = {}
    for c in ROUTES:
        n_pred = sum(counts[g][c] for g in ROUTES)
        n_gold = sum(counts[c][p] for p in ROUTES)
        if n_pred == 0 and n_gold == 0:
            out[c] = None
        elif n_pred == 0 or n_gold == 0:
            out[c] = 0.0
        else:
            out[c] = 2 * counts[c][c] / (n_pred + n_gold)
    return out


def mean_route_cost(records: Records, cost: CostMatrix = DEFAULT_COST) -> Mean:
    """P8:353 — trung bình `cost[gold][pred]` trên lá có điểm log 4 (đơn vị: một lượt duyệt). Khác
    `decision_math.expected_cost` (nhận p + ngưỡng): ở đây pred đã có sẵn."""
    _require(records)
    pairs = _pairs(records)
    return Mean(float(sum(cost.costs[gold][pred] for gold, pred in pairs)), len(pairs))


def safety(records: Records, cost: CostMatrix = DEFAULT_COST) -> SafetyMetrics:
    """P8 §6.1: FNR (P8:350) + cận trên Clopper–Pearson 95%, FPR (P8:351), accuracy + ma trận + macro-F1 (P8:352),
    chi phí kỳ vọng (P8:353)."""
    _require(records)
    pairs = _pairs(records)
    need = [pred for gold, pred in pairs if gold != "AUTO"]
    fnr = Rate(sum(1 for pred in need if pred == "AUTO"), len(need))
    upper = clopper_pearson_upper(fnr.k, fnr.n) if fnr.n else None
    auto = [pred for gold, pred in pairs if gold == "AUTO"]
    fpr = Rate(sum(1 for pred in auto if pred != "AUTO"), len(auto))
    counts = _confusion(pairs)
    per_class = _f1_by_class(counts)
    present = [v for v in per_class.values() if v is not None]
    return SafetyMetrics(
        n_m5=len(pairs),
        fnr=fnr,
        fnr_upper95=upper,
        fpr=fpr,
        accuracy=Rate(sum(counts[c][c] for c in ROUTES), len(pairs)),
        confusion=MappingProxyType({g: MappingProxyType(row) for g, row in counts.items()}),
        f1_by_class=MappingProxyType(per_class),
        macro_f1=sum(present) / len(present) if present else None,
        cost=mean_route_cost(records, cost),
    )


def _prob(r: PredictionRecord, which: Literal["raw", "calibrated"]) -> float | None:
    return r.raw_prob if which == "raw" else r.calibrated_prob


def calibration_scores(records: Records, which: Literal["raw", "calibrated"]) -> CalibrationScores | None:
    """P8:354–355 — ECE 10 bin + Brier, chỉ ca `decided_by = llm` có p (Brier lọc như ECE — chốt 5); y = 1 nếu gold ≠ AUTO.
    "Trước" = `raw_prob`, "sau" = `calibrated_prob`, cùng lần chạy test (chốt 1). Trộn nhiều `p_method` → ValueError.
    Không có ca LLM có p → None."""
    _require(records)
    if which not in ("raw", "calibrated"):
        raise ValueError("which: phải là 'raw' hoặc 'calibrated'")
    llm = [r for r in records if r.decided_by == "llm"]
    rows = [(r, p) for r in llm if (p := _prob(r, which)) is not None]
    if not rows:
        return None
    methods = {r.p_method for r, _ in rows}
    if len(methods) > 1:
        raise ValueError("p_method: trộn nhiều cách lấy p trong một phép tính")
    probs = np.array([p for _, p in rows], dtype=float)
    labels = np.array([r.expected_route != "AUTO" for r, _ in rows], dtype=bool)
    return CalibrationScores(which, len(rows), methods.pop(), ece(probs, labels), brier(probs, labels))


def decided_by_distribution(records: Records) -> DecidedByDistribution:
    """P8:356 — % ca do luật / do LLM trên lá có điểm log 4."""
    _require(records)
    m5 = [r for r in records if r.route is not None]
    n = len(m5)
    return DecidedByDistribution(
        rule=Rate(sum(1 for r in m5 if r.decided_by == "rule"), n),
        llm=Rate(sum(1 for r in m5 if r.decided_by == "llm"), n),
        missing=Rate(sum(1 for r in m5 if r.decided_by is None), n),
    )


# ---- §6.2 hiệu quả và trải nghiệm ------------------------------------------------------------------------------------

type Group = Literal["routine", "approval", "sensitive"]
GROUPS: tuple[Group, ...] = ("routine", "approval", "sensitive")
_GROUP_OF: Mapping[Route, Group] = MappingProxyType({"AUTO": "routine", "HITL": "approval", "ESCALATE_L2": "sensitive"})
MIX_TOL = 1e-9
type MixLike = Mapping[Group, float] | Mapping[str, float]  # hằng đóng băng hoặc dict của người gọi

# Chuỗi P8 §6.2 — phải thuộc hằng DB (FINAL_STATES, RESOLUTION_PATHS, CLOSE_REASONS; test đồng bộ).
RESOLVED_STATE: Final = S_RESOLVED  # P8:364
DEFLECTED_PATH: Final = "deflected"  # P8:366
ONE_TURN_CLOSE_REASON: Final = "resolved_user_confirmed"  # P8:368


def check_mix(mix: MixLike) -> Mapping[Group, float]:
    """Phân bố vận hành: đủ đúng 3 nhóm, mỗi trọng số hữu hạn ≥ 0, tổng = 1 (± MIX_TOL) → bản sao đóng băng; sai → ValueError."""
    if set(mix) != set(GROUPS):
        raise ValueError("mix: phải có đúng 3 nhóm routine, approval, sensitive")
    if any(not math.isfinite(w) or w < 0 for w in mix.values()):
        raise ValueError("mix: mỗi trọng số phải hữu hạn và ≥ 0")
    if abs(sum(mix.values()) - 1.0) > MIX_TOL:
        raise ValueError("mix: tổng trọng số phải bằng 1")
    return MappingProxyType({g: float(mix[g]) for g in GROUPS})


OPERATING_MIX: Mapping[Group, float] = check_mix({"routine": 0.7, "approval": 0.2, "sensitive": 0.1})  # P8:399, N3
SENSITIVITY_MIXES: Mapping[str, Mapping[Group, float]] = MappingProxyType({  # P8:365 — độ nhạy N3
    "60/30/10": check_mix({"routine": 0.6, "approval": 0.3, "sensitive": 0.1}),
    "80/15/5": check_mix({"routine": 0.8, "approval": 0.15, "sensitive": 0.05}),
})  # fmt: skip


def n3_group(expected_route: Route) -> Group:
    """Nhóm N3 theo nhãn GOLD (#32 mục 5): AUTO → routine, HITL → approval, ESCALATE_L2 → sensitive. Không phụ thuộc phương án
    đang đo (Full-auto không qua M5 vẫn chia nhóm như mọi phương án khác).

    Khác M9 (`monitor/queries/business.py`): M9 chia theo quyết định M5 (`policy_decision`/`risk_level` của điểm log 4) vì dữ liệu
    vận hành không có gold. M8 và M9 không dùng chung code [Chốt 17.9.4] — không import `app.monitor`."""
    return _GROUP_OF[expected_route]


@dataclass(frozen=True)
class WeightedRate:
    """Escalation trên phân bố vận hành giả định: Σ_g mix[g]·rate_g, rate_g = escalation thô trong nhóm g. Nhóm rỗng →
    `value` None + `missing_groups` (Q5) — không chuẩn hoá lại trên nhóm còn lại."""

    mix: Mapping[Group, float]
    by_group: Mapping[Group, Rate]
    missing_groups: tuple[Group, ...]
    value: float | None


@dataclass(frozen=True)
class EfficiencyMetrics:
    """P8 §6.2 trên `n_leaves` lá. Độ trễ, chi phí LLM, tin/lượt (P8:369–371) → v2 (M1)."""

    n_leaves: int
    automation: Rate
    escalation: Rate
    exit_codes: Mapping[str, Rate]
    escalation_weighted: WeightedRate
    escalation_sensitivity: Mapping[str, WeightedRate]
    deflection: Rate
    clarification: Mean
    one_turn: Rate


def _escalated(r: PredictionRecord) -> bool:
    """P8:365 — có `exit_code` (mọi mã, gồm E0 — Q9)."""
    return r.exit_code is not None


def _automated(r: PredictionRecord) -> bool:
    """P8:364 — đóng S_RESOLVED mà không qua người: "không phiếu duyệt" = `not has_approval`, "không escalation" =
    `exit_code is None` [Đề xuất, duyệt #32]."""
    return r.final_state == RESOLVED_STATE and not r.has_approval and r.exit_code is None


def escalation_weighted(records: Records, mix: MixLike) -> WeightedRate:
    _require(records)
    frozen = check_mix(mix)
    by_group = {g: [r for r in records if n3_group(r.expected_route) == g] for g in GROUPS}
    rates = {g: Rate(sum(1 for r in rows if _escalated(r)), len(rows)) for g, rows in by_group.items()}
    missing = tuple(g for g in GROUPS if rates[g].n == 0)
    present = [g for g in GROUPS if g not in missing]
    value = None if missing else sum(frozen[g] * rates[g].k / rates[g].n for g in present)
    return WeightedRate(frozen, MappingProxyType(rates), missing, value)


def efficiency(
    records: Records,
    mix: MixLike = OPERATING_MIX,
    sensitivity_mixes: Mapping[str, MixLike] = SENSITIVITY_MIXES,
) -> EfficiencyMetrics:
    """P8 §6.2 (P8:364–368): Automation, Escalation thô + phân bố theo `exit_code` + có trọng số (mix chính và các bộ độ nhạy),
    Deflection, Lượt hỏi lại TB, Giải quyết một lượt. Mẫu số = mọi lá. Cờ "cảnh báo > 40%" (P8:365) thuộc báo cáo."""
    _require(records)
    leaves = list(records)  # P8:342 — mọi lá, gồm lá không tới M5 (Q7)
    n = len(leaves)
    return EfficiencyMetrics(
        n_leaves=n,
        automation=Rate(sum(1 for r in leaves if _automated(r)), n),
        escalation=Rate(sum(1 for r in leaves if _escalated(r)), n),
        exit_codes=MappingProxyType({c: Rate(sum(1 for r in leaves if r.exit_code == c), n) for c in EXIT_CODES}),
        escalation_weighted=escalation_weighted(leaves, mix),
        escalation_sensitivity=MappingProxyType({k: escalation_weighted(leaves, m) for k, m in sensitivity_mixes.items()}),
        deflection=Rate(sum(1 for r in leaves if r.resolution_path == DEFLECTED_PATH), n),
        clarification=Mean(float(sum(r.clarification_turns for r in leaves)), n),
        one_turn=Rate(sum(1 for r in leaves if r.clarification_turns == 0 and r.close_reason == ONE_TURN_CLOSE_REASON), n),
    )
