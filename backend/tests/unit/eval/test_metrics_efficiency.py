"""S3 T29 — chỉ số hiệu quả và trải nghiệm P8 §6.2 (`app.eval.metrics`). Mẫu số = MỌI lá (P8:342), kể cả lá không tới M5
(Q7). Chỉ dữ liệu tổng hợp; số tính tay khớp 1e-9.

Bộ A (8 lá) — cột: gold, route, final_state, has_approval, exit_code, close_reason, resolution_path, clarification_turns
    1  AUTO  AUTO  S_RESOLVED   F  —   resolved_user_confirmed    auto       0   tự động, một lượt
    2  AUTO  AUTO  S_RESOLVED   F  —   resolved_auto_timeout_48h  auto       0   tự động (close khác → không "một lượt")
    3  HITL  HITL  S_RESOLVED   T  —   resolved_user_confirmed    approved   1   qua duyệt
    4  HITL  HITL  S_RESOLVED   F  E5  resolved_after_escalation  escalated  2   có exit_code
    5  L2    L2    S_ESCALATED  F  E1  —                          escalated  0
    6  AUTO  —     S_RESOLVED   F  —   resolved_user_confirmed    deflected  0   không tới M5: tự động, deflect, một lượt
    7  AUTO  —     S_BLOCKED    F  E0  blocked_injection_detected —          0   không tới M5, E0
    8  HITL  —     S_ESCALATED  F  E4  —                          escalated  3   không tới M5
"""

import itertools
import math
from typing import Any

import pytest
from app.db.models import CLOSE_REASONS, EXIT_CODES, FINAL_STATES, RESOLUTION_PATHS
from app.eval.metrics import (
    DEFLECTED_PATH,
    GROUPS,
    ONE_TURN_CLOSE_REASON,
    OPERATING_MIX,
    RESOLVED_STATE,
    SENSITIVITY_MIXES,
    check_mix,
    efficiency,
    escalation_weighted,
    n3_group,
)
from app.eval.predictions import PredictionRecord

TOL = 1e-9
_ids = itertools.count()


def leaf(
    gold: str,
    route: str | None = None,
    *,
    state: str | None = "S_RESOLVED",
    approval: bool = False,
    exit_code: str | None = None,
    close: str | None = None,
    path: str | None = None,
    turns: int = 0,
) -> PredictionRecord:
    i = next(_ids)
    data: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": "hybrid", "split": "test",
        "scenario_id": f"S-{i}", "family": f"F-{i}", "ticket_id": f"T-{i}", "parent_ticket_id": None,
        "expected_route": gold, "route": route, "decided_by": "rule" if route is not None else None,
        "raw_prob": None, "calibrated_prob": None, "p_method": None,
        "final_state": state, "exit_code": exit_code, "close_reason": close, "resolution_path": path,
        "has_approval": approval, "clarification_turns": turns,
        "intent": "vpn", "gold_intent": "vpn", "doc_ids": None, "gold_doc_ids": (),
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def a_set() -> list[PredictionRecord]:
    uc = "resolved_user_confirmed"
    return [
        leaf("AUTO", "AUTO", close=uc, path="auto"),
        leaf("AUTO", "AUTO", close="resolved_auto_timeout_48h", path="auto"),
        leaf("HITL", "HITL", approval=True, close=uc, path="approved", turns=1),
        leaf("HITL", "HITL", exit_code="E5", close="resolved_after_escalation", path="escalated", turns=2),
        leaf("ESCALATE_L2", "ESCALATE_L2", state="S_ESCALATED", exit_code="E1", path="escalated"),
        leaf("AUTO", None, close=uc, path="deflected"),
        leaf("AUTO", None, state="S_BLOCKED", exit_code="E0", close="blocked_injection_detected"),
        leaf("HITL", None, state="S_ESCALATED", exit_code="E4", path="escalated", turns=3),
    ]


