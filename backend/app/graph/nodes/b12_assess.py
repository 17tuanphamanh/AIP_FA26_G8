"""B12–B13 — node THẬT (Phase 3 chặng 3h; phase3 mục 11.3, B12-B14 §5; Phase 6 6C — phase6 mục 6). Gate2 (`FAKE_SCENARIO`)
dùng bản giả `graph/nodes/fake/b12_assess.py`.

Input DUY NHẤT của M5: `intended_action` + `build_ctx(state, now, business_hours)` — `build_ctx` chỉ đọc `intended_action`,
`requester_context`, `ctx_flags` (P2, h21); `now` = Clock của lượt. `evaluate(action, ctx)` giữ chữ ký (h22).

- Chiến lược (D-67) = giá trị CHỤP trên ticket lúc tạo (`deps.tickets.strategy_of`; ticket con kế thừa từ cha; NULL → `hybrid`;
  giá trị ngoài tập cho phép của chế độ — vận hành: `RUNTIME_SELECTABLE`, EVAL_MODE: `STRATEGIES` — → `hybrid` + log cảnh báo, KHÔNG
  chạy chiến lược lạ): `needs_rules` → `evaluate`; `needs_llm` → B14. Quyết định CHỈ qua `risk.strategy.decide` (bảng 5.3).
- Luật khớp (hybrid) → không gọi estimator/LLM (h18): `allow` → `S_EXECUTING`/B17; `approval_required` → B15; `deny` → E5 `policy_deny`
  (M2, ĐP 08/11 — tách khỏi lỗi lớp AI `llm_layer_disabled`; route, mã thoát không đổi).
- Không luật nào khớp → B14 `deps.estimator` — trích đoạn KB CHỈ qua `evidence_for_estimator` (Phase 4 S0-P9). Lỗi estimator
  (`LLMUnavailable`, `LLMSchemaError`, `LLMBudgetExceeded`) → E5 `llm_layer_disabled` "Không ước lượng được rủi ro → không tự làm".
  Có ước lượng → `kb_gap` trên phần bằng chứng THỰC gửi (Q-6C-4: ≤ `MAX_EVIDENCE` khối, trừ khối gateway cắt) → `decide`
  (calibrator None → không bao giờ AUTO, D-38; `kb_gap` → tối đa HITL, D-34). AUTO → B17 + `action_plan_hash` (D-42 — B17 chỉ nhận
  AUTO do LLM khi hash khớp); HITL → B15; chuyển L2 → E5 `llm_high_risk`.
- `full_auto` (Q-6-8 = C, chỉ EVAL_MODE — `check_strategy` lúc khởi động): không luật, không estimator, không `RiskDecision`
  (`risk=None` → cột `decided_by` NULL); điểm 4 `detail` đúng 3 khoá `{strategy, route: AUTO, policy_sha256}`; → B17 (không
  `action_plan_hash`) — B17 kiểm lại luật: `deny`/`approval_required`/không khớp → E5, chỉ `allow` thực thi.
- Điểm log 4 (3.6) qua `audit_detail` của chính lần `goto` + `policy_sha256`; ca LLM thêm `calibrated_prob`, `thresholds`, `factors`,
  `kb_gap`, `calibrator_version` (6C P5); `detail.strategy` ở MỌI đường điểm 4, cả lúc vận hành (D-67 thay Q-6C-3: trước chỉ khi EVAL_MODE). Dòng `lineage` cùng transaction
  audit; ca LLM thêm `prompt_id`, `prompt_version`, `model`, `calibrator_version`, `p_method`. Không lưu `rationale` (D-40).
- Mỗi nhánh một `goto` với `step`/`exit_code`/`escalation_reason_detail` hằng (P1). `step="B13/B14"`.
"""

import logging
from typing import Any, Literal, cast

from app.core.errors import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.core.hashing import hash_action
from app.domain.action import PARAMS_BY_ACTION, Action
from app.domain.exit_codes import ExitCode
from app.domain.facts import check_facts
from app.domain.intents import ANSWER_ONLY_INTENTS
from app.domain.states import S_ASSESSING, S_ESCALATED, S_EXECUTING
from app.domain.ticket_state import ChunkRef, RiskDecision
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.risk.context import build_ctx
from app.risk.estimator import MAX_EVIDENCE, RiskEstimate, evidence_for_estimator
from app.risk.policy_engine import evaluate
from app.risk.strategy import (
    RUNTIME_SELECTABLE,
    STRATEGIES,
    FullAutoBypass,
    Strategy,
    decide,
    needs_llm,
    needs_rules,
)
from app.settings import policy_sha256

