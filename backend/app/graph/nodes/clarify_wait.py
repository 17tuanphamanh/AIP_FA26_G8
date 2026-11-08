"""Node chờ `S_CLARIFYING` (B11) — node THẬT (phase3 mục 10.4, 8.6; PLAN-3g chốt P2, P3, Q-3g-4). Bản giả (gate2,
`FAKE_SCENARIO`): `graph/nodes/fake/clarify_wait.py`. KHÔNG side effect nào trước `interrupt()` — resume chạy lại node từ đầu.

Sau `interrupt()`, thứ tự cố định:
1. `screen_reply` (L0 + L2) trên câu trả lời — khớp → `security_events(injection_detected)` qua `effects.once` → E0
   `injection_in_reply`; câu trả lời KHÔNG vào `conversation`, không gọi LLM (3-Q3).
2. Hết hạn 24 h (worker) → E4 `clarify_timeout`.
3. Che L1 bằng `redact_text` THUẦN (P3, Q-3g-4 — API đã che, node không tin đầu vào; không ghi sự kiện/notice lần hai). Từ
   đây CHỈ bản đã che được gửi LLM, đưa vào `sanitize_slots`, lưu `conversation`; bản thô không lưu ở đâu cả.
4. LLM fast `b11_extract_slots` (biến `question` = chữ của tin `kind="question"` CUỐI trong `conversation` — câu B11 vừa gửi, đã qua
   dọn khoá slot + output guard, kể cả câu cố định L-03; không có → "" — M4 bn-a) → `sanitize_slots(spec, got.slots, text=bản đã che,
   allowed=missing)` (P2: slot phải có trong CÂU TRẢ LỜI — câu hỏi KHÔNG vào `text`, chỉ nhận slot đang thiếu, key fact bị bỏ — 3-Q1). Không slot sạch hoặc LLM báo lạc đề → `off_topic_streak`+1;
   2 lần liên tiếp → E4 `off_topic_twice` [Chốt].
5. Còn lại → `S_CLARIFYING` → `b11_slots` (hỏi tiếp hoặc dựng Action).
   Q-T20a-6 (Phase 5 T20a, duyệt DỪNG 2): `target_user` bị `sanitize_slots` bỏ (BẤT KỲ lý do, kể cả `unknown_key` vì không phải
   slot đang thiếu) → người dùng nhắm NGƯỜI KHÁC ở lượt trả lời → ghi `ctx_flags={"target_is_other": True}` (như B3, Q-T20a-4);
   không thêm giá trị slot vào audit. B11 không ghi `ctx_flags`; B12 `build_ctx` đọc.
   be-target-guard (L-03): cờ còn bật khi intent ∈ {account, access}, slot (đã gộp) CHƯA có `target_user` hợp lệ VÀ câu TRẢ LỜI nêu
   người khác hoặc có khoá bị bỏ `unknown_key` NGOÀI `spec.keys` (khoá đã khai báo mà không đang hỏi KHÔNG tính) —
   `domain/target.target_check`. Không bao giờ hạ cờ. `detail` thêm `other_target_mention`, `other_target_reason` (không câu/token).

Lỗi LLM → E2 `llm_schema_error`/`llm_unavailable`; hết hạn cả lượt → E2 `turn_budget_exceeded` (bắt tường minh, `step="B11"`).
Audit `detail`: key slot bị bỏ + lý do (chỉ key đã khai báo — Q-3f-5), cờ lạc đề — không câu người dùng, không giá trị slot.
"""

from typing import Any

from langgraph.types import interrupt

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.exit_codes import ExitCode
from app.domain.messages import last_question, user_msg
from app.domain.slots import audit_dropped, sanitize_slots
from app.domain.states import S_CLARIFYING, S_ESCALATED
from app.domain.target import requester_id_of, target_check
from app.graph import effects
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard.screen import screen_reply
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import ExtractSlotsOut


def make(deps: NodeDeps) -> NodeFn:
    known = deps.slots.declared_names

    async def clarify_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "clarify"})
        raw = str(ev.get("text") or "")
        if (hit := screen_reply(raw)) is not None:  # 3-Q3: trước mọi nhánh, trước khi che hay gửi LLM
            await effects.once(
                state, "security_event", deps.security_events.record, "injection_detected",
                ticket_id=state["ticket_id"], detail={"layer": "regex_reply", "pattern_id": hit.id}, step="B11",
            )  # fmt: skip
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="injection_in_reply",
                exit_code=ExitCode.E0.value, escalation_reason_detail="injection_in_reply",
            )  # fmt: skip
        if ev["kind"] == "timeout":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="clarify_timeout",
                exit_code=ExitCode.E4.value, escalation_reason_detail="clarify_timeout",
            )  # fmt: skip
        text = deps.privacy.redact_text(raw).text  # P3: từ đây chỉ dùng bản ĐÃ CHE
        info: dict[str, Any] = {"prompt": None, "llm_error": None, "off_topic": None, "streak": None,
                                "other_target_mention": False, "other_target_reason": None,
                                **audit_dropped({}, known)}  # fmt: skip
        try:
            return await _extract(state, text, info)
        except TurnBudgetExceeded:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="turn_budget_exceeded", audit_detail=info,
                exit_code=ExitCode.E2.value, conversation=[user_msg(text)],
                escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip

    async def _extract(state: Any, text: str, info: dict[str, Any]) -> dict[str, Any]:
        missing = list(state.get("missing_slots") or [])
        try:
            got, meta = await deps.llm.complete(
                "fast", "b11_extract_slots",
                {"text": text, "missing": missing, "intent": state["intent"], "question": last_question(state)},
                ExtractSlotsOut,
            )  # fmt: skip
        except LLMSchemaError as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="llm_schema_error", audit_detail=info,
                exit_code=ExitCode.E2.value, conversation=[user_msg(text)], escalation_reason_detail="llm_schema_error",
            )  # fmt: skip
        except (LLMUnavailable, LLMBudgetExceeded) as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="llm_unavailable", audit_detail=info,
                exit_code=ExitCode.E2.value, conversation=[user_msg(text)], escalation_reason_detail="llm_unavailable",
            )  # fmt: skip
        spec = deps.slots.intents[state["intent"]]
        clean, dropped = sanitize_slots(spec, got.slots, text=text, allowed=frozenset(missing))  # 3-Q1 + P2: cửa DUY NHẤT
        merged = {**(state.get("slots") or {}), **clean}
        mention, reason = target_check(state["intent"], merged, dropped, spec.keys, text, requester_id_of(state))  # L-03
        streak = 0 if clean and not got.off_topic else int(state.get("off_topic_streak") or 0) + 1
        info.update(prompt=f"{meta.prompt_id}@{meta.prompt_version}", off_topic=got.off_topic, streak=streak,
                    other_target_mention=mention, other_target_reason=reason, **audit_dropped(dropped, known))  # fmt: skip
        if streak >= 2:  # [Chốt] lạc đề 2 lần liên tiếp
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="off_topic_twice", audit_detail=info,
                exit_code=ExitCode.E4.value, off_topic_streak=streak, conversation=[user_msg(text)],
                escalation_reason_detail="off_topic_twice",
            )  # fmt: skip
        flags = {"ctx_flags": {"target_is_other": True}} if reason is not None else {}  # Q-T20a-6 + L-03
        return await goto(
            state, S_CLARIFYING, next_node="b11_slots", step="B11", event="user_replied", audit_detail=info,
            slots=merged, off_topic_streak=streak, conversation=[user_msg(text)],
            **flags,
        )  # fmt: skip

    return clarify_wait