def w_set(routes: tuple[str | None, ...] | None = None) -> list[PredictionRecord]:
    """Bộ W (8 lá) — nhóm theo GOLD:
        routine   (gold AUTO)  4 lá, 1 có exit_code (E2)        → 1/4 = 0,25
        approval  (gold HITL)  2 lá, 1 có exit_code (E6)        → 1/2 = 0,5
        sensitive (gold L2)    2 lá, 2 có exit_code (E1, E9)    → 2/2 = 1,0
    `routes` thay route từng lá (mặc định route ≠ gold ở vài lá, 1 lá không tới M5)."""
    golds = ("AUTO", "AUTO", "AUTO", "AUTO", "HITL", "HITL", "ESCALATE_L2", "ESCALATE_L2")
    exits = ("E2", None, None, None, "E6", None, "E1", "E9")
    rs = routes or ("HITL", "AUTO", None, "AUTO", "AUTO", "HITL", "ESCALATE_L2", "HITL")
    return [leaf(g, r, exit_code=e) for g, r, e in zip(golds, rs, exits, strict=True)]


def close(a: float | None, b: float) -> bool:
    return a is not None and math.isclose(a, b, rel_tol=0, abs_tol=TOL)


# ---- tỉ lệ thô (bộ A) -----------------------------------------------------------------------------------------------


def test_automation_hand() -> None:
    # S_RESOLVED ∧ không phiếu duyệt ∧ không exit_code: lá 1, 2, 6 → 3/8 = 0,375.
    # Lá 3 (S_RESOLVED nhưng has_approval) và lá 4 (S_RESOLVED nhưng E5) bị loại.
    e = efficiency(a_set())
    assert (e.automation.k, e.automation.n) == (3, 8)
    assert close(e.automation.value, 0.375)


def test_escalation_raw_hand() -> None:
    # Có exit_code (mọi mã, gồm E0 — Q9): lá 4 (E5), 5 (E1), 7 (E0), 8 (E4) → 4/8 = 0,5.
    e = efficiency(a_set())
    assert (e.escalation.k, e.escalation.n) == (4, 8)
    assert close(e.escalation.value, 0.5)


def test_exit_code_distribution_hand() -> None:
    # E0 1, E1 1, E4 1, E5 1, mã khác 0; mẫu số = 8 lá (lá không có mã không vào mã nào).
    e = efficiency(a_set())
    assert set(e.exit_codes) == set(EXIT_CODES)
    assert {c: r.k for c, r in e.exit_codes.items() if r.k} == {"E0": 1, "E1": 1, "E4": 1, "E5": 1}
    assert all(r.n == 8 for r in e.exit_codes.values())
    assert close(e.exit_codes["E0"].value, 0.125)
    assert sum(r.k for r in e.exit_codes.values()) == e.escalation.k


def test_deflection_hand() -> None:
    # resolution_path = deflected: lá 6 → 1/8 = 0,125 (mẫu số mọi lá, không chỉ 5 lá có route).
    e = efficiency(a_set())
    assert (e.deflection.k, e.deflection.n) == (1, 8)
    assert close(e.deflection.value, 0.125)


def test_clarification_mean_hand() -> None:
    # Σ clarification_turns = 0+0+1+2+0+0+0+3 = 6, n = 8 → 0,75.
    e = efficiency(a_set())
    assert (e.clarification.total, e.clarification.n) == (6.0, 8)
    assert close(e.clarification.value, 0.75)


def test_one_turn_requires_both() -> None:
    # clarification_turns = 0 ∧ close_reason = resolved_user_confirmed: lá 1, 6 → 2/8 = 0,25.
    # Lá 2, 5, 7 có 0 lượt nhưng close_reason khác; lá 3 đúng close_reason nhưng 1 lượt.
    e = efficiency(a_set())
    assert (e.one_turn.k, e.one_turn.n) == (2, 8)
    assert close(e.one_turn.value, 0.25)


