"""S4 T29 — bootstrap theo họ kịch bản (P8 §6.4, `app.eval.stats`). Chỉ dữ liệu tổng hợp.

Thống kê dùng trong test: tỉ lệ lá có `exit_code` (`esc`) — đơn giản để tính tay.
"""

import itertools
import math
import random
from collections import Counter
from collections.abc import Sequence
from typing import Any

import pytest
from app.eval.metrics import safety
from app.eval.predictions import PredictionRecord
from app.eval.stats import (
    BOOTSTRAP_N,
    SEED,
    family_bootstrap_ci,
    paired_family_bootstrap_diff,
    percentile_interval,
)
from tests.unit.eval.contract_v11 import V11

_ids = itertools.count()


def leaf(
    family: str,
    escalated: bool,
    *,
    gold: str = "HITL",
    route: str | None = "HITL",
    scenario: str | None = None,
    split: str = "test",
) -> PredictionRecord:
    i = next(_ids)
    data: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": "hybrid", "split": split,
        "scenario_id": scenario or f"S-{i}", "family": family, "ticket_id": f"T-{i:05d}", "parent_ticket_id": None,
        "expected_route": gold, "route": route, "decided_by": "rule" if route is not None else None,
        "raw_prob": None, "calibrated_prob": None, "p_method": None,
        "final_state": "S_ESCALATED" if escalated else "S_RESOLVED", "exit_code": "E1" if escalated else None,
        "close_reason": None, "resolution_path": None, "has_approval": False, "clarification_turns": 0,
        "intent": "vpn", "gold_intent": "vpn", "doc_ids": None, "gold_doc_ids": (),
        **V11,
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def esc(rs: Sequence[PredictionRecord]) -> float:
    return sum(1 for r in rs if r.exit_code is not None) / len(rs)


class Recorder:
    """Bọc thống kê: ghi lại kích thước mẫu, đếm lá theo họ và giá trị trả về của từng lần gọi."""

    def __init__(self, fn: Any = esc) -> None:
        self.fn = fn
        self.sizes: list[int] = []
        self.family_counts: list[Counter[str]] = []
        self.values: list[float | None] = []

    def __call__(self, rs: Sequence[PredictionRecord]) -> float | None:
        self.sizes.append(len(rs))
        self.family_counts.append(Counter(r.family for r in rs))
        v = self.fn(rs)
        self.values.append(v)
        return v


def six_families() -> list[PredictionRecord]:
    """F1 3 lá (1 esc), F2 2 (2), F3 4 (0), F4 1 (1), F5 2 (1), F6 3 (3) — 15 lá, 8 esc → point 8/15."""
    spec = {"F1": (3, 1), "F2": (2, 2), "F3": (4, 0), "F4": (1, 1), "F5": (2, 1), "F6": (3, 3)}
    return [leaf(f, i < k) for f, (n, k) in spec.items() for i in range(n)]


# ---- phân vị ---------------------------------------------------------------------------------------------------------


def test_percentile_hand() -> None:
    # Dãy [10, 0, 4, 2, 8, 6] → sắp [0, 2, 4, 6, 8, 10], N = 6. Nội suy tuyến tính (numpy "linear"): vị trí = q·(N−1).
    #   2,5%  → 0,025·5 = 0,125 → 0 + 0,125·(2 − 0) = 0,25
    #   97,5% → 0,975·5 = 4,875 → 8 + 0,875·(10 − 8) = 9,75
    # level 0,90 → 5% / 95%: vị trí 0,25 → 0,5; vị trí 4,75 → 8 + 0,75·2 = 9,5
    assert percentile_interval([10, 0, 4, 2, 8, 6], 0.95) == pytest.approx((0.25, 9.75), abs=1e-12)
    assert percentile_interval([10, 0, 4, 2, 8, 6], 0.90) == pytest.approx((0.5, 9.5), abs=1e-12)
    # 1..10: 2,5% → vị trí 0,225 → 1,225; 97,5% → vị trí 8,775 → 9,775
    assert percentile_interval(list(range(1, 11)), 0.95) == pytest.approx((1.225, 9.775), abs=1e-12)
    assert percentile_interval([0.4], 0.95) == (0.4, 0.4)


