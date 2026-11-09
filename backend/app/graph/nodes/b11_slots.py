"""B11 — node THẬT, VPN (Phase 3) + account/software/access (T20a) (phase3 mục 10.4; PLAN-3g chốt P4–P8, P6 (a), Q-3g-6, Q-3g-7, f4). Node giả (Phase 2,
`FAKE_SCENARIO`): `graph/nodes/fake/b11_slots.py`. Node chờ: `graph/nodes/clarify_wait.py`.

1. `missing` = slot bắt buộc (`config/slots.yaml`) chưa có trong `slots` — T20a P4: `IntentSlots.missing` = `required` thiếu + (khi
   đã có slot `action`) `required_by_action[action]` thiếu, theo thứ tự khai báo (VPN không có `required_by_action` → như cũ).
2. Đủ slot → `validate_targets` (P6 (a)): gọi SONG SONG đúng các tool có `device_id` trong `arg_slots`
   (`check_device_registered`, `check_vpn_cert_expiry`; `caller_step="B11"`) cho `slots.device_id`. Lỗi hệ thống → E2
   `target_check_error`; 404/rỗng = dữ liệu (máy không tồn tại → `device_registered=false`, luật quyết). `infer_vpn` (tên
   thật) tính lại fact PHỤ THUỘC MÁY: bỏ mọi giá trị máy cũ, giữ fact theo người; BỎ `slots` mà `infer_vpn` trả (không tự đặt
   `action`/`device_id` — máy người khác không bao giờ sinh hành động). `build_action` chỉ từ slot đã sanitize + metadata +
   facts (P8; key lạ → `FactKeyViolation` → E9).
   **T20a (phase5 5.1.5):** VPN giữ nguyên từng dòng trên. Intent trong `DIAGNOSERS` (account, software, access):
   `module.target_calls(requester, slots)` (đủ bộ tool trên slot cuối) → lỗi hệ thống → E2 `target_check_error` →
   `facts = module.infer(...)` THAY TOÀN BỘ fact của B6 (mọi fact của 3 intent phụ thuộc slot cuối: `rf`, path, tên, máy,
   `account_type`) → slot suy ra BỎ → `build_action` → căn cứ quy trình như dưới.
   **Căn cứ quy trình (Phase 4 S0-P10, Q-4-U A+, D-34):** sau `build_action`, TRƯỚC `goto(S_ASSESSING)`: tài liệu
   `ActionMeta.procedure_doc` của `action_type` phải có trong KB HIỆN HÀNH (alias đọc lúc này — chốt S0-A3, không dùng
   `kb_version` ghim ở B8), enabled, người gửi được xem (`RagPort.procedure_available`, `base_filter`). Không → E3
   `no_procedure` (kèm `intended_action` để L2 thấy hành động dự kiến); `RetrievalSystemError` → E2 `rag_system_error`.
   Có → `S_ASSESSING`; audit `procedure_doc` + `procedure_kb_version`.
3. Đã hỏi đủ `MAX_CLARIFICATION_TURNS` lượt mà vẫn thiếu → E4 `clarification_exhausted`.
4. Hỏi ≤ 2 slot: LLM fast `b11_clarify_question` v4 (Q3 M2: + `missing_desc` = `slot_text.describe_missing` — nhãn + giải thích + ví
   dụ từng slot, slot `action` kèm nhãn các việc của intent; `action_label` = nhãn `slots.action` hoặc "chưa rõ" — chỉ HẰNG, không chữ
   người dùng; `diagnostics_summary` = `facts` + `device_id` các máy CỦA người gửi — f4;
   `previous_reply` ∈ none/usable/unusable — ĐP 08/11 P6: chỉ chào lượt đầu, trả lời trước không dùng được thì "Mình chưa rõ ý
   bạn,", tối đa 2 câu. **Q11 (ĐP 09/11):** + `user_request` = `state["redacted_request"]` — bản ĐÃ che, cùng bản B3 đọc, KHÔNG có câu gốc
   trong state; ticket con: `redacted_request` của con = span của con (B3 `_seed`); context builder cắt đuôi theo `budget_in` vai fast
   (`trim_vars`) — và `last_question` = `domain.messages.last_question(state)` (tin `question` cuối, đã qua scrub + output guard) hoặc
   "(chưa có)" ở lượt đầu) → output guard (P4) → vi phạm: E3 `output_guard_block`, 0 tin. `notify_user` (needs=answer) + hạn `clarify` 24 h qua
   `effects.once`, khoá RIÊNG từng lượt hỏi (`sub=f"q{n}"`, P5) → `S_CLARIFYING`.
5. be-target-guard (L-03): intent ∈ {account, access}, `ctx_flags.target_is_other` bật mà CHƯA có `target_user` → `missing =
   ["target_user", *missing]` (`target_required`). Câu hỏi CỐ ĐỊNH `domain/target.TARGET_QUESTION` — KHÔNG gọi LLM (`prompt` None),
   vẫn qua output guard, `notify_user`, hạn như bước 4; hết lượt → E4 `clarification_exhausted` như bước 3. Không dựng `Action` trên
   người gửi khi người dùng chưa nêu đích. Cờ KHÔNG hạ dù người dùng trả lời mã của chính mình (→ HITL/chốt B15).

7. Q2 M4 (ĐP 09/11) — TRƯỚC KHI HỎI, intent `vpn`, có slot `device_id` mà B6 đã tra ĐÚNG máy đó (`device_lookup`: fact
   `device_registered` có mặt; danh sách `diagnostics.check_device_registered` — tra theo mã trả máy bất kể chủ, 404 → None):
   - máy có trong danh sách và `device_owner_is_requester is False` → KHÔNG hỏi hành động: E5 `approval_target_unverified`
     ngay (step B11, audit `owner_mismatch_early=true`) — trước kiểm hết lượt hỏi;
   - máy không có (404) → bỏ slot `device_id` + fact máy (`vpn.DEVICE_FACTS`), hỏi câu CỐ ĐỊNH `messages.device_not_found_question`
     (không LLM, `prompt` None; output guard, notify, hạn, hết lượt như bước 5; audit `device_not_found=true`). Máy người dùng gửi
     lại KHÔNG do B6 tra → lần sau đi luồng cũ (không hỏi câu này lần 2, không tự suy máy khác).
   B6 tra theo người (có `device_count`) mà máy không có trong danh sách → không kết luận (luồng cũ).
   ĐP 09/11 điểm 1: máy 404 ĐỦ slot (B3 đã gợi ý hành động — bằng chứng (d)) cũng hỏi lại mã như trên, giữ slot `action`, KHÔNG dựng
   Action, không gọi tool. Máy của người khác ở đường đủ slot giữ luồng cũ (`_build` → B12 → chốt P6 ở B15).

Lỗi LLM → E2 `llm_schema_error`/`llm_unavailable`; hết hạn cả lượt (LLM hoặc tool) → E2 `turn_budget_exceeded`, bắt tường
minh (`step="B11"`). Không `except Exception`. Chẩn đoán lại D-20: không có ở 3g (Q-3g-7 — cờ bật thì không khởi động).
5b. Q3 M1 (ĐP 09/11): MỌI slot đang thiếu thuộc `FIXED_QUESTION_SLOTS` (account_type, action, permission_level) → câu CỐ ĐỊNH của intent
   (`IntentSlots.fixed_question` — `config/slots.yaml` `fixed_questions`, ghép ≤ 2 câu theo thứ tự thiếu), KHÔNG gọi LLM (`prompt` None) —
   như bước 5: output guard, `notify_user`, hạn, khoá theo lượt. Còn slot tự do → bước 4 (LLM).
6. be-b11-khoa-slot: câu LLM viết (chỉ nhánh LLM) qua `domain/slot_text.scrub_slot_keys` TRƯỚC output guard / notify / conversation — bỏ
   "(device_id)"… và thay khoá trơn bằng nhãn tiếng Việt, với MỌI khoá slot của `config/slots.yaml`; rỗng sau khi dọn → câu cố định.
Audit `detail`: tên slot thiếu, lượt hỏi, tool đã gọi, `facts` (enum/bool/int), `target_required`, `slot_keys_removed` (số đếm),
`owner_mismatch_early`, `device_not_found` (bool) — không câu người dùng, không chữ LLM (kể cả sau Q11: `user_request`/`last_question`
chỉ đi vào prompt, không vào audit).
"""

