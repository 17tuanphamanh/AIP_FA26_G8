"""Lỗi dùng chung. Node quyết định lỗi nào thành mã thoát nào — xem từng file nhánh."""


class DomainError(Exception):
    """Vi phạm quy tắc nghiệp vụ (ví dụ chuyển trạng thái không hợp lệ). Là bug, không phải
    lỗi của người dùng: lọt tới boundary thì thành E9."""


class ExternalSystemError(Exception):
    """Hệ thống ngoài (AD, VPN, ml-service, RAG…) lỗi sau retry. Khác kết quả rỗng: E2 ≠ E3."""


class LLMSchemaError(Exception):
    """LLM trả sai schema sau 1 lần sửa (P2 mục 10)."""
