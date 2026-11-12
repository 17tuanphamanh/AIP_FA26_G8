"""V6 soát 12/11 (agent 05, D-91): slot CHUẨN HOÁ phải có dấu vết trong câu người dùng.

Trước: `account_type`, `permission_level`, `duration`, `action` do LLM điền không cần bằng chứng (`slots.MUST_APPEAR_IN_TEXT` không có) →
"Gia hạn quyền thư mục … giúp mình" + LLM bịa `duration=90` → gia hạn 90 ngày AUTO; "Đặt lại mật khẩu giúp mình" + LLM đoán `erp` →
đặt lại mật khẩu ERP AUTO; "… bị khoá, mở khoá giúp mình" + LLM trả `reset_password` → đặt lại mật khẩu thay vì mở khoá.

Luật (tất định, so trên bản chữ thường VÀ bản bỏ dấu):
- `account_type` / `permission_level`: câu phải có từ khoá của ĐÚNG giá trị đó.
- `duration`: câu phải có số + đơn vị (ngày/tuần/tháng/năm, số viết bằng chữ cũng được) hoặc CHỈ là một con số (câu trả lời cho câu hỏi số
  ngày); số ngày LLM điền phải bằng một trong các khoảng thời gian đọc được.
- `action` (account): chỉ bỏ khi câu có dấu vết của hành động KIA mà không có dấu vết của hành động LLM chọn (mâu thuẫn) — câu không nói rõ
  thì giữ như cũ (luồng chỉ tả lỗi đã chốt AUTO, C1 12/11).
Không khớp → `slot_not_in_text` → B11 hỏi câu cố định / câu hỏi slot như khi LLM để trống. Chiều an toàn: chỉ thêm câu hỏi.
"""

import re
import unicodedata
from typing import Final


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _both(pattern: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    return re.compile(pattern), re.compile(_fold(pattern))


_ACCOUNT_TYPE: Final = {
    "ad": _both(r"(?<!\w)(?:ad|active directory|windows|win|domain|pc|laptop|svc)(?!\w)|máy tính|đăng nhập máy|đăng nhập vào máy"
                r"|tài khoản máy|máy công ty|máy làm việc|tài khoản dịch vụ|service account|tài khoản công ty"),  # tài khoản dịch vụ nằm trong AD (R03)
    "email": _both(r"e-?mail|(?<!\w)mail(?!\w)|outlook|hộp thư|thư điện tử|webmail"),
    "erp": _both(r"(?<!\w)(?:erp|sap|misa|bravo)(?!\w)|phần mềm kế toán|hệ thống kế toán"),
}  # fmt: skip
_PERMISSION_LEVEL: Final = {
    "read": _both(r"đọc|chỉ xem|(?<!\w)(?:xem|read|view|readonly|read-only)(?!\w)"),
    "write": _both(r"(?<!\w)(?:ghi|sửa|chỉnh|write|edit|upload)(?!\w)|chỉnh sửa|tải lên|cập nhật|thêm file|xoá file|xóa file"),
    "full": _both(r"toàn quyền|(?<!\w)(?:full|admin)(?!\w)|đầy đủ|mọi quyền|quản trị"),
}  # fmt: skip
# Mở khoá: mọi nhắc tới "khoá/lock" (cả "bị quản trị viên khoá"); đặt lại: chỉ dấu vết rõ (không "sai mật khẩu" — hay đi kèm phủ định)
_UNLOCK: Final = _both(r"khoá|khóa|(?<!\w)(?:unlock|locked|lock)(?!\w)")
_RESET: Final = _both(r"đặt lại|(?<!\w)(?:reset|quên)(?!\w)|đổi mật khẩu|mật khẩu mới|cấp lại mật khẩu|không nhớ"
                      r"|hết hạn mật khẩu|mật khẩu hết hạn|(?<!\w)(?:mk|pass|password) mới")  # fmt: skip

_NUMBER_WORDS: Final = {
    "một": 1.0, "hai": 2.0, "ba": 3.0, "bốn": 4.0, "tư": 4.0, "năm": 5.0, "sáu": 6.0, "bảy": 7.0, "tám": 8.0, "chín": 9.0,
    "mười": 10.0, "nửa": 0.5,
}  # fmt: skip
_UNIT_DAYS: Final = {"ngày": 1, "day": 1, "days": 1, "tuần": 7, "week": 7, "weeks": 7, "tháng": 30, "month": 30, "months": 30,
                     "năm": 365, "year": 365, "years": 365}  # fmt: skip
_FOLDED_NUMBERS: Final = {_fold(k): v for k, v in _NUMBER_WORDS.items()}
_FOLDED_UNITS: Final = {_fold(k): v for k, v in _UNIT_DAYS.items()}
_NUM: Final = r"\d{1,3}|" + "|".join(sorted({*_NUMBER_WORDS, *_FOLDED_NUMBERS}, key=len, reverse=True))
_UNIT: Final = "|".join(sorted({*_UNIT_DAYS, *_FOLDED_UNITS}, key=len, reverse=True))
_SPAN: Final = re.compile(rf"(?<!\w)({_NUM})\s*({_UNIT})(?!\w)")
_BARE_NUMBER: Final = re.compile(r"\s*(\d{1,3})\s*(?:ngày|ngay)?\s*[.!]?\s*")


def _hit(pair: tuple[re.Pattern[str], re.Pattern[str]], text: str) -> bool:
    lowered = text.casefold()
    return pair[0].search(lowered) is not None or pair[1].search(_fold(lowered)) is not None


def durations_in_text(text: str) -> frozenset[int]:
    """Các khoảng thời gian (ngày) đọc được trong câu: "30 ngày", "2 tuần", "một tháng", "nửa tháng"; câu chỉ là "30" → {30}."""
    lowered = text.casefold()
    if (bare := _BARE_NUMBER.fullmatch(lowered)) is not None:
        return frozenset({int(bare.group(1))})
    found: set[int] = set()
    for source in (lowered, _fold(lowered)):
        for m in _SPAN.finditer(source):
            raw, unit = m.group(1), m.group(2)
            n = float(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw, _FOLDED_NUMBERS.get(raw, 0.0))
            found.add(round(n * _UNIT_DAYS.get(unit, _FOLDED_UNITS.get(unit, 0))))
    return frozenset(d for d in found if d > 0)


def lacks_evidence(key: str, value: str, text: str, *, intent_actions: frozenset[str] = frozenset()) -> bool:
    """True khi slot chuẩn hoá `key=value` KHÔNG có dấu vết trong `text` (câu đã che) → bỏ `slot_not_in_text`. Khoá khác → False."""
    if key == "account_type":
        pair = _ACCOUNT_TYPE.get(value)
        return pair is None or not _hit(pair, text)
    if key == "permission_level":
        pair = _PERMISSION_LEVEL.get(value)
        return pair is None or not _hit(pair, text)
    if key == "duration":
        return not value.isdigit() or int(value) not in durations_in_text(text)
    if key == "action" and intent_actions == {"reset_password", "unlock_account"}:
        unlock, reset = _hit(_UNLOCK, text), _hit(_RESET, text)
        return (value == "reset_password" and unlock and not reset) or (value == "unlock_account" and reset and not unlock)
    return False
