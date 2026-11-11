"""Tài khoản CÁ NHÂN bên ngoài công ty (kiểm thử máy demo 12/11 02:25, LLM thật).

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

# Soát 12/11 03:50: thêm google / gg / g-mail, Microsoft cá nhân, YouTube, Insta, Grab, tài khoản ngân hàng; bỏ "fb" ("em fb lại" =
# phản hồi). Không nhận khi tên dịch vụ chỉ là KÊNH hay NƠI ("gửi mật khẩu tạm qua Zalo", "em không có Zalo để nhận mã", "trên app
# Gmail của điện thoại", "hotline qua Messenger", "đối soát đơn Shopee", "thư từ Gmail của khách") — việc vẫn là tài khoản công ty.
_SERVICES: Final = (
    r"gmail|g-mail|google|gg|yahoo|hotmail|outlook\.com|live\.com|icloud|apple id|microsoft cá nhân|facebook|messenger|zalo|instagram|"
    r"insta|youtube|tiktok|telegram|viber|whatsapp|twitter|shopee|lazada|tiki|grab|gojek|momo|zalopay|vnpay|internet banking|"
    r"tài khoản ngân hàng|vietcombank|vcb|techcombank|bidv|vietinbank|agribank|mbbank|tpbank|sacombank|netflix|spotify"
)
_NOT_CHANNEL: Final = r"(?<!qua )(?<!bằng )(?<!trên )(?<!app )(?<!ứng dụng )(?<!có )(?<!đơn )(?<!hotline )(?<!nhắn )(?<!gọi )(?<!từ )"
_RE: Final = re.compile(rf"{_NOT_CHANNEL}\b(?:{_SERVICES})\b")
_RE_FOLDED: Final = re.compile(rf"{fold(_NOT_CHANNEL)}\b(?:{fold(_SERVICES)})\b")


def personal_account_mentioned(text: str, intents: Collection[str]) -> bool:
    """True khi câu nhắc tài khoản của dịch vụ bên ngoài công ty và có intent `account`."""
    if "account" not in intents:
        return False
    lowered = text.lower()
    return bool(_RE.search(lowered) or _RE_FOLDED.search(fold(lowered)))