# ---- family_bootstrap_ci ------------------------------------------------------------------------------------------------


def test_defaults() -> None:
    assert BOOTSTRAP_N == 2000  # P8:379, P8:399
    assert SEED == 20260925  # P8:399
    ci = family_bootstrap_ci(six_families(), esc)
    assert (ci.n_boot, ci.seed, ci.level, ci.n_families) == (2000, 20260925, 0.95, 6)
    assert ci == family_bootstrap_ci(six_families(), esc, n_boot=2000, seed=20260925, level=0.95)


def test_bootstrap_deterministic_seed() -> None:
    a, b, c = Recorder(), Recorder(), Recorder()
    ci_a = family_bootstrap_ci(six_families(), a, n_boot=300, seed=7)
    ci_b = family_bootstrap_ci(six_families(), b, n_boot=300, seed=7)
    family_bootstrap_ci(six_families(), c, n_boot=300, seed=8)
    assert a.values == b.values and ci_a == ci_b  # cùng seed → cùng dãy, cùng khoảng
    assert a.values != c.values  # khác seed → khác dãy


def test_bootstrap_input_order_invariant() -> None:
    rows = six_families()
    shuffled = rows[:]
    random.Random(1).shuffle(shuffled)
    a, b = Recorder(), Recorder()
    ci_a = family_bootstrap_ci(rows, a, n_boot=300, seed=11)
    ci_b = family_bootstrap_ci(shuffled, b, n_boot=300, seed=11)
    assert a.values == b.values
    assert ci_a == ci_b


