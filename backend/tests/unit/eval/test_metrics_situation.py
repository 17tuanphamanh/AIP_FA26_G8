"""G5 — Full-auto giải tích và FNR theo tình huống (`app.eval.metrics`, P8 §5.4, §6.1). Chỉ dữ liệu tổng hợp; số tính tay khớp 1e-9.

Bộ U (đơn vị mặc định = họ; `[gold → pred]`, A = AUTO, H = HITL, L = ESCALATE_L2, - = route None, ? = chưa nhãn):
    F1  H → H (rule), H → A (llm)                 cần người, có câu AUTO → bỏ sót
    F2  L → H (rule), ? → A, H → -                 cần người, không AUTO (lá chưa nhãn và lá route None bị bỏ)
    F3  A → A, A → A                               không cần người
    F4  H → A (llm, hidden_factor = true)          cần người, bỏ sót
    F5  A → H, H → H                               cần người, gold lẫn AUTO / không-AUTO (n_mixed)
Tất cả: n = 4 (F1, F2, F4, F5), k = 2 (F1, F4), n_leaves = 2 + 1 + 2 + 1 + 2 = 8, n_mixed = 1.
"""

import itertools
from math import comb
from typing import Any

from app.eval.metrics import SituationFnr, full_auto_baseline, situation_fnr
from app.eval.predictions import PredictionRecord
from app.eval.stats import clopper_pearson_two_sided
from app.risk.decision_math import clopper_pearson_upper
from tests.unit.eval.contract_v11 import V11

TOL = 1e-9
FULL = {"A": "AUTO", "H": "HITL", "L": "ESCALATE_L2", "-": None, "?": None}
_ids = itertools.count()


def leaf(family: str, gold: str, pred: str, *, by: str = "rule", hidden: bool = False) -> PredictionRecord:
    i = next(_ids)
    route = FULL[pred]
    data: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": "hybrid", "split": "test",
        "scenario_id": f"S-{i}", "family": family, "ticket_id": f"T-{i}", "parent_ticket_id": None,
        "expected_route": FULL[gold], "route": route, "decided_by": by if route is not None else None,
        "raw_prob": None, "calibrated_prob": None, "p_method": None,
        "final_state": "S_RESOLVED", "exit_code": None, "close_reason": "resolved_user_confirmed",
        "resolution_path": "auto", "has_approval": False, "clarification_turns": 0,
        "intent": "vpn", "gold_intent": "vpn", "doc_ids": None, "gold_doc_ids": (),
        **V11, "hidden_factor": hidden,
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def bundle() -> list[PredictionRecord]:
    return [
        leaf("F1", "H", "H"), leaf("F1", "H", "A", by="llm"),
        leaf("F2", "L", "H"), leaf("F2", "?", "A"), leaf("F2", "H", "-"),
        leaf("F3", "A", "A"), leaf("F3", "A", "A"),
        leaf("F4", "H", "A", by="llm", hidden=True),
        leaf("F5", "A", "H"), leaf("F5", "H", "H"),
    ]  # fmt: skip


def close(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) <= TOL


def cdf(k: int, n: int, p: float) -> float:
    """P(X ≤ k), X ~ Binomial(n, p)."""
    return sum(comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k + 1))


def test_situation_fnr_hand() -> None:
    f = situation_fnr(bundle())
    assert (f.k, f.n, f.n_leaves, f.n_mixed) == (2, 4, 8, 1)
    assert close(f.value, 0.5)
    assert f.upper95 is not None and close(f.upper95, clopper_pearson_upper(2, 4))
    assert abs(cdf(2, 4, f.upper95) - 0.05) < TOL  # một phía 95%
    assert (f.lo95, f.hi95) == clopper_pearson_two_sided(2, 4)
    assert f.lo95 is not None and abs((1 - cdf(1, 4, f.lo95)) - 0.025) < TOL  # P(X ≥ 2) = 2,5% tại cận dưới


def test_situation_fnr_any_not_all() -> None:
    # F1 có H → H lẫn H → A: "ít nhất một câu AUTO" → vẫn bỏ sót (k = 2, không phải 1)
    f1 = situation_fnr([r for r in bundle() if r.family == "F1"])
    assert (f1.k, f1.n) == (1, 1)
    assert situation_fnr(bundle()).k == 2


def test_situation_fnr_unit_of() -> None:
    f = situation_fnr(bundle(), lambda r: r.scenario_id)  # mỗi lá một đơn vị: cần người = F1×2, F2 L→H, F4, F5 H→H
    assert (f.k, f.n, f.n_mixed) == (2, 5, 0)


def test_situation_fnr_hidden() -> None:
    only = situation_fnr(bundle(), hidden="only")
    assert (only.k, only.n, only.n_leaves) == (1, 1, 1)
    assert only.upper95 == 1.0 and only.hi95 == 1.0 and close(only.lo95, 0.025)  # k = n
    rest = situation_fnr(bundle(), hidden="except")
    assert (rest.k, rest.n, rest.n_leaves, rest.n_mixed) == (1, 3, 7, 1)


def test_situation_fnr_only_llm() -> None:
    f = situation_fnr(bundle(), only_llm=True)  # chỉ F1 (H → A llm), F4
    assert (f.k, f.n, f.n_leaves) == (2, 2, 2)
    assert f.upper95 == 1.0


def test_situation_fnr_k0_and_n0() -> None:
    f2 = situation_fnr([r for r in bundle() if r.family == "F2"])  # k = 0
    assert (f2.k, f2.n, f2.n_leaves) == (0, 1, 1)
    assert f2.lo95 == 0.0 and close(f2.upper95, 0.95) and close(f2.hi95, 0.975)
    f3 = situation_fnr([r for r in bundle() if r.family == "F3"])  # không tình huống cần người
    assert (f3.k, f3.n, f3.n_leaves, f3.value, f3.upper95, f3.lo95, f3.hi95) == (0, 0, 2, None, None, None, None)
    assert situation_fnr([]) == SituationFnr(0, 0, 0, 0, None, None, None)  # ngoại lệ quy ước: rỗng không ValueError


def test_full_auto_baseline_hand() -> None:
    src = [leaf("F1", "A", "A"), leaf("F1", "H", "H"), leaf("F2", "L", "L"), leaf("F2", "H", "-")]
    out = full_auto_baseline(src)
    assert [r.route for r in out] == ["AUTO", "AUTO", "AUTO", None]
    assert {r.strategy for r in out} == {"full_auto"}
    keep = {"route", "strategy"}
    assert [r.model_dump(exclude=keep) for r in out] == [r.model_dump(exclude=keep) for r in src]
    assert [r.route for r in src] == ["AUTO", "HITL", "ESCALATE_L2", None] and {r.strategy for r in src} == {"hybrid"}