import asyncio
from datetime import timedelta
from typing import Any, Final, Literal

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.action import TARGET_USER_INTENTS, build_action
from app.domain.exit_codes import ExitCode
from app.domain.intents import ANSWER_ONLY_INTENTS
from app.domain.messages import (
    ACTION_LABELS,
    device_not_found_question,
    last_question,
    question_msg,
)
from app.domain.slot_text import UNKNOWN_ACTION, describe_missing, scrub_slot_keys
from app.domain.states import S_ASSESSING, S_CLARIFYING, S_ESCALATED
from app.domain.target import TARGET_QUESTION
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.ports import ToolResult
from app.graph.tracing import NodeFn
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import QuestionOut
from app.rag.models import RetrievalSystemError
from app.tools.diagnosis import DIAGNOSERS, vpn
from app.tools.retry import retries_of

NO_LAST_QUESTION: Final = "(chưa có)"  # biến `last_question` ở lượt hỏi đầu (Q11) — đúng chữ lời giao, prompt v4 giải thích nghĩa


def _info(missing: list[str], turns: int, target_required: bool) -> dict[str, Any]:
    return {"missing": missing, "turn": turns, "prompt": None, "llm_error": None, "guard": None, "tools_called": [],
            "tool_retry_count": 0, "facts": None, "procedure_doc": None, "procedure_kb_version": None,
            "rag_error": None, "target_required": target_required, "slot_keys_removed": 0,
            "owner_mismatch_early": False, "device_not_found": False}  # fmt: skip