def test_bootstrap_resamples_families() -> None:
    # Họ A: 10 lá đều esc; họ B: 1 lá không esc. Mỗi lần rút 2 họ CÓ LẶP, mang theo mọi lá của họ:
    #   AA (xác suất 1/4) → 20 lá, esc 20/20 = 1,0;  AB/BA (1/2) → 11 lá, 10/11;  BB (1/4) → 2 lá, 0
    # → phân vị 2,5% = 0 (25% khối lượng ở 0), 97,5% = 1,0 → khoảng [0; 1].
    # (Lấy mẫu theo lá — 11 lá rút có lặp — luôn ra 11 lá, hiếm khi chạm 0 → khoảng hẹp giả tạo.)
    rows = [leaf("A", True) for _ in range(10)] + [leaf("B", False)]
    rec = Recorder()
    ci = family_bootstrap_ci(rows, rec)
    assert len(rec.sizes) == ci.n_boot + 1 and rec.sizes[0] == 11  # lần gọi đầu = dữ liệu gốc
    boot_sizes, boot_counts = rec.sizes[1:], rec.family_counts[1:]
    assert ci.n_families == 2
    assert set(boot_sizes) <= {20, 11, 2}
    assert {20, 2} <= set(boot_sizes)
    # mỗi lần rút đúng n_families = 2 họ, mỗi họ trọn vẹn (A luôn đủ bội số 10 lá)
    assert all(c["A"] % 10 == 0 and c["A"] // 10 + c["B"] == 2 for c in boot_counts)
    assert ci.lo == 0.0 and ci.hi == 1.0
    assert math.isclose(ci.point or -1, 10 / 11)


def test_bootstrap_single_family() -> None:
    # 1 họ, 5 lá, 2 esc → mọi lần rút đều đúng họ đó → mọi giá trị 0,4 → lo = hi = point = 0,4 (độ rộng 0).
    rows = [leaf("F", i < 2) for i in range(5)]
    ci = family_bootstrap_ci(rows, esc)
    assert (ci.n_families, ci.n_used, ci.n_undefined) == (1, 2000, 0)
    assert ci.point == ci.lo == ci.hi == 0.4


def test_bootstrap_undefined_counted() -> None:
    # Thống kê None khi mẫu không có họ A. A: 2 lá esc, B: 1 lá, C: 1 lá → P(không A) = (2/3)^3 ≈ 0,296.
    def needs_a(rs: Sequence[PredictionRecord]) -> float | None:
        return esc(rs) if any(r.family == "A" for r in rs) else None

    rows = [leaf("A", True), leaf("A", True), leaf("B", False), leaf("C", False)]
    rec = Recorder(needs_a)
    ci = family_bootstrap_ci(rows, rec, n_boot=500, seed=3)
    assert len(rec.values) == 501  # 1 lần trên dữ liệu gốc (đầu tiên) + 500 lần rút
    boot = rec.values[1:]
    assert ci.n_undefined == sum(1 for v in boot if v is None) > 0
    assert ci.n_used + ci.n_undefined == 500
    assert ci.lo is not None and ci.lo > 0  # lần None bị bỏ, không coi là 0


def test_all_undefined() -> None:
    ci = family_bootstrap_ci([leaf("A", True), leaf("B", False)], lambda rs: None, n_boot=50)
    assert ci.point is None and ci.lo is None and ci.hi is None
    assert (ci.n_used, ci.n_undefined) == (0, 50)


def test_point_is_on_original_data() -> None:
    # Bộ A/B ở trên: point = esc(dữ liệu gốc) = 10/11; trung bình các lần rút ≈ 0,25·1 + 0,5·10/11 + 0 ≈ 0,70 — khác.
    rows = [leaf("A", True) for _ in range(10)] + [leaf("B", False)]
    ci = family_bootstrap_ci(rows, esc, n_boot=400, seed=5)
    assert ci.point == esc(rows) == 10 / 11


def test_bootstrap_with_metric_none() -> None:
    # Dùng thẳng chỉ số §6.1: FNR None khi mẫu không có ca cần người → bỏ, đếm.
    rows = [leaf("A", False, gold="HITL", route="AUTO"), leaf("B", False, gold="AUTO", route="AUTO")]
    ci = family_bootstrap_ci(rows, lambda rs: safety(rs).fnr.value, n_boot=200, seed=2)
    assert ci.point == 1.0
    assert ci.n_undefined > 0 and ci.n_used + ci.n_undefined == 200
    assert ci.lo == ci.hi == 1.0


# ---- paired_family_bootstrap_diff ----------------------------------------------------------------------------------------


def paired_sets() -> tuple[list[PredictionRecord], list[PredictionRecord]]:
    """4 họ × 2 lá. Esc theo họ: A = (2, 1, 1, 2), B = (1, 0, 0, 1) → mỗi họ A hơn B đúng 1 lá esc.
    Gốc: A 6/8 = 0,75; B 2/8 = 0,25; hiệu 0,5. Cùng dãy họ → mọi lần rút k_A − k_B = 4 trên 8 lá → hiệu = 0,5 đúng.
    A và B cùng tập scenario_id (`<họ>-<i>`) và cùng split — hai lần chạy trên cùng kịch bản."""
    fams = ("f1", "f2", "f3", "f4")
    a = [leaf(f, i < k, scenario=f"{f}-{i}") for f, k in zip(fams, (2, 1, 1, 2), strict=True) for i in range(2)]
    b = [leaf(f, i < k, scenario=f"{f}-{i}") for f, k in zip(fams, (1, 0, 0, 1), strict=True) for i in range(2)]
    return a, b


def test_paired_identical_zero_width() -> None:
    rows = six_families()
    d = paired_family_bootstrap_diff(rows, rows, esc, n_boot=300)
    assert d.point == d.lo == d.hi == 0.0
    assert d.contains_zero is True
    assert (d.n_used, d.n_undefined, d.n_families) == (300, 0, 6)


def test_paired_same_family_sequence() -> None:
    # Cùng dãy họ cho A và B → hiệu luôn 0,5 → lo = hi = 0,5, không chứa 0.
    # (Hai dãy độc lập: A* và B* rút họ khác nhau → hiệu dao động, khoảng rộng và chứa giá trị khác 0,5.)
    a, b = paired_sets()
    d = paired_family_bootstrap_diff(a, b, esc)
    assert d.point == 0.5
    assert d.lo == d.hi == 0.5
    assert d.contains_zero is False
    assert (d.n_boot, d.seed, d.level) == (2000, 20260925, 0.95)


def test_paired_input_order_invariant() -> None:
    a, b = paired_sets()
    rb = b[::-1]
    assert paired_family_bootstrap_diff(a, b, esc, n_boot=200) == paired_family_bootstrap_diff(a, rb, esc, n_boot=200)


def test_paired_undefined_counted() -> None:
    # Thống kê None khi mẫu thiếu họ f1 (cùng dãy họ → A và B cùng thiếu) → bỏ, đếm.
    def needs_f1(rs: Sequence[PredictionRecord]) -> float | None:
        return esc(rs) if any(r.family == "f1" for r in rs) else None

    a, b = paired_sets()
    d = paired_family_bootstrap_diff(a, b, needs_f1, n_boot=400, seed=9)
    assert d.n_undefined > 0 and d.n_used + d.n_undefined == 400
    assert d.lo == d.hi == 0.5


def test_paired_family_mismatch() -> None:
    a, b = paired_sets()
    with pytest.raises(ValueError, match="họ"):
        paired_family_bootstrap_diff(a, [*b, leaf("f5", True)], esc, n_boot=10)
    with pytest.raises(ValueError, match="họ"):
        paired_family_bootstrap_diff(a, b[:6], esc, n_boot=10)  # thiếu f4


def test_paired_scenario_mismatch() -> None:
    # Cùng tập họ nhưng B thay 1 kịch bản của f2 bằng kịch bản khác cùng họ (vd một lần chạy rơi ticket) → lỗi.
    a, b = paired_sets()
    swapped = [*b[:2], b[2].model_copy(update={"scenario_id": "S-khac"}), *b[3:]]
    assert {r.family for r in swapped} == {r.family for r in a}
    with pytest.raises(ValueError, match="scenario_id") as e:
        paired_family_bootstrap_diff(a, swapped, esc, n_boot=10)
    assert "S-khac" not in str(e.value) and "f2-0" not in str(e.value)  # không in giá trị
    with pytest.raises(ValueError, match="scenario_id"):
        paired_family_bootstrap_diff(a, b[:-1], esc, n_boot=10)  # f4 còn 1 lá: cùng họ, thiếu 1 kịch bản


def test_paired_split_mismatch() -> None:
    # Cùng họ, cùng scenario_id, khác split → lỗi (không so số calibration với số test).
    a, b = paired_sets()
    b_cal = [r.model_copy(update={"split": "calibration"}) for r in b]
    with pytest.raises(ValueError, match="split") as e:
        paired_family_bootstrap_diff(a, b_cal, esc, n_boot=10)
    assert "calibration" not in str(e.value) and "test" not in str(e.value)  # không in giá trị


# ---- tham số sai -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [({"n_boot": 0}, "n_boot"), ({"n_boot": -1}, "n_boot"), ({"n_boot": True}, "n_boot"), ({"n_boot": 2.0}, "n_boot"),
     ({"level": 1.0}, "level"), ({"level": 0.0}, "level"), ({"level": 1.5}, "level"), ({"level": math.nan}, "level"),
     ({"seed": "x"}, "seed")],
)  # fmt: skip
def test_bad_args_raise(kwargs: dict[str, Any], match: str) -> None:
    rows = six_families()
    with pytest.raises(ValueError, match=match):
        family_bootstrap_ci(rows, esc, **kwargs)
    with pytest.raises(ValueError, match=match):
        paired_family_bootstrap_diff(rows, rows, esc, **kwargs)


def test_empty_records_raise() -> None:
    rows = six_families()
    with pytest.raises(ValueError, match="rỗng"):
        family_bootstrap_ci([], esc)
    with pytest.raises(ValueError, match="rỗng"):
        paired_family_bootstrap_diff([], rows, esc)
    with pytest.raises(ValueError, match="rỗng"):
        paired_family_bootstrap_diff(rows, [], esc)
    with pytest.raises(ValueError, match="rỗng"):
        percentile_interval([], 0.95)
