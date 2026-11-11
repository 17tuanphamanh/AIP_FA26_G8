"""E0–E9, block_reason, close_reason — NGU-CANH-DAY-DU.md Phần IV mục 1.3, 3 và khối CTX.

Không thêm mã thoát hay close_reason mới ngoài danh sách này (docs/spec/CLAUDE.md mục 4).
"""

from enum import StrEnum


class ExitCode(StrEnum):
    E0 = "E0"  # Prompt injection
    E1 = "E1"  # Ngoài phạm vi
    E2 = "E2"  # Tool/RAG lỗi hệ thống sau retry
    E3 = "E3"  # Không có căn cứ (NO_EVIDENCE)
    E4 = "E4"  # Hỏi 3 lần vẫn thiếu
    E5 = "E5"  # Rủi ro cao / deny / hash lệch
    E6 = "E6"  # Hết hạn duyệt (fail-safe)
    E7 = "E7"  # Thực thi lỗi
    E8 = "E8"  # Người dùng báo chưa xong
    E9 = "E9"  # Lỗi chưa lường trước


# Ưu tiên hàng đợi L2 — bảng mã thoát trong khối CTX.
L2_PRIORITY: dict[ExitCode, str] = {
    ExitCode.E0: "An ninh",
    ExitCode.E1: "Thường",
    ExitCode.E2: "Hạ tầng",
    ExitCode.E3: "Thường, kèm cờ bổ sung KB",
    ExitCode.E4: "Thường",
    ExitCode.E5: "Cao",
    ExitCode.E6: "Có SLA",
    ExitCode.E7: "Rất cao",
    ExitCode.E8: "Thường",
    ExitCode.E9: "Ngang E2",
}


class BlockReason(StrEnum):
    INVALID_CREDENTIALS = "invalid_credentials"  # B1, không phải sự cố an ninh
    REPEATED_AUTH_FAILURE = "repeated_auth_failure"  # B1, sự cố an ninh
    INJECTION_DETECTED = "injection_detected"  # B2, sự cố an ninh (E0)


class CloseReason(StrEnum):
    RESOLVED_USER_CONFIRMED = "resolved_user_confirmed"
    RESOLVED_AUTO_TIMEOUT_48H = "resolved_auto_timeout_48h"
    RESOLVED_AFTER_ESCALATION = "resolved_after_escalation"
    RESOLVED_AFTER_DENY_REVIEW = "resolved_after_deny_review"
    REJECTED_BY_APPROVER = "rejected_by_approver"
    BLOCKED_INVALID_CREDENTIALS = "blocked_invalid_credentials"
    BLOCKED_REPEATED_AUTH_FAILURE = "blocked_repeated_auth_failure"
    BLOCKED_INJECTION_DETECTED = "blocked_injection_detected"


BLOCK_TO_CLOSE: dict[BlockReason, CloseReason] = {
    BlockReason.INVALID_CREDENTIALS: CloseReason.BLOCKED_INVALID_CREDENTIALS,
    BlockReason.REPEATED_AUTH_FAILURE: CloseReason.BLOCKED_REPEATED_AUTH_FAILURE,
    BlockReason.INJECTION_DETECTED: CloseReason.BLOCKED_INJECTION_DETECTED,
}

SECURITY_BLOCK_REASONS = frozenset({BlockReason.REPEATED_AUTH_FAILURE, BlockReason.INJECTION_DETECTED})


# Giá trị `escalations.reason_detail`/`escalation_reason_detail` hợp lệ (Phase 3, mục 3.4 + giá trị
# đã có từ Phase 2 ở node giả B1/B3 và runner). Test AST (test_state_keys_ast.py, c33) quét mọi chuỗi
# gán cho `escalation_reason_detail` trong `graph/**` phải thuộc tập này.
REASON_DETAILS: frozenset[str] = frozenset({
    # Phase 3 mục 3.4 (22 giá trị)
    "rag_system_error", "no_grounding", "llm_unavailable", "llm_schema_error",
    "screening_unavailable", "injection_in_reply", "intent_not_enabled",
    "multi_intent_not_enabled", "tool_system_error", "max_loops_exceeded",
    "invalid_citation", "output_guard_block", "clarification_exhausted",
    "clarify_timeout", "off_topic_twice", "target_check_error", "llm_layer_disabled",
    "recheck_failed", "action_plan_changed_since_approval", "person_no_longer_valid",
    "exec_failed", "exec_interrupted",
    # Phase 3 mục 9.0 (3f S0): hạn cho cả lượt — boundary + B2/B3/B6
    "turn_budget_exceeded",
    # Phase 4 S0-P10 (Q-4-U A+): B11 — tài liệu quy trình của action_type không có/tắt/không được xem trong KB hiện hành → E3
    "no_procedure",
    # Phase 4 4b (P11, Q-4b-1, Q-4b-5): B15 — không người duyệt hợp lệ (E5), tra AD người duyệt lỗi (E2 — cả B17 `decided_by`),
    # đích chưa xác minh chủ (E5, P6), thiếu khoá HMAC để đồng bộ người duyệt (E2); B17 — người đã duyệt không còn hợp lệ (E5)
    "no_valid_approver", "approver_lookup_error", "approval_target_unverified", "approver_sync_unavailable",
    "approver_no_longer_valid",
    # Phase 6 6C (P3, Q-6C-2): B12 — lớp LLM của M5 định tuyến chuyển L2 (E5); lỗi estimator vẫn là `llm_layer_disabled`
    "llm_high_risk",
    # M2 (ĐP 08/11): B12 — luật `deny` khớp → E5 (trước: không ghi lý do); tách khỏi lỗi lớp AI (`llm_layer_disabled`). Không đổi route/mã
    "policy_deny",
    # D-84 (kiểm thử 12/11): B3/B4 hoặc clarify_wait — người dùng xin thao tác NGƯỢC (thu hồi, khoá, báo mất máy, gỡ cài, đừng làm, huỷ)
    # mà hệ thống không có → E1, không dựng hành động (`domain/reverse_action.py`)
    "reverse_action_requested",
    # Đã có trong code từ Phase 2 (node giả B1/B3, runner)
    "execution_interrupted", "identity_unverifiable", "intent_low_confidence",
    "out_of_scope", "role_unmappable", "recover_exhausted",
    # Phase 5 T20b (P2, bảng 5.2.2, D-49): `span` của một ý (câu nhiều ý) rỗng hoặc không nằm trong câu → con E1
    "split_span_invalid",
    # Phase 5 gói 1 (D-52, bảng 4.2 #4 #5): B2 `review` — model nghi (p ≥ τ hoặc 422 too_many_windows) mà LLM chấm nói không → E1
    # (không mã thoát mới; tin người dùng = tin E0 — B20; không security_event/security_flag)
    "injection_suspected",
})  # fmt: skip
