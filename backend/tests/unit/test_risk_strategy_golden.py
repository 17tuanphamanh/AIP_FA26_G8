"""Golden `risk.strategy.decide` — chốt kết quả trên ma trận đầu vào cố định (gói tuần 8, D-60).

Ma trận: mọi chiến lược (kể cả giá trị lạ) × {không có kết quả luật, không khớp, allow, approval_required, deny} × ước lượng
(không có + 8 xác suất quanh ngưỡng) × {có, không} calibrator × kb_gap. Ngưỡng và mã luật là giá trị giả (R81…R83), không lấy từ
config. Bản golden được sinh MỘT lần từ commit 806b860 (trước khi sửa `risk/strategy.py`); sửa logic quyết định mà test này đỏ
nghĩa là số RQ1 đo trên tag không còn áp dụng được — KHÔNG sinh lại golden để làm test xanh.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.risk.calibrator import Calibrator, CalibratorParams, FitInfo
from app.risk.estimator import RiskEstimate
from app.risk.models import RuleVerdict
from app.risk.strategy import FullAutoBypass, decide, needs_llm, needs_rules

GOLDEN = Path(__file__).parent / "golden" / "decide_matrix.golden"

CAL = Calibrator(CalibratorParams(
    version="platt-20261010-0123abcd", method="platt", a=1.0, b=0.0,
    fitted_on=FitInfo(split="calibration", n=40, n_pos=10, n_families=8, data_sha256="0" * 64),
    created_at=datetime(2026, 10, 10, tzinfo=UTC),
))  # fmt: skip

T_RAW = (0.20, 0.60)  # ngưỡng giả — dùng khi không có calibrator
T_CAL = (
    CAL.transform(0.20),
    CAL.transform(0.60),
)  # ngưỡng giả trong không gian đã hiệu chỉnh (ca biên không phụ thuộc bit cuối)
RAWS = (0.01, 0.19, 0.20, 0.21, 0.59, 0.60, 0.61, 0.99)

STRATEGIES = (
    "hybrid",
    "rule_only",
    "llm_only",
    "full_auto",
    "hybrid_guarded",
    "manual",
)  # "manual" = giá trị lạ
VERDICTS: dict[str, RuleVerdict | None] = {
    "verdict_none": None,
    "no_match": RuleVerdict(
        matched=False, decision=None, rule_id=None, all_matched=[], description=None
    ),
    "allow": RuleVerdict(
        matched=True,
        decision="allow",
        rule_id="R81",
        all_matched=["R81"],
        description="Mô tả giả R81",
    ),
    "approval_required": RuleVerdict(
        matched=True,
        decision="approval_required",
        rule_id="R82",
        all_matched=["R82"],
        description="Mô tả giả R82",
    ),
    "deny": RuleVerdict(
        matched=True,
        decision="deny",
        rule_id="R83",
        all_matched=["R83"],
        description="Mô tả giả R83",
    ),
}


def _est(raw: float) -> RiskEstimate:
    return RiskEstimate(raw_prob=raw, p_method="self_report", factors=(), prompt_id="b14_risk_estimate",
                        prompt_version="1", model="strong-gia")  # fmt: skip


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 9)


def _outcome(
    strategy: str,
    verdict: RuleVerdict | None,
    raw: float | None,
    calibrated: bool,
    kb_gap: bool,
) -> Any:
    calibrator = CAL if calibrated else None
    thresholds = T_CAL if calibrated else T_RAW
    try:
        out = decide(strategy, verdict, None if raw is None else _est(raw), calibrator=calibrator,  # type: ignore[arg-type]
                     thresholds=thresholds, kb_gap=kb_gap)  # fmt: skip
    except ValueError as exc:
        return {"error": "ValueError", "message": str(exc)}
    if isinstance(out, FullAutoBypass):
        return {"result": "FullAutoBypass"}
    th = (
        None
        if out.thresholds is None
        else [_round(out.thresholds[0]), _round(out.thresholds[1])]
    )
    return {
        "decided_by": out.decided_by, "policy_decision": out.policy_decision, "matched_rule_id": out.matched_rule_id,
        "raw_prob": _round(out.raw_prob), "calibrated_prob": _round(out.calibrated_prob), "p_method": out.p_method,
        "risk_level": out.risk_level, "route": out.route, "thresholds": th,
        "reason_sha256": hashlib.sha256(out.reason.encode()).hexdigest()[:16],
    }  # fmt: skip


def _flags(strategy: str, verdict: RuleVerdict | None) -> Any:
    s: Any = strategy  # "manual" là giá trị lạ có chủ ý
    out: dict[str, Any] = {}
    for name, fn in (
        ("needs_rules", lambda: needs_rules(s)),
        ("needs_llm", lambda: needs_llm(s, verdict)),
    ):
        try:
            out[name] = fn()
        except ValueError as exc:
            out[name] = {"error": "ValueError", "message": str(exc)}
    return out


def build_snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {}
    for s in STRATEGIES:
        for vname, v in VERDICTS.items():
            snap[f"flags|{s}|{vname}"] = _flags(s, v)
            for raw in (None, *RAWS):
                for calibrated in (True, False):
                    for kb_gap in (False, True):
                        key = f"{s}|{vname}|raw={raw}|cal={int(calibrated)}|kb_gap={int(kb_gap)}"
                        snap[key] = _outcome(s, v, raw, calibrated, kb_gap)
    return snap


def test_golden_matrix_size() -> None:
    assert len(build_snapshot()) == len(STRATEGIES) * len(VERDICTS) * (1 + 9 * 4)


def test_decide_matches_golden() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    snap = build_snapshot()
    assert snap.keys() == golden.keys()
    diffs = [k for k in golden if snap[k] != golden[k]]
    assert not diffs, f"{len(diffs)} ô lệch golden, ví dụ: {diffs[:5]}"


@pytest.mark.parametrize("strategy", ["hybrid", "rule_only", "hybrid_guarded"])
def test_golden_rule_decisions_are_independent_of_probability(strategy: str) -> None:
    """Chốt thêm: luật approval_required/deny giữ route của luật ở mọi xác suất (hybrid_guarded chỉ nâng mức từ allow)."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for raw in RAWS:
        for cal in (0, 1):
            for vname, route in (
                ("approval_required", "HITL"),
                ("deny", "ESCALATE_L2"),
            ):
                assert (
                    golden[f"{strategy}|{vname}|raw={raw}|cal={cal}|kb_gap=0"]["route"]
                    == route
                )
