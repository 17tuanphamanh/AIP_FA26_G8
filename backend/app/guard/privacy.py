"""Privacy guard ở API (B02 lớp L0–L1, D-07; phase3 mục 8.3): chạy TRƯỚC khi lưu ticket hay đưa tin nhắn vào graph —
ticket, checkpoint, audit, LLM chỉ thấy bản đã che.

`RegexPrivacyGuard` (3e, KHÔNG dùng Presidio — 3-Q22): L0 guard (`guard/normalize.l0`) rồi 10 luật của
`config/privacy_patterns.json` theo đúng thứ tự: bí mật (PEM, JWT, API key, cụm mật khẩu, OTP, chuỗi entropy cao) →
`[BÍ_MẬT_ĐÃ_ẨN]`, KHÔNG giữ giá trị; PII (email ngoài tên miền công ty, SĐT, CCCD, STK) → `<LOẠI_n>` — cùng giá trị
(đã chuẩn hoá) trong MỘT văn bản → cùng nhãn. Không lưu ánh xạ nhãn ↔ giá trị (3-Q23). Không log văn bản.
be-pii-uuid: khớp PII mà phần bị thay CHỒNG lên một vùng `pii_exclude` (UUID 8-4-4-4-12, tính trên văn bản hiện tại của từng luật) →
giữ nguyên, không đếm. Không miễn URL; luật bí mật/entropy không đổi.

`NotRedactingGuard` (không che) CHỈ nạp khi `PRIVACY_GUARD=none` VÀ `APP_ENV` ∈ {dev, test} (`main._default_guard`).
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel

from app.guard.normalize import l0
from app.guard.patterns import (
    VALUE_GROUP,
    Canonical,
    PrivacyPatterns,
    PrivacyRule,
    privacy_patterns,
)
from app.settings import Settings

# Nguyên văn phase3 mục 8.3 — người dùng thấy trong `notices` của body 202.
NOTICE_SECRET = "Vui lòng không gửi mật khẩu hoặc mã bí mật qua chat. Phần đó đã được ẩn và không được lưu."
NOTICE_PII = "Một số thông tin cá nhân trong tin nhắn đã được ẩn."

_TOKEN = re.compile(r"\S+")
_EDGE_PUNCT = "\"'()[]{}<>,.;:!?"
_NON_DIGIT = re.compile(r"\D")


class RedactionResult(BaseModel):
    """B02 mục 4 — hợp đồng giữ nguyên; 3e chỉ THÊM `pii_found` (có mặc định)."""

    text: str  # đã che
    secrets_found: int  # số chỗ bí mật bị thay — không lưu giá trị
    pii_map_id: str | None  # Phase 3 luôn None (3-Q23: không lưu ánh xạ)
    notices: list[str]  # ví dụ "Vui lòng không gửi mật khẩu qua chat"
    pii_found: dict[str, int] = {}  # nhãn → số chỗ bị thay


class PrivacyGuard(Protocol):
    async def redact(self, text: str) -> RedactionResult: ...


class TextRedactor(Protocol):
    """Bản THUẦN cho node (3g, chốt Q-3g-4): `clarify_wait` che lại câu trả lời — không ghi sự kiện/notice lần hai."""

    def redact_text(self, text: str) -> RedactionResult: ...


class NotRedactingGuard:
    """Không che gì — chỉ dev/test với `PRIVACY_GUARD=none` (bên gọi phải qua `Settings.require_dev_fakes` trước)."""

    async def redact(self, text: str) -> RedactionResult:
        return self.redact_text(text)

    def redact_text(self, text: str) -> RedactionResult:
        return RedactionResult(text=text, secrets_found=0, pii_map_id=None, notices=[])


def guard_from_settings(settings: Settings) -> "RegexPrivacyGuard | NotRedactingGuard":
    """Mặc định MỌI env: guard regex thật (3e). `PRIVACY_GUARD=none` chỉ dev/test (phase3 mục 8.3, e17). Dùng chung cho API
    (`main._default_guard`) và runtime graph (`graph/wiring._open` → `NodeDeps.privacy`, 3g)."""
    if settings.privacy_guard == "none":
        settings.require_dev_fakes("PRIVACY_GUARD=none (NotRedactingGuard — privacy guard không che)")
        return NotRedactingGuard()
    return RegexPrivacyGuard.from_settings(settings)


def shannon_bits(text: str) -> float:
    n = len(text)
    return -sum(c / n * math.log2(c / n) for c in Counter(text).values()) if n else 0.0


def _canonical(value: str, how: Canonical) -> str:
    if how == "lower":
        return value.lower()
    if how in ("phone", "digits"):
        digits = _NON_DIGIT.sub("", value)
        return "0" + digits[2:] if how == "phone" and digits.startswith("84") else digits
    return value


class _Labels:
    """Đánh số nhãn PII trong MỘT văn bản: (loại, giá trị chuẩn hoá) → `<LOẠI_n>`, n theo thứ tự xuất hiện đầu."""

    def __init__(self) -> None:
        self._seen: dict[str, dict[str, int]] = {}

    def of(self, label: str, key: str) -> str:
        seen = self._seen.setdefault(label, {})
        return f"<{label}_{seen.setdefault(key, len(seen) + 1)}>"


def _value_span(m: re.Match[str]) -> tuple[int, int]:
    """Đoạn cần thay: nhóm `v` nếu mẫu có (chỉ giá trị), không thì cả đoạn khớp."""
    if VALUE_GROUP in m.re.groupindex and m.group(VALUE_GROUP) is not None:
        return m.span(VALUE_GROUP)
    return m.span()


def _replace(m: re.Match[str], replacement: str) -> str:
    start, end = _value_span(m)
    whole = m.group(0)
    return whole[: start - m.start()] + replacement + whole[end - m.start() :]


class RegexPrivacyGuard:
    def __init__(self, patterns: PrivacyPatterns, company_email_domains: Sequence[str]) -> None:
        self._p = patterns
        self._company = tuple(d.lower().strip(".") for d in company_email_domains)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RegexPrivacyGuard":
        return cls(privacy_patterns(settings.config_dir), settings.company_email_domains)

    async def redact(self, text: str) -> RedactionResult:
        return self.redact_text(text)

    def redact_text(self, text: str) -> RedactionResult:
        out = l0(text)
        secrets = 0
        pii: Counter[str] = Counter()
        labels = _Labels()
        for rule in self._p.rules:
            if rule.kind == "secret":
                out, n = self._secret(rule, out)
                secrets += n
            elif rule.kind == "entropy":
                out, n = self._entropy(rule, out)
                secrets += n
            else:
                out, n = self._pii(rule, out, labels)
                if n:
                    pii[str(rule.label)] += n
        notices = ([NOTICE_SECRET] if secrets else []) + ([NOTICE_PII] if pii else [])
        return RedactionResult(text=out, secrets_found=secrets, pii_map_id=None, notices=notices, pii_found=dict(pii))

    def _secret(self, rule: PrivacyRule, text: str) -> tuple[str, int]:
        assert rule.pattern is not None
        return rule.pattern.subn(lambda m: _replace(m, self._p.secret_mask), text)

    def _entropy(self, rule: PrivacyRule, text: str) -> tuple[str, int]:
        count = 0
        mask = self._p.secret_mask

        def hit(core: str) -> bool:
            return not (
                len(core) < rule.min_len
                or any(ex.search(core) for _, ex in self._p.entropy_exclude)
                or shannon_bits(core) < rule.min_bits
            )

        def piece(part: str) -> str:
            nonlocal count
            core = part.strip(_EDGE_PUNCT)
            if not hit(core):
                return part
            count += 1
            return part.replace(core, mask, 1)

        def one(m: re.Match[str]) -> str:
            nonlocal count
            token = m.group(0)
            core = token.strip(_EDGE_PUNCT)
            if mask not in core and hit(core):  # logic trước F15, giữ nguyên: đã che thì dùng kết quả này
                count += 1
                return token.replace(core, mask, 1)
            # Việc treo 34: bản trước F15 bỏ qua token chứa mặt nạ → chuỗi ngẫu nhiên dính liền mặt nạ lọt. Chỉ khi logic cũ
            # KHÔNG che: tách theo mặt nạ, xét từng mảnh bằng đúng điều kiện trên → không bao giờ che ít hơn bản cũ.
            return mask.join(piece(p) for p in token.split(mask))

        return _TOKEN.sub(one, text), count

    def _pii(self, rule: PrivacyRule, text: str, labels: _Labels) -> tuple[str, int]:
        assert rule.pattern is not None and rule.label is not None
        label = rule.label
        count = 0
        protected = [m.span() for _, ex in self._p.pii_exclude for m in ex.finditer(text)]

        def one(m: re.Match[str]) -> str:
            nonlocal count
            start, end = _value_span(m)
            value = m.string[start:end]
            if any(s < end and start < e for s, e in protected):  # be-pii-uuid: nằm (một phần) trong UUID → không phải PII
                return m.group(0)
            if rule.id == "email" and self._is_company(value):
                return m.group(0)
            count += 1
            return _replace(m, labels.of(label, _canonical(value, rule.canonical)))

        return rule.pattern.sub(one, text), count

    def _is_company(self, email: str) -> bool:
        domain = email.rsplit("@", 1)[-1].lower()
        return any(domain == d or domain.endswith("." + d) for d in self._company)
