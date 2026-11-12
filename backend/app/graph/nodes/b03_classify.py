"""B3–B4 — node THẬT, Phase 3 chỉ VPN (thiết kế mục 9.3; PLAN-3f chốt Q-3f-2…6). Node giả (Phase 2, `FAKE_SCENARIO`):
`graph/nodes/fake/b03_classify.py`. Tách ý + ticket con (B5): Phase 5.

1. `reasoning_loops + 1 > MAX_LOOPS` → E2 `max_loops_exceeded`.
2. `deps.ml.classify_intent` — Phase 3 luôn `model_missing`; lỗi hạ tầng cũng vậy → xuống LLM. Có kết quả (model đã có) ở
   Phase 3 VẪN xuống LLM, chỉ ghi `model_probs`/`model_version` (nhánh model + `cascade_decide`: Phase 5).
3. LLM fast `b03_classify` (`ClassifyOut`): `LLMSchemaError` → E2 `llm_schema_error`; `LLMUnavailable`/`LLMBudgetExceeded`
   → E2 `llm_unavailable`; hết hạn cả lượt (ở ml hoặc LLM) → E2 `turn_budget_exceeded`.
4. Thứ tự kiểm CỐ ĐỊNH (mỗi ca E1 đúng một `reason_detail`): không ý nào trong phạm vi → `out_of_scope` → (D-84, 12/11) câu xin
   thao tác NGƯỢC (thu hồi, khoá, báo mất máy, gỡ cài, đừng làm, huỷ — `domain/reverse_action`) mà có intent ghi → `reverse_action_requested`
   cả ticket, không tách, không slot → (12/11) có intent `account` mà câu nhắc tài khoản dịch vụ BÊN NGOÀI (Gmail, Zalo… —
   `domain/personal_account`) → `out_of_scope` (cờ audit `personal_account`) → có ≥ 2 ý (đếm
   MỌI ý, kể cả ý ngoài phạm vi — Q-3f-6; câu xã giao không phải ý, prompt v2) → B4/B5 nhiều ý (dưới) → confidence <
   `TAU_INTENT` → `intent_low_confidence` → intent ∉ `ENABLED_INTENTS` → `intent_not_enabled`.
   **Nhiều ý (Phase 5 T20b P2, P3; D-49; phase5 5.2.2–5.2.3):** phán TỪNG ý theo bảng 5.2.2 (`out_of_scope` → `span` rỗng/không
   nằm trong câu → `split_span_invalid` → confidence thấp → intent chưa bật → chạy được). ≥ 1 ý chạy được → tách MỌI ý: mỗi ý
   `effects.once("child_create", tickets.create_child, sub=cid)` (dòng `tickets` con, id `<cha>-<i>`), `mark_parent_once`, `goto`
   `S_CLASSIFYING → S_CLASSIFYING` (`step="B5"`, `split_into_<n>_children`) → `parent_wait` với `is_parent`, `children`, `child_seeds`
   (seed bền TRƯỚC khi con chạy — `parent_wait` khởi động con). Slot của ý: `sanitize_slots(text=span của ý)`; `target_user` bị bỏ →
   `ctx_flags.target_is_other` của CHÍNH con đó. 0 ý chạy được → cả câu E1 (`step="B4"`): `reason_detail` của ý ĐẦU TIÊN trong phạm
   vi theo bảng 5.2.2 (Q-T20b-2 = B — không còn `multi_intent_not_enabled`). Điểm log 1 của cha thêm `children` (số), `verdicts`.
   **Chạy lại cùng lượt (Q-T20b-12):** cache LLM không bảo đảm cùng kết quả (bypass, model dự phòng, chết trước khi ghi cache…) —
   `child_create` trả `<con>|<số ý>|<loại ý>`; lần chạy lại thấy ref cũ lệch (số ý / loại ý), hoặc không còn tách mà con 1 đã được tạo
   → `SplitChanged` (E9 của cha — boundary; thấy được nhờ Q-T20b-5), KHÔNG tạo thêm con hay đổi seed.
5. Còn lại: `sanitize_slots` (3-Q1; P1, P2, Q-3f-3) → `S_DIAGNOSING` → B6, `facts={}` (B3 KHÔNG BAO GIỜ ghi fact — G-01).
   `span` chỉ giữ khi là đoạn con của câu người dùng (Q-3f-4).
6. Q-T20a-4 (Phase 5 T20a, duyệt DỪNG 1): `target_user` bị `sanitize_slots` bỏ (BẤT KỲ lý do — sai mẫu như họ tên, không có trong
   câu…) nghĩa là người dùng nhắm NGƯỜI KHÁC mà định danh không dùng được → không để `requested_for` âm thầm thành người gửi (luật
   allow chạy trên chính họ): ghi `ctx_flags={"target_is_other": True}` (B6 không ghi đè; B12 `build_ctx` đọc). Không thêm giá trị
   slot vào audit — điểm log 1 đã có key bị bỏ.
7. be-target-guard (L-03): cờ đó còn bật khi intent ∈ {account, access}, CHƯA có `target_user` hợp lệ VÀ câu nêu người khác
   (`domain/target.mention_reason`: định danh lạ / cụm "tài khoản dịch vụ", "đồng nghiệp"…) hoặc có khoá lạ `unknown_key`
   (`domain/target.target_check`). Một ý: dò câu; B5: TỪNG con dò TOÀN CÂU GỐC (không chỉ span — ý tự xưng trong câu có nêu người
   khác cũng bật, chấp nhận có chủ ý); Q4: con bỏ qua slot tài nguyên đã sạch của các ý CHẠY ĐƯỢC khác (`sibling_slots`, xem
   `domain/target.py`), mọi lời gọi truyền `device_prefixes` (config). Không bao giờ hạ cờ. Điểm log 1 thêm `other_target_mention` (bool), `other_target_reason`
   (hằng | None); dòng tách B5: `other_target_mention` (bất kỳ con) + `children_other_target_reason` (theo con). Không câu/token.

8. M1 — báo trùng yêu cầu (nhánh đơn ý `intent_classified`, ticket lá): có ticket CÒN MỞ (`final_state IS NULL`) của cùng người gửi,
   cùng intent, tạo trong `DEDUP_WINDOW_HOURS` (`config/dedup.yaml`) → MỘT tin cố định theo mẫu (không LLM) qua output guard +
   `effects.once("notify_user", step="B3", sub="duplicate")` và điểm log 1 thêm `duplicate_of` (mã ticket — không chữ tự do). KHÔNG dừng
   luồng, KHÔNG đổi `exit_code`, KHÔNG vào state/ctx (M5 không thấy — `test_dedup_isolation_ast.py`). Quyết định ở
   `domain/dedup.pick_duplicate`; store chỉ trả tập cha (`TicketStore.open_candidates`). Output guard chặn mẫu → không gửi tin, audit
   vẫn ghi `duplicate_of`. Lỗi ĐỌC store (`open_candidates`) KHÔNG lan thành E9 (ĐP 08/11): bắt `Exception`, log cảnh báo chỉ có tên lớp
   lỗi + mã ticket (không thông điệp, không traceback), bỏ qua tin báo trùng, luồng chạy tiếp; riêng `TurnBudgetExceeded` vẫn lan lên (E2).
   Phạm vi bắt lỗi CHỈ là bước đọc store — gửi tin hỏng (notifier) vẫn là lỗi thật → E9. Chấm thử 11/11: ticket đã có tin `duplicate`
   trong `conversation` (vòng hỏi tiếp D-78 đi lại B3) → không gửi lại; chỉ đọc `kind` của tin, không đọc chữ.

9. Q1 (D-75, ĐP 09/11 — TC11): nhánh MỘT ý — `intents` rỗng (chào/cảm ơn/mơ hồ, prompt v6) HOẶC đúng 1 ý trong phạm vi mà `confidence <
   TAU_INTENT` → nếu ticket CHƯA hỏi phân loại (`triage` None) → MỘT câu CỐ ĐỊNH `messages.triage_question(enable_it_help)` (không LLM) qua
   output guard (chặn → không gửi, E1 như trước lô, audit `guard`) + `effects.once("notify_user", needs=answer, sub="triage")` + hạn `clarify`
   (`CLARIFY_TIMEOUT_HOURS`, như B11) → `S_CLASSIFYING → S_CLARIFYING` (event `triage_asked`, `triage="waiting"`) → `clarify_wait` (nhánh phân
   loại: ghép câu trả lời → B2 → B3 lần 2). ĐÃ hỏi (`triage` có giá trị) → E1 như cũ (`out_of_scope` / `intent_low_confidence`). Có ý
   `out_of_scope` rõ mà 0 ý trong phạm vi → E1 ngay, không hỏi. Nhiều ý: không đổi. Hỏi phân loại KHÔNG tính vào `clarification_turns`.
   Audit `triage_asked`: điểm log 1 + `triage_reason` ∈ {no_intent, low_confidence} + `guard` — không chữ người dùng.

10. D-76 (ĐP chốt 09/11, bản demo lo-0811 — lô Q12): `it_help` (câu HỎI cách làm / BÁO hiện tượng IT ngoài 4 loại, trả lời từ KB `general`).
   Ngay sau LLM: cờ `ENABLE_IT_HELP` tắt HOẶC câu ≥ 2 ý → mọi ý `it_help` đổi thành `out_of_scope` (con bắt đầu ở B6 — `children.py` — không có
   luồng chỉ-trả-lời; tin tổng hợp của cha báo phần đó chuyển kỹ thuật viên). Một ý `it_help` qua ngưỡng `TAU_INTENT` (dưới ngưỡng → hỏi
   phân loại như mục 9) → KHÔNG kiểm `enabled_intents` (it_help không thuộc tập này), KHÔNG `sanitize_slots` (slot `{}`), KHÔNG báo trùng M1
   → `S_DIAGNOSING` → B6 (0 tool). Điểm log 1 thêm `request_trimmed` (bool — gateway cắt đuôi `redacted_request` theo `budget_in`, prompt v6
   `trim_vars`; an toàn vì B2 đã sàng lọc TRỌN câu trước B3). Sau câu hỏi phân loại (`triage="done"`): gateway giữ trọn câu trả lời
   (`keep_tail` = độ dài bản L0 của `triage_reply_chars` ký tự cuối), cắt PHẦN ĐẦU câu gốc trước — ĐP chốt điểm 2.

11. Q13b (D-79, 11/11, bản nộp main): ticket mở từ "Hỏi tiếp" của ticket ĐÃ kết thúc → `label_hint` = `state["prior_hint"]` (MỘT dòng dựng từ
   cột đóng của ticket cũ — `domain/session_memory.prior_label_hint`; không chữ người dùng/bot, không slot). Prompt đã nói "Gợi ý nhãn (nếu
   có) chỉ để tham khảo" — không đổi prompt. Audit điểm log 1 thêm cờ `follows_ticket` (bool, không id).

Điểm log 1 ở MỌI nhánh (kể cả lỗi) qua `audit_detail`: lớp, intent, confidence, prompt id@version, lỗi ml/LLM (tên lớp),
slot bị bỏ (chỉ key đã khai báo — Q-3f-5), `slot_fact_collision`, `span_not_in_text`. KHÔNG có câu người dùng hay giá trị
slot. E1 ghi `step="B4"`, còn lại `"B3"`. Không `except Exception` — lỗi khác (`ScriptExhausted`, `MlContractError`…) → E9.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any, Final, Literal

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.children import child_id, child_ref
from app.domain.dedup import duplicate_text, pick_duplicate
from app.domain.exit_codes import ExitCode
from app.domain.intents import ANSWER_ONLY_INTENTS
from app.domain.messages import duplicate_msg, triage_msg, triage_question
from app.domain.personal_account import personal_account_mentioned
from app.domain.reverse_action import reverse_action_kind
from app.domain.slots import audit_dropped, phrase_in_text, sanitize_slots
from app.domain.states import S_CLARIFYING, S_CLASSIFYING, S_DIAGNOSING, S_ESCALATED
from app.domain.target import requester_id_of, target_check
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard.normalize import l0
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import ClassifyOut, IntentItem

log = logging.getLogger(__name__)

RUNNABLE: Final = "runnable"  # kết quả bảng 5.2.2 #5 — ý chạy được (các kết quả khác là `reason_detail` E1 của con)


class SplitChanged(RuntimeError):
    """B3 chạy lại cùng lượt ra cách tách KHÁC lần trước (đã tạo con) — Q-T20b-12. Thông điệp chỉ có id/số/loại ý, không chữ người dùng."""


def _point1() -> dict[str, Any]:
    return {
        "layer": None, "intent": None, "confidence": None, "is_multi": None, "model_probs": None,
        "model_version": None, "prompt": None, "ml_error": None, "llm_error": None, "span_not_in_text": False,
        "other_target_mention": False, "other_target_reason": None, "request_trimmed": False, **audit_dropped({}, frozenset()),
        "follows_ticket": False,  # Q13b (D-79): ticket mở từ "Hỏi tiếp" (có gợi ý loại việc trước) — chỉ cờ, không id/chữ
        "reverse_action": None,  # D-84: nhãn loại thao tác ngược (lost_device, compromised, revoke, lock, negate, cancel, uninstall)
        "personal_account": False,  # 12/11: câu nhắc tài khoản dịch vụ bên ngoài (Gmail, Zalo…) → E1 out_of_scope — chỉ cờ, không chữ
    }  # fmt: skip


def _subset(small: Mapping[str, Any], big: Mapping[str, Any]) -> bool:
    """Mọi slot của `small` có trong `big` với cùng giá trị (U1)."""
    return all(k in big and big[k] == v for k, v in small.items())

def make(deps: NodeDeps) -> NodeFn:
    known = deps.slots.declared_names

    async def b03_classify(state: Any) -> dict[str, Any]:
        loops = int(state.get("reasoning_loops") or 0) + 1
        info = _point1()
        info["follows_ticket"] = state.get("follows_ticket_id") is not None
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
        request, keep = _llm_request(state, text)
        try:
            out, meta = await deps.llm.complete(
                "fast", "b03_classify",
                {"redacted_request": request, "label_hint": state.get("prior_hint")}, ClassifyOut, keep_tail=keep,
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
        info["request_trimmed"] = meta.trimmed_chars > 0  # Q1 điểm 2: chỉ cờ, không độ dài/chữ
        intents = _answer_only_as_out_of_scope(out.intents)  # D-76: cờ tắt / nhiều ý
        intents, merged = _dedupe(intents, text)  # U1 (soát 12/11): một việc bị tách thành 2 ý giống nhau → gộp, không chạy 2 lần
        if merged:
            info["deduplicated_intents"] = merged
        in_scope = [i for i in intents if i.type != "out_of_scope"]
        if not _splits(intents, text):  # Q-T20b-12: lần trước đã tách (con 1 đã tạo) mà lần này không → không đi tiếp đường khác
            first = child_id(state["ticket_id"], 1)
            if await effects.peek(state, "child_create", step="B5", sub=first) is not None:
                raise SplitChanged(f"B3 chạy lại: lần trước đã tách ticket con, lần này {len(intents)} ý không tách")
        if not intents and state.get("triage") is None:  # Q1: chào / cảm ơn / mơ hồ → hỏi MỘT câu phân loại
            return await _ask_triage(state, "no_intent", loops, info)
        if not in_scope:
            return await _out_of_scope(state, loops, info)
        if (kind := reverse_action_kind(text, {i.type for i in in_scope})) is not None:  # D-84: thao tác ngược → người, không hành động
            return await _reverse_action(state, kind, loops, info)
        if personal_account_mentioned(text, {i.type for i in in_scope}):  # 12/11: "Gmail cá nhân" → không đặt lại email CÔNG TY
            info["personal_account"] = True
            return await _out_of_scope(state, loops, info)
        if len(intents) >= 2:  # Q-3f-6: MỌI ý (vpn + ngoài phạm vi = 2 ý) — T20b: phán từng ý → B5 tách ticket con
            return await _split(state, intents, text, loops, info)
        it = in_scope[0]
        info["intent"], info["confidence"] = it.type, it.confidence
        if it.confidence < deps.constants.TAU_INTENT:  # D-27: không chắc thì không đoán
            if state.get("triage") is None:  # Q1: chưa hỏi phân loại → hỏi một lần thay vì chuyển người ngay
                return await _ask_triage(state, "low_confidence", loops, info)
            return await _low_confidence(state, loops, info)
        if it.type in ANSWER_ONLY_INTENTS:  # D-76: chỉ trả lời — không slot, không báo trùng, không thuộc ENABLED_INTENTS
            span_ok = bool(it.span.strip()) and phrase_in_text(it.span, text)
            info["span_not_in_text"] = bool(it.span.strip()) and not span_ok
            return await goto(
                state, S_DIAGNOSING, next_node="b06_diagnose", step="B3", event="intent_classified", audit_detail=info,
                intent=it.type, intent_confidence=it.confidence, span=it.span if span_ok else None, slots={}, facts={},
                reasoning_loops=loops,
            )  # fmt: skip
        if it.type not in deps.enabled_intents:  # 3-Q27
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_not_enabled", audit_detail=info,
                exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="intent_not_enabled",
            )  # fmt: skip
        raw = {**it.slots, **({"action": it.action_hint} if it.action_hint else {})}
        spec = deps.slots.intents[it.type]
        prefixes = deps.slots.device_prefixes  # Q4
        slots, dropped = sanitize_slots(spec, raw, text=text, device_prefixes=prefixes)  # 3-Q1: cửa DUY NHẤT
        span = it.span if it.span.strip() and phrase_in_text(it.span, text) else None  # Q-3f-4
        mention, reason = target_check(it.type, slots, dropped, spec.keys, text, requester_id_of(state),
                                       device_prefixes=prefixes)  # Q-T20a-4 + L-03  # fmt: skip
        info.update(audit_dropped(dropped, known), span_not_in_text=bool(it.span.strip()) and span is None,
                    other_target_mention=mention, other_target_reason=reason)  # fmt: skip
        flags = {"ctx_flags": {"target_is_other": True}} if reason is not None else {}
        flags.update(await _duplicate_notice(state, it.type, info))  # M1: sau khi chắc có intent, trước khi sang B6
        return await goto(
            state, S_DIAGNOSING, next_node="b06_diagnose", step="B3", event="intent_classified", audit_detail=info,
            intent=it.type, intent_confidence=it.confidence, span=span, slots=slots, facts={}, reasoning_loops=loops,
            **flags,
        )  # fmt: skip

    def _llm_request(state: Any, text: str) -> tuple[str, dict[str, int] | None]:
        """Q1 điểm 2 (ĐP chốt 09/11): sau câu hỏi phân loại, `redacted_request` = câu gốc + "\n" + câu trả lời (`triage_reply_chars` ký tự
        cuối). Gửi LLM bản L0 của hai phần và nhờ gateway giữ trọn phần trả lời (`keep_tail`) — vượt trần thì cắt PHẦN ĐẦU câu gốc trước.
        B2 đã sàng lọc TRỌN câu ghép. Ca khác: như cũ (gateway cắt đuôi theo `trim_vars`)."""
        n = state.get("triage_reply_chars")
        if state.get("triage") != "done" or not isinstance(n, int) or n <= 0:
            return text, None
        whole = str(state["redacted_request"])
        head, reply = l0(whole[: len(whole) - n].rstrip("\n")), l0(whole[len(whole) - n :])
        return (f"{head}\n{reply}" if head else reply), {"redacted_request": len(reply)}

    def _answer_only_as_out_of_scope(intents: Sequence[IntentItem]) -> list[IntentItem]:
        """D-76: `it_help` chỉ chạy ở ticket một ý khi cờ bật; còn lại coi như `out_of_scope` (E1 / con E1 như trước lô)."""
        if deps.enable_it_help and len(intents) < 2:
            return list(intents)
        return [i.model_copy(update={"type": "out_of_scope"}) if i.type in ANSWER_ONLY_INTENTS else i for i in intents]

    async def _out_of_scope(state: Any, loops: int, info: dict[str, Any]) -> dict[str, Any]:
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_out_of_scope", audit_detail=info,
            exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="out_of_scope",
        )  # fmt: skip

    async def _reverse_action(state: Any, kind: str, loops: int, info: dict[str, Any]) -> dict[str, Any]:
        """D-84: câu xin thu hồi / khoá / báo mất máy / gỡ cài / đừng làm — hệ thống không có thao tác đó; KHÔNG để LLM ánh xạ sang thao
        tác thuận (cấp lại, cài, gia hạn). Cả ticket (kể cả câu nhiều ý) chuyển L2 — audit chỉ nhãn loại, không chữ người dùng."""
        info["reverse_action"] = kind
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B4", event="reverse_action_requested", audit_detail=info,
            exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="reverse_action_requested",
        )  # fmt: skip

    async def _low_confidence(state: Any, loops: int, info: dict[str, Any]) -> dict[str, Any]:
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_low_confidence",
            audit_detail=info, exit_code=ExitCode.E1.value, reasoning_loops=loops,
            escalation_reason_detail="intent_low_confidence",
        )  # fmt: skip

    async def _ask_triage(
        state: Any, reason: Literal["no_intent", "low_confidence"], loops: int, info: dict[str, Any]
    ) -> dict[str, Any]:
        """Q1 (D-75): câu hỏi phân loại CỐ ĐỊNH, qua output guard + `effects.once` (chạy lại node / resume không gửi lại)."""
        text = triage_question(deps.enable_it_help)
        info.update(triage_reason=reason, guard=deps.output_guard.violation(text))
        if info["guard"] is not None:  # câu do cấu hình viết — vẫn qua cổng đầu ra; chặn → không gửi, E1 như trước lô
            return await (_out_of_scope if reason == "no_intent" else _low_confidence)(state, loops, info)
        run = current_run()
        ref = await effects.once(
            state, "notify_user", deps.notifier.notify_user, state["ticket_id"], text, "answer", step="B3", sub="triage",
        )  # fmt: skip
        deadline = run.clock.now() + timedelta(hours=deps.constants.CLARIFY_TIMEOUT_HOURS)
        await effects.once(
            state, "deadline_set", deps.deadlines.set, state["ticket_id"], "clarify", deadline, run.turn_id, step="B3",
            sub="triage",
        )  # fmt: skip
        return await goto(
            state, S_CLARIFYING, next_node="clarify_wait", step="B3", event="triage_asked", audit_detail=info,
            triage="waiting", conversation=[triage_msg(text, ref)], reasoning_loops=loops,
        )  # fmt: skip

    async def _duplicate_notice(state: Any, intent: str, info: dict[str, Any]) -> dict[str, Any]:
        """M1 — trả phần cập nhật state (`conversation` một tin) hoặc {}; ghi `info["duplicate_of"]` khi có ticket trùng."""
        requester = requester_id_of(state)
        if not requester:  # node trần (test) không có người gửi → không có gì để so
            return {}
        since = current_run().clock.now() - deps.dedup.window
        try:
            candidates = await deps.tickets.open_candidates(requester, since=since)
        except TurnBudgetExceeded:  # hạn cả lượt (9.0) không bao giờ bị nuốt — vẫn E2 `turn_budget_exceeded` ở `b03_classify`
            raise
        except Exception as exc:  # noqa: BLE001 — ĐP 08/11: tin báo trùng chỉ là phụ, không đáng làm hỏng ticket (không E9)
            # Chỉ tên lớp lỗi + mã ticket: thông điệp của driver có thể chứa tham số truy vấn / chữ người dùng; không traceback.
            log.warning("B3: bỏ qua báo trùng yêu cầu, không đọc được ticket đang mở (%s), ticket %s", type(exc).__name__, state["ticket_id"])
            return {}
        found = pick_duplicate(
            candidates, ticket_id=state["ticket_id"], parent_ticket_id=state.get("parent_ticket_id"),
            requester_id=requester, intent=intent, since=since,
        )  # fmt: skip
        if found is None:
            return {}
        info["duplicate_of"] = found
        if any(m.get("kind") == "duplicate" for m in state.get("conversation") or []):
            # Chấm thử 11/11 (T7): vòng hỏi tiếp D-78 đi lại B3 → tin báo trùng lặp lại mỗi vòng. Ticket đã báo một lần → không báo nữa
            # (audit vẫn ghi `duplicate_of`).
            return {}
        text = duplicate_text(deps.dedup.template, intent, found)
        if deps.output_guard.violation(text) is not None:  # mẫu do cấu hình viết — vẫn qua cổng đầu ra như mọi tin gửi đi
            return {}
        ref = await effects.once(
            state, "notify_user", deps.notifier.notify_user, state["ticket_id"], text, "none", step="B3", sub="duplicate"
        )
        return {"conversation": [duplicate_msg(text, ref)]}

    def _verdict(it: IntentItem, text: str) -> str:
        """Bảng 5.2.2 — thứ tự kiểm CỐ ĐỊNH, mỗi ý đúng một kết quả (hằng trong `VERDICTS`)."""
        if it.type == "out_of_scope":
            return "out_of_scope"
        if not it.span.strip() or not phrase_in_text(it.span, text):
            return "split_span_invalid"
        if it.confidence < deps.constants.TAU_INTENT:
            return "intent_low_confidence"
        if it.type not in deps.enabled_intents:
            return "intent_not_enabled"
        return RUNNABLE

    def _dedupe(intents: Sequence[IntentItem], text: str) -> tuple[list[IntentItem], int]:
        """U1 (soát 12/11, agent 18 L1): LLM tách MỘT việc thành 2 ý cùng loại → 2 con → thực thi 2 lần. Hai ý CHẠY ĐƯỢC cùng `type` + cùng
        `action_hint` (khác None) mà slot sạch (trong `span` của chính ý, như `_seed`) của một ý ⊆ ý kia → bỏ ý ít thông tin hơn (bằng nhau →
        giữ ý trước, ở vị trí cũ). Khác đích / khác máy (slot lệch), thiếu `action_hint`, khác loại → giữ. Trả (danh sách mới, số ý đã bỏ)."""
        kept: list[tuple[IntentItem, dict[str, Any] | None]] = []
        for it in intents:
            clean = None
            if it.action_hint and _verdict(it, text) == RUNNABLE:
                spec = deps.slots.intents[it.type]
                clean = sanitize_slots(spec, it.slots, text=l0(it.span), device_prefixes=deps.slots.device_prefixes)[0]
            for k, (other, other_clean) in enumerate(kept):
                if clean is None or other_clean is None or (other.type, other.action_hint) != (it.type, it.action_hint):
                    continue
                if _subset(clean, other_clean):
                    break  # ý này không thêm gì → bỏ
                if _subset(other_clean, clean):
                    kept[k] = (it, clean)  # ý trước ít thông tin hơn → thay bằng ý này, giữ vị trí
                    break
            else:
                kept.append((it, clean))
        return [it for it, _ in kept], len(intents) - len(kept)

    def _splits(intents: Sequence[IntentItem], text: str) -> bool:
        """Có đi `_split` và tạo con không: ≥ 1 ý trong phạm vi, ≥ 2 ý, ≥ 1 ý chạy được (bảng 5.2.2)."""
        return len(intents) >= 2 and any(i.type != "out_of_scope" for i in intents) \
            and any(_verdict(it, text) == RUNNABLE for it in intents)  # fmt: skip

    def _seed(
        state: Any, cid: str, it: IntentItem, verdict: str, text: str, loops: int, siblings: Sequence[dict[str, str]] = ()
    ) -> tuple[dict[str, Any], bool, str | None]:
        """Seed của con (bảng 5.2.3) — KHÔNG `requester_context` (ChildOps đọc lại từ state cha), KHÔNG `risk`/`action`, `facts={}`
        (G-01). Slot chỉ lấy trong `span` của CHÍNH ý (P2 — chống "mượn" đích của ý khác); dò người khác trên TOÀN CÂU GỐC (L-03).
        Trả (seed, câu nêu người khác?, lý do cờ của con)."""
        span_ok = bool(it.span.strip()) and phrase_in_text(it.span, text)
        seed: dict[str, Any] = {
            "ticket_id": cid, "parent_ticket_id": state["ticket_id"], "session_id": state.get("session_id"),
            "redacted_request": it.span if span_ok else state["redacted_request"], "status": S_CLASSIFYING,
            "span": it.span if span_ok else None, "slots": {}, "facts": {}, "conversation": [], "clarification_turns": 0,
            "off_topic_streak": 0, "reasoning_loops": loops, "is_parent": False, "children": [],
        }  # fmt: skip
        if verdict != "out_of_scope":
            seed.update(intent=it.type, intent_confidence=it.confidence)
        if verdict != RUNNABLE:
            # `verdict` ∈ hằng của `_verdict` (bảng 5.2.2) — `ChildOps` kiểm lại ∈ `E1_REASONS` (4 hằng bảng 5.2.2) và `exit_code == "E1"`
            # trước khi gieo (test AST chỉ quét tham số `escalation_reason_detail=` dạng hằng)
            seed["exit_code"], seed["escalation_reason_detail"] = ExitCode.E1.value, verdict
            return seed, False, None
        raw = {**it.slots, **({"action": it.action_hint} if it.action_hint else {})}
        spec = deps.slots.intents[it.type]
        prefixes = deps.slots.device_prefixes  # Q4
        slots, dropped = sanitize_slots(spec, raw, text=l0(it.span), device_prefixes=prefixes)  # P2: text = span của ý
        seed["slots"] = slots
        mention, reason = target_check(it.type, slots, dropped, spec.keys, text, requester_id_of(state), device_prefixes=prefixes,
                                       sibling_slots=siblings, own_span=it.span)  # TOÀN CÂU GỐC; Q4: ý bên cạnh  # fmt: skip
        if reason is not None:  # Q-T20a-4 + L-03 áp TỪNG con
            seed["ctx_flags"] = {"target_is_other": True}
        return seed, mention, reason

    async def _split(state: Any, intents: Sequence[IntentItem], text: str, loops: int, info: dict[str, Any]) -> dict[str, Any]:
        """B4/B5 (P2, P3; D-49): ≥ 1 ý chạy được → tách MỌI ý; 0 ý chạy được → cả câu E1 (Q-T20b-2 = B)."""
        verdicts = [_verdict(it, text) for it in intents]
        info.update(children=len(intents), verdicts=verdicts)
        if RUNNABLE not in verdicts:
            return await _whole_e1(state, intents, verdicts, loops, info)
        parent, run = state["ticket_id"], current_run()
        clean = [sanitize_slots(deps.slots.intents[it.type], it.slots, text=l0(it.span), device_prefixes=deps.slots.device_prefixes)[0]
                 if v == RUNNABLE else {} for it, v in zip(intents, verdicts, strict=True)]  # Q4: slot sạch của mọi ý chạy được  # fmt: skip
        seeds: dict[str, dict[str, Any]] = {}
        mentions: list[bool] = []
        reasons: list[str | None] = []
        for i, (it, verdict) in enumerate(zip(intents, verdicts, strict=True), start=1):
            cid = child_id(parent, i)
            siblings = [c for j, c in enumerate(clean, start=1) if j != i]
            seeds[cid], mention, reason = _seed(state, cid, it, verdict, text, loops, siblings)
            mentions.append(mention)
            reasons.append(reason)
            ref = await effects.once(
                state, "child_create", deps.tickets.create_child, cid, parent_id=parent,
                redacted_request=seeds[cid]["redacted_request"], created_at=run.clock.now(), step="B5", sub=cid,
                intents=len(intents), intent_type=it.type,
            )  # fmt: skip
            if ref != child_ref(cid, len(intents), it.type):  # Q-T20b-12: lần trước tách khác (số ý / loại ý) → không đè, E9 cha
                raise SplitChanged(f"B3 chạy lại: {cid} đã tạo với {ref!r}, lần này {len(intents)} ý, ý {i} loại {it.type}")
        await deps.tickets.mark_parent_once(parent)  # D-30 — idempotent
        info.update(other_target_mention=any(mentions), children_other_target_reason=reasons)
        return await goto(
            state, S_CLASSIFYING, next_node="parent_wait", step="B5", event=f"split_into_{len(seeds)}_children",
            audit_detail=info, is_parent=True, children=list(seeds), child_seeds=seeds, reasoning_loops=loops,
        )  # fmt: skip

    async def _whole_e1(
        state: Any, intents: Sequence[IntentItem], verdicts: Sequence[str], loops: int, info: dict[str, Any]
    ) -> dict[str, Any]:
        """Q-T20b-2 = B: `reason_detail` của Ý ĐẦU TIÊN trong phạm vi theo bảng 5.2.2 (ý ngoài phạm vi đã loại ở nhánh trước)."""
        it, verdict = next((it, v) for it, v in zip(intents, verdicts, strict=True) if it.type != "out_of_scope")
        info["intent"], info["confidence"] = it.type, it.confidence
        if verdict == "split_span_invalid":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="split_span_invalid", audit_detail=info,
                exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="split_span_invalid",
            )  # fmt: skip
        if verdict == "intent_low_confidence":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_low_confidence", audit_detail=info,
                exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="intent_low_confidence",
            )  # fmt: skip
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_not_enabled", audit_detail=info,
            exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="intent_not_enabled",
        )  # fmt: skip

    return b03_classify
