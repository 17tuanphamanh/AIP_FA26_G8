"""B11 — node THẬT, Phase 3 chỉ VPN (phase3 mục 10.4; PLAN-3g chốt P4–P8, P6 (a), Q-3g-6, Q-3g-7, f4). Node giả (Phase 2,
`FAKE_SCENARIO`): `graph/nodes/fake/b11_slots.py`. Node chờ: `graph/nodes/clarify_wait.py`.

1. `missing` = slot bắt buộc (`config/slots.yaml`) chưa có trong `slots`.
2. Đủ slot → `validate_targets` (P6 (a)): gọi SONG SONG đúng các tool có `device_id` trong `arg_slots`
   (`check_device_registered`, `check_vpn_cert_expiry`; `caller_step="B11"`) cho `slots.device_id`. Lỗi hệ thống → E2
   `target_check_error`; 404/rỗng = dữ liệu (máy không tồn tại → `device_registered=false`, luật quyết). `infer_vpn` (tên
   thật) tính lại fact PHỤ THUỘC MÁY: bỏ mọi giá trị máy cũ, giữ fact theo người; BỎ `slots` mà `infer_vpn` trả (không tự đặt
   `action`/`device_id` — máy người khác không bao giờ sinh hành động). `build_action` chỉ từ slot đã sanitize + metadata +
   facts (P8; key lạ → `FactKeyViolation` → E9).
   **Căn cứ quy trình (Phase 4 S0-P10, Q-4-U A+, D-34):** sau `build_action`, TRƯỚC `goto(S_ASSESSING)`: tài liệu
   `ActionMeta.procedure_doc` của `action_type` phải có trong KB HIỆN HÀNH (alias đọc lúc này — chốt S0-A3, không dùng
   `kb_version` ghim ở B8), enabled, người gửi được xem (`RagPort.procedure_available`, `base_filter`). Không → E3
   `no_procedure` (kèm `intended_action` để L2 thấy hành động dự kiến); `RetrievalSystemError` → E2 `rag_system_error`.
   Có → `S_ASSESSING`; audit `procedure_doc` + `procedure_kb_version`.
3. Đã hỏi đủ `MAX_CLARIFICATION_TURNS` lượt mà vẫn thiếu → E4 `clarification_exhausted`.
4. Hỏi ≤ 2 slot: LLM fast `b11_clarify_question` (`diagnostics_summary` = `facts` + `device_id` các máy CỦA người gửi — f4)
   → output guard (P4) → vi phạm: E3 `output_guard_block`, 0 tin. `notify_user` (needs=answer) + hạn `clarify` 24 h qua
   `effects.once`, khoá RIÊNG từng lượt hỏi (`sub=f"q{n}"`, P5) → `S_CLARIFYING`.

Lỗi LLM → E2 `llm_schema_error`/`llm_unavailable`; hết hạn cả lượt (LLM hoặc tool) → E2 `turn_budget_exceeded`, bắt tường
minh (`step="B11"`). Không `except Exception`. Chẩn đoán lại D-20: không có ở 3g (Q-3g-7 — cờ bật thì không khởi động).
Audit `detail`: tên slot thiếu, lượt hỏi, tool đã gọi, `facts` (enum/bool/int) — không câu người dùng, không chữ LLM.
"""

import asyncio
from datetime import timedelta
from typing import Any

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.action import build_action
from app.domain.exit_codes import ExitCode
from app.domain.messages import question_msg
from app.domain.states import S_ASSESSING, S_CLARIFYING, S_ESCALATED
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.ports import ToolResult
from app.graph.tracing import NodeFn
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import QuestionOut
from app.rag.models import RetrievalSystemError
from app.tools.diagnosis import vpn
from app.tools.retry import retries_of


def _info(missing: list[str], turns: int) -> dict[str, Any]:
    return {"missing": missing, "turn": turns, "prompt": None, "llm_error": None, "guard": None, "tools_called": [],
            "tool_retry_count": 0, "facts": None, "procedure_doc": None, "procedure_kb_version": None,
            "rag_error": None}  # fmt: skip


def _error_kind(error: str) -> str:
    """"TimeoutException: …url…" → "TimeoutException" — không chép URL (có user_id/device_id) vào state/audit."""
    return error.split(":", 1)[0].strip()[:64]


def diagnostics_summary(state: Any, facts: dict[str, Any]) -> dict[str, Any]:
    """f4: chỉ enum/bool/số (`facts`) + `device_id` các máy CỦA người gửi (B6 tra theo `user_id`) — không chữ tự do."""
    requester = state["requester_context"].user_id
    devices = (state.get("diagnostics") or {}).get("check_device_registered") or []
    return {"facts": dict(facts), "devices": [d["device_id"] for d in devices if d.get("owner_id") == requester]}


