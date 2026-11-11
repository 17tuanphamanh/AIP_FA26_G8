"""Tài khoản CÁ NHÂN bên ngoài công ty (kiểm thử máy demo 12/11 03:10, LLM thật).

Đo được: "Đặt lại mật khẩu Gmail cá nhân giúp chị" (lan.dt) → B3 xếp `account`, slot `account_type=email` → luật R01 cho tự làm →
hệ thống ĐẶT LẠI mật khẩu email CÔNG TY của người gửi (mật khẩu tạm gửi qua email). Người dùng không xin việc đó; tài khoản Gmail,
Facebook, Zalo, ngân hàng… không thuộc hệ thống công ty. Cùng loại câu với Facebook / Zalo thì LLM đã tự xếp `out_of_scope` (E1) —
riêng "Gmail" / "Yahoo" / "iCloud" dễ bị gộp thành "email".

`personal_account_mentioned(text, intents)` — hàm THUẦN, TẤT ĐỊNH, chỉ xét khi có intent `account` (intent khác không đặt lại / mở khoá
tài khoản). Khớp → nơi gọi coi như ngoài phạm vi (E1 `out_of_scope`), KHÔNG dựng hành động. Chỉ THÊM đường chuyển người.

Chỉ nhận TÊN DỊCH VỤ bên ngoài, không nhận "tài khoản cá nhân" / "email cá nhân": trong KB (KB-ACC-001…004) "tài khoản cá nhân" là
tài khoản công ty CỦA CHÍNH người dùng (đối lập tài khoản dịch vụ / quản trị). "Outlook" trần là ứng dụng thư công ty — chỉ nhận
"outlook.com" / "hotmail".
"""

import re
from collections.abc import Collection
from typing import Final

from app.domain.target import fold

_SERVICES: Final = (
    r"gmail|google account|tài khoản google|yahoo|hotmail|outlook\.com|live\.com|icloud|apple id|facebook|fb|messenger|zalo|instagram|"
    r"tiktok|telegram|viber|whatsapp|twitter|shopee|lazada|tiki|momo|zalopay|vnpay|internet banking|netflix|spotify"
)
_RE: Final = re.compile(rf"\b(?:{_SERVICES})\b")
_RE_FOLDED: Final = re.compile(rf"\b(?:{fold(_SERVICES)})\b")


def personal_account_mentioned(text: str, intents: Collection[str]) -> bool:
    """True khi câu nhắc tài khoản của dịch vụ bên ngoài công ty và có intent `account`."""
    if "account" not in intents:
        return False
    lowered = text.lower()
    return bool(_RE.search(lowered) or _RE_FOLDED.search(fold(lowered)))
