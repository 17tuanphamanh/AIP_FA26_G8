"""Lỗi của gateway (P2 mục 4; phase3 mục 3.3).

Ba lỗi node phải bắt — `LLMSchemaError`, `LLMUnavailable`, `LLMBudgetExceeded` — nằm ở `core/errors.py` để node và
`risk` dùng chung; re-export ở đây. Ba lỗi dưới là BUG (hợp đồng sai), không phải lỗi provider: chúng xuyên qua vòng
retry của gateway (không bao giờ thành `LLMUnavailable`) và boundary đổi thành E9.
"""

from app.core.errors import (
    DomainError,
    LLMBudgetExceeded,
    LLMSchemaError,
    LLMUnavailable,
)

__all__ = [
    "LLMBudgetExceeded", "LLMSchemaError", "LLMUnavailable", "PromptContractError", "PromptVariableError",
    "ScriptExhausted",
]  # fmt: skip


class PromptVariableError(DomainError):
    """Biến ngoài `allowed_vars`, hoặc thiếu biến mà template cần (P2 mục 7). Thông điệp chỉ nêu TÊN biến."""


class PromptContractError(DomainError):
    """`prompt_id` lạ, hoặc `role`/`schema`/`cache_policy` node truyền lệch YAML prompt (PLAN-3d Q-3d-5)."""


class ScriptExhausted(DomainError):
    """ScriptedLLM hết kịch bản / không có kịch bản cho prompt — không bao giờ tự trả mặc định (3-Q26)."""
