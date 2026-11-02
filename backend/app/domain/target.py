"""target — chốt "hành động chạy trên SAI ĐỐI TƯỢNG" (L-03, nhánh be-target-guard). Hàm THUẦN, hằng trong code (không cấu hình).

Lỗ: người gửi nhắm NGƯỜI KHÁC ("đặt lại mật khẩu cho tài khoản dịch vụ svc-backup") mà LLM KHÔNG đưa khoá `target_user` → `requested_for_of`
về người gửi (fail-open) → luật allow (R01) chạy trên CHÍNH người gửi. Cờ `ctx_flags.target_is_other` cũ chỉ bật khi đúng khoá
`target_user` bị `sanitize_slots` bỏ — không đủ.

`target_check` (B3 một ý, B5 từng con, `clarify_wait`): intent ∈ {account, access} (`TARGET_USER_INTENTS`) → lý do bật cờ:
- `target_user` bị bỏ (BẤT KỲ lý do) → `dropped` — luôn bật như Q-T20a-4/6 cũ (kể cả khi đã có `target_user` hợp lệ: không yếu hơn bản cũ);
- chưa có `target_user` hợp lệ VÀ: câu nêu người khác (`mention_reason`: `identifier` | `phrase`), hoặc có khoá bị bỏ `unknown_key` NẰM
  NGOÀI `spec.keys` (khoá lạ của LLM như `account_name` — khoá đã khai báo mà không đang hỏi ở B11 không tính) → `unknown_key`.
Không bao giờ trả lý do để HẠ cờ; nơi gọi chỉ ghi True.

`mention_reason(text, requester_id, ignore=…)`:
- `identifier`: token định danh ASCII `[a-z0-9][a-z0-9._-]*[a-z0-9]` (casefold) có ≥ 1 chữ VÀ (≥ 1 số hoặc `.`/`_`/`-`), khác `requester_id`.
  LOẠI: token chứa `/` (đường dẫn), `@`, `:`; mã máy `^[a-z]{2,4}-\\d{3,5}$`; mã lỗi hex; phiên bản `v1.2`; đuôi tệp; URL/tên miền;
  `STOPLIST`; token TRÙNG ĐÚNG (casefold) giá trị slot TÀI NGUYÊN đã qua `sanitize_slots` (`RESOURCE_SLOTS`: `resource_path`,
  `software_name`, `device_id` — truyền qua `ignore`, A1). Mặt nạ PII `<LOẠI_n>`
  TÍNH là định danh lạ (thận trọng); `[BÍ_MẬT_ĐÃ_ẨN]` KHÔNG tính.
- `phrase`: cụm gợi ý người khác, so cả bản có dấu lẫn bản bỏ dấu. Tự xưng ("cho em", "giúp em", "của em", "mình", "tôi") không tính.

Audit chỉ ghi lý do (hằng) + bool — KHÔNG ghi câu hay token.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from app.domain.action import TARGET_USER_INTENTS
from app.domain.context import RequesterContext

type MentionReason = Literal["identifier", "phrase"]
type FlagReason = Literal["identifier", "phrase", "dropped", "unknown_key"]

# B11 hỏi `target_user` khi cờ bật mà chưa có đích — câu CỐ ĐỊNH, không gọi LLM (vẫn qua output guard, notify, hạn).
TARGET_QUESTION = (
    "Bạn cần xử lý cho tài khoản của ai? Vui lòng ghi đúng mã tài khoản trong hệ thống (ví dụ: nv005). "
    "Nếu là tài khoản của chính bạn, hãy ghi mã nhân viên của bạn."
)

# A1: slot TÀI NGUYÊN — giá trị đã sạch của các khoá này không phải định danh người.
RESOURCE_SLOTS = frozenset({"resource_path", "software_name", "device_id"})

STOPLIST = frozenset({
    "e-mail", "wi-fi", "log-in", "log-out", "sign-in", "sign-up", "sign-out", "check-in", "plug-in", "add-in", "pop-up",
    "set-up", "back-up", "follow-up", "re-login", "utf-8", "office365", "o365", "m365", "microsoft365", "2fa", "mfa-2fa",
    "win7", "win10", "win11", "windows7", "windows10", "windows11", "ipv4", "ipv6", "3g", "4g", "5g", "mp3", "mp4", "a3", "a4",
    "covid-19", "24h", "24-7",
})  # fmt: skip

_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]*[a-z0-9]")
_MACHINE = re.compile(r"[a-z]{2,4}-\d{3,5}")
_HEX = re.compile(r"0x[0-9a-f]+|[0-9a-f]{8}")
_VERSION = re.compile(r"v\d+(?:[._-]\d+)*")
_FILE_EXT = re.compile(
    r".+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|exe|msi|zip|rar|7z|png|jpe?g|gif|log|ini|cfg|conf|json|xml|ya?ml|bat|ps1|sh|dmg|pkg|"
    r"iso|apk|mp3|mp4|pst|ost)"
)
_DOMAIN = re.compile(r"(?:www\..+|.+\.(?:com|vn|net|org|local|io|edu|gov|info|biz|co|corp|lan|int|dev|app))")
_PII_MASK = re.compile(r"<[^\s<>]+_\d+>")  # guard/privacy.py: `<LOẠI_n>`
_SECRET_MASK = "[BÍ_MẬT_ĐÃ_ẨN]"
_EDGE_PUNCT = ".,;:!?()[]{}<>\"'“”‘’«»…"

_PHRASES = (
    r"tài khoản dịch vụ", r"service account", r"\bsvc\b", r"người khác", r"đồng nghiệp", r"nhân viên mới",
    r"\b(?:anh|chị|em|bạn|cậu|cô|chú) ấy\b", r"tài khoản của (?:anh|chị|bạn|sếp|cô|chú)\b", r"\bhộ (?:anh|chị|bạn)\b",
)  # fmt: skip
_NAMED = r"(?i:\bcho (?:anh|chị|bạn|sếp|cô|chú)) (\w)"  # "cho chị Hoa" — tên viết hoa (so trên bản giữ hoa/thường)


def fold(text: str) -> str:
    """Bỏ dấu tiếng Việt (giữ hoa/thường): NFD → bỏ dấu kết hợp, đ/Đ → d/D."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if not unicodedata.combining(c)))