def test_no_action_cases_in_denominator() -> None:
    # Q7: lá 6–8 không tới M5 (route None) vẫn vào mẫu số và vẫn đóng góp tử số.
    e = efficiency(a_set())
    assert e.n_leaves == 8
    assert e.automation.n == e.escalation.n == e.deflection.n == e.one_turn.n == e.clarification.n == 8
    only_no_m5 = efficiency(a_set()[5:])
    # Lá 6, 7, 8: tự động 1 (lá 6), escalation 2 (E0, E4), deflection 1, một lượt 1 (lá 6) — trên 3.
    assert (only_no_m5.automation.k, only_no_m5.escalation.k, only_no_m5.deflection.k, only_no_m5.one_turn.k) == (1, 2, 1, 1)
    assert only_no_m5.n_leaves == 3


def test_single_record() -> None:
    e = efficiency([leaf("AUTO", "AUTO", close="resolved_user_confirmed", path="auto")])
    assert (e.automation.value, e.escalation.value, e.deflection.value, e.one_turn.value) == (1.0, 0.0, 0.0, 1.0)
    assert e.clarification.value == 0.0
    assert e.escalation_weighted.value is None
    assert e.escalation_weighted.missing_groups == ("approval", "sensitive")


# ---- nhóm + escalation có trọng số (bộ W) ------------------------------------------------------------------------------


def test_n3_group() -> None:
    assert n3_group("AUTO") == "routine"
    assert n3_group("HITL") == "approval"
    assert n3_group("ESCALATE_L2") == "sensitive"
    assert GROUPS == ("routine", "approval", "sensitive")


def test_escalation_weighted_hand() -> None:
    # 70/20/10: 0,7·0,25 + 0,2·0,5 + 0,1·1,0 = 0,175 + 0,1 + 0,1 = 0,375. Thô: 4/8 = 0,5.
    e = efficiency(w_set())
    w = e.escalation_weighted
    assert {g: (r.k, r.n) for g, r in w.by_group.items()} == {"routine": (1, 4), "approval": (1, 2), "sensitive": (2, 2)}
    assert w.missing_groups == ()
    assert close(w.value, 0.375)
    assert close(e.escalation.value, 0.5)
    assert dict(w.mix) == {"routine": 0.7, "approval": 0.2, "sensitive": 0.1}


def test_escalation_weighted_sensitivity() -> None:
    # 60/30/10: 0,6·0,25 + 0,3·0,5 + 0,1·1,0 = 0,15 + 0,15 + 0,1 = 0,4.
    # 80/15/5 : 0,8·0,25 + 0,15·0,5 + 0,05·1,0 = 0,2 + 0,075 + 0,05 = 0,325.
    s = efficiency(w_set()).escalation_sensitivity
    assert set(s) == {"60/30/10", "80/15/5"}
    assert close(s["60/30/10"].value, 0.4)
    assert close(s["80/15/5"].value, 0.325)


def test_escalation_weighted_custom_mix() -> None:
    # Trọng số truyền qua tham số (Q6): 1/3 mỗi nhóm → (0,25 + 0,5 + 1,0)/3 = 0,583333333333.
    mix = {"routine": 1 / 3, "approval": 1 / 3, "sensitive": 1 / 3}
    assert close(escalation_weighted(w_set(), mix).value, 1.75 / 3)
    assert close(efficiency(w_set(), mix=mix).escalation_weighted.value, 1.75 / 3)


def test_group_by_gold_not_pred() -> None:
    # Đổi route của mọi lá (toàn AUTO / toàn None / đảo) → nhóm theo gold không đổi → vẫn 0,375.
    for routes in (("AUTO",) * 8, (None,) * 8, ("ESCALATE_L2", "ESCALATE_L2", "HITL", "HITL", "AUTO", "AUTO", "AUTO", "AUTO")):
        e = efficiency(w_set(routes))
        assert close(e.escalation_weighted.value, 0.375), routes
        assert {g: (r.k, r.n) for g, r in e.escalation_weighted.by_group.items()} == {
            "routine": (1, 4), "approval": (1, 2), "sensitive": (2, 2),
        }  # fmt: skip


