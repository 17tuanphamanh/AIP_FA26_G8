"""Output guard (phase3 mục 10.3; B10 §2, §10 [Chốt 17.6: kiểm đầu ra]) — hàm thuần, không gọi mạng, không log văn bản.

MỌI chữ do LLM viết mà sắp được LƯU hoặc GỬI người dùng đi qua đây TRƯỚC `notify_user` (chốt P4 3g): thân câu trả lời B10
(đã render theo mẫu) và câu hỏi B11. `violation(text)` trả loại vi phạm (enum, ghi được vào audit) hoặc `None`:

- `"secret"` — một trong luật bí mật 1–6 của `config/privacy_patterns.json` (PEM, JWT, API key, cụm mật khẩu, OTP, chuỗi
  entropy cao) khớp trên bản L0. Dùng lại CHÍNH `RegexPrivacyGuard.redact_text` (`secrets_found > 0`) — một định nghĩa
  "bí mật" cho cả đầu vào lẫn đầu ra. PII (email, SĐT…) không tính ở đây.
- `"canary"` — chứa một chuỗi trong `Settings.output_canaries` (không phân biệt hoa thường, so cả bản gốc lẫn bản L0).
- `"system_prompt"` — chứa một đoạn ≥ `SYSTEM_SHINGLE` ký tự trùng một dòng `system` của bất kỳ prompt nào đã nạp. So sau
  khi L0 + casefold + gộp khoảng trắng (chặt hơn "nguyên văn": đổi hoa thường/khoảng trắng không lách được).

Q-3g-8: luật 4 (cụm mật khẩu) cũng chặn câu KB kiểu "Mật khẩu: tối thiểu 12 ký tự" — giữ chặn (phân vân → chặn); probe mốc G.
"""

from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.guard.normalize import l0
from app.guard.patterns import PrivacyPatterns, privacy_patterns
from app.guard.privacy import RegexPrivacyGuard
from app.llm.registry import load_prompts
from app.settings import get_settings

SYSTEM_SHINGLE = 40  # phase3 10.3 (c)

type Violation = Literal["secret", "canary", "system_prompt"]


def _squash(text: str) -> str:
    return " ".join(l0(text).casefold().split())


class OutputGuard:
    def __init__(self, patterns: PrivacyPatterns, canaries: Sequence[str], system_texts: Iterable[str]) -> None:
        # Tên miền công ty không liên quan (PII không tính) — truyền rỗng để luật email không phụ thuộc cấu hình.
        self._secrets = RegexPrivacyGuard(patterns, ())
        self._canaries = tuple(c.casefold() for c in canaries if c.strip())
        shingles: set[str] = set()
        for text in system_texts:
            for line in text.splitlines():
                s = _squash(line)
                shingles.update(s[i : i + SYSTEM_SHINGLE] for i in range(len(s) - SYSTEM_SHINGLE + 1))
        if not shingles:
            raise ValueError("output guard: không có dòng system nào ≥ 40 ký tự — prompt chưa nạp?")
        self._shingles = frozenset(shingles)

    @classmethod
    def from_config(cls, config_dir: Path, canaries: Sequence[str]) -> "OutputGuard":
        """Luật bí mật + dòng `system` của mọi prompt trong `config/prompts` (cùng nguồn với gateway)."""
        prompts = load_prompts(config_dir / "prompts")
        return cls(privacy_patterns(config_dir), canaries, (p.spec.system for p in prompts))

    def violation(self, text: str) -> Violation | None:
        if self._secrets.redact_text(text).secrets_found:
            return "secret"
        lowered = (text.casefold(), l0(text).casefold())
        if any(c in form for c in self._canaries for form in lowered):
            return "canary"
        s = _squash(text)
        if any(s[i : i + SYSTEM_SHINGLE] in self._shingles for i in range(len(s) - SYSTEM_SHINGLE + 1)):
            return "system_prompt"
        return None

    def violates(self, text: str) -> bool:
        return self.violation(text) is not None


@lru_cache
def default_output_guard() -> OutputGuard:
    """Mặc định của `NodeDeps.output_guard` (test, dev) — cấu hình repo + `OUTPUT_CANARIES`. Runtime dựng tường minh."""
    settings = get_settings()
    return OutputGuard.from_config(settings.config_dir, settings.output_canaries)
