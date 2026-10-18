"""Thay nhãn che bằng từ thường TRƯỚC khi model chặn tấn công chấm (gói 1, D-52; `dac-ta-bat-2-model.md` 4.3).

Model `injection-clf` không thấy nhãn che lúc huấn luyện: câu thường có `<SĐT_1>` bị chấm cao (9/22 ≥ 0,90 trong bàn giao của
Dương; thay bằng từ thường thì 0/22). Bộ từ đúng bàn giao của Dương (`MASK_WORDS`, `SECRET_WORD`). Nhãn lấy từ
`config/privacy_patterns.json` (`secret_mask`, `label` của luật pii) — không chép tay; label pii không có từ thay →
`PatternFileError` (lệch bộ từ thì không khởi động). Chuẩn hoá NFC trước khi so khớp.

Chỉ đổi ĐẦU VÀO MODEL ở chế độ `review`: văn bản lưu, văn bản gửi LLM chấm và audit giữ nguyên (B2 chỉ ghi SỐ nhãn đã thay).
Từ thay không chứa nhãn nào nên chạy hai lần như một lần. Dùng chung cho B3 nếu D-53 bật bước thay. Thuần, không log văn bản.
"""

import re
import unicodedata
from collections.abc import Mapping
from functools import lru_cache

from app.guard.patterns import PatternFileError, PrivacyPatterns, privacy_patterns
from app.settings import get_settings

MASK_WORDS: Mapping[str, str] = {
    "SĐT": "số điện thoại",
    "EMAIL": "địa chỉ email",
    "CCCD": "số CCCD",
    "STK": "số tài khoản",
}
SECRET_WORD = "***"


@lru_cache
def _compiled(secret_mask: str, labels: tuple[str, ...]) -> re.Pattern[str]:
    unknown = [label for label in labels if label not in MASK_WORDS]
    if unknown:
        raise PatternFileError(f"privacy_patterns.json: nhãn pii {unknown} không có từ thay trong MASK_WORDS")
    names = "|".join(re.escape(unicodedata.normalize("NFC", label)) for label in labels)
    return re.compile(f"{re.escape(unicodedata.normalize('NFC', secret_mask))}|<(?P<label>{names})_\\d+>")


def mask_regex(patterns: PrivacyPatterns) -> re.Pattern[str]:
    labels = tuple(dict.fromkeys(r.label for r in patterns.rules if r.kind == "pii" and r.label is not None))
    return _compiled(patterns.secret_mask, labels)


def replace_masks(text: str, patterns: PrivacyPatterns | None = None) -> tuple[str, int]:
    """(văn bản đã thay, số nhãn đã thay). `patterns` None → file mẫu của cấu hình đang chạy."""
    regex = mask_regex(patterns if patterns is not None else privacy_patterns(get_settings().config_dir))
    words = {unicodedata.normalize("NFC", k): v for k, v in MASK_WORDS.items()}

    def one(m: re.Match[str]) -> str:
        label = m.group("label")
        return SECRET_WORD if label is None else words[label]

    return regex.subn(one, unicodedata.normalize("NFC", text))
