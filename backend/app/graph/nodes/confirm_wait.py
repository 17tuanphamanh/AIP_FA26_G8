"""Node chờ `S_CONFIRMING` — B19 (node chung, không có bản giả). Không side effect trước
`interrupt()`. Im lặng 48 giờ → tự đóng `resolved_auto_timeout_48h` [Chốt].

3e (thiết kế Phase 3 mục 8.6, 3-Q3 phương án A): `note` của xác nhận qua `screen_reply` (L0 + L2) NGAY sau
`interrupt()`, trước mọi nhánh (kể cả "đã xong") — khớp → `security_events(injection_detected)` qua `effects.once` →
`S_ESCALATED` E0 `injection_in_reply`.

Q13a (D-78, 11/11, bản nộp main) — hỏi tiếp sau câu trả lời KB trong CÙNG ticket. "Chưa ổn" + ghi chú KHÔNG rỗng (sau che L1 bằng
`redact_text` thuần, như `clarify_wait`) quay lại B2 thay vì E8 ngay khi ĐỦ cả bốn điều kiện:
1. cờ `ENABLE_KB_FOLLOWUP` bật;
2. ticket tới đây bằng CÂU TRẢ LỜI KB (`need_type == "info"` — it_help, info, symptom_to_info); ticket đã thực thi hành động (`need_type ==
   "action"`, qua B17) giữ E8 như cũ;
3. ticket KHÔNG phải ticket con (vòng tin của cha — D-31/D-77 — không đổi trong lô này);
4. chưa dùng hết `FOLLOWUP_MAX_ROUNDS` vòng.
Khi đó: `redacted_request` = câu gốc + "\\n" + `FOLLOWUP_PREFIX` + ghi chú (`combine_triage` — giữ TRỌN phần ghi chú, cắt phần đầu câu gốc nếu
vượt trần), `triage="done"` + `triage_reply_chars` = độ dài phần ghép (B3 dùng `keep_tail` như sau câu hỏi phân loại, không hỏi phân loại
lần nữa) → `S_CONFIRMING → S_SCREENING` (event `followup_reply`, step B19) → B2 sàng lọc ĐẦY ĐỦ câu ghép → đi lại TRỌN đường như ticket mới
(B3 → B6 → B8 → B10; thành yêu cầu hành động thì đủ B11–B17 với policy như mọi ticket). `b10_answer` nhận `previous_answer` để không lặp bước.
`reasoning_loops` đặt lại 0 (vòng hỏi tiếp là một yêu cầu mới của người dùng — B3/B6 đếm lại `MAX_LOOPS` cho vòng đó; tổng số lượt vẫn bị
chặn bởi `FOLLOWUP_MAX_ROUNDS`; khoá `effects.once` không trùng vì mỗi vòng là một `turn_id` mới).
Audit `followup_reply`: `followup_round`, `note_chars`, `combined_trimmed` — không chữ người dùng. E8 ghi `followup_rounds` đã dùng.
"""

from typing import Any

from langgraph.types import interrupt

from app.domain.exit_codes import CloseReason, ExitCode
from app.domain.messages import (
    FOLLOWUP_MAX_ROUNDS,
    FOLLOWUP_PREFIX,
    combine_triage,
    user_msg,
)
from app.domain.states import S_ESCALATED, S_RESOLVED, S_SCREENING
from app.graph import effects
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard.screen import screen_reply


def can_follow_up(state: Any, *, enabled: bool) -> bool:
    """Bốn điều kiện mở vòng hỏi tiếp (Q13a) — thuần, chưa xét ghi chú."""
    return (
        enabled
        and state.get("need_type") == "info"
        and not state.get("parent_ticket_id")
        and int(state.get("followup_round") or 0) < FOLLOWUP_MAX_ROUNDS
    )


def make(deps: NodeDeps) -> NodeFn:
    async def confirm_wait(state: Any) -> dict[str, Any]:
        ev = interrupt({"wait": "confirm"})
        if (hit := screen_reply(str(ev.get("note") or ""))) is not None:
            await effects.once(
                state, "security_event", deps.security_events.record, "injection_detected",
                ticket_id=state["ticket_id"], detail={"layer": "regex_reply", "pattern_id": hit.id}, step="B19",
            )  # fmt: skip
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B19", event="injection_in_reply",
                exit_code=ExitCode.E0.value, escalation_reason_detail="injection_in_reply",
            )  # fmt: skip
        if ev["kind"] == "timeout":
            return await goto(
                state, S_RESOLVED, next_node="b20_audit", step="B19",
                event="auto_closed_no_response_48h",
                close_reason=CloseReason.RESOLVED_AUTO_TIMEOUT_48H.value,
            )  # fmt: skip
        if ev["kind"] == "confirmed":
            return await goto(
                state, S_RESOLVED, next_node="b20_audit", step="B19", event="user_confirmed",
                close_reason=CloseReason.RESOLVED_USER_CONFIRMED.value,
            )  # fmt: skip
        rounds = int(state.get("followup_round") or 0)
        if can_follow_up(state, enabled=deps.enable_kb_followup):
            note = deps.privacy.redact_text(str(ev.get("note") or "")).text.strip()  # chỉ bản ĐÃ CHE đi tiếp
            if note:
                tail = FOLLOWUP_PREFIX + note
                combined, trimmed = combine_triage(str(state["redacted_request"]), tail)
                return await goto(
                    state, S_SCREENING, next_node="b02_screen", step="B19", event="followup_reply",
                    audit_detail={"followup_round": rounds + 1, "note_chars": len(note), "combined_trimmed": trimmed},
                    redacted_request=combined, triage="done", triage_reply_chars=len(tail), followup_round=rounds + 1,
                    reasoning_loops=0,  # vòng hỏi tiếp = một yêu cầu mới của người dùng; tổng vẫn bị chặn bởi FOLLOWUP_MAX_ROUNDS
                    conversation=[user_msg(note)],
                )  # fmt: skip
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B19", event="user_reported_unresolved",
            exit_code=ExitCode.E8.value, audit_detail={"followup_rounds": rounds},
        )  # fmt: skip

    return confirm_wait
