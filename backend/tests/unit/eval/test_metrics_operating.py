"""G1 — chỉ số theo ROUTE có trọng số theo phân bố vận hành (`app.eval.metrics.operating_metrics`; P8 §6.1, §6.2; chốt #32 18/10:
(2) `l2` theo route khác `escalation` theo log 8, (4) số chính RQ1 = chi phí không trọng số, (5) khối lượng duyệt = chỉ HITL).
Chỉ dữ liệu tổng hợp; số tính tay khớp 1e-9.

Bộ D (`DEFAULT_COST`) — nhóm theo GOLD, n_g = lá đã nhãn có route:
    routine   (gold AUTO)  route AUTO, AUTO, AUTO, HITL  → cost (0+0+0+1)/4 = 0,25 · AUTO 3/4 · HITL 1/4 · L2 0/4
    approval  (gold HITL)  route AUTO, HITL              → cost (10+1)/2 = 5,5   · AUTO 1/2 · HITL 1/2 · L2 0/2
    sensitive (gold L2)    route HITL, L2                → cost (6+3)/2 = 4,5    · AUTO 0/2 · HITL 1/2 · L2 1/2
    + 1 lá gold AUTO không tới M5 (route None) — ngoài mẫu số.
Không trọng số: 21/8 = 2,625.
    mix       cost                          automation      review              l2
    70/20/10  .7·.25+.2·5.5+.1·4.5 = 1,725  .525+.1 = .625  .175+.1+.05 = .325  .05
    60/30/10  .15+1.65+.45 = 2,25           .45+.15 = .60   .15+.15+.05 = .35   .05
    80/15/5   .2+.825+.225 = 1,25           .6+.075 = .675  .2+.075+.025 = .30  .025
"""

import itertools
import math
from dataclasses import FrozenInstanceError, fields
from inspect import signature
from typing import Any, Final

import pytest
from app.eval.metrics import (
    GROUPS,
    EfficiencyMetrics,
    OperatingPoint,
    WeightedRate,
    calibration_scores,
    efficiency,
    escalation_weighted,
    mean_route_cost,
    operating_metrics,
)
from app.eval.predictions import PredictionRecord
from app.eval.stats import family_bootstrap_ci
from app.risk.decision_math import cost_matrix_for_ratio
from tests.unit.eval.contract_v11 import V11

TOL = 1e-9
L2: Final = "ESCALATE_L2"
_ids = itertools.count()


def leaf(
    gold: str | None,
    route: str | None,
    *,
    exit_code: str | None = None,
    by: str | None = "rule",
    strategy: str = "hybrid",
) -> PredictionRecord:
    """Lá tổng hợp. `route=None` = không tới M5 → mọi trường rủi ro None. `gold=None` = chưa nhãn."""
    i = next(_ids)
    data: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": strategy, "split": "test",
        "scenario_id": f"S-{i}", "family": f"F-{i}", "ticket_id": f"T-{i}", "parent_ticket_id": None,
        "expected_route": gold, "route": route, "decided_by": by if route is not None else None,
        "raw_prob": None, "calibrated_prob": None, "p_method": None,
        "final_state": "S_RESOLVED", "exit_code": exit_code, "close_reason": None, "resolution_path": None,
        "has_approval": False, "clarification_turns": 0,
        "intent": "vpn", "gold_intent": "vpn", "doc_ids": None, "gold_doc_ids": (),
        **V11,
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def d_set() -> list[PredictionRecord]:
    return [
        leaf("AUTO", "AUTO"), leaf("AUTO", "AUTO"), leaf("AUTO", "AUTO"), leaf("AUTO", "HITL"),
        leaf("HITL", "AUTO"), leaf("HITL", "HITL"),
        leaf(L2, "HITL"), leaf(L2, L2),
        leaf("AUTO", None),
    ]  # fmt: skip


def no_sensitive() -> list[PredictionRecord]:
    return [r for r in d_set() if r.expected_route != L2]


def close(a: float | None, b: float) -> bool:
    return a is not None and math.isclose(a, b, rel_tol=0, abs_tol=TOL)


def values(p: OperatingPoint) -> tuple[float | None, ...]:
    return (p.cost.value, p.automation.value, p.review.value, p.l2.value)


HAND: Final = {
    "70/20/10": (1.725, 0.625, 0.325, 0.05),
    "60/30/10": (2.25, 0.60, 0.35, 0.05),
    "80/15/5": (1.25, 0.675, 0.30, 0.025),
}


