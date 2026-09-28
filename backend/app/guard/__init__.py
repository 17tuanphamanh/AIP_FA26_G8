"""B2 — L0 guard, privacy guard (L1), mẫu injection (L2), sàng lọc tin trả lời. Xem phase3 mục 8, PLAN-3e."""

from app.guard.patterns import PatternFileError, check_guard
from app.guard.privacy import (
    NotRedactingGuard,
    PrivacyGuard,
    RedactionResult,
    RegexPrivacyGuard,
)

__all__ = [
    "NotRedactingGuard", "PatternFileError", "PrivacyGuard", "RedactionResult", "RegexPrivacyGuard", "check_guard",
]  # fmt: skip
