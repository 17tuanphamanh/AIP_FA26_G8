"""B12–B14 — node GIẢ (Phase 2a). Luật + LLM hiệu chỉnh thật: Phase 3/6."""

from typing import Any

from app.domain.exit_codes import ExitCode
from app.domain.states import S_ASSESSING, S_ESCALATED, S_EXECUTING
from app.graph.fakes import NodeDeps, fake_risk
from app.graph.goto import goto
from app.graph.tracing import NodeFn


def make(deps: NodeDeps) -> NodeFn:
    async def b12_assess(state: Any) -> dict[str, Any]:
        outcome = deps.scenario.pick(state, "b12_assess")
        if outcome == "auto":
            return await goto(
                state, S_EXECUTING, next_node="b17_execute", step="B13/B14", event="risk_decided",
                risk=fake_risk("AUTO"),
            )  # fmt: skip
        if outcome == "deny":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B13/B14", event="risk_decided",
                risk=fake_risk("ESCALATE_L2"), exit_code=ExitCode.E5.value,
            )  # fmt: skip
        if outcome == "high_risk":  # E5 do LLM ước lượng rủi ro cao — KHÔNG có luật deny khớp
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B13/B14", event="risk_decided",
                risk=fake_risk("ESCALATE_L2").model_copy(
                    update={"decided_by": "llm", "policy_decision": None, "matched_rule_id": None,
                            "calibrated_prob": 0.9}),
                exit_code=ExitCode.E5.value,
            )  # fmt: skip
        return await goto(
            state, S_ASSESSING, next_node="b15_prepare_approval", step="B13/B14",
            event="risk_decided", risk=fake_risk("HITL"),
        )  # fmt: skip

    return b12_assess
