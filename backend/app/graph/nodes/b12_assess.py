"""B12–B13 — node THẬT (Phase 3 chặng 3h; phase3 mục 11.3, B12-B14 §5). Gate2 (`FAKE_SCENARIO`) dùng bản giả
`graph/nodes/fake/b12_assess.py`.

Input DUY NHẤT của M5: `intended_action` + `build_ctx(state, now, business_hours)` — `build_ctx` chỉ đọc `intended_action`,
`requester_context`, `ctx_flags` (P2, h21); `now` = Clock của lượt. `evaluate(action, ctx)` giữ chữ ký (h22).

- Luật khớp → trả ngay, KHÔNG gọi estimator/LLM (h18): `allow` → `S_EXECUTING`/B17; `approval_required` → B15 (tạo phiếu,
  `S_PENDING_APPROVAL`); `deny` → E5 (không vào hàng đợi duyệt [Chốt]).
- Không luật nào khớp → B14 `deps.estimator` — trích đoạn KB CHỈ qua `evidence_for_estimator` (Phase 4 S0-P9: dưới ngưỡng
  truy hồi → `[]`; không đọc thẳng `state["retrieved"]`). Phase 3 là `DisabledEstimator` (3-Q30): ném `LLMUnavailable` → E5
  `llm_layer_disabled`, "Không ước lượng được rủi ro → không tự làm". Estimator TRẢ về xác suất ở Phase 3 = cấu hình sai
  (lớp 2 chưa hiện thực) → ném lỗi → E9 qua boundary, không bao giờ tự làm (M-3h-9).
- Điểm log 4 (3.6) qua `audit_detail` của chính lần `goto` + `policy_sha256` (3-Q29, `policy_version_id` NULL ở Phase 3);
  dòng `lineage` cùng transaction audit (`goto(lineage=…)`, như B10 3g); `commit_sha` = `deps.commit_sha` (Phase 4 P4).
- Mỗi nhánh một `goto` với `step`/`exit_code`/`escalation_reason_detail` hằng (P1). `step="B13/B14"` như bản giả / mã giả B12 §5.
"""

from typing import Any, Literal

from app.core.errors import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.domain.action import Action
from app.domain.exit_codes import ExitCode
from app.domain.states import S_ASSESSING, S_ESCALATED, S_EXECUTING
from app.domain.ticket_state import RiskDecision
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.risk.context import build_ctx
from app.risk.estimator import evidence_for_estimator
from app.risk.policy_engine import evaluate
from app.settings import policy_sha256

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


def make(deps: NodeDeps) -> NodeFn:
    async def b12_assess(state: Any) -> dict[str, Any]:
        action = Action.model_validate(state["intended_action"])  # thiếu = bug B11 → E9
        ctx = build_ctx(state, current_run().clock.now(), deps.business_hours)
        verdict = evaluate(action, ctx)
        lineage = {"policy_version_id": None, "kb_version": state.get("kb_version"), "commit_sha": deps.commit_sha}
        if verdict.matched and verdict.decision is not None:
            decision = RiskDecision(
                decided_by="rule", policy_decision=verdict.decision, matched_rule_id=verdict.rule_id,
                raw_prob=None, calibrated_prob=None, p_method=None, risk_level=_LEVEL[verdict.decision],
                route=_ROUTE[verdict.decision], reason=verdict.description or verdict.rule_id or "",
                thresholds=None,
            )  # fmt: skip
            detail = _point4(decision, verdict.all_matched)
            if verdict.decision == "allow":
                return await goto(
                    state, S_EXECUTING, next_node="b17_execute", step="B13/B14", event="risk_decided",
                    audit_detail=detail, lineage=lineage, risk=decision,
                )  # fmt: skip
            if verdict.decision == "approval_required":
                return await goto(
                    state, S_ASSESSING, next_node="b15_prepare_approval", step="B13/B14", event="risk_decided",
                    audit_detail=detail, lineage=lineage, risk=decision,
                )  # fmt: skip
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B13/B14", event="risk_decided",
                audit_detail=detail, lineage=lineage, risk=decision, exit_code=ExitCode.E5.value,
            )  # fmt: skip
        try:  # LỚP 2 (B14) — chỉ khi không luật nào khớp
            evidence = evidence_for_estimator(
                state.get("retrieved") or [], state.get("retrieval_score"), deps.constants.RETRIEVAL_THRESHOLD
            )  # S0-P9
            await deps.estimator.estimate(action, ctx, evidence)
        except (LLMUnavailable, LLMSchemaError, LLMBudgetExceeded) as exc:
            decision = RiskDecision(
                decided_by="llm", policy_decision=None, matched_rule_id=None, raw_prob=None, calibrated_prob=None,
                p_method=None, risk_level="high", route="ESCALATE_L2", reason=LLM_DOWN_REASON, thresholds=None,
            )  # fmt: skip
            detail = {**_point4(decision, []), "estimator_error": type(exc).__name__}
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B13/B14", event="llm_layer_disabled",
                audit_detail=detail, lineage=lineage, risk=decision, exit_code=ExitCode.E5.value,
                escalation_reason_detail="llm_layer_disabled",
            )  # fmt: skip
        raise RuntimeError("B14 trả xác suất nhưng lớp LLM rủi ro chưa hiện thực ở Phase 3 (3-Q30) — không tự làm")

    return b12_assess