log = logging.getLogger(__name__)
DEFAULT_STRATEGY: Strategy = "hybrid"  # trước D-67 chỉ có `hybrid` chạy lúc vận hành → ticket cũ (strategy NULL) chạy như vậy
LLM_DOWN_REASON = "Không ước lượng được rủi ro → không tự làm"  # B12 §5 [Đề xuất], phase3 11.3
_ROUTE: dict[str, Literal["AUTO", "HITL", "ESCALATE_L2"]] = {
    "allow": "AUTO", "approval_required": "HITL", "deny": "ESCALATE_L2",
}  # fmt: skip
_LEVEL: dict[str, Literal["low", "medium", "high"]] = {"allow": "low", "approval_required": "medium", "deny": "high"}
_POINT4 = ("decided_by", "policy_decision", "matched_rule_id", "risk_level", "reason", "route", "raw_prob", "p_method")


def _point4(decision: RiskDecision, all_matched: list[str]) -> dict[str, Any]:
    """Điểm log 4 (phase3 3.6) — định danh luật, enum, câu mô tả luật từ `policy.json`; không chữ người dùng."""
    data = decision.model_dump(mode="json")
    return {
        **{k: data[k] for k in _POINT4}, "all_matched": all_matched, "policy_version_id": None,
        "policy_sha256": policy_sha256(),
    }  # fmt: skip


def kb_gap(evidence: list[ChunkRef], est: RiskEstimate) -> bool:
    """6C P9 (N4, Q-6C-4): không còn khối bằng chứng nào THỰC tới LLM — estimator gửi tối đa `MAX_EVIDENCE` khối, gateway có thể
    cắt (`evidence_trimmed`). Rỗng → True. Q-6C-8: `evidence_trimmed` không phải `int` thật (kể cả `bool`) hoặc âm → coi là thiếu
    bằng chứng (estimator khác `LlmRiskEstimator` không được mở đường AUTO bằng số đếm sai)."""
    trimmed = est.evidence_trimmed
    if type(trimmed) is not int or trimmed < 0:  # `type(...) is int` loại cả bool (lớp con của int)
        return True
    return min(len(evidence), MAX_EVIDENCE) - trimmed <= 0


async def ticket_strategy(deps: NodeDeps, ticket_id: str) -> Strategy:
    """D-67: chiến lược đã chụp trên ticket. NULL (ticket cũ) → `hybrid`. Ngoài tập cho phép của chế độ hiện tại (không được xảy ra:
    route PUT chỉ nhận `RUNTIME_SELECTABLE`, ticket chỉ nhận chiến lược EVAL từ env đã qua `check_strategy`) → KHÔNG chạy chiến lược
    đó: `hybrid` + log cảnh báo (id ticket, không chữ người dùng)."""
    raw = await deps.tickets.strategy_of(ticket_id)
    if raw is None:
        return DEFAULT_STRATEGY
    allowed: frozenset[str] = STRATEGIES if deps.eval_mode else frozenset(RUNTIME_SELECTABLE)
    if raw not in allowed:
        log.warning("ticket %s: chiến lược %r ngoài tập cho phép của chế độ hiện tại — chạy %s", ticket_id, raw, DEFAULT_STRATEGY)
        return DEFAULT_STRATEGY
    return cast(Strategy, raw)


