"""Nhãn tiếng Việt cho ghi chú bàn giao L2 (quyết định ĐP 02/11 12:45) — trích từ bảng từ ngữ giao diện (ĐP chốt 26/10).

Ba bảng: mã kết thúc E0–E9 (+ E1 · `injection_suspected`), lý do (`escalation_reason_detail` — bảng lý do E5, "lý do khác" và câu
của sự kiện cùng tên), cách xử lý (route); thêm bên quyết định (`decided_by`) để không lộ khoá thô. Người đọc (L2) thấy
"nhãn chữ · mã", mã để cuối. Mã lạ → "Khác · mã" (không để trống, không hiện thô một mình). Hàm thuần, hằng trong code.
"""

from typing import Final

from app.domain.exit_codes import ExitCode

EXIT_LABELS: Final[dict[ExitCode, str]] = {
    ExitCode.E0: "Nghi tấn công, đã chặn",
    ExitCode.E1: "Ngoài phạm vi hoặc chưa rõ yêu cầu",
    ExitCode.E2: "Lỗi khi xử lý (AI hoặc công cụ)",
    ExitCode.E3: "Thiếu tài liệu hướng dẫn",
    ExitCode.E4: "Thiếu thông tin từ người dùng",
    ExitCode.E5: "Không đủ điều kiện tự xử lý",
    ExitCode.E6: "Quá hạn chờ duyệt",
    ExitCode.E7: "Thực hiện không thành công",
    ExitCode.E8: "Người dùng báo chưa giải quyết",
    ExitCode.E9: "Lỗi hệ thống bất ngờ",
}
# E1 do B2 review (D-52): model nghi mà LLM chưa xác nhận — nhãn riêng thay nhãn E1 chung.
E1_INJECTION_SUSPECTED: Final = "Nghi tấn công, cần người xem"

REASON_LABELS: Final[dict[str, str]] = {
    # Lý do E5
    "recheck_failed": "Kiểm tra lại trước khi thực hiện không đạt",
    "llm_layer_disabled": "Lớp AI không phản hồi",
    "llm_high_risk": "AI đánh giá rủi ro cao",
    "approval_target_unverified": "Không xác minh được người hưởng lợi",
    "policy_deny": "Không được phép theo chính sách",  # M2 (ĐP 08/11) — như frontend/src/lib/nhan.ts
    # Lý do khác (duyệt 26/10 23:45)
    "no_grounding": "Không có tài liệu đủ căn cứ",
    "screening_unavailable": "Chưa kiểm tra an toàn được",
    "multi_intent_not_enabled": "Yêu cầu nhiều ý chưa bật",
    # Câu của sự kiện cùng tên
    "identity_unverifiable": "Không xác thực được người gửi",
    "role_unmappable": "Không xác định được vai trò",
    "injection_suspected": "Nghi tấn công, cần người xem",
    "injection_in_reply": "Nghi tấn công trong câu trả lời bổ sung",
    "intent_low_confidence": "Chưa chắc loại yêu cầu",
    "out_of_scope": "Ngoài phạm vi hỗ trợ",
    "reverse_action_requested": "Xin thu hồi, khoá, gỡ, huỷ hoặc báo mất máy / lộ mật khẩu — hệ thống không tự làm",  # D-84
    "intent_not_enabled": "Loại yêu cầu chưa bật",
    "split_span_invalid": "Tách ý không hợp lệ",
    "tool_system_error": "Công cụ chẩn đoán lỗi",
    "rag_system_error": "Hệ thống tra cứu lỗi",
    "invalid_citation": "Trích dẫn tài liệu không hợp lệ",
    "output_guard_block": "Câu trả lời bị chặn khi kiểm tra",
    "no_procedure": "Chưa có quy trình cho thao tác này",
    "clarify_timeout": "Hết hạn chờ bổ sung",
    "clarification_exhausted": "Hỏi lại nhiều lần vẫn thiếu thông tin",
    "off_topic_twice": "Trả lời lạc đề hai lần",
    "llm_unavailable": "Lớp AI không phản hồi",
    "llm_schema_error": "AI trả kết quả sai dạng",
    "target_check_error": "Không kiểm tra được đối tượng",
    "no_valid_approver": "Không có người duyệt hợp lệ",
    "approver_lookup_error": "Tra cứu người duyệt lỗi",
    "approver_sync_unavailable": "Chưa đồng bộ được người duyệt",
    "approver_no_longer_valid": "Người duyệt không còn hợp lệ",
    "person_no_longer_valid": "Người hưởng lợi không còn hợp lệ",
    "action_plan_changed_since_approval": "Thao tác đã đổi sau khi duyệt",
    "exec_failed": "Thực hiện lỗi",
    "exec_interrupted": "Thực hiện bị gián đoạn",
    "execution_interrupted": "Thực hiện bị gián đoạn",
    "max_loops_exceeded": "Vượt số vòng xử lý",
    "turn_budget_exceeded": "Hết thời gian cho lượt xử lý",
    "recover_exhausted": "Khôi phục không thành công",
}  # fmt: skip

ROUTE_LABELS: Final[dict[str, str]] = {"AUTO": "Tự xử lý", "HITL": "Chờ IT duyệt", "ESCALATE_L2": "Chuyển kỹ thuật viên L2"}
DECIDED_BY_LABELS: Final[dict[str, str]] = {"rule": "Theo luật", "llm": "Theo đánh giá của AI", "model": "Theo model chặn tấn công"}
OTHER: Final = "Khác"


def labeled(label: str | None, code: str) -> str:
    """"nhãn · mã" — mã luôn để cuối; không có nhãn → "Khác · mã"."""
    return f"{label or OTHER} · {code}"


def exit_label(code: str, reason_detail: str | None) -> str:
    if code == ExitCode.E1.value and reason_detail == "injection_suspected":
        return labeled(E1_INJECTION_SUSPECTED, code)
    known = {c.value: label for c, label in EXIT_LABELS.items()}
    return labeled(known.get(code), code)


def reason_label(reason: str) -> str:
    return labeled(REASON_LABELS.get(reason), reason)
