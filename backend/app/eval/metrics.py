"""Công thức chỉ số M8 (P8 §6) — hàm thuần trên `PredictionRecord` (hợp đồng v1, `predictions.py`). S2: §6.1; S3: §6.2;
S5: §6.3.

Quy ước (chốt #32, 13/10):
- Danh sách bản ghi rỗng → `ValueError` (như `decision_math`). Mẫu số con = 0 → `None`, không trả 0 giả.
- §6.1 chỉ tính trên lá có điểm log 4 (`route ≠ None`, P8:342); "cần người" = `expected_route ≠ AUTO` (P8:346).
- §6.2 tính trên MỌI lá (P8:342), kể cả lá không tới M5 (Q7).
- Lá CHƯA NHÃN (`expected_route` None — dữ liệu thật tới 25/10, G2-Q22): chỉ số cần gold (§6.1 an toàn, chi phí, ECE/Brier,
  escalation có trọng số theo nhóm N3) bỏ qua lá đó và đếm `n_unlabeled`; chỉ số không cần gold (§6.2 thô, §6.3) tính như cũ.
- CP, ECE, Brier, ma trận chi phí IMPORT từ `app.risk.decision_math` — không viết lại (D-37).
- Tỉ lệ trả `Rate(k, n)` để báo cáo và tính tay; `value = k/n`.
"""

import math
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Protocol, cast

import numpy as np

