"""Ghi chú bàn giao 4 phần cho L2 (B20 mục 4.2) — sinh bằng mẫu, KHÔNG dùng LLM: tất định, không bịa
việc đã làm. Phần (4) `next_for_l2` lấy từ `config/escalation_templates.yaml`.

- (1) `request`: CHỈ lấy từ `redacted_request` (bản đã che, D-07) — quyết định Q-D 2b-2.
- (2) `done_so_far`: đọc từ state — xác thực, phân loại, chẩn đoán, tra cứu, hỏi lại, Action, duyệt,
  thực thi/hoàn tác. Không có gì → nói rõ là chưa làm bước nào.
- (3) `why_escalated`: mã E + nhãn, `reason_detail` (D-27), ghi chú escalate, luật/p nếu có.
- `is_deny_case`: MỌI E5 (2b-Q4) — L2 không được "hoàn tất" (422 ở Phase 7), `next_for_l2` kèm cảnh báo.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.domain.exit_codes import L2_PRIORITY, ExitCode
from app.settings import EscalationTemplates

REQUEST_MAX = 500


class HandoffNote(BaseModel):
    request: str = Field(min_length=1)
    done_so_far: str = Field(min_length=1)
    why_escalated: str = Field(min_length=1)
    next_for_l2: str = Field(min_length=1)


def is_deny_case(exit_code: str) -> bool:
    return exit_code == ExitCode.E5.value


def _json(value: Any) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def _request(state: Mapping[str, Any]) -> str:
    text = str(state.get("redacted_request") or "").strip()
    if not text:
        return "(không có nội dung yêu cầu)"
    return text if len(text) <= REQUEST_MAX else text[: REQUEST_MAX - 1] + "…"


def _done(state: Mapping[str, Any]) -> str:
    done: list[str] = []
    ctx = _json(state.get("requester_context"))
    if ctx:
        done.append(f"Đã xác minh người gửi qua AD (role {ctx['role']}, phòng {ctx['department']}).")
    if state.get("intent"):
        conf = state.get("intent_confidence")
        done.append(f"Phân loại: {state['intent']}" + (f" (độ tin cậy {conf:.2f})." if conf else "."))
    if state.get("diagnostics"):
        done.append("Chẩn đoán đã chạy: " + ", ".join(sorted(state["diagnostics"])) + ".")
    if state.get("tool_errors"):
        done.append("Lỗi tool: " + "; ".join(state["tool_errors"]) + ".")
    if state.get("retrieved"):
        docs = sorted({_json(c)["doc_id"] for c in state["retrieved"]})
        done.append("Tài liệu KB tra được: " + ", ".join(docs) + ".")
    if state.get("retrieval_error"):
        done.append(f"Tra cứu KB lỗi: {state['retrieval_error']}.")
    if state.get("clarification_turns"):
        done.append(f"Đã hỏi lại người dùng {state['clarification_turns']} lần.")
    action = _json(state.get("intended_action"))
    if action:
        done.append(f"Hành động dự kiến: {action['type']} → {action['target']}.")
    if state.get("approval_result"):
        done.append(f"Kết quả duyệt: {state['approval_result']}.")
    execution = _json(state.get("execution"))
    if execution:
        steps = ", ".join(execution["steps_done"]) or "chưa bước nào"
        done.append(
            f"Thực thi: đã làm {steps}; bước lỗi {execution['failed_step'] or '—'}; "
            f"hoàn tác {execution['rollback_status']}."
        )
    return " ".join(done) or "Chưa thực hiện bước xử lý nào."


def _why(state: Mapping[str, Any], code: str) -> str:
    parts = [f"{code} — {L2_PRIORITY[ExitCode(code)]}."]
    if state.get("escalation_reason_detail"):
        parts.append(f"Chi tiết: {state['escalation_reason_detail']}.")
    if state.get("escalation_note"):
        parts.append(str(state["escalation_note"]).rstrip(".") + ".")
    risk = _json(state.get("risk"))
    if risk:
        rule = f", luật {risk['matched_rule_id']}" if risk.get("matched_rule_id") else ""
        prob = f", p={risk['calibrated_prob']:.2f}" if risk.get("calibrated_prob") is not None else ""
        decision = risk["policy_decision"] or "không luật nào khớp, ước lượng rủi ro"
        parts.append(
            f"Quyết định rủi ro: {decision} (bởi {risk['decided_by']}{rule}{prob}) — {risk['reason']}."
        )
    return " ".join(parts)


def build_handoff(state: Mapping[str, Any], templates: EscalationTemplates) -> HandoffNote:
    code = str(state["exit_code"])
    next_for_l2 = templates.of(code).next_for_l2
    if is_deny_case(code):
        next_for_l2 = f"{next_for_l2} {templates.deny_warning}"
    return HandoffNote(
        request=_request(state), done_so_far=_done(state), why_escalated=_why(state, code),
        next_for_l2=next_for_l2,
    )  # fmt: skip