def target_required(state: Any, slots: dict[str, Any]) -> bool:
    """L-03: account/access, cờ `target_is_other` bật, chưa có `target_user` → phải hỏi đích trước khi dựng `Action`."""
    flag = (state.get("ctx_flags") or {}).get("target_is_other", False) is not False
    return state["intent"] in TARGET_USER_INTENTS and flag and not slots.get("target_user")


def _error_kind(error: str) -> str:
    """"TimeoutException: …url…" → "TimeoutException" — không chép URL (có user_id/device_id) vào state/audit."""
    return error.split(":", 1)[0].strip()[:64]


def diagnostics_summary(state: Any, facts: dict[str, Any]) -> dict[str, Any]:
    """f4: chỉ enum/bool/số (`facts`) + `device_id` các máy CỦA người gửi (B6 tra theo `user_id`) — không chữ tự do.
    be-target-guard-2 (ĐP Q1 = a): cờ `target_is_other` bật → `devices = []` — câu hỏi không gợi ý máy của người gửi."""
    if (state.get("ctx_flags") or {}).get("target_is_other", False) is not False:
        return {"facts": dict(facts), "devices": []}
    requester = state["requester_context"].user_id
    devices = (state.get("diagnostics") or {}).get("check_device_registered") or []
    return {"facts": dict(facts), "devices": [d["device_id"] for d in devices if d.get("owner_id") == requester]}