from app.db.models import EXIT_CODES, INTENTS
from app.domain.states import S_RESOLVED
from app.eval.predictions import PredictionRecord
from app.eval.stats import clopper_pearson_two_sided
from app.risk.decision_math import (
    DEFAULT_COST,
    ROUTES,
    CostMatrix,
    Route,
    brier,
    clopper_pearson_upper,
    cost_matrix_for_ratio,
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
    n_unlabeled: int = 0  # lá chưa nhãn bị bỏ qua (G2-Q22)


@dataclass(frozen=True)
class CalibrationScores:
    """ECE (10 bin) + Brier trên `n` ca `decided_by = llm` có p; `which` = cột p đã dùng."""

    which: Literal["raw", "calibrated"]
    n: int
    p_method: str | None
    ece: float
    brier: float
    n_unlabeled: int = 0


@dataclass(frozen=True)
class DecidedByDistribution:
    """P8:356 — mẫu số = lá có điểm log 4. `missing` = lá tới M5 mà `decided_by` None [Đề xuất]."""

    rule: Rate
    llm: Rate
    missing: Rate


def _require(records: Records) -> None:
    if len(records) == 0:
        raise ValueError("records: rỗng")


class _Gold(Protocol):
    """Lá ĐÃ NHÃN (`expected_route` khác None) — chỉ tạo qua `_gold`."""

    @property
    def expected_route(self) -> Route: ...

    @property
    def route(self) -> Route | None: ...


def _labelled(records: Records) -> list[PredictionRecord]:
    return [r for r in records if r.expected_route is not None]


def _gold(records: Records) -> list[_Gold]:
    return cast(list[_Gold], _labelled(records))


def n_unlabeled(records: Records) -> int:
    """Số lá chưa nhãn (`expected_route` None) — bị bỏ qua ở chỉ số cần gold."""
    return sum(1 for r in records if r.expected_route is None)


def _pairs(records: Sequence[_Gold]) -> list[tuple[Route, Route]]:
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
    pairs = _pairs(_gold(records))
    return Mean(float(sum(cost.costs[gold][pred] for gold, pred in pairs)), len(pairs))


def safety(records: Records, cost: CostMatrix = DEFAULT_COST) -> SafetyMetrics:
    """P8 §6.1: FNR (P8:350) + cận trên Clopper–Pearson 95%, FPR (P8:351), accuracy + ma trận + macro-F1 (P8:352),
    chi phí kỳ vọng (P8:353)."""
    _require(records)
    pairs = _pairs(_gold(records))
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
        n_unlabeled=n_unlabeled(records),
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
    unlabeled = n_unlabeled(records)
    records = _labelled(records)
    llm = [r for r in records if r.decided_by == "llm"]
    rows = [(r, p) for r in llm if (p := _prob(r, which)) is not None]
    if not rows:
        return None
    methods = {r.p_method for r, _ in rows}
    if len(methods) > 1:
        raise ValueError("p_method: trộn nhiều cách lấy p trong một phép tính")
    probs = np.array([p for _, p in rows], dtype=float)
    labels = np.array([r.expected_route != "AUTO" for r, _ in rows], dtype=bool)
    return CalibrationScores(which, len(rows), methods.pop(), ece(probs, labels), brier(probs, labels), unlabeled)


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


def n3_group(expected_route: Route | None) -> Group:
    """Nhóm N3 theo nhãn GOLD (#32 mục 5): AUTO → routine, HITL → approval, ESCALATE_L2 → sensitive. Không phụ thuộc phương án
    đang đo (Full-auto không qua M5 vẫn chia nhóm như mọi phương án khác).

    Khác M9 (`monitor/queries/business.py`): M9 chia theo quyết định M5 (`policy_decision`/`risk_level` của điểm log 4) vì dữ liệu
    vận hành không có gold. M8 và M9 không dùng chung code [Chốt 17.9.4] — không import `app.monitor`."""
    if expected_route is None:
        raise ValueError("n3_group: lá chưa nhãn (expected_route None) — lọc trước khi chia nhóm")
    return _GROUP_OF[expected_route]


@dataclass(frozen=True)
class WeightedRate:
    """Escalation trên phân bố vận hành giả định: Σ_g mix[g]·rate_g, rate_g = escalation thô trong nhóm g. Nhóm rỗng →
    `value` None + `missing_groups` (Q5) — không chuẩn hoá lại trên nhóm còn lại."""

    mix: Mapping[Group, float]
    by_group: Mapping[Group, Rate]
    missing_groups: tuple[Group, ...]
    value: float | None
    n_unlabeled: int = 0  # lá chưa nhãn: không thuộc nhóm N3 nào → bỏ qua (G2-Q22)


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
    unlabeled = n_unlabeled(records)
    records = _labelled(records)
    by_group = {g: [r for r in records if n3_group(r.expected_route) == g] for g in GROUPS}
    rates = {g: Rate(sum(1 for r in rows if _escalated(r)), len(rows)) for g, rows in by_group.items()}
    missing = tuple(g for g in GROUPS if rates[g].n == 0)
    present = [g for g in GROUPS if g not in missing]
    value = None if missing else sum(frozen[g] * rates[g].k / rates[g].n for g in present)
    return WeightedRate(frozen, MappingProxyType(rates), missing, value, unlabeled)


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


# ---- G1: chỉ số theo ROUTE có trọng số + điểm hoà vốn (P8 §6.1, §6.2, §5.2; chốt #32 18/10) ----------------------------------
# Hàm thuần trên `route` — route của stack (Chỉ-luật), offline §5.3 (phương án có LLM) hoặc giải tích (Thủ công). Ca không tới
# điểm log 4 do `offline.py` đổi thành ESCALATE_L2 trước khi gọi (chốt 3); ở đây route None = ngoài mẫu số như §6.1.
# TODO(G1-Q8): đặt trong metrics.py (P8 §2), N3d của mutate_g1.py giữ chuỗi gốc của đột biến cũ — chờ Tuấn Anh xác nhận ở #32.

BREAKEVEN_RATIOS: tuple[float, ...] = (5.0, 10.0, 20.0)  # P8 §5.3 — độ nhạy tỉ lệ bỏ sót/duyệt 5/10/20
SLOPE_TOL = 1e-12  # |miss_A − miss_B| ≤ SLOPE_TOL → coi là bằng nhau (chốt 1: b_A = b_B → không có điểm hoà vốn)
type BreakevenReason = Literal["ok", "equal_miss", "dominated", "no_common", "missing_groups"]


@dataclass(frozen=True)
class WeightedMean:
    """Như `WeightedRate` nhưng trên trung bình: Σ_g mix[g]·mean_g. Nhóm rỗng → `value` None + `missing_groups` (Q5) — không
    chuẩn hoá lại trên nhóm còn lại."""

    mix: Mapping[Group, float]
    by_group: Mapping[Group, Mean]
    missing_groups: tuple[Group, ...]
    value: float | None
    n_unlabeled: int = 0


@dataclass(frozen=True)
class OperatingPoint:
    """Chỉ số theo ROUTE trên một phân bố vận hành, nhóm theo gold, n_g = lá đã nhãn có route: `cost` lượt duyệt/ticket;
    `automation` = route AUTO; `review` = route HITL — khối lượng duyệt, L2 không tính (chốt 5); `l2` = route ESCALATE_L2 — khác
    `escalation` của `efficiency()` (điểm log 8, `exit_code`; chốt 2)."""

    mix: Mapping[Group, float]
    cost: WeightedMean
    automation: WeightedRate
    review: WeightedRate
    l2: WeightedRate


@dataclass(frozen=True)
class OperatingMetrics:
    """`cost` = chi phí kỳ vọng KHÔNG trọng số (§6.1, = `mean_route_cost`) — số chính RQ1 (chốt 4); `main` (mix chính) và
    `sensitivity` (các bộ độ nhạy) là số phụ. TODO(G1-Q6): giữ `cost` dù trùng `safety().cost` — chờ xác nhận ở #32."""

    n_m5: int
    n_unlabeled: int
    cost: Mean
    main: OperatingPoint
    sensitivity: Mapping[str, OperatingPoint]


def _reached(records: Records) -> dict[Group, list[PredictionRecord]]:
    """Lá ĐÃ NHÃN có điểm log 4 (route ≠ None), chia theo nhóm N3 của GOLD (#32 mục 5). Lá chưa nhãn bỏ qua (G2-Q22)."""
    rows: dict[Group, list[PredictionRecord]] = {g: [] for g in GROUPS}
    for r in _labelled(records):
        if r.route is not None:
            rows[n3_group(r.expected_route)].append(r)
    return rows


def _weigh(frozen: Mapping[Group, float], parts: Mapping[Group, float | None]) -> tuple[tuple[Group, ...], float | None]:
    """(nhóm thiếu, Σ_g mix[g]·phần_g); có nhóm thiếu (phần None) → giá trị None, không chuẩn hoá lại (Q5)."""
    missing = tuple(g for g in GROUPS if parts[g] is None)
    return missing, None if missing else sum(frozen[g] * cast(float, parts[g]) for g in GROUPS)


def _weighted_cost(
    reached: Mapping[Group, list[PredictionRecord]], frozen: Mapping[Group, float], cost: CostMatrix, unlabeled: int
) -> WeightedMean:
    means = {g: mean_route_cost(rs, cost) if rs else Mean(0.0, 0) for g, rs in reached.items()}
    missing, value = _weigh(frozen, {g: m.value for g, m in means.items()})
    return WeightedMean(frozen, MappingProxyType(means), missing, value, unlabeled)


def _share(
    reached: Mapping[Group, list[PredictionRecord]], frozen: Mapping[Group, float], routes: Collection[str], unlabeled: int
) -> WeightedRate:
    rates = {g: Rate(sum(1 for r in rs if r.route in routes), len(rs)) for g, rs in reached.items()}
    missing, value = _weigh(frozen, {g: q.value for g, q in rates.items()})
    return WeightedRate(frozen, MappingProxyType(rates), missing, value, unlabeled)


def _point(reached: Mapping[Group, list[PredictionRecord]], mix: MixLike, cost: CostMatrix, unlabeled: int) -> OperatingPoint:
    frozen = check_mix(mix)
    return OperatingPoint(
        mix=frozen,
        cost=_weighted_cost(reached, frozen, cost, unlabeled),
        automation=_share(reached, frozen, ("AUTO",), unlabeled),
        review=_share(reached, frozen, ("HITL",), unlabeled),
        l2=_share(reached, frozen, ("ESCALATE_L2",), unlabeled),
    )


def operating_metrics(
    records: Records,
    mix: MixLike = OPERATING_MIX,
    sensitivity_mixes: Mapping[str, MixLike] = SENSITIVITY_MIXES,
    cost: CostMatrix = DEFAULT_COST,
) -> OperatingMetrics:
    """P8 §6.2 "với phương án có LLM, automation và escalation tính từ route offline" + chi phí §6.1 có trọng số (G1): mỗi chỉ số
    = Σ_g mix[g]·(chỉ số trong nhóm gold g), mix chính và các bộ độ nhạy. Mẫu số = lá đã nhãn có route (như §6.1); lá chưa nhãn
    đếm `n_unlabeled`. Đơn vị chi phí: lượt duyệt/ticket; `cost` truyền được `cost_matrix_for_ratio(5|20)`."""
    plain = mean_route_cost(records, cost)  # `[]` → ValueError
    unlabeled = n_unlabeled(records)
    reached = _reached(records)
    return OperatingMetrics(
        n_m5=plain.n,
        n_unlabeled=unlabeled,
        cost=plain,
        main=_point(reached, mix, cost, unlabeled),
        sensitivity=MappingProxyType({k: _point(reached, m, cost, unlabeled) for k, m in sensitivity_mixes.items()}),
    )


def manual_baseline(records: Records) -> list[PredictionRecord]:
    """Thủ công giải tích (P8 §5.2: mọi ca có hành động coi là qua người): lá có điểm log 4 (route ≠ None) → HITL, lá route None
    giữ None; `strategy = "manual"`, các trường khác giữ nguyên. Hợp đồng không có trường "có hành động" → route ≠ None là đại diện
    (P8 §6: đơn vị = lá có hành động đi tới M5). TODO(G1-Q1): Thủ công dựng từ CHÍNH phương án đem so — chờ xác nhận ở #32."""
    out: list[PredictionRecord] = []
    for r in records:
        update: dict[str, object] = {"strategy": "manual"}
        if r.route is not None:  # lá có hành động
            update["route"] = "HITL"
        out.append(r.model_copy(update=update))
    return out


# Ô chi phí theo họ C(r) = `cost_matrix_for_ratio(r)` (affine theo r): C(r)[g][p] = _FIXED[g][p] + _MISS[g][p]·r. Lấy từ chính hàm
# đó (không hard-code ô nào phụ thuộc r): hiện HITL→AUTO có _MISS = 1, L2→AUTO có _MISS = 2, các ô khác _MISS = 0.
_C1 = cost_matrix_for_ratio(1).costs
_C2 = cost_matrix_for_ratio(2).costs
_MISS: Mapping[Route, Mapping[Route, float]] = MappingProxyType(
    {g: MappingProxyType({p: _C2[g][p] - _C1[g][p] for p in ROUTES}) for g in ROUTES}
)
_FIXED: Mapping[Route, Mapping[Route, float]] = MappingProxyType(
    {g: MappingProxyType({p: _C1[g][p] - _MISS[g][p] for p in ROUTES}) for g in ROUTES}
)


@dataclass(frozen=True)
class Breakeven:
    """Điểm hoà vốn A vs B (chốt #32 18/10 câu 1, phương án A) trên phần giao `n` lá. Chi phí/ticket của X theo C(r) là
    fixed_X + miss_X·r: `fixed` = lượt duyệt/ticket không phụ thuộc r; `miss` = ca bỏ sót quy đổi/ticket (HITL→AUTO 1, L2→AUTO 2
    — tỉ lệ 2:1 của `cost_matrix_for_ratio`). `r_star` = (fixed_B − fixed_A)/(miss_A − miss_B), đơn vị lượt duyệt / một ca bỏ sót:
    dưới r*, bên có `miss` lớn hơn rẻ hơn. `saving[r]` = cost_B(r) − cost_A(r), lượt duyệt/ticket (dương = A rẻ hơn).
    `mix` None = không trọng số (số chính, chốt 4)."""

    mix: Mapping[Group, float] | None
    n: int
    n_unlabeled: int
    n_excluded_a: int
    n_excluded_b: int
    fixed_a: float | None
    miss_a: float | None
    fixed_b: float | None
    miss_b: float | None
    r_star: float | None
    reason: BreakevenReason
    missing_groups: tuple[Group, ...]
    saving: Mapping[float, float | None]


def _avg(cells: Mapping[Route, Mapping[Route, float]], pairs: list[tuple[Route, Route]]) -> float | None:
    return sum(cells[g][p] for g, p in pairs) / len(pairs) if pairs else None


def _fixed_miss(
    rows: Records, frozen: Mapping[Group, float] | None
) -> tuple[tuple[Group, ...], float | None, float | None]:
    """(nhóm thiếu, fixed, miss) của một phương án trên phần giao; `frozen` None → không trọng số."""
    pairs = _pairs(_gold(rows))
    if frozen is None:
        return (), _avg(_FIXED, pairs), _avg(_MISS, pairs)
    by_group = {g: [(gd, p) for gd, p in pairs if n3_group(gd) == g] for g in GROUPS}
    missing, fixed = _weigh(frozen, {g: _avg(_FIXED, ps) for g, ps in by_group.items()})
    _, miss = _weigh(frozen, {g: _avg(_MISS, ps) for g, ps in by_group.items()})
    return missing, fixed, miss


def _cost_at(rows: Records, frozen: Mapping[Group, float] | None, cm: CostMatrix) -> float | None:
    """Chi phí/ticket với ma trận `cm`, tính TRỰC TIẾP (§6.1 hoặc bản trọng số) — không qua fixed/miss."""
    if frozen is None:
        return mean_route_cost(rows, cm).value if rows else None
    return _weighted_cost(_reached(rows), frozen, cm, 0).value


def _minus(b: float | None, a: float | None) -> float | None:
    return b - a if a is not None and b is not None else None


def _r_star(
    n: int, missing: tuple[Group, ...], fa: float | None, ma: float | None, fb: float | None, mb: float | None
) -> tuple[float | None, BreakevenReason]:
    if n == 0:
        return None, "no_common"
    if missing or fa is None or ma is None or fb is None or mb is None:
        return None, "missing_groups"
    if abs(ma - mb) <= SLOPE_TOL:
        return None, "equal_miss"  # chốt 1: b_A = b_B
    r = (fb - fa) / (ma - mb)
    return (r, "ok") if r > 0 else (None, "dominated")  # TODO(G1-Q2): r* ≤ 0 → một bên rẻ hơn với mọi r > 0


def breakeven(
    records_a: Records,
    records_b: Records,
    mix: MixLike | None = None,
    ratios: Sequence[float] = BREAKEVEN_RATIOS,
) -> Breakeven:
    """Điểm hoà vốn r* của A so với B + tiết kiệm/ticket ở từng `ratios` (chốt 1; v1 không có ticket/tháng). Báo cáo gọi cho mỗi
    phương án có LLM X, trên phần giao chung của các phương án (G5, như T1): `breakeven(X, manual_baseline(X))` và
    `breakeven(X, <Chỉ-luật>)`; mỗi cặp với `mix=None` (số chính) và
    từng mix (số phụ). TODO(G1-Q7): một mix mỗi lần gọi — chờ xác nhận ở #32.

    - Hai bên phải cùng tập `scenario_id`, cùng `split` (như `paired_family_bootstrap_diff`) và cùng `expected_route` theo
      `scenario_id` → khác: ValueError. `[]`, mix sai, ratio ≤ 0 → ValueError.
    - Phần giao (P8 §5.4 — so trên ca tới M5 ở mọi phương án): lá đã nhãn có route ở CẢ HAI bên. `n_excluded_a` =
      lá đã nhãn có route ở A mà None ở B; `n_excluded_b` ngược lại. Lá chưa nhãn bỏ qua, đếm `n_unlabeled`.
    - Không có điểm hoà vốn → `r_star` None + `reason`: `no_common` (phần giao rỗng), `missing_groups` (có mix, nhóm rỗng — Q5),
      `equal_miss` (miss bằng nhau), `dominated` (r* ≤ 0). `saving` dấu cost_B − cost_A."""
    _require(records_a)
    _require(records_b)
    gold_a = {r.scenario_id: r.expected_route for r in records_a}
    gold_b = {r.scenario_id: r.expected_route for r in records_b}
    if gold_a.keys() != gold_b.keys():
        raise ValueError("records_a, records_b: tập scenario_id khác nhau — hai phương án phải trên cùng tập kịch bản")
    if {r.split for r in records_a} ^ {r.split for r in records_b}:
        raise ValueError("records_a, records_b: split khác nhau — không so hai phương án trên hai tập dữ liệu khác")
    # TODO(G1-Q4): cùng scenario_id khác gold → ValueError — chờ Tuấn Anh xác nhận ở #32.
    if any(gold_a[s] != gold_b[s] for s in gold_a):
        raise ValueError("records_a, records_b: cùng scenario_id mà expected_route khác nhau — hai file khác gold")
    frozen = check_mix(mix) if mix is not None else None
    matrices = {float(r): cost_matrix_for_ratio(r) for r in ratios}  # ratio ≤ 0 → ValueError
    route_a = {r.scenario_id: r.route for r in records_a}
    route_b = {r.scenario_id: r.route for r in records_b}
    labelled = [s for s, g in gold_a.items() if g is not None]
    # TODO(G1-Q3): phần giao + n_excluded_a/b — chờ Tuấn Anh xác nhận ở #32.
    keep = {s for s in labelled if route_a[s] is not None and route_b[s] is not None}
    common_a = [r for r in records_a if r.scenario_id in keep]
    common_b = [r for r in records_b if r.scenario_id in keep]
    missing, fa, ma = _fixed_miss(common_a, frozen)
    _, fb, mb = _fixed_miss(common_b, frozen)
    r_star, reason = _r_star(len(keep), missing, fa, ma, fb, mb)
    # TODO(G1-Q5): saving = cost_B − cost_A (dương = A rẻ hơn) — chờ Tuấn Anh xác nhận ở #32.
    saving = {r: _minus(_cost_at(common_b, frozen, cm), _cost_at(common_a, frozen, cm)) for r, cm in matrices.items()}
    return Breakeven(
        mix=frozen,
        n=len(keep),
        n_unlabeled=n_unlabeled(records_a),
        n_excluded_a=sum(1 for s in labelled if route_a[s] is not None and route_b[s] is None),
        n_excluded_b=sum(1 for s in labelled if route_b[s] is not None and route_a[s] is None),
        fixed_a=fa,
        miss_a=ma,
        fixed_b=fb,
        miss_b=mb,
        r_star=r_star,
        reason=reason,
        missing_groups=missing,
        saving=MappingProxyType(saving),
    )


# ---- §6.3 chất lượng truy hồi và intent (P8:375) ---------------------------------------------------------------------

TOP_K: Final = 5  # P8:375 "@5"; = `GATE_TOP_DOCS` của cổng ingest (test đồng bộ — Q3: không import `gate` ở đây)


def _gold_set(gold: Collection[str]) -> set[str]:
    """Tập tài liệu đúng (khử trùng). Rỗng → ValueError: Recall và IDCG không xác định."""
    gold_set = set(gold)
    if not gold_set:
        raise ValueError("gold: rỗng — Recall/MRR/nDCG không xác định")
    return gold_set


def first_hit_rank(gold: Collection[str], ranked: Sequence[str], k: int = TOP_K) -> int | None:
    """Hạng 1-gốc THEO VỊ TRÍ trong `ranked[:k]` của tài liệu đúng đầu tiên; không có → None. Cắt theo vị trí, không khử trùng
    trước khi cắt — như `gate.metrics()` (Phase 3) [Đề xuất E2]."""
    gold_set = set(gold)
    return next((i for i, d in enumerate(ranked[:k], start=1) if d in gold_set), None)


def recall_at_k(gold: Collection[str], ranked: Sequence[str], k: int = TOP_K) -> float:
    """Recall@k chuẩn = |gold ∩ top k| / |gold| (M3, chốt #32). Khi có đúng 1 tài liệu đúng → = hit@k của cổng ingest."""
    gold_set = _gold_set(gold)
    return len(gold_set & set(ranked[:k])) / len(gold_set)


def reciprocal_rank_at_k(gold: Collection[str], ranked: Sequence[str], k: int = TOP_K) -> float:
    """1 / hạng của tài liệu đúng đầu tiên trong top k; ngoài top k → 0 (như `gate.metrics()`)."""
    _gold_set(gold)
    rank = first_hit_rank(gold, ranked, k)
    return 1.0 / rank if rank is not None else 0.0


def ndcg_at_k(gold: Collection[str], ranked: Sequence[str], k: int = TOP_K) -> float:
    """nDCG@k nhị phân: DCG = Σ_{i≤k} rel_i / log2(i+1), rel_i = 1 nếu doc thứ i đúng VÀ chưa gặp trong top k (doc trùng chỉ
    tính lần đầu, bản trùng vẫn chiếm chỗ); IDCG = Σ_{i=1}^{min(|gold|, k)} 1 / log2(i+1) [Đề xuất, duyệt #32]."""
    gold_set = _gold_set(gold)
    seen: set[str] = set()
    dcg = 0.0
    for i, d in enumerate(ranked[:k], start=1):
        if d in gold_set and d not in seen:
            dcg += 1.0 / math.log2(i + 1)
        seen.add(d)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold_set), k) + 1))
    return dcg / idcg