def points(records: list[PredictionRecord], **kw: Any) -> dict[str, OperatingPoint]:
    om = operating_metrics(records, **kw)
    return {"70/20/10": om.main, **om.sensitivity}


# ---- số chính + bảng tính tay -----------------------------------------------------------------------------------------


def test_operating_plain_cost_is_main() -> None:
    # Chốt 4: số chính RQ1 = chi phí KHÔNG trọng số (§6.1) = mean_route_cost = 21/8.
    om = operating_metrics(d_set())
    assert om.cost == mean_route_cost(d_set())
    assert (om.cost.total, om.cost.n) == (21.0, 8)
    assert close(om.cost.value, 2.625)
    assert not close(om.main.cost.value, 2.625)  # bản trọng số (1,725) là số phụ, khác số chính


def test_operating_weighted_hand() -> None:
    om = operating_metrics(d_set())
    assert set(om.sensitivity) == {"60/30/10", "80/15/5"}
    assert dict(om.main.mix) == {"routine": 0.7, "approval": 0.2, "sensitive": 0.1}
    assert dict(om.sensitivity["80/15/5"].mix) == {"routine": 0.8, "approval": 0.15, "sensitive": 0.05}
    for name, p in points(d_set()).items():
        got = values(p)
        assert all(close(g, e) for g, e in zip(got, HAND[name], strict=True)), (name, got)
        assert p.cost.missing_groups == p.automation.missing_groups == p.review.missing_groups == p.l2.missing_groups == ()


def test_operating_by_group_hand() -> None:
    p = operating_metrics(d_set()).main
    assert {g: (m.total, m.n) for g, m in p.cost.by_group.items()} == {
        "routine": (1.0, 4), "approval": (11.0, 2), "sensitive": (9.0, 2),
    }  # fmt: skip
    assert {g: (r.k, r.n) for g, r in p.automation.by_group.items()} == {"routine": (3, 4), "approval": (1, 2), "sensitive": (0, 2)}
    assert {g: (r.k, r.n) for g, r in p.review.by_group.items()} == {"routine": (1, 4), "approval": (1, 2), "sensitive": (1, 2)}
    assert {g: (r.k, r.n) for g, r in p.l2.by_group.items()} == {"routine": (0, 4), "approval": (0, 2), "sensitive": (1, 2)}


def test_operating_group_by_gold() -> None:
    # Mọi lá route AUTO: nhóm theo gold vẫn (4, 2, 2) → cost 70/20/10 = .7·0 + .2·10 + .1·20 = 4,0; automation 1,0.
    # (Nhóm theo pred sẽ dồn hết vào routine → approval/sensitive thiếu → None.)
    rows = [leaf(r.expected_route, "AUTO" if r.route is not None else None) for r in d_set()]
    p = operating_metrics(rows).main
    assert {g: r.n for g, r in p.automation.by_group.items()} == {"routine": 4, "approval": 2, "sensitive": 2}
    assert close(p.cost.value, 4.0)
    assert close(p.automation.value, 1.0)
    assert p.automation.missing_groups == ()


def test_operating_excludes_route_none() -> None:
    om = operating_metrics(d_set())
    assert om.n_m5 == 8  # 9 lá, 1 lá route None
    assert om.main.automation.by_group["routine"].n == 4  # 5 lá gold AUTO, 1 không tới M5
    assert om.main.cost.by_group["routine"].n == 4


# ---- lá chưa nhãn (G2-Q22) ---------------------------------------------------------------------------------------------


def unlabeled(*routes: str | None) -> list[PredictionRecord]:
    return [leaf(None, r) for r in routes]


def test_operating_skips_unlabeled() -> None:
    base = operating_metrics(d_set())
    om = operating_metrics(d_set() + unlabeled("AUTO", "HITL"))
    assert om.n_unlabeled == 2 and base.n_unlabeled == 0
    assert om.n_m5 == 8
    assert om.cost == base.cost
    for name, p in points(d_set() + unlabeled("AUTO", "HITL")).items():
        assert values(p) == values({"70/20/10": base.main, **base.sensitivity}[name])
        assert p.cost.n_unlabeled == p.automation.n_unlabeled == p.review.n_unlabeled == p.l2.n_unlabeled == 2


