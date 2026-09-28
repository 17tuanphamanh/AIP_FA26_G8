"""B2 — sàng lọc prompt injection THẬT (B02 mục 2, 5; thiết kế Phase 3 mục 8.5; PLAN-3e).

Thứ tự rẻ → đắt, không lớp nào "mở cửa" khi lớp trước lỗi:
1. L2 regex (`guard.injection.match`, L0 bên trong): khớp → E0 `S_BLOCKED`, `layer_decided=regex`.
2. L3 `deps.ml.classify` (Phase 3 luôn `model_missing` → xuống L4 ngay, không retry): `p_mal ≥ TAU_BLOCK` → E0;
   `≤ TAU_PASS` → qua; giữa hai ngưỡng HOẶC lỗi → L4.
3. L4 LLM fast `b02_injection_judge` (prompt riêng, không cache — [Chốt 17.5]): `is_attack` → E0, không → qua.
   `LLMUnavailable`/`LLMBudgetExceeded`/`LLMSchemaError` → E2 `S_ESCALATED` + `security_flag` +
   `screening_unavailable` (không đi tiếp khi chưa sàng lọc được, nhưng cũng không gắn nhãn tấn công — B02 mục 6).

E0: `security_events(injection_detected)` QUA `effects.once("security_event")` (chạy lại node không ghi hai lần);
`detail`/`screening` KHÔNG chứa câu người dùng. Tin trung tính cho người dùng do B20 gửi theo mẫu E0 sẵn có (không nêu
lớp/mẫu nào bắt). Lỗi khác (`ScriptExhausted`, `PromptContractError`, `MlContractError`…) là bug → boundary → E9.
"""

from typing import Any

from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import S_BLOCKED, S_CLASSIFYING, S_ESCALATED
from app.graph import effects
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard import injection
from app.guard.injection import TAU_BLOCK, TAU_PASS
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import InjectionJudgeOut


def make(deps: NodeDeps) -> NodeFn:
    async def b02_screen(state: Any) -> dict[str, Any]:
        text = state["redacted_request"]
        if (hit := injection.match(text)) is not None:  # L2 (L0 bên trong)
            return await _block(state, layer_decided="regex", pattern_id=hit.id, group=hit.group)
        r = await deps.ml.classify(text)  # L3 — Phase 3 luôn model_missing
        p_mal = r.data.p_malicious if r.error is None and r.data is not None else None
        if p_mal is not None:
            if p_mal >= TAU_BLOCK:
                return await _block(state, layer_decided="classifier", p_mal=p_mal)
            if p_mal <= TAU_PASS:
                return await _pass(state, layer_decided="classifier", p_mal=p_mal)
        try:  # L4: vùng giữa HOẶC L3 lỗi
            out, _ = await deps.llm.complete(
                "fast", "b02_injection_judge", {"text": text}, InjectionJudgeOut, cache_policy="bypass"
            )
        except (LLMUnavailable, LLMBudgetExceeded, LLMSchemaError) as exc:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B2", event="guard_unavailable",
                audit_detail={"ml_error": r.error, "llm_error": type(exc).__name__},
                exit_code=ExitCode.E2.value, security_flag=True,
                escalation_reason_detail="screening_unavailable",
            )  # fmt: skip
        if out.is_attack:
            return await _block(state, layer_decided="llm", p_mal=p_mal, llm_category=out.category)
        return await _pass(state, layer_decided="llm", p_mal=p_mal)

    async def _block(state: Any, **info: Any) -> dict[str, Any]:
        # `info` chỉ có lớp, id/nhóm mẫu, p_mal, loại của L4 — KHÔNG có câu người dùng (8.5)
        await effects.once(
            state, "security_event", deps.security_events.record, "injection_detected",
            ticket_id=state["ticket_id"], detail=info, step="B2",
        )  # fmt: skip
        return await goto(
            state, S_BLOCKED, next_node="b20_audit", step="B2", event="injection_detected",
            exit_code=ExitCode.E0.value, block_reason=BlockReason.INJECTION_DETECTED.value,
            close_reason=CloseReason.BLOCKED_INJECTION_DETECTED.value, screening=info,
        )  # fmt: skip

    async def _pass(state: Any, **info: Any) -> dict[str, Any]:
        return await goto(
            state, S_CLASSIFYING, next_node="b03_classify", step="B2", event="screened", screening=info
        )

    return b02_screen