@dataclass(frozen=True)
class RetrievalMetrics:
    """P8:375 — trung bình Recall@5, MRR@5, nDCG@5 trên `n` lá có `gold_doc_ids` và đã tới B8. `n_no_retrieval` = lá có gold
    mà `doc_ids is None` (không tới B8, ngoài mẫu); `n_no_gold` = lá `gold_doc_ids` rỗng (ngoài mẫu [Đề xuất E1])."""

    n: int
    n_no_retrieval: int
    n_no_gold: int
    recall5: Mean
    mrr5: Mean
    ndcg5: Mean


def retrieval(records: Records, k: int = TOP_K) -> RetrievalMetrics:
    """P8:375 — Recall@5, MRR@5, nDCG@5 theo `gold_doc_ids` (điểm log 3). Rỗng 3 mức (chỉnh 2, #32): (a) không lá nào có
    `gold_doc_ids` → ValueError; (b) có gold mà `doc_ids == ()` → trượt (0), vẫn trong mẫu; (c) `doc_ids is None` → ngoài mẫu,
    đếm `n_no_retrieval`. Lá `gold_doc_ids` rỗng (câu không có đáp án — false-grounding, ngoài v1) → ngoài mẫu, đếm `n_no_gold`
    [Đề xuất E1]. Mẫu rỗng sau (c) → `Mean(…, 0)` → None."""
    _require(records)
    rows: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    no_gold = no_retrieval = 0
    for r in records:
        if not r.gold_doc_ids:
            no_gold += 1
        elif r.doc_ids is None:
            no_retrieval += 1
        else:
            rows.append((r.gold_doc_ids, r.doc_ids))
    if no_gold == len(records):
        raise ValueError("gold_doc_ids: không lá nào có tài liệu đúng — không đo được truy hồi")
    n = len(rows)
    return RetrievalMetrics(
        n=n,
        n_no_retrieval=no_retrieval,
        n_no_gold=no_gold,
        recall5=Mean(float(sum(recall_at_k(g, d, k) for g, d in rows)), n),
        mrr5=Mean(float(sum(reciprocal_rank_at_k(g, d, k) for g, d in rows)), n),
        ndcg5=Mean(float(sum(ndcg_at_k(g, d, k) for g, d in rows)), n),
    )