_PHRASE_RES = tuple(re.compile(p) for p in _PHRASES) + tuple(re.compile(fold(p)) for p in _PHRASES)
_NAMED_RES = (re.compile(_NAMED), re.compile(fold(_NAMED)))


def _ignored_values(values: Iterable[str]) -> frozenset[str]:
    """A1 (chốt ĐP): CHỈ token TRÙNG ĐÚNG (casefold) giá trị slot — không tách đoạn `/`, không khớp một phần."""
    return frozenset(v.strip().casefold() for v in values)


def _is_identifier(token: str, requester: str, ignore: frozenset[str]) -> bool:
    if not token.isascii() or _TOKEN.fullmatch(token) is None:
        return False
    if not any(c.isalpha() for c in token) or not any(c.isdigit() or c in "._-" for c in token):
        return False
    if token == requester or token in ignore or token in STOPLIST:
        return False
    return not any(r.fullmatch(token) for r in (_MACHINE, _HEX, _VERSION, _FILE_EXT, _DOMAIN))


def _has_identifier(text: str, requester_id: str, ignore: frozenset[str]) -> bool:
    if _PII_MASK.search(text):  # mặt nạ PII = định danh lạ (thận trọng)
        return True
    requester = requester_id.strip().casefold()
    for piece in text.replace(_SECRET_MASK, " ").split():
        token = piece.strip(_EDGE_PUNCT).casefold()
        if token and _is_identifier(token, requester, ignore):
            return True
    return False


def _has_phrase(text: str) -> bool:
    lowered = text.casefold()
    folded = fold(lowered)
    if any(r.search(lowered) or r.search(folded) for r in _PHRASE_RES):
        return True
    for r in _NAMED_RES:
        for target in (text, fold(text)):
            if any(m.group(1).isupper() for m in r.finditer(target)):
                return True
    return False


def mention_reason(text: str, requester_id: str, *, ignore: Iterable[str] = ()) -> MentionReason | None:
    """Câu có nêu người KHÁC người gửi không — `identifier` | `phrase` | None. `ignore`: giá trị slot tài nguyên đã sạch (A1)."""
    if _has_identifier(text, requester_id, _ignored_values(ignore)):
        return "identifier"
    if _has_phrase(text):
        return "phrase"
    return None


def mentions_other_target(text: str, requester_id: str, *, ignore: Iterable[str] = ()) -> bool:
    return mention_reason(text, requester_id, ignore=ignore) is not None


def requester_id_of(state: Mapping[str, Any]) -> str:
    """user_id người gửi (B1) từ state — thiếu (test node trần) → "" (mọi định danh đều là "người khác": thận trọng)."""
    rc = state.get("requester_context")
    return "" if rc is None else RequesterContext.model_validate(rc).user_id


def target_check(
    intent: str | None,
    slots: Mapping[str, str],
    dropped: Mapping[str, str],
    spec_keys: frozenset[str],
    text: str,
    requester_id: str,
) -> tuple[bool, FlagReason | None]:
    """(câu nêu người khác?, lý do bật cờ hoặc None). `slots` = slot SẠCH hiện có (clarify: đã gộp); `dropped` = khoá bị bỏ ở lượt
    này. intent ngoài account/access → (False, None)."""
    if intent not in TARGET_USER_INTENTS:
        return False, None
    ignore = [v for k, v in slots.items() if k in RESOURCE_SLOTS]
    mention = mention_reason(text, requester_id, ignore=ignore)
    if "target_user" in dropped:
        return mention is not None, "dropped"
    if slots.get("target_user"):
        return mention is not None, None
    if mention is not None:
        return True, mention
    if any(r == "unknown_key" and k not in spec_keys for k, r in dropped.items()):
        return False, "unknown_key"
    return False, None