def test_operating_all_unlabeled() -> None:
    om = operating_metrics(unlabeled("AUTO", "HITL", None))
    assert (om.n_m5, om.n_unlabeled, om.cost.value) == (0, 3, None)
    for p in points(unlabeled("AUTO", "HITL", None)).values():
        assert values(p) == (None, None, None, None)
        assert p.cost.missing_groups == p.automation.missing_groups == GROUPS


# ---- nhóm rỗng, rỗng ---------------------------------------------------------------------------------------------------


def test_operating_empty_group() -> None:
    # Không lá gold L2 → sensitive rỗng → mọi bản trọng số None + tên nhóm (Q5), KHÔNG chuẩn hoá lại
    # (chuẩn hoá lại cost: (.7·.25 + .2·5.5)/.9 ≈ 1,416666666667 — sai). Số chính vẫn có: 12/6 = 2,0.
    om = operating_metrics(no_sensitive())
    for p in points(no_sensitive()).values():
        assert values(p) == (None, None, None, None)
        assert p.cost.missing_groups == p.automation.missing_groups == p.review.missing_groups == p.l2.missing_groups == (
            "sensitive",
        )
    assert {g: (m.total, m.n) for g, m in om.main.cost.by_group.items()} == {
        "routine": (1.0, 4), "approval": (11.0, 2), "sensitive": (0.0, 0),
    }  # fmt: skip
    assert close(om.cost.value, 2.0)


def test_operating_group_all_route_none() -> None:
    # Nhóm sensitive CÓ lá nhưng mọi lá không tới M5 → n = 0 → missing, không ValueError.
    rows = no_sensitive() + [leaf(L2, None), leaf(L2, None)]
    p = operating_metrics(rows).main
    assert p.cost.missing_groups == p.l2.missing_groups == ("sensitive",)
    assert p.l2.by_group["sensitive"].n == 0 and p.cost.by_group["sensitive"].n == 0
    assert p.l2.value is None


def test_operating_all_route_none() -> None:
    om = operating_metrics([leaf("AUTO", None), leaf("HITL", None), leaf(L2, None)])
    assert (om.n_m5, om.cost.value) == (0, None)
    assert values(om.main) == (None, None, None, None)
    assert om.main.review.missing_groups == GROUPS


def test_operating_empty_records_raises() -> None:
    with pytest.raises(ValueError, match="rỗng"):
        operating_metrics([])


def test_operating_single_leaf_groups() -> None:
    # Mỗi nhóm 1 lá đúng: cost .7·0 + .2·1 + .1·3 = 0,5; automation 0,7; review 0,2; l2 0,1.
    p = operating_metrics([leaf("AUTO", "AUTO"), leaf("HITL", "HITL"), leaf(L2, L2)]).main
    assert all(close(g, e) for g, e in zip(values(p), (0.5, 0.7, 0.2, 0.1), strict=True))


def test_operating_shares_sum_to_one() -> None:
    for p in points(d_set()).values():
        assert close(sum(v for v in (p.automation.value, p.review.value, p.l2.value) if v is not None), 1.0)


# ---- chốt 2, 5: review chỉ HITL; l2 ≠ escalation -------------------------------------------------------------------------


def test_review_counts_hitl_only() -> None:
    # Không lá nào route HITL → review = 0 (L2 không tính vào khối lượng duyệt); l2 = .2·1 + .1·1 = 0,3.
    p = operating_metrics([leaf("AUTO", "AUTO"), leaf("HITL", L2), leaf(L2, L2)]).main
    assert p.review.value == 0.0
    assert all(r.k == 0 for r in p.review.by_group.values())
    assert close(p.l2.value, 0.3)


def test_l2_is_not_escalation() -> None:
    # l2 theo ROUTE: routine 0/1, approval 1/1, sensitive 1/1 → .2 + .1 = 0,3.
    # escalation theo log 8 (exit_code): routine 1/1 (E5), approval 0/1, sensitive 1/1 (E1) → .7 + .1 = 0,8.
    rows = [leaf("AUTO", "AUTO", exit_code="E5"), leaf("HITL", L2), leaf(L2, L2, exit_code="E1")]
    assert close(operating_metrics(rows).main.l2.value, 0.3)
    assert close(efficiency(rows).escalation_weighted.value, 0.8)
    assert "escalation" not in {f.name for f in fields(OperatingPoint)}
    assert "l2" not in {f.name for f in fields(EfficiencyMetrics)}


# ---- tham số -------------------------------------------------------------------------------------------------------------