# ---- G5: Full-auto giải tích + FNR theo tình huống (P8 §5.4, §6.1) — dời từ report.py, không đổi kết quả ------------------

type UnitOf = Callable[[PredictionRecord], str]
type Hidden = Literal["all", "only", "except"]


def full_auto_baseline(records: Records) -> list[PredictionRecord]:
    """Full-auto giải tích (P8 §5.4: mọi ca có hành động = AUTO; B17 vẫn chặn khi chạy thật): lá có điểm log 4 (`route ≠ None`)
    → AUTO, `strategy = "full_auto"`, các trường khác giữ nguyên. Đối xứng `manual_baseline`."""
    return [r.model_copy(update={"strategy": "full_auto", **({"route": "AUTO"} if r.route is not None else {})}) for r in records]


@dataclass(frozen=True)
class SituationFnr:
    """FNR theo tình huống: `k` tình huống cần người có ít nhất một câu pred = AUTO, trên `n` tình huống cần người. `upper95` =
    cận trên Clopper–Pearson MỘT phía 95% (vế an toàn §6.5); `lo95`/`hi95` = khoảng hai phía 95%. `n_mixed` = đơn vị có nhãn
    gold lẫn AUTO và không-AUTO (ánh xạ sai hoặc thiếu); `n_leaves` = số lá đã nhãn có route trong phạm vi."""

    k: int
    n: int
    n_leaves: int
    n_mixed: int
    upper95: float | None
    lo95: float | None
    hi95: float | None

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None


