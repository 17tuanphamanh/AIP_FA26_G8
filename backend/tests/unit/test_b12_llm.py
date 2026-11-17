"""Phase 6 chặng 6C — B12 nối lớp LLM của M5 (phase6 bảng 6.4 c3–c8, c14; 6.1 P3, P5, P9; PLAN-6C TQ-5, TQ-6, Q-6C-3, Q-6C-4).
Viết TỪ ĐẶC TẢ trước code — node gọi trực tiếp (khung `test_b12_assess._node`).

- Đường LLM chạy qua gateway THẬT + ScriptedLLM (`make_gateway(vpn_scripts(...))`) + `LlmRiskEstimator(gw.client, …)`; ca cần ép
  `evidence_trimmed`/lỗi thì dùng `FakeRiskEstimator` (`tests/fakes/risk_estimator.py`).
- "Không luật nào khớp" = G-02 (máy của người khác, trong giờ — `_action(owner=False)`); "luật khớp" = `_state()` mặc định trong
  giờ → R20 allow.
- Ngưỡng = `policy.json constants` (0,25; 0,75). `kb_gap = (min(len(evidence), 3) - est.evidence_trimmed) <= 0` (Q-6C-4).
- Điểm log 4 ca LLM: khoá `detail` cũ + `calibrated_prob`, `thresholds`, `factors`, `kb_gap`, `calibrator_version`; D-67 (thay
  Q-6C-3): `strategy` ở MỌI đường điểm 4, có EVAL_MODE hay không. Chiến lược đặt trên ticket (`h.tickets.strategies`), không qua deps. Lineage ca LLM thêm `prompt_id`, `prompt_version`, `model`, `p_method`,
  `calibrator_version` (P5). Không trường nào mang `rationale` (D-40).
"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.core.clock import FakeClock
from app.core.errors import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.risk_factors import FactorCode
from app.domain.states import S_ASSESSING, S_ESCALATED, S_EXECUTING
from app.domain.ticket_state import ChunkRef, RiskDecision
from app.graph.builder import wrap_node
from app.graph.nodes import b12_assess
from app.llm.ports import CachePolicy, LLMMeta, Role, Sensitivity
from app.risk.calibrator import Calibrator, CalibratorParams, FitInfo
from app.risk.estimator import LlmRiskEstimator, PMethod, RiskEstimate
from app.risk.models import RiskContext
from app.risk.strategy import Strategy
from pydantic import BaseModel
from tests.fakes.graph import GraphHarness
from tests.fakes.llm import Gateway, make_gateway
from tests.fakes.risk_estimator import FakeRiskEstimator
from tests.fakes.scripted_llm import Reply, Script
from tests.fixtures.llm.vpn import vpn_scripts
from tests.unit.test_b12_assess import (
    IN_HOURS,
    POINT4,
    _action,
    _requester,
    _run,
    _state,
)

REPO = Path(__file__).resolve().parents[3]
PROMPT_VERSION = str(yaml.safe_load((REPO / "config" / "prompts" / "b14_risk_estimate.yaml").read_text(encoding="utf-8"))["version"])
THRESHOLDS = [0.25, 0.75]  # policy.json constants THRESHOLD_LOW/HIGH
LLM_POINT4 = POINT4 | {"calibrated_prob", "thresholds", "factors", "kb_gap", "calibrator_version"}  # P5 / TQ-6
KB_GAP_SENTENCE = " Không có tài liệu quy định đủ liên quan → tối đa chờ người duyệt."  # 5.3 mẫu reason bước 3
RULE_ONLY_REASON = "Không luật nào khớp → chờ duyệt (chỉ-luật)"  # [Chốt B12 §5] (5.3, st8)
CANARY = "CANARY-b14-rationale-6c"

CAL = Calibrator(CalibratorParams(
    version="platt-20261013-0123abcd", method="platt", a=1.0, b=0.0,
    fitted_on=FitInfo(split="calibration", n=40, n_pos=10, n_families=8, data_sha256="0" * 64),
    created_at=datetime(2026, 10, 13, tzinfo=UTC),
))  # fmt: skip  — Platt a=1, b=0 ≈ identity (TQ-13, như st4 của 6B)


def _chunk(i: int, score: float = 0.9) -> ChunkRef:
    return ChunkRef(chunk_id=f"KB-VPN-004#{i}", doc_id="KB-VPN-004", version=1, seq=i, title=f"Tiêu đề {i}",
                    heading_path=f"Gia hạn > Bước {i}", score=score, excerpt=f"trích-đoạn-số-{i}")  # fmt: skip


def _no_match(chunks: list[ChunkRef] | None = None, score: float | None = None) -> dict[str, Any]:
    """G-02 trong giờ: không luật nào khớp. Mặc định 1 trích đoạn, điểm truy hồi 0,9 ≥ RETRIEVAL_THRESHOLD 0,6 (có bằng chứng)."""
    chunks = [_chunk(0)] if chunks is None else chunks
    top = score if score is not None else (max(c.score for c in chunks) if chunks else 0.0)
    return _state(intended_action=_action(owner=False), retrieved=chunks, retrieval_score=top)


def _rule_match() -> dict[str, Any]:
    """`_state()` trong giờ → R20 allow (luật khớp)."""
    return _state(retrieved=[_chunk(0)], retrieval_score=0.9)


def _estimate_reply(p: float, factors: Sequence[str] = ("routine_low_risk",), rationale: str = "x") -> Reply:
    return Reply({"prob_needs_human": p, "factors": list(factors), "rationale": rationale})


def _scripts(p: float | None = None, **kw: Any) -> dict[str, Script]:
    """`vpn_scripts` (b14 mặc định 0,9 — Q-6C-5); `p` → ghi đè `b14_risk_estimate` bằng hàm (gọi lại bao nhiêu lần cũng được)."""
    if p is None:
        return vpn_scripts()
    reply = _estimate_reply(p, **kw)
    return vpn_scripts(b14_risk_estimate=lambda _v: reply)


async def _node(
    state: dict[str, Any], *, at: datetime = IN_HOURS, scripts: dict[str, Script] | None = None,
    estimator: Any = None, calibrator: Calibrator | None = None, strategy: Strategy = "hybrid", eval_mode: bool = False,
    p_method: PMethod = "self_report", boundary: bool = False,
) -> tuple[dict[str, Any], GraphHarness, Gateway]:  # fmt: skip
    gw = make_gateway(scripts if scripts is not None else vpn_scripts())
    h = GraphHarness(clock=FakeClock(at), llm=gw.client)
    deps = h.deps()
    deps.estimator = estimator if estimator is not None else LlmRiskEstimator(gw.client, p_method=p_method,
                                                                              eval_mode=eval_mode)  # fmt: skip
    deps.calibrator = calibrator
    h.tickets.strategies[state["ticket_id"]] = strategy  # D-67: chiến lược chụp trên ticket, B12 đọc qua `tickets.strategy_of`
    deps.eval_mode = eval_mode
    fn = b12_assess.make(deps)
    with _run(h):
        out = await (wrap_node("b12_assess", fn) if boundary else fn)(state)
    return out, h, gw


def _risk(out: dict[str, Any]) -> RiskDecision:
    return RiskDecision.model_validate(out["risk"])


def _point4(h: GraphHarness) -> dict[str, Any]:
    [row] = h.audit.of("t1", "risk_decided")
    assert row["step"] == "B13/B14"
    return row


def _b14_calls(gw: Gateway) -> list[str]:
    return [c.prompt_id for c in gw.llm.calls if c.prompt_id.startswith("b14")]


def _est(raw: float, trimmed: int) -> RiskEstimate:
    return RiskEstimate(raw_prob=raw, p_method="self_report", factors=(FactorCode.ROUTINE_LOW_RISK,),
                        prompt_id="b14_risk_estimate", prompt_version="1", model="strong-gia",
                        evidence_trimmed=trimmed)  # fmt: skip


def _assert_llm_path_events(h: GraphHarness) -> None:
    """Mọi nhánh đường LLM: `step="B13/B14"`, `event="risk_decided"` — KHÔNG có sự kiện `llm_layer_disabled` (P3)."""
    events = h.audit.events("t1")
    assert ("B13/B14", "risk_decided") in events
    assert not [e for e in events if e[1] == "llm_layer_disabled"]


# ---- c3: không khớp + chưa hiệu chỉnh → HITL ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c3_no_match_uncalibrated_low_raw_goes_hitl_b15() -> None:
    """c3 (D-38, M-6C-9): không khớp, calibrator None, raw 0,02, có bằng chứng → HITL → B15 (KHÔNG AUTO); điểm 4 `decided_by=llm`,
    `raw_prob=0.02` (cột VÀ `detail` — TQ-12, M-6C-4), `calibrated_prob=None`, reason có "chưa hiệu chỉnh"."""
    out, h, gw = await _node(_no_match(), scripts=_scripts(0.02))
    assert _b14_calls(gw) == ["b14_risk_estimate"]
    assert (out["status"], out["next"]) == (S_ASSESSING, "b15_prepare_approval")
    assert "exit_code" not in out
    risk = _risk(out)
    assert (risk.decided_by, risk.policy_decision, risk.matched_rule_id, risk.route, risk.risk_level) == (
        "llm", None, None, "HITL", "medium")
    assert (risk.raw_prob, risk.calibrated_prob, risk.p_method) == (0.02, None, "self_report")
    row = _point4(h)
    assert (row["decided_by"], row["raw_prob"], row["p_method"], row["risk_level"]) == ("llm", 0.02, "self_report", "medium")
    assert row.get("calibrated_prob") is None  # cột chỉ có khi khác None
    assert "chưa hiệu chỉnh" in row["reason"]
    detail = row["detail"]
    assert detail["raw_prob"] == 0.02
    assert detail["calibrated_prob"] is None
    assert (detail["decided_by"], detail["route"], detail["p_method"]) == ("llm", "HITL", "self_report")
    assert detail["thresholds"] == THRESHOLDS
    assert detail["factors"] == ["routine_low_risk"]
    assert detail["kb_gap"] is False
    assert detail["calibrator_version"] is None
    _assert_llm_path_events(h)


@pytest.mark.asyncio
async def test_c3_point4_detail_keys_exact_without_eval_mode() -> None:
    """P5 / TQ-6 — sửa có chủ ý theo D-67: điểm 4 ca LLM, `eval_mode` False → đúng khoá cũ + 5 khoá mới + `strategy` (trước D-67,
    Q-6C-3: KHÔNG có `strategy`)."""
    _, h, _ = await _node(_no_match(), scripts=_scripts(0.02))
    detail = _point4(h)["detail"]
    assert set(detail) == LLM_POINT4
    assert detail["strategy"] == "hybrid"


# ---- c4: preset 0,9 chưa hiệu chỉnh → E5 llm_high_risk ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_c4_no_match_preset_09_escalates_llm_high_risk() -> None:
    """c4 (P3, 6.3, Q-6C-2): không khớp + `vpn_scripts` mặc định (b14 = 0,9 — Q-6C-5), chưa hiệu chỉnh → E5
    `escalation_reason_detail="llm_high_risk"`, `event="risk_decided"`, không tới B15 (0 phiếu), không có `llm_layer_disabled`."""
    out, h, gw = await _node(_no_match())
    assert _b14_calls(gw) == ["b14_risk_estimate"]
    assert (out["status"], out["next"], out["exit_code"]) == (S_ESCALATED, "b20_audit", "E5")
    assert out["escalation_reason_detail"] == "llm_high_risk"
    risk = _risk(out)
    assert (risk.decided_by, risk.route, risk.risk_level, risk.raw_prob) == ("llm", "ESCALATE_L2", "high", 0.9)
    row = _point4(h)
    assert (row["decided_by"], row["detail"]["route"]) == ("llm", "ESCALATE_L2")
    assert h.approvals.count("t1") == 0
    _assert_llm_path_events(h)


@pytest.mark.asyncio
async def test_c4_d98_llm_high_risk_carries_factor_codes() -> None:
    """D-98 (17/11): nhánh `llm_high_risk` đặt `risk_factors` = mã B14 chọn (đúng thứ tự) — B20 ghép vế "Lý do chính" từ nhãn cố định.
    Nhánh khác (HITL, AUTO, luật) KHÔNG đặt khoá này."""
    out, _, _ = await _node(_no_match(), scripts=_scripts(0.95, factors=("target_is_other", "outside_business_hours")))
    assert out["escalation_reason_detail"] == "llm_high_risk"
    assert out["risk_factors"] == ["target_is_other", "outside_business_hours"]
    assert "factors" not in _risk(out).model_dump()  # hợp đồng `RiskView` của phiếu duyệt giữ nguyên
    rule_out, _, _ = await _node(_rule_match())
    assert "risk_factors" not in rule_out


# ---- c5: calibrator + raw 0,05 + có bằng chứng → AUTO + action_plan_hash -------------------------------------------------


@pytest.mark.asyncio
async def test_c5_calibrated_low_p_with_evidence_auto_sets_action_plan_hash() -> None:
    """c5 (P3, D-42): không khớp + calibrator Platt a=1,b=0 + raw 0,05 + có bằng chứng → AUTO → `S_EXECUTING`/B17; update có
    `action_plan_hash == hash_action(action)`; dòng điểm 4 mang cùng cột `action_plan_hash`."""
    state = _no_match()
    out, h, gw = await _node(state, scripts=_scripts(0.05), calibrator=CAL)
    assert _b14_calls(gw) == ["b14_risk_estimate"]
    assert (out["status"], out["next"]) == (S_EXECUTING, "b17_execute")
    expected = hash_action(Action.model_validate(state["intended_action"]))
    assert out["action_plan_hash"] == expected
    risk = _risk(out)
    assert (risk.decided_by, risk.policy_decision, risk.route, risk.risk_level) == ("llm", None, "AUTO", "low")
    assert risk.calibrated_prob == pytest.approx(0.05, abs=1e-9)
    row = _point4(h)
    assert row["action_plan_hash"] == expected
    assert row["calibrated_prob"] == pytest.approx(0.05, abs=1e-9)
    detail = row["detail"]
    assert detail["calibrated_prob"] == pytest.approx(0.05, abs=1e-9)
    assert (detail["route"], detail["kb_gap"], detail["calibrator_version"]) == ("AUTO", False, CAL.params.version)
    assert detail["thresholds"] == THRESHOLDS
    _assert_llm_path_events(h)


@pytest.mark.asyncio
@pytest.mark.parametrize(("p", "route"), [(0.5, "HITL"), (0.9, "ESCALATE_L2")])
async def test_c5_calibrated_mid_and_high_p_routes(p: float, route: str) -> None:
    """P3 + bảng 5.3 bước 2 (ngưỡng 0,25/0,75, Platt a=1,b=0): p 0,5 → HITL → B15; p 0,9 → E5 `llm_high_risk`."""
    out, h, _ = await _node(_no_match(), scripts=_scripts(p), calibrator=CAL)
    assert _risk(out).route == route
    if route == "HITL":
        assert (out["status"], out["next"]) == (S_ASSESSING, "b15_prepare_approval")
    else:
        assert (out["status"], out["next"], out["exit_code"]) == (S_ESCALATED, "b20_audit", "E5")
        assert out["escalation_reason_detail"] == "llm_high_risk"
    _assert_llm_path_events(h)


# ---- c6: kb_gap (N4, Q-6C-4) ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("chunks", "score"), [([], 0.0), ([_chunk(0, 0.3)], 0.3)], ids=["retrieved-rong", "duoi-nguong"])
async def test_c6a_empty_evidence_kb_gap_demotes_auto_to_hitl(chunks: list[ChunkRef], score: float) -> None:
    """c6 (a) (D-34, M-6C-2): như c5 nhưng không có bằng chứng (retrieved rỗng / điểm dưới ngưỡng → `evidence_for_estimator` = [])
    → HITL; reason có câu kb_gap; `detail.kb_gap is True`."""
    out, h, _ = await _node(_no_match(chunks, score), scripts=_scripts(0.05), calibrator=CAL)
    assert (out["status"], out["next"]) == (S_ASSESSING, "b15_prepare_approval")
    risk = _risk(out)
    assert (risk.decided_by, risk.route) == ("llm", "HITL")
    row = _point4(h)
    assert KB_GAP_SENTENCE in row["reason"]
    assert row["detail"]["kb_gap"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("n_chunks", "trimmed", "route"), [
    (2, 2, "HITL"),   # (b) gateway cắt hết 2 khối đã gửi
    (5, 3, "HITL"),   # (c) 5 đoạn đạt ngưỡng, gửi 3 (MAX_EVIDENCE), cắt cả 3 (Q-6C-4)
    (5, 2, "AUTO"),   # (d) đối chứng: còn 1 khối tới LLM
    (2, 1, "AUTO"),   # đối chứng: còn 1 khối
], ids=["b-2-cat-2", "c-5-cat-3", "d-5-cat-2", "2-cat-1"])  # fmt: skip
async def test_c6_trimmed_evidence_kb_gap(n_chunks: int, trimmed: int, route: str) -> None:
    """c6 (b)(c)(d) (N4, Q-6C-4, M-6C-8): `kb_gap = (min(len(evidence), 3) - est.evidence_trimmed) <= 0`. Calibrator a=1,b=0 +
    raw 0,05: cắt hết khối đã gửi → HITL; còn ≥ 1 khối → AUTO. Estimator giả ép `evidence_trimmed`."""
    fake = FakeRiskEstimator(_est(0.05, trimmed))
    chunks = [_chunk(i) for i in range(n_chunks)]
    out, h, _ = await _node(_no_match(chunks), estimator=fake, calibrator=CAL)
    [(_, _, seen)] = fake.calls
    assert len(seen) == n_chunks  # B12 đưa đủ bằng chứng đạt ngưỡng cho estimator
    risk = _risk(out)
    assert (risk.decided_by, risk.route) == ("llm", route)
    detail = _point4(h)["detail"]
    assert detail["kb_gap"] is (route == "HITL")
    if route == "AUTO":
        assert (out["status"], out["next"]) == (S_EXECUTING, "b17_execute")
    else:
        assert (out["status"], out["next"]) == (S_ASSESSING, "b15_prepare_approval")
        assert KB_GAP_SENTENCE in _point4(h)["reason"]


class TrimmingLlm:
    """`LlmPort` giả (c6 e): trả `schema.model_validate(reply)` + `LLMMeta(trimmed_evidence=k)`; k theo `sample_idx` (k = 5) hoặc cố
    định (tự nêu)."""

    def __init__(self, trimmed: Sequence[int]) -> None:
        self._trimmed = list(trimmed)
        self.calls: list[str] = []

    async def complete[T: BaseModel](
        self,
        role: Role,
        prompt_id: str,
        variables: Mapping[str, Any],
        schema: type[T],
        *,
        sensitivity: Sensitivity = "internal",
        cache_policy: CachePolicy = "default",
        n: int = 1,
        temperature: float | None = None,
        kb_version: str | None = None,
        keep_tail: Mapping[str, int] | None = None,  # Q1 điểm 2 — LlmPort
    ) -> tuple[T, LLMMeta]:
        self.calls.append(prompt_id)
        if prompt_id == "b14_risk_vote":
            idx = int(variables["sample_idx"])
            reply: dict[str, Any] = {"needs_human": idx % 2 == 0, "factors": ["routine_low_risk"]}
            k = self._trimmed[idx]
        else:
            reply = {"prob_needs_human": 0.05, "factors": ["routine_low_risk"], "rationale": "x"}
            k = self._trimmed[0]
        meta = LLMMeta(
            span_id=f"span-{len(self.calls)}", provider="gia", model="strong-gia", model_version=None, prompt_id=prompt_id,
            prompt_version="1", prompt_hash="h" * 64, tokens_in=1, tokens_out=1, cost_usd=0.0, latency_ms=1, cache_hit=False,
            json_valid_first_try=True, used_fallback=False, trimmed_evidence=k,
        )  # fmt: skip
        return schema.model_validate(reply), meta


@pytest.mark.asyncio
@pytest.mark.parametrize(("p_method", "trimmed", "expected"), [
    ("self_report", [2], 2),
    ("sampling_k5", [0, 3, 1, 0, 2], 3),
], ids=["self_report", "sampling_k5-max"])  # fmt: skip
async def test_c6e_estimator_carries_trimmed_evidence_from_meta(p_method: PMethod, trimmed: list[int], expected: int) -> None:
    """c6 (e) (P9, TQ-8): `LlmRiskEstimator` đặt `RiskEstimate.evidence_trimmed` = `LLMMeta.trimmed_evidence` — tự nêu: của lời gọi
    duy nhất; k = 5: LỚN NHẤT trong 5 phiếu."""
    port = TrimmingLlm(trimmed)
    ctx = RiskContext(requester=_requester(), facts={}, now=IN_HOURS, within_business_hours=True, target_is_other=True)
    est = await LlmRiskEstimator(port, p_method=p_method, eval_mode=False).estimate(
        _action(owner=False), ctx, [_chunk(0), _chunk(1), _chunk(2)])  # fmt: skip
    assert len(port.calls) == (1 if p_method == "self_report" else 5)
    assert est.evidence_trimmed == expected


# ---- c7: lỗi estimator → E5 llm_layer_disabled (giữ) -------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [LLMUnavailable("x"), LLMSchemaError("x"), LLMBudgetExceeded("x")],
                         ids=["LLMUnavailable", "LLMSchemaError", "LLMBudgetExceeded"])  # fmt: skip
async def test_c7_estimator_error_keeps_e5_llm_layer_disabled(exc: Exception) -> None:
    """c7 (P3 "giữ nguyên nhánh"): estimator ném `LLMUnavailable`/`LLMSchemaError`/`LLMBudgetExceeded` → E5
    `llm_layer_disabled`, `event="llm_layer_disabled"` (không AUTO, không HITL) — kể cả khi đã có calibrator."""
    fake = FakeRiskEstimator(exc)
    out, h, _ = await _node(_no_match(), estimator=fake, calibrator=CAL)
    assert len(fake.calls) == 1
    assert (out["status"], out["next"], out["exit_code"]) == (S_ESCALATED, "b20_audit", "E5")
    assert out["escalation_reason_detail"] == "llm_layer_disabled"
    [row] = h.audit.of("t1", "llm_layer_disabled")
    assert row["detail"]["estimator_error"] == type(exc).__name__


# ---- c8: luật khớp → 0 lời gọi b14 ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c8_rule_match_never_calls_estimator() -> None:
    """c8 (h18): luật khớp (R20 allow) → estimator 0 lần (`FakeRiskEstimator.calls == []`), đường luật như cũ."""
    fake = FakeRiskEstimator(_est(0.05, 0))
    out, h, gw = await _node(_rule_match(), estimator=fake, calibrator=CAL)
    assert fake.calls == []
    assert _b14_calls(gw) == []
    assert (out["status"], out["next"]) == (S_EXECUTING, "b17_execute")
    risk = _risk(out)
    assert (risk.decided_by, risk.policy_decision, risk.matched_rule_id, risk.route) == ("rule", "allow", "R20", "AUTO")
    assert set(_point4(h)["detail"]) == POINT4  # đường luật: khoá cũ (D-67: gồm `strategy`, cả khi eval_mode False)


@pytest.mark.asyncio
async def test_c8_rule_match_real_gateway_zero_b14_calls() -> None:
    """c8: luật khớp với estimator THẬT qua gateway → ScriptedLLM 0 lời gọi `b14_*`."""
    out, _, gw = await _node(_rule_match(), calibrator=CAL)
    assert _b14_calls(gw) == []
    assert _risk(out).decided_by == "rule"


# ---- c14: lineage ca LLM ----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c14_lineage_llm_uncalibrated() -> None:
    """c14 (P5): lineage dòng `B13/B14` ca LLM có `prompt_id="b14_risk_estimate"`, `prompt_version` = version file yaml,
    `model` = model của lời gọi ScriptedLLM, `p_method="self_report"`, `calibrator_version=None`; vẫn có `kb_version`,
    `commit_sha`, `policy_version_id`; không trường nào chứa "rationale"; canary đặt trong `rationale` không ra audit/lineage."""
    _, h, gw = await _node(_no_match(), scripts=_scripts(0.02, rationale=f"lý do {CANARY}"))
    [call] = gw.llm.calls_for("b14_risk_estimate")
    [lin] = [r for r in h.audit.lineage if r["step"] == "B13/B14"]
    assert (lin["prompt_id"], lin["prompt_version"], lin["model"]) == ("b14_risk_estimate", PROMPT_VERSION, call.model)
    assert (lin["p_method"], lin["calibrator_version"]) == ("self_report", None)
    assert lin["kb_version"] == "a" * 64
    assert {"commit_sha", "policy_version_id"} <= set(lin)
    assert not [k for k in lin if "rationale" in k]
    assert not [k for k in _point4(h)["detail"] if "rationale" in k]
    dumped = json.dumps([h.audit.rows, h.audit.lineage], ensure_ascii=False, default=str)
    assert CANARY not in dumped


@pytest.mark.asyncio
async def test_c14_lineage_llm_calibrated_version() -> None:
    """c14 (P5 "calibrator_version khớp policy"): ca c5 → lineage `calibrator_version == cal.params.version`."""
    _, h, _ = await _node(_no_match(), scripts=_scripts(0.05), calibrator=CAL)
    [lin] = [r for r in h.audit.lineage if r["step"] == "B13/B14"]
    assert lin["calibrator_version"] == CAL.params.version
    assert (lin["prompt_id"], lin["p_method"]) == ("b14_risk_estimate", "self_report")


# ---- Q-6C-3 phần B12 → D-67: detail.strategy ở MỌI đường điểm 4, cả lúc vận hành; rule_only không khớp ---------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["luat", "llm"])
async def test_q6c3_eval_mode_writes_strategy_on_every_point4_path(path: str) -> None:
    """Q-6C-3 = A: `deps.eval_mode` True → `detail.strategy == "hybrid"` ở MỌI đường điểm 4 (luật khớp lẫn LLM)."""
    state = _rule_match() if path == "luat" else _no_match()
    _, h, _ = await _node(state, scripts=_scripts(0.02), eval_mode=True)
    detail = _point4(h)["detail"]
    assert detail["strategy"] == "hybrid"
    assert set(detail) == (POINT4 if path == "luat" else LLM_POINT4) | {"strategy"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["luat", "llm"])
@pytest.mark.parametrize("strategy", ["hybrid", "hybrid_guarded"])
async def test_d67_no_eval_mode_still_writes_strategy(path: str, strategy: Strategy) -> None:
    """D-67 (thay `test_q6c3_no_eval_mode_no_strategy_key` — trước: khoá `strategy` VẮNG khi không EVAL_MODE): `deps.eval_mode`
    False → `detail.strategy` = chiến lược của ticket ở mọi đường điểm 4."""
    state = _rule_match() if path == "luat" else _no_match()
    _, h, _ = await _node(state, scripts=_scripts(0.02), eval_mode=False, strategy=strategy)
    assert _point4(h)["detail"]["strategy"] == strategy


@pytest.mark.asyncio
@pytest.mark.parametrize("eval_mode", [True, False], ids=["danh-gia", "deps-mac-dinh"])
async def test_q6c3_rule_only_no_match_goes_hitl_without_llm(eval_mode: bool) -> None:
    """P3 + st8 + Q-6C-3: ticket `strategy="rule_only"` + không khớp → HITL (B15), `decided_by="rule"`, `policy_decision=None`,
    reason đúng chữ [Chốt B12 §5]; estimator 0 lần, 0 lời gọi `b14_*`. D-67 (sửa có chủ ý): `detail.strategy == "rule_only"` ở CẢ
    hai chế độ (trước: chỉ khi eval_mode)."""
    fake = FakeRiskEstimator(_est(0.05, 0))
    out, h, gw = await _node(_no_match(), estimator=fake, calibrator=CAL, strategy="rule_only", eval_mode=eval_mode)
    assert fake.calls == []
    assert _b14_calls(gw) == []
    assert (out["status"], out["next"]) == (S_ASSESSING, "b15_prepare_approval")
    risk = _risk(out)
    assert (risk.decided_by, risk.policy_decision, risk.matched_rule_id, risk.route) == ("rule", None, None, "HITL")
    assert risk.reason == RULE_ONLY_REASON
    row = _point4(h)
    assert (row["decided_by"], row["detail"]["route"]) == ("rule", "HITL")
    assert row["detail"]["strategy"] == "rule_only"