def test_operating_cost_param() -> None:
    # ratio 20: approval (20+1)/2 = 10,5 → 70/20/10: .175 + 2,1 + .45 = 2,725; 60/30/10: .15 + 3,15 + .45 = 3,75;
    # 80/15/5: .2 + 1,575 + .225 = 2,0. Số chính: (1 + 21 + 9)/8 = 3,875. Tỉ lệ route không đổi.
    cm = cost_matrix_for_ratio(20)
    om = operating_metrics(d_set(), cost=cm)
    assert close(om.cost.value, 3.875)
    for name, expected in {"70/20/10": 2.725, "60/30/10": 3.75, "80/15/5": 2.0}.items():
        p = points(d_set(), cost=cm)[name]
        assert close(p.cost.value, expected), name
        assert values(p)[1:] == pytest.approx(HAND[name][1:], abs=TOL)


@pytest.mark.parametrize(
    "mix",
    [
        {"routine": 0.8, "approval": 0.2},
        {"routine": 0.7, "approval": 0.2, "sensitive": 0.1, "other": 0.0},
        {"routine": 0.9, "approval": 0.2, "sensitive": -0.1},
        {"routine": 0.7, "approval": 0.2, "sensitive": 0.2},
        {"routine": math.nan, "approval": 0.2, "sensitive": 0.1},
    ],
    ids=["thieu-nhom", "thua-nhom", "am", "tong-1.1", "nan"],
)
def test_operating_mix_validated(mix: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="mix"):
        operating_metrics(d_set(), mix=mix)
    with pytest.raises(ValueError, match="mix"):
        operating_metrics(d_set(), sensitivity_mixes={"x": mix})


def test_operating_full_auto_counted() -> None:
    # Full-auto: route AUTO, decided_by None → vào automation/cost; ECE/Brier chỉ lọc decided_by = llm → None.
    rows = [leaf(g, "AUTO", by=None, strategy="full_auto") for g in ("AUTO", "HITL", L2)]
    p = operating_metrics(rows).main
    assert close(p.automation.value, 1.0)
    assert close(p.cost.value, 4.0)  # .7·0 + .2·10 + .1·20
    assert calibration_scores(rows, "raw") is None


def test_operating_frozen() -> None:
    src = {"routine": 0.7, "approval": 0.2, "sensitive": 0.1}
    om = operating_metrics(d_set(), mix=src)
    src["routine"] = 0.0
    assert om.main.mix["routine"] == 0.7 and om.main.cost.mix["routine"] == 0.7
    with pytest.raises(FrozenInstanceError):
        om.n_m5 = 0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        om.main.cost.value = 0.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        om.main.cost.by_group["routine"] = om.cost  # type: ignore[index]
    with pytest.raises(TypeError):
        om.sensitivity["x"] = om.main  # type: ignore[index]


def test_operating_bootstrap_compatible() -> None:
    # Dùng được làm `statistic` của bootstrap theo họ; lần rút không có họ gold L2 → None → đếm n_undefined.
    ci = family_bootstrap_ci(d_set(), lambda rs: operating_metrics(rs).main.cost.value, n_boot=50)
    assert close(ci.point, 1.725)
    assert ci.n_undefined > 0
    assert ci.n_used + ci.n_undefined == 50


# ---- G1 không đổi efficiency() / escalation_weighted() (chốt 2) ---------------------------------------------------------


def test_efficiency_untouched() -> None:
    assert [f.name for f in fields(EfficiencyMetrics)] == [
        "n_leaves", "automation", "escalation", "exit_codes", "escalation_weighted", "escalation_sensitivity",
        "deflection", "clarification", "one_turn",
    ]  # fmt: skip
    assert [f.name for f in fields(WeightedRate)] == ["mix", "by_group", "missing_groups", "value", "n_unlabeled"]
    assert list(signature(escalation_weighted).parameters) == ["records", "mix"]
    assert list(signature(efficiency).parameters) == ["records", "mix", "sensitivity_mixes"]
    # escalation_weighted theo log 8 vẫn gồm lá không tới M5: routine 1/5 (E2 ở lá route None), approval 0/2, sensitive 0/2.
    rows = d_set()
    rows[-1] = leaf("AUTO", None, exit_code="E2")
    w = escalation_weighted(rows, {"routine": 0.7, "approval": 0.2, "sensitive": 0.1})
    assert {g: (r.k, r.n) for g, r in w.by_group.items()} == {"routine": (1, 5), "approval": (0, 2), "sensitive": (0, 2)}
    assert close(w.value, 0.14)