def situation_fnr(
    records: Records,
    unit_of: UnitOf | None = None,
    *,
    only_llm: bool = False,
    hidden: Hidden = "all",
) -> SituationFnr:
    """FNR theo tình huống (P8 §6.1): #(tình huống cần người có ≥ 1 câu pred = AUTO) / #(tình huống cần người). Hàm thuần, mẫu =
    lá đã nhãn có `route` (≠ None). `unit_of` ánh xạ lá → mã tình huống (mặc định `family`). Tình huống "cần người" nếu có ≥ 1 lá
    `expected_route ≠ AUTO`. `only_llm` chỉ giữ lá `decided_by = llm` (vế 2 §6.5: tình huống đi qua lớp LLM). `hidden`: `only` =
    chỉ tình huống có lá `hidden_factor = True`, `except` = loại chúng (§6.1 nhóm yếu tố M5 không thấy). Mẫu số 0 → `value` và
    cận None. NGOẠI LỆ quy ước đầu file: `[]` KHÔNG ValueError mà trả k = n = 0 (báo cáo gọi trên phần giao có thể rỗng)."""
    key = unit_of or (lambda r: r.family)
    units: dict[str, list[PredictionRecord]] = {}
    for r in records:
        if r.expected_route is None or r.route is None or (only_llm and r.decided_by != "llm"):
            continue
        units.setdefault(key(r), []).append(r)
    k = n = leaves = mixed = 0
    for rows in units.values():
        is_hidden = any(r.hidden_factor is True for r in rows)
        if (hidden == "only" and not is_hidden) or (hidden == "except" and is_hidden):
            continue
        leaves += len(rows)
        needs = {r.expected_route != "AUTO" for r in rows}
        mixed += len(needs) > 1
        if True not in needs:
            continue
        n += 1
        k += any(r.route == "AUTO" for r in rows)
    if n == 0:
        return SituationFnr(0, 0, leaves, mixed, None, None, None)
    lo, hi = clopper_pearson_two_sided(k, n)
    return SituationFnr(k, n, leaves, mixed, clopper_pearson_upper(k, n), lo, hi)