def make(deps: NodeDeps) -> NodeFn:
    async def b12_assess(state: Any) -> dict[str, Any]:
        if state.get("intent") in ANSWER_ONLY_INTENTS:  # D-76: intent chỉ-trả-lời không bao giờ tới M5 — tới đây là bug → E9
            raise ValueError(f"b12_assess nhận intent chỉ-trả-lời {state.get('intent')!r} — không bao giờ đánh giá hành động")
        action = Action.model_validate(state["intended_action"])  # thiếu = bug B11 → E9
        hours_mode = await deps.hours_mode.mode()  # D-97: chế độ giả lập giờ hành chính lúc đánh giá (`real` = giờ thật)
        ctx = build_ctx(state, current_run().clock.now(), deps.business_hours, hours_mode=hours_mode)
        strategy = await ticket_strategy(deps, state["ticket_id"])
        verdict = evaluate(action, ctx) if needs_rules(strategy) else None
        all_matched = list(verdict.all_matched) if verdict is not None else []
        lineage: dict[str, Any] = {"policy_version_id": None, "kb_version": state.get("kb_version"), "commit_sha": deps.commit_sha}
        mode: dict[str, Any] = {"strategy": strategy}  # D-67: ở MỌI đường điểm 4, cả lúc vận hành (trước: chỉ khi EVAL_MODE — Q-6C-3)
        if hours_mode != "real":  # D-97: ca chạy với giờ giả lập — truy được ở điểm 4 (giờ thật: không thêm khoá, detail như cũ)
            mode["hours_mode"] = hours_mode
        est: RiskEstimate | None = None
        gap = False
        if needs_llm(strategy, verdict):
            # Q-6C-9: kiểm lại đầu vào B14 (danh sách trắng N1 dựa vào `type` + `facts` tập đóng) — lệch = bug → E9 qua boundary,
            # NGOÀI nhánh bắt lỗi estimator (không thành E5 `llm_layer_disabled`); estimator không được gọi.
            check_facts(action.facts)
            if action.type not in PARAMS_BY_ACTION:
                raise ValueError("B14: action.type ngoài PARAMS_BY_ACTION")
            try:  # LỚP 2 (B14)
                evidence = evidence_for_estimator(
                    state.get("retrieved") or [], state.get("retrieval_score"), deps.constants.RETRIEVAL_THRESHOLD
                )  # S0-P9
                est = await deps.estimator.estimate(action, ctx, evidence)
            except (LLMUnavailable, LLMSchemaError, LLMBudgetExceeded) as exc:
                down = RiskDecision(
                    decided_by="llm", policy_decision=None, matched_rule_id=None, raw_prob=None, calibrated_prob=None,
                    p_method=None, risk_level="high", route="ESCALATE_L2", reason=LLM_DOWN_REASON, thresholds=None,
                )  # fmt: skip
                detail = {**_point4(down, all_matched), "estimator_error": type(exc).__name__, **mode}
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B13/B14", event="llm_layer_disabled",
                    audit_detail=detail, lineage=lineage, risk=down, exit_code=ExitCode.E5.value,
                    escalation_reason_detail="llm_layer_disabled",
                )  # fmt: skip
            gap = kb_gap(evidence, est)
        c = deps.constants
        outcome = decide(
            strategy, verdict, est, calibrator=deps.calibrator, thresholds=(c.THRESHOLD_LOW, c.THRESHOLD_HIGH),
            kb_gap=gap,
        )  # fmt: skip
        if isinstance(outcome, FullAutoBypass):  # 6C P4 (Q-6-8 = C): không `RiskDecision` → cột `decided_by` NULL; B17 kiểm lại luật
            return await goto(
                state, S_EXECUTING, next_node="b17_execute", step="B13/B14", event="risk_decided",
                audit_detail={"strategy": "full_auto", "route": "AUTO", "policy_sha256": policy_sha256()}, lineage=lineage,
                risk=None,
            )  # fmt: skip
        decision = outcome
        detail = {**_point4(decision, all_matched), **mode}
        llm_auto: dict[str, Any] = {}
        if decision.decided_by == "llm" and est is not None:  # 6C P5 — điểm 4 + lineage ca LLM (không `rationale`, D-40)
            cal_version = deps.calibrator.params.version if deps.calibrator is not None else None
            data = decision.model_dump(mode="json")
            detail |= {
                "calibrated_prob": data["calibrated_prob"], "thresholds": data["thresholds"],
                "factors": [f.value for f in est.factors], "kb_gap": gap, "calibrator_version": cal_version,
            }  # fmt: skip
            lineage |= {
                "prompt_id": est.prompt_id, "prompt_version": est.prompt_version, "model": est.model,
                "calibrator_version": cal_version, "p_method": est.p_method,
            }  # fmt: skip
            llm_auto = {"action_plan_hash": hash_action(action)}  # D-42: B17 nhận AUTO do LLM chỉ khi hash khớp
        if decision.route == "AUTO":
            return await goto(
                state, S_EXECUTING, next_node="b17_execute", step="B13/B14", event="risk_decided",
                audit_detail=detail, lineage=lineage, risk=decision, **llm_auto,
            )  # fmt: skip
        if decision.route == "HITL":
            return await goto(
                state, S_ASSESSING, next_node="b15_prepare_approval", step="B13/B14", event="risk_decided",
                audit_detail=detail, lineage=lineage, risk=decision,
            )  # fmt: skip
        if decision.decided_by == "llm":  # 6C P3: LLM chuyển L2 — mã riêng, khác lỗi estimator (`llm_layer_disabled`)
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B13/B14", event="risk_decided",
                audit_detail=detail, lineage=lineage, risk=decision, exit_code=ExitCode.E5.value,
                escalation_reason_detail="llm_high_risk",
                risk_factors=[f.value for f in est.factors] if est is not None else None,  # D-98: chỉ B20 đọc (vế lý do)
            )  # fmt: skip
        return await goto(  # luật `deny` (M2: lý do riêng, khác lỗi estimator `llm_layer_disabled`)
            state, S_ESCALATED, next_node="b20_audit", step="B13/B14", event="risk_decided",
            audit_detail=detail, lineage=lineage, risk=decision, exit_code=ExitCode.E5.value,
            escalation_reason_detail="policy_deny",
        )  # fmt: skip

    return b12_assess
