"""B3–B4 — node THẬT, Phase 3 chỉ VPN (thiết kế mục 9.3; PLAN-3f chốt Q-3f-2…6). Node giả (Phase 2, `FAKE_SCENARIO`):
`graph/nodes/fake/b03_classify.py`. Tách ý + ticket con (B5): Phase 5.

1. `reasoning_loops + 1 > MAX_LOOPS` → E2 `max_loops_exceeded`.
2. `deps.ml.classify_intent` — Phase 3 luôn `model_missing`; lỗi hạ tầng cũng vậy → xuống LLM. Có kết quả (model đã có) ở
   Phase 3 VẪN xuống LLM, chỉ ghi `model_probs`/`model_version` (nhánh model + `cascade_decide`: Phase 5).
3. LLM fast `b03_classify` (`ClassifyOut`): `LLMSchemaError` → E2 `llm_schema_error`; `LLMUnavailable`/`LLMBudgetExceeded`
   → E2 `llm_unavailable`; hết hạn cả lượt (ở ml hoặc LLM) → E2 `turn_budget_exceeded`.
4. Thứ tự kiểm CỐ ĐỊNH (mỗi ca E1 đúng một `reason_detail`): không ý nào trong phạm vi → `out_of_scope` → có ≥ 2 ý (đếm
   MỌI ý, kể cả ý ngoài phạm vi — Q-3f-6; câu xã giao không phải ý, prompt v2) → `multi_intent_not_enabled` → confidence <
   `TAU_INTENT` → `intent_low_confidence` → intent ∉ `ENABLED_INTENTS` → `intent_not_enabled`.
5. Còn lại: `sanitize_slots` (3-Q1; P1, P2, Q-3f-3) → `S_DIAGNOSING` → B6, `facts={}` (B3 KHÔNG BAO GIỜ ghi fact — G-01).
   `span` chỉ giữ khi là đoạn con của câu người dùng (Q-3f-4).

Điểm log 1 ở MỌI nhánh (kể cả lỗi) qua `audit_detail`: lớp, intent, confidence, prompt id@version, lỗi ml/LLM (tên lớp),
slot bị bỏ (chỉ key đã khai báo — Q-3f-5), `slot_fact_collision`, `span_not_in_text`. KHÔNG có câu người dùng hay giá trị
slot. E1 ghi `step="B4"`, còn lại `"B3"`. Không `except Exception` — lỗi khác (`ScriptExhausted`, `MlContractError`…) → E9.
"""

from typing import Any

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.exit_codes import ExitCode
from app.domain.slots import audit_dropped, phrase_in_text, sanitize_slots
from app.domain.states import S_DIAGNOSING, S_ESCALATED
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard.normalize import l0
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import ClassifyOut

RECENT_MESSAGES = 4  # B03 mục 2: ≤ 4 tin gần nhất


def _point1() -> dict[str, Any]:
    return {
        "layer": None, "intent": None, "confidence": None, "is_multi": None, "model_probs": None,
        "model_version": None, "prompt": None, "ml_error": None, "llm_error": None, "span_not_in_text": False,
        **audit_dropped({}, frozenset()),
    }  # fmt: skip


def make(deps: NodeDeps) -> NodeFn:
    known = deps.slots.declared_names

    async def b03_classify(state: Any) -> dict[str, Any]:
        loops = int(state.get("reasoning_loops") or 0) + 1
        info = _point1()
        if loops > deps.constants.MAX_LOOPS:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B3", event="max_loops_exceeded", audit_detail=info,
                exit_code=ExitCode.E2.value, reasoning_loops=loops, escalation_reason_detail="max_loops_exceeded",
            )  # fmt: skip
        try:
            return await _classify(state, loops, info)
        except TurnBudgetExceeded:  # 9.0: ml hoặc LLM — không cho qua, không E9
            info["llm_error" if info["layer"] == "llm" else "ml_error"] = "TurnBudgetExceeded"
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B3", event="turn_budget_exceeded", audit_detail=info,
                exit_code=ExitCode.E2.value, reasoning_loops=loops, escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip

    async def _classify(state: Any, loops: int, info: dict[str, Any]) -> dict[str, Any]:
        text = l0(state["redacted_request"])
        r = await deps.ml.classify_intent(text)
        info["ml_error"] = r.error
        if r.data is not None:  # Phase 3: không tới (model_missing) — có model thì chỉ ghi, vẫn xuống LLM
            info["model_probs"], info["model_version"] = dict(r.data.probs), r.data.version
        info["layer"] = "llm"
        recent = list(state.get("conversation") or [])[-RECENT_MESSAGES:]
        try:
            out, meta = await deps.llm.complete(
                "fast", "b03_classify",
                {"redacted_request": text, "recent_messages": recent, "label_hint": None}, ClassifyOut,
            )  # fmt: skip
        except LLMSchemaError:
            info["llm_error"] = "LLMSchemaError"
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B3", event="classifier_unavailable",
                audit_detail=info, exit_code=ExitCode.E2.value, reasoning_loops=loops,
                escalation_reason_detail="llm_schema_error",
            )  # fmt: skip
        except (LLMUnavailable, LLMBudgetExceeded) as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B3", event="classifier_unavailable",
                audit_detail=info, exit_code=ExitCode.E2.value, reasoning_loops=loops,
                escalation_reason_detail="llm_unavailable",
            )  # fmt: skip
        info["prompt"], info["is_multi"] = f"{meta.prompt_id}@{meta.prompt_version}", out.is_multi
        in_scope = [i for i in out.intents if i.type != "out_of_scope"]
        if not in_scope:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_out_of_scope", audit_detail=info,
                exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="out_of_scope",
            )  # fmt: skip
        if len(out.intents) >= 2:  # Q-3f-6: MỌI ý (vpn + ngoài phạm vi = 2 ý) — Phase 5 → B5 tách ticket con
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="multi_intent_not_enabled",
                audit_detail=info, exit_code=ExitCode.E1.value, reasoning_loops=loops,
                escalation_reason_detail="multi_intent_not_enabled",
            )  # fmt: skip
        it = in_scope[0]
        info["intent"], info["confidence"] = it.type, it.confidence
        if it.confidence < deps.constants.TAU_INTENT:  # D-27: không chắc thì không đoán
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_low_confidence",
                audit_detail=info, exit_code=ExitCode.E1.value, reasoning_loops=loops,
                escalation_reason_detail="intent_low_confidence",
            )  # fmt: skip
        if it.type not in deps.enabled_intents:  # 3-Q27
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_not_enabled", audit_detail=info,
                exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="intent_not_enabled",
            )  # fmt: skip
        raw = {**it.slots, **({"action": it.action_hint} if it.action_hint else {})}
        slots, dropped = sanitize_slots(deps.slots.intents[it.type], raw, text=text)  # 3-Q1: cửa DUY NHẤT
        span = it.span if it.span.strip() and phrase_in_text(it.span, text) else None  # Q-3f-4
        info.update(audit_dropped(dropped, known), span_not_in_text=bool(it.span.strip()) and span is None)
        return await goto(
            state, S_DIAGNOSING, next_node="b06_diagnose", step="B3", event="intent_classified", audit_detail=info,
            intent=it.type, intent_confidence=it.confidence, span=span, slots=slots, facts={}, reasoning_loops=loops,
        )  # fmt: skip

    return b03_classify