def device_lookup(state: Any) -> Literal["mine", "other", "not_found"] | None:
    """Q2 M4: kết quả B6 cho ĐÚNG máy trong slot (vpn). None = không kết luận được (không phải vpn, chưa có máy, B6 không tra máy
    này, B6 tra theo người mà máy không trong danh sách). Chỉ đọc dữ liệu tool (`facts`, `diagnostics`) — không đọc câu người dùng."""
    device_id = (state.get("slots") or {}).get("device_id")
    facts = state.get("facts") or {}
    if state.get("intent") != "vpn" or not device_id or "device_registered" not in facts:
        return None
    listed = (state.get("diagnostics") or {}).get("check_device_registered") or []
    if not any(isinstance(d, dict) and d.get("device_id") == device_id for d in listed):
        return None if "device_count" in facts else "not_found"  # tra theo người: danh sách chỉ có máy của họ
    return "other" if facts.get("device_owner_is_requester") is False else "mine"


def previous_reply(state: Any, turns: int) -> str:
    """Biến `previous_reply` của `b11_clarify_question` (từ v2) — enum do node tính, LLM không thấy câu người dùng:
    `none` = câu hỏi đầu tiên (chưa hỏi lượt nào); `unusable` = câu trả lời trước không cho slot sạch nào hoặc lạc đề
    (`off_topic_streak` ≥ 1, đặt ở `clarify_wait`); còn lại `usable`."""
    if turns <= 0:
        return "none"
    return "unusable" if int(state.get("off_topic_streak") or 0) >= 1 else "usable"


def action_label(state: Any) -> str:
    """Q3 M2: biến `action_label` (v3) — nhãn tiếng Việt của `slots.action` (`ACTION_LABELS`), chưa có/không nhãn → "chưa rõ"."""
    action = (state.get("slots") or {}).get("action")
    return ACTION_LABELS.get(action, UNKNOWN_ACTION) if isinstance(action, str) else UNKNOWN_ACTION


def action_choices(deps: NodeDeps, intent: str) -> list[str]:
    """Q3 M2: nhãn các việc của intent (theo thứ tự `action_types`) cho dòng mô tả slot `action`."""
    return [ACTION_LABELS[a] for a in deps.slots.intents[intent].action_types if a in ACTION_LABELS]