def make(deps: NodeDeps) -> NodeFn:
    async def b11_slots(state: Any) -> dict[str, Any]:
        spec = deps.slots.intents[state["intent"]]
        slots = dict(state.get("slots") or {})
        missing = [s for s in spec.required if s not in slots]
        info = _info(missing, int(state.get("clarification_turns") or 0))
        try:
            return await (_ask(state, missing, info) if missing else _build(state, slots, info))
        except TurnBudgetExceeded:  # 9.0: ở LLM hoặc tool — không cho qua, không E9
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="turn_budget_exceeded", audit_detail=info,
                exit_code=ExitCode.E2.value, missing_slots=missing, escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip

    async def _build(state: Any, slots: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
        requester = state["requester_context"].user_id
        calls = vpn.target_calls(requester, slots["device_id"])
        info["tools_called"] = [t for t, _ in calls]
        results = await _gather(calls)
        retries = sum(retries_of(r.attempts, failed=r.error is not None) for r in results)
        info["tool_retry_count"] = retries
        if errors := [f"{r.tool}: {_error_kind(r.error)}" for r in results if r.error is not None]:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="target_check_error",
                audit_detail={**info, "tool_errors": errors}, exit_code=ExitCode.E2.value, tool_errors=errors,
                tool_retry_count=retries, escalation_reason_detail="target_check_error",
            )  # fmt: skip
        diag = {t: None for t in vpn.TOOLS} | {r.tool: (None if r.empty else r.data) for r in results}
        _, fresh = vpn.infer_vpn(diag, requester_id=requester, device_id=slots["device_id"])  # slots trả về: BỎ (P6)
        kept = {k: v for k, v in (state.get("facts") or {}).items() if k not in vpn.DEVICE_FACTS}
        facts = kept | {k: v for k, v in fresh.items() if k in vpn.DEVICE_FACTS}
        info["facts"] = facts
        metadata = deps.action_metadata[state["intent"]]
        action = build_action(state["intent"], slots, facts, state["requester_context"], metadata)
        info["procedure_doc"] = doc = metadata[action.type].procedure_doc
        try:  # S0-P10: căn cứ của hành động = quy trình khai báo có mặt trong KB hiện hành (kiểm tất định, không độ giống)
            check = await deps.rag.procedure_available(doc, state["requester_context"])
        except RetrievalSystemError as exc:
            info["rag_error"] = exc.stage
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="rag_system_error", audit_detail=info,
                exit_code=ExitCode.E2.value, retrieval_error=exc.stage, tool_retry_count=retries,
                escalation_reason_detail="rag_system_error",
            )  # fmt: skip
        info["procedure_kb_version"] = check.kb_version
        if not check.available:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="no_procedure", audit_detail=info,
                exit_code=ExitCode.E3.value, intended_action=action, facts=facts, missing_slots=[],
                tool_retry_count=retries, escalation_reason_detail="no_procedure",
            )  # fmt: skip
        return await goto(
            state, S_ASSESSING, next_node="b12_assess", step="B11", event="action_built", audit_detail=info,
            intended_action=action, facts=facts, missing_slots=[], tool_retry_count=retries,
        )  # fmt: skip

    async def _ask(state: Any, missing: list[str], info: dict[str, Any]) -> dict[str, Any]:
        turns = info["turn"]
        if turns >= deps.constants.MAX_CLARIFICATION_TURNS:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="clarification_exhausted",
                audit_detail=info, exit_code=ExitCode.E4.value, missing_slots=missing,
                escalation_reason_detail="clarification_exhausted",
            )  # fmt: skip
        summary = diagnostics_summary(state, dict(state.get("facts") or {}))
        try:
            q, meta = await deps.llm.complete(
                "fast", "b11_clarify_question",
                {"missing": missing[:2], "intent": state["intent"], "diagnostics_summary": summary}, QuestionOut,
            )  # fmt: skip
        except LLMSchemaError as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="llm_schema_error", audit_detail=info,
                exit_code=ExitCode.E2.value, missing_slots=missing, escalation_reason_detail="llm_schema_error",
            )  # fmt: skip
        except (LLMUnavailable, LLMBudgetExceeded) as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="llm_unavailable", audit_detail=info,
                exit_code=ExitCode.E2.value, missing_slots=missing, escalation_reason_detail="llm_unavailable",
            )  # fmt: skip
        info["prompt"] = f"{meta.prompt_id}@{meta.prompt_version}"
        info["guard"] = deps.output_guard.violation(q.text)
        if info["guard"] is not None:  # P4: câu hỏi do LLM viết cũng là chữ sắp gửi người dùng
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="output_guard_block", audit_detail=info,
                exit_code=ExitCode.E3.value, missing_slots=missing, escalation_reason_detail="output_guard_block",
            )  # fmt: skip
        n = turns + 1
        run = current_run()
        ref = await effects.once(
            state, "notify_user", deps.notifier.notify_user, state["ticket_id"], q.text, "answer", step="B11",
            sub=f"q{n}",
        )  # fmt: skip
        deadline = run.clock.now() + timedelta(hours=deps.constants.CLARIFY_TIMEOUT_HOURS)
        await effects.once(
            state, "deadline_set", deps.deadlines.set, state["ticket_id"], "clarify", deadline, run.turn_id, step="B11",
            sub=f"q{n}",
        )  # fmt: skip
        return await goto(
            state, S_CLARIFYING, next_node="clarify_wait", step="B11", event="asked", audit_detail=info,
            clarification_turns=n, missing_slots=missing, conversation=[question_msg(q.text, ref)],
        )  # fmt: skip

    async def _gather(calls: list[tuple[str, dict[str, str]]]) -> list[ToolResult]:
        """Như B6: song song, mọi lời gọi tự cắt theo hạn lượt ở registry; lỗi hợp đồng ưu tiên ném (E9), sau đó hết hạn."""
        outs = await asyncio.gather(
            *[deps.directory.call(t, a, caller_step="B11") for t, a in calls], return_exceptions=True
        )
        excs = [o for o in outs if isinstance(o, BaseException)]
        if bug := next((e for e in excs if not isinstance(e, TurnBudgetExceeded)), None):
            raise bug
        if excs:
            raise excs[0]
        return [o for o in outs if not isinstance(o, BaseException)]

    return b11_slots
