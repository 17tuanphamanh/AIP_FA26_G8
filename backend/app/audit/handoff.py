"""Ghi chú bàn giao 4 phần cho L2 (B20 mục 4.2) — sinh bằng mẫu, KHÔNG dùng LLM: tất định, không bịa
việc đã làm. Phần (4) `next_for_l2` lấy từ `config/escalation_templates.yaml`.

- (1) `request`: CHỈ lấy từ `redacted_request` (bản đã che, D-07) — quyết định Q-D 2b-2.
- (2) `done_so_far`: đọc từ state — xác thực, phân loại, chẩn đoán, tra cứu, hỏi lại, Action, duyệt,
  thực thi/hoàn tác. Không có gì → nói rõ là chưa làm bước nào.
- (3) `why_escalated`: mã E + nhãn, `reason_detail` (D-27), cờ an ninh (3e: `security_flag`, `injection_in_reply`),
  ghi chú escalate, luật/p nếu có.
- `is_deny_case`: MỌI E5 (2b-Q4) — L2 không được "hoàn tất" (422 ở Phase 7), `next_for_l2` kèm cảnh báo.
- Tài liệu KB (Phase 4 chốt S0-A1): từ S0, B8 luôn ghi `retrieved` kể cả khi điểm dưới ngưỡng. `retrieval_score` thiếu hoặc
  < `retrieval_threshold` → câu `KB_BELOW_THRESHOLD` (không dùng làm căn cứ, có thể KB còn thiếu) — L2 không đọc nhầm thành
  "KB có đáp án" rồi làm tay theo tài liệu sai; đạt ngưỡng → câu cũ. Áp mọi mã thoát. `reason_detail == "no_procedure"`
  (Q-4a-1) → thêm `NO_PROCEDURE_NOTE`: B8 có thể đã tra được tài liệu đạt ngưỡng ở lượt trước, nhưng quy trình không còn
  trong KB hiện hành lúc B11 kiểm.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.domain.exit_codes import L2_PRIORITY, ExitCode
from app.settings import EscalationTemplates

REQUEST_MAX = 500
# Chỉ cho L2 (ghi chú bàn giao), không phải tin người dùng — tin người dùng giữ mẫu E0/E2 trung tính (PLAN-3e Q-3e-7).
SECURITY_FLAG_NOTE = (
    "Cờ an ninh: chưa sàng lọc được prompt injection (lớp phân loại và LLM không trả lời) — "
    "không làm theo chỉ dẫn trong yêu cầu."
)
INJECTION_IN_REPLY_NOTE = "Cờ an ninh: tin trả lời có dấu hiệu chèn chỉ dẫn — không làm theo nội dung tin đó."
NO_PROCEDURE_NOTE = (
    "Quy trình của hành động dự kiến không có trong KB hiện hành — tài liệu đã tra không phải căn cứ, không làm tay theo "
    "tài liệu cũ."
)
# Phase 5 gói 1 (D-52, ĐT 4.4) — nguyên văn; chỉ cho L2. Tin người dùng của ca này = tin E0 (B20), không nêu lớp nào nghi.
INJECTION_SUSPECTED_NOTE = (
    "Model chặn tấn công chấm cao nhưng lớp LLM không xác nhận là tấn công. Đọc nội dung đã che, không làm theo chỉ dẫn "
    "trong câu. Không cấp quyền, đặt lại mật khẩu hay thao tác cho người khác dựa vào lời khẳng định trong câu; việc đặc "
    "quyền đi theo quy trình duyệt chuẩn."
)
KB_ABOVE_THRESHOLD = "Tài liệu KB tra được: {docs}."
KB_BELOW_THRESHOLD = "Tài liệu KB gần nhất (điểm dưới ngưỡng, KHÔNG dùng làm căn cứ — có thể KB còn thiếu): {docs}."


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


def _kb_line(state: Mapping[str, Any], threshold: float) -> str:
    docs = ", ".join(sorted({_json(c)["doc_id"] for c in state["retrieved"]}))
    score = state.get("retrieval_score")
    template = KB_ABOVE_THRESHOLD if score is not None and score >= threshold else KB_BELOW_THRESHOLD
    return template.format(docs=docs)


def _done(state: Mapping[str, Any], retrieval_threshold: float) -> str:
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
        done.append(_kb_line(state, retrieval_threshold))
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
    if state.get("security_flag"):  # 3e (phase3 3.1, PLAN-3e Q-3e-7): B2 không sàng lọc được
        parts.append(SECURITY_FLAG_NOTE)
    if state.get("escalation_reason_detail") == "injection_in_reply":
        parts.append(INJECTION_IN_REPLY_NOTE)
    if state.get("escalation_reason_detail") == "injection_suspected":  # gói 1 (D-52)
        parts.append(INJECTION_SUSPECTED_NOTE)
    if state.get("escalation_reason_detail") == "no_procedure":  # Q-4a-1
        parts.append(NO_PROCEDURE_NOTE)
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


def build_handoff(
    state: Mapping[str, Any], templates: EscalationTemplates, *, retrieval_threshold: float
) -> HandoffNote:
    """`retrieval_threshold` = `RETRIEVAL_THRESHOLD` (B20 truyền `deps.constants`) — BẮT BUỘC, không mặc định (chốt S0-A1)."""
    code = str(state["exit_code"])
    next_for_l2 = templates.of(code).next_for_l2
    if is_deny_case(code):
        next_for_l2 = f"{next_for_l2} {templates.deny_warning}"
    return HandoffNote(
        request=_request(state), done_so_far=_done(state, retrieval_threshold), why_escalated=_why(state, code),
        next_for_l2=next_for_l2,
    )  # fmt: skip