@dataclass(frozen=True)
class IntentMetrics:
    """P8:375 — Intent macro-F1 trên `n` lá có `gold_intent`. `f1_by_class` gồm `INTENTS` + nhãn gold ngoài tập đó; None = lớp
    vắng cả gold lẫn pred (loại khỏi trung bình, như §6.1). `n_pred_none` = lá có gold mà `intent` None (tính là sai)."""

    n: int
    n_no_gold: int
    n_pred_none: int
    f1_by_class: Mapping[str, float | None]
    macro_f1: float


def intent_quality(records: Records) -> IntentMetrics:
    """P8:375 — Intent macro-F1: pred = `intent` (= `tickets.intent` của lá, chỉnh 4), gold = `gold_intent` [Đề xuất E3]:
    lá `gold_intent` None → loại, đếm `n_no_gold`; không lá nào có → ValueError. `intent` None → đoán sai (cộng #gold lớp gold,
    không cộng #pred lớp nào). F1 lớp = 2·TP / (#pred + #gold) (TP = 0 → 0)."""
    _require(records)
    labelled = [(r.gold_intent, r.intent) for r in records if r.gold_intent is not None]
    if not labelled:
        raise ValueError("gold_intent: không lá nào có nhãn intent — không đo được intent macro-F1")
    tp = Counter(g for g, p in labelled if g == p)
    n_gold = Counter(g for g, _ in labelled)
    n_pred = Counter(p for _, p in labelled if p is not None)
    classes = (*INTENTS, *sorted(set(n_gold) - set(INTENTS)))
    f1: dict[str, float | None] = {
        c: 2 * tp[c] / (n_pred[c] + n_gold[c]) if n_pred[c] + n_gold[c] else None for c in classes
    }
    scored = [v for v in f1.values() if v is not None]
    return IntentMetrics(
        n=len(labelled),
        n_no_gold=len(records) - len(labelled),
        n_pred_none=sum(1 for _, p in labelled if p is None),
        f1_by_class=MappingProxyType(f1),
        macro_f1=sum(scored) / len(scored),
    )