def test_weighted_empty_group() -> None:
    # Không lá gold L2 → nhóm sensitive rỗng → bản có trọng số = None + tên nhóm thiếu (Q5), KHÔNG chuẩn hoá lại
    # (chuẩn hoá lại: (0,7·0,5 + 0,2·0)/0,9 ≈ 0,388888888889 — sai). Áp cho cả 2 bản độ nhạy.
    rows = [leaf("AUTO", "AUTO", exit_code="E2"), leaf("AUTO", "AUTO"), leaf("HITL", "HITL"), leaf("HITL", None)]
    e = efficiency(rows)
    assert e.escalation_weighted.value is None
    assert e.escalation_weighted.missing_groups == ("sensitive",)
    assert (e.escalation_weighted.by_group["sensitive"].k, e.escalation_weighted.by_group["sensitive"].n) == (0, 0)
    assert all(w.value is None and w.missing_groups == ("sensitive",) for w in e.escalation_sensitivity.values())
    assert close(e.escalation.value, 0.25)  # bản thô vẫn có: 1/4


# ---- mix ------------------------------------------------------------------------------------------------------------------


def test_mix_defaults() -> None:
    assert dict(OPERATING_MIX) == {"routine": 0.7, "approval": 0.2, "sensitive": 0.1}
    assert {k: dict(v) for k, v in SENSITIVITY_MIXES.items()} == {
        "60/30/10": {"routine": 0.6, "approval": 0.3, "sensitive": 0.1},
        "80/15/5": {"routine": 0.8, "approval": 0.15, "sensitive": 0.05},
    }


@pytest.mark.parametrize(
    "mix",
    [
        {"routine": 0.8, "approval": 0.2},
        {"routine": 0.7, "approval": 0.2, "sensitive": 0.1, "other": 0.0},
        {"routine": 0.9, "approval": 0.2, "sensitive": -0.1},
        {"routine": 0.7, "approval": 0.2, "sensitive": 0.0},
        {"routine": 0.7, "approval": 0.2, "sensitive": 0.2},
        {"routine": math.nan, "approval": 0.2, "sensitive": 0.1},
    ],
    ids=["thieu-nhom", "thua-nhom", "am", "tong-0.9", "tong-1.1", "nan"],
)
def test_mix_validation(mix: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="mix"):
        check_mix(mix)
    with pytest.raises(ValueError, match="mix"):
        efficiency(w_set(), mix=mix)
    with pytest.raises(ValueError, match="mix"):
        efficiency(w_set(), sensitivity_mixes={"x": mix})


def test_mix_sum_tolerance() -> None:
    # 0,1 + 0,2 + 0,7 trong số thực ≠ đúng 1 → vẫn nhận (dung sai).
    assert sum(check_mix({"routine": 0.1, "approval": 0.2, "sensitive": 0.7}).values()) == pytest.approx(1.0)


def test_mix_frozen() -> None:
    with pytest.raises(TypeError):
        OPERATING_MIX["routine"] = 0.5  # type: ignore[index]
    with pytest.raises(TypeError):
        SENSITIVITY_MIXES["60/30/10"]["routine"] = 0.5  # type: ignore[index]
    with pytest.raises(TypeError):
        SENSITIVITY_MIXES["x"] = OPERATING_MIX  # type: ignore[index]
    src = {"routine": 0.7, "approval": 0.2, "sensitive": 0.1}
    w = escalation_weighted(w_set(), src)
    src["routine"] = 0.0
    assert w.mix["routine"] == 0.7  # kết quả giữ bản sao đóng băng, không trỏ vào dict của người gọi


# ---- đồng bộ hằng DB, rỗng -------------------------------------------------------------------------------------------


def test_literals_in_db_constants() -> None:
    assert RESOLVED_STATE == "S_RESOLVED" and RESOLVED_STATE in FINAL_STATES
    assert DEFLECTED_PATH == "deflected" and DEFLECTED_PATH in RESOLUTION_PATHS
    assert ONE_TURN_CLOSE_REASON == "resolved_user_confirmed" and ONE_TURN_CLOSE_REASON in CLOSE_REASONS


def test_empty_records_raises() -> None:
    with pytest.raises(ValueError, match="rỗng"):
        efficiency([])
    with pytest.raises(ValueError, match="rỗng"):
        escalation_weighted([], OPERATING_MIX)
