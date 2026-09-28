"""Lỗi dùng chung. Node quyết định lỗi nào thành mã thoát nào — xem từng file nhánh."""


class DomainError(Exception):
    """Vi phạm quy tắc nghiệp vụ (ví dụ chuyển trạng thái không hợp lệ). Là bug, không phải
    lỗi của người dùng: lọt tới boundary thì thành E9."""


class ExternalSystemError(Exception):
    """Hệ thống ngoài (AD, VPN, ml-service, RAG…) lỗi sau retry. Khác kết quả rỗng: E2 ≠ E3."""


class LLMSchemaError(Exception):
    """LLM trả sai schema sau 1 lần sửa (P2 mục 10)."""


class LLMUnavailable(Exception):
    """Gateway hết retry và fallback, hết `deadline_s`, hoặc không đọc được tổng chi tiêu (P2 mục 4, 9;
    PLAN-3d Q-3d-7, Q-3d-14). Node ánh xạ theo phase3 mục 3.3 (B3/B10/B11 → E2 `llm_unavailable`)."""


class LLMBudgetExceeded(Exception):
    """Vượt trần: token đầu vào sau khi cắt (`budget_in`), trần chi tiêu (`spend.cap_usd`), hoặc model không có
    dòng `pricing` (P2 mục 4, 5; 3-Q26). Không một request nào được gửi đi. Node ánh xạ như `LLMUnavailable`."""
