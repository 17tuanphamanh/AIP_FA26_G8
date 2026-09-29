"""B2 — L0 guard, privacy guard (L1), mẫu injection (L2), sàng lọc tin trả lời. Xem phase3 mục 8, PLAN-3e."""

from app.guard.injection import TAU_BLOCK, TAU_PASS, ScreenHit
from app.guard.injection import match as screen_input
from app.guard.patterns import PatternFileError, check_guard
from app.guard.privacy import (
    NotRedactingGuard,
    PrivacyGuard,
    RedactionResult,
    RegexPrivacyGuard,
)
from app.guard.screen import screen_reply

__all__ = [
    "TAU_BLOCK", "TAU_PASS", "NotRedactingGuard", "PatternFileError", "PrivacyGuard", "RedactionResult",
    "RegexPrivacyGuard", "ScreenHit", "check_guard", "screen_input", "screen_reply",
]  # fmt: skip