def make(deps: NodeDeps) -> NodeFn:
    async def b11_slots(state: Any) -> dict[str, Any]:
        if state["intent"] in ANSWER_ONLY_INTENTS:  # D-76: chỉ-trả-lời không có slot/hành động — tới đây là bug → E9 (fail-closed)
            raise ValueError(f"b11_slots nhận intent chỉ-trả-lời {state['intent']!r} — không bao giờ dựng hành động")
        spec = deps.slots.intents[state["intent"]]
        slots = dict(state.get("slots") or {})
        missing = spec.missing(slots)  # T20a P4
        need_target = target_required(state, slots)
        if need_target:  # L-03: hỏi đích TRƯỚC
            missing = ["target_user", *missing]
        info = _info(missing, int(state.get("clarification_turns") or 0), need_target)
        try:
            if missing or device_lookup(state) == "not_found":  # ĐP 09/11 điểm 1: máy 404 hỏi lại mã cả khi đủ slot
                return await _ask(state, missing, info)
            return await _build(state, slots, info)
        except TurnBudgetExceeded:  # 9.0: ở LLM hoặc tool — không cho qua, không E9
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="turn_budget_exceeded", audit_detail=info,
                exit_code=ExitCode.E2.value, missing_slots=missing, escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip

    async def _build(state: Any, slots: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
        requester = state["requester_context"].user_id
        intent = state["intent"]
        module = DIAGNOSERS.get(intent)
        if intent != "vpn" and module is None:  # B3 chỉ cho qua intent đã bật — không có bộ chẩn đoán là bug → E9
            raise ValueError(f"b11_slots không có bộ chẩn đoán cho intent {intent!r}")
        if module is None:
            calls = vpn.target_calls(requester, slots["device_id"])
        else:
            calls = module.target_calls(requester, slots)
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
        if module is None:  # VPN (3g P6 (a)) — không đổi
            diag = {t: None for t in vpn.TOOLS} | {r.tool: (None if r.empty else r.data) for r in results}
            _, fresh = vpn.infer_vpn(diag, requester_id=requester, device_id=slots["device_id"])  # slots trả về: BỎ (P6)
            kept = {k: v for k, v in (state.get("facts") or {}).items() if k not in vpn.DEVICE_FACTS}
            facts = kept | {k: v for k, v in fresh.items() if k in vpn.DEVICE_FACTS}
        else:  # T20a: thay TOÀN BỘ fact của B6 theo slot cuối; slot suy ra BỎ (như VPN P6 (a))
            diag = {t: None for t in module.TOOLS} | {r.tool: r.data for r in results}
            _, facts = module.infer(diag, requester_id=requester, slots=slots)
        info["facts"] = facts
        metadata = deps.action_metadata[intent]
        action = build_action(intent, slots, facts, state["requester_context"], metadata)
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
        seen = device_lookup(state)
        if seen == "other":  # Q2 M4: máy của người khác — không hỏi hành động, chuyển L2 ngay (như chốt P6 ở B15)
            info["owner_mismatch_early"] = True
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="approval_target_unverified",
                audit_detail=info, exit_code=ExitCode.E5.value, missing_slots=missing,
                escalation_reason_detail="approval_target_unverified",
            )  # fmt: skip
        dropped: dict[str, Any] = {}
        if seen == "not_found":  # Q2 M4: mã máy không có — bỏ slot + fact máy cũ (kể cả khi đã đủ slot — ĐP 09/11 điểm 1)
            slots = {k: v for k, v in state["slots"].items() if k != "device_id"}
            facts = {k: v for k, v in (state.get("facts") or {}).items() if k not in vpn.DEVICE_FACTS}
            missing = deps.slots.intents[state["intent"]].missing(slots)
            info["missing"], info["device_not_found"] = missing, True
            dropped = {"slots": slots, "facts": facts}
        if turns >= deps.constants.MAX_CLARIFICATION_TURNS:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B11", event="clarification_exhausted",
                audit_detail=info, exit_code=ExitCode.E4.value, missing_slots=missing,
                escalation_reason_detail="clarification_exhausted",
            )  # fmt: skip
        fixed = deps.slots.intents[state["intent"]].fixed_question(missing)  # Q3 M1: mọi slot thiếu đều là slot enum
        if seen == "not_found":  # hỏi lại mã bằng câu CỐ ĐỊNH (không LLM)
            q = QuestionOut(text=device_not_found_question(str(state["slots"]["device_id"])))
        elif info["target_required"]:  # L-03: câu CỐ ĐỊNH, không gọi LLM (`prompt` None) — vẫn qua guard/notify/hạn dưới
            q = QuestionOut(text=TARGET_QUESTION)
        elif fixed is not None:  # Q3 M1: câu cố định từ `config/slots.yaml` — không LLM, vẫn qua guard/notify/hạn như trên
            q = QuestionOut(text=fixed)
        else:
            summary = diagnostics_summary(state, dict(state.get("facts") or {}))
            asked = missing[:2]
            try:
                q, meta = await deps.llm.complete(
                    "fast", "b11_clarify_question",
                    {"missing": asked, "intent": state["intent"], "diagnostics_summary": summary,
                     "previous_reply": previous_reply(state, turns),
                     "missing_desc": describe_missing(asked, action_choices=action_choices(deps, state["intent"])),
                     "action_label": action_label(state), "user_request": str(state["redacted_request"]),
                     # Q1: lượt B11 đầu không đọc `conversation` — tin `question` có thể là câu hỏi phân loại của B3, không phải "câu B11 vừa hỏi"
                     "last_question": (last_question(state) if turns > 0 else "") or NO_LAST_QUESTION}, QuestionOut,
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
            all_keys = {k for spec in deps.slots.intents.values() for k in spec.keys}
            text, removed = scrub_slot_keys(q.text, all_keys, missing[0] if missing else None)
            if removed:
                q = QuestionOut(text=text)
            info["slot_keys_removed"] = removed
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
            clarification_turns=n, missing_slots=missing, conversation=[question_msg(q.text, ref)], **dropped,
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
