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
