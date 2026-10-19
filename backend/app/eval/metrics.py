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
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Protocol, cast

import numpy as np

from app.db.models import EXIT_CODES, INTENTS
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
