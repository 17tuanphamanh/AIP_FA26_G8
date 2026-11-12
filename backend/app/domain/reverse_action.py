"""D-84 (kiểm thử máy demo 12/11): người dùng xin thao tác NGƯỢC — hệ thống KHÔNG có thao tác đó.

Danh mục hành động (`config/slots.yaml`) chỉ có chiều "thuận": cấp lại / gia hạn chứng chỉ VPN, cài phần mềm, cấp / gia hạn quyền,
mở khoá / đặt lại mật khẩu. Không có thu hồi, khoá, vô hiệu hoá, gỡ cài đặt, huỷ. Đo trực tiếp (LLM thật, 12/11 00:20):
- "Em làm mất laptop LAP-0610, chặn/thu hồi VPN máy đó" → phiếu **cấp lại** quyền VPN cho máy bị mất;
- "Gỡ Zoom khỏi máy LAP-0342" → hành động **cài** Zoom ("Zoom đã có sẵn…"); máy chưa có thì cài thật;
- trả lời "LAP-0417, à thôi đừng gia hạn, chỉ kiểm tra thôi" → phiếu **gia hạn**.
Ban đêm các việc này chỉ thành phiếu duyệt nhờ R18 (ngoài giờ); trong giờ hành chính luật allow (R20, R11, R10, R01/R02) sẽ TỰ LÀM —
âm tính giả: làm điều người dùng không xin (hoặc xin điều ngược lại).

`reverse_action_kind(text, intents)` — hàm THUẦN, TẤT ĐỊNH (không LLM) trên văn bản ĐÃ CHE + L0 (cùng bản B3/clarify_wait dùng). Khớp →
nơi gọi chuyển L2 (E1 `reverse_action_requested`), KHÔNG dựng hành động. Chỉ THÊM một đường chuyển người, không bớt đường nào — không
nới an toàn; khớp nhầm (dương tính giả) = một ca đáng tự làm bị chuyển kỹ thuật viên (chiều an toàn).

Bổ sung 12/11 02:30 (đo tiếp trên máy demo): "Rút / Bỏ / Gỡ quyền ghi …" → hỏi "xem, xin mới hay gia hạn?" lặp; "Hạ quyền … xuống chỉ
đọc" → phiếu CẤP quyền đọc; "Khoá tài khoản ERP của em lại" → dựng hành động MỞ khoá (chỉ lớp LLM chặn); "Em bị lộ mật khẩu email,
đặt lại giúp" → TỰ đặt lại, mật khẩu tạm gửi vào chính hộp thư đã lộ. Thêm nhãn `compromised` (tài khoản bị lộ / bị hack / bị chiếm —
KB-GEN-008 coi là sự cố an toàn thông tin, kỹ thuật viên xử lý), mẫu rút / hạ quyền, "khoá … lại", "không cần … nữa". 02:45: "ngắt / tắt
VPN" (thành phiếu GIA HẠN / CẤP LẠI VPN), máy nhiễm mã độc (`compromised`). 03:50: viết lại sau soát 133 câu (subagent) — trước:
bỏ lọt 63/71, bắt nhầm 38/48 (kể cả "Tài khoản bị tạm khoá do nhập sai, mở giúp em"); sau: 2/71, 0/48 (`test_d84_review_1211.py`).

Mẫu viết cho bản CÓ DẤU (chữ thường) và bản BỎ DẤU (`fold`). Bản bỏ dấu BỎ các mẫu dễ trùng nghĩa khi mất dấu: "máy"/"mấy" (cùng "may"),
"đừng"/"dùng" (cùng "dung"), "gỡ"/"gõ" (cùng "go") — chỉ giữ dạng không lẫn. Loại trừ có chủ đích (test âm tính): "VPN bị mất kết nối",
"máy mất mạng", "laptop mất 10 phút", "tài khoản bị khoá", "mở khoá tài khoản", "mạng chặn VPN", "gỡ lỗi / gỡ rối", "lỡ nhập SAI mật
khẩu", "khoá tài khoản tự mở lại sau bao lâu?", "toàn bộ quyền" (bỏ dấu = "bo quyen"), "có ai biết cách gia hạn VPN không?",
"ổ C bị chiếm hết dung lượng".
"""

import re
import unicodedata
from collections.abc import Collection
from typing import Final, Literal

from app.domain.target import fold

type ReverseKind = Literal["lost_device", "compromised", "revoke", "lock", "negate", "cancel", "uninstall"]

# Kiểm hộp đen 12/11 (subagent, 348 câu mới): chữ full-width lọt 121/121, zero-width trong từ lọt 111/121, NBSP lọt 40/121 — mẫu viết
# cho chữ thường có dấu dựng sẵn. Chuẩn hoá trước khi dò: NFKC (gộp dấu tách rời kiểu NFD, full-width → thường, NBSP → cách), bỏ ký tự
# không bề rộng, gộp dấu cách liền nhau (lookbehind độ dài cố định "(?<!bị )" bị né bởi hai dấu cách).
_ZERO_WIDTH: Final = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
_SPACES: Final = re.compile(r"[^\S\n]+")


# API cắt chữ THÔ ở 4 000 ký tự nhưng NFKC ở l0 có thể nở ra (U+FDFA → 18 ký tự): soát bảo mật 12/11 đo chuỗi tệ nhất lọt qua API
# ~38 000 ký tự → 0,33 s mỗi lần dò (mẫu có lookahead tới hết câu là bậc hai). Chỉ dò 8 000 ký tự đầu — gấp đôi trần API.
_MAX_DETECT_CHARS: Final = 8_000


def normalize_for_detect(text: str) -> str:
    """Chuẩn hoá văn bản cho các bộ dò tất định (D-84, D-87): NFKC, bỏ zero-width, gộp dấu cách, chữ thường, cắt 8 000 ký tự."""
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text.translate(_ZERO_WIDTH)))[:_MAX_DETECT_CHARS].lower()

# Intent có hành động GHI — chỉ ở các intent này mới có nguy cơ ánh xạ ngược. it_help / out_of_scope không dựng hành động.
WRITE_INTENTS: Final = frozenset({"vpn", "account", "access", "software"})

_DEVICE = (
    r"(?:laptop|máy tính|máy(?!\s*chủ)|điện thoại|đt|thiết bị|macbook|ipad|iphone|smartphone|ổ cứng|usb|thẻ nhân viên|lap|"
    r"[a-z]{2,4}-\d{3,5})"
)
# bỏ "may" (máy/mấy); "dt" = "đt" (điện thoại); mã máy (LAP-0610) cũng là thiết bị
_DEVICE_FOLDED = r"(?:laptop|may tinh|dien thoai|dt|thiet bi|macbook|ipad|iphone|smartphone|o cung|usb|the nhan vien|lap|[a-z]{2,4}-\d{3,5})"
# "Cài phần mềm theo dõi thất lạc thiết bị (Find My Device)" — chống mất, không phải báo mất (kiểm hộp đen 12/11).
# "Em không bị mất máy, chỉ quên mật khẩu thôi" — phủ định.
_NOT_ANTI_LOSS = r"(?<!theo dõi )(?<!chống )(?<!phòng )(?<!tìm )(?<!không )(?<!ko )(?<!chưa )(?<!không bị )(?<!ko bị )(?<!chưa bị )"
# "phát hiện cái laptop LAP-0342 không còn trong xe nữa", "không thấy laptop đâu"
_GONE = (
    r"\bkhông\s+(?:còn|thấy)\s+(?:ở\s+)?(?:trong|ở|trên)\s+(?:xe|ô tô|túi|balo|ba lô|cặp|phòng|bàn|tủ|ngăn|taxi|grab|chỗ|văn phòng)\b"
    r"|\bkhông\s+(?:còn\s+)?thấy\s+(?:\S+\s+)?đâu\b"
)
# Báo mất máy bằng tiếng Anh (kiểm hộp đen 12/11, LLM thật: "My laptop was stolen yesterday, pls reset my password and VPN cert" →
# TỰ gia hạn chứng chỉ VPN cho đúng máy vừa bị trộm).
_EN_DEVICE = r"(?:laptop|notebook|phone|iphone|smartphone|macbook|ipad|computer|pc|device|[a-z]{2,4}-\d{3,5})"
_LOST_EN = (
    rf"\b{_EN_DEVICE}\b[^.!?\n]{{0,30}}?\b(?:was|got|has been|have been|is|been|were)\s+(?:stolen|lost|taken|snatched)\b"
    rf"|\b(?:lost|stolen)\s+(?:my\s+|the\s+|our\s+|a\s+)?(?:company\s+|work\s+|office\s+)?{_EN_DEVICE}\b"
    r"(?!\s+(?:charger|bag|case|password|connection|cable))"
    r"|\bsomeone\s+(?:stole|took|has stolen)\b"
)
_LOSS_VERB = (
    r"(?:làm mất|đánh mất|bị mất|mất|thất lạc|đánh rơi|làm rơi|rơi mất|bỏ quên|để quên|bị trộm|bị ăn trộm|bị đánh cắp|bị cướp giật|"
    r"bị cướp|bị giật|cướp giật|bị lấy mất|lấy mất|bị móc túi mất|bị móc túi)"
)
_LOSS_AFTER = (
    r"(?:bị mất|đã mất|làm mất|thất lạc|bị trộm|bị ăn trộm|bị đánh cắp|bị cướp|bị giật|để quên|bỏ quên|lấy mất|bị lấy mất|"
    r"bị kẻ gian lấy mất)"
)
# Sau "bị mất / thất lạc / bị trộm…" chỉ coi là BÁO MẤT MÁY khi tiếp theo là hết câu hoặc từ chỉ hoàn cảnh (rồi, trộm, ở, hôm…) —
# danh sách CHO PHÉP thay vì loại trừ: "máy bị mất kết nối", "bị mất sạc" (mất cục sạc), "mất 10 phút" đều không khớp (bộ đánh giá có
# "Máy LAP-0342 của mình bị mất sạc, công ty có cấp lại không?" — tự soát 12/11). "luôn" / "ngay" chỉ khi kết câu / chỉ nơi chốn
# ("laptop bị mất luôn icon VPN", "bị mất ngay biểu tượng" là lỗi giao diện — soát 12/11 03:50).
_LOSS_END = (
    r"(?=\s*(?:$|[.,!?;:)]|rồi|trộm|cắp|cướp|mất|ở|tại|trên|dưới|lúc|khi|hôm|tối|sáng|chiều|trưa|ngoài|trong|giữa|giúp|nên|mà|và|"
    r"với|thì|gấp|đâu|đó|này|ấy|cmnr|r\b|luôn(?=\s*(?:$|[.,!?;:]|rồi|r\b))|ngay(?=\s*(?:tại|ở|trên|lúc|khi|hôm))))"
)
# "Em để quên laptop ở nhà, cấp VPN tạm cho máy mượn" — để quên ở nhà không phải sự cố an ninh.
_NOT_HOME = r"(?![^.!?\n]{0,20}\bở nhà\b)"
_OBJECT = r"(?:vpn|chứng chỉ|cert|quyền|truy cập|tài khoản|tk|account|email|mail)"
# Việc ĐÃ xảy ra (người dùng kể lại, không xin làm): "em bị thu hồi quyền VPN, cấp lại giúp", "em đã xoá chứng chỉ cũ rồi cài lại",
# "em vừa gỡ Zoom" — bỏ qua. Lookbehind độ dài cố định nên tách từng cụm.
_NOT_PAST = r"(?<!bị )(?<!đã )(?<!vừa )(?<!mới )(?<!lỡ )(?<!nhầm )"
# Người KHÁC / hệ thống đã làm ("Sếp thu hồi quyền ghi của em", "Hệ thống tự thu hồi quyền", "Em bị IT hạ quyền") và câu có xin LẠI
# ("… rồi cấp lại cái mới", "giờ em cần lại") — đó là xin làm thuận (soát 12/11 03:50).
# Kiểm hộp đen 12/11: "(?<!it )" trần làm lọt câu XIN "Bạn Lan nghỉ việc từ hôm nay, IT vô hiệu hoá tài khoản giúp chị" — chỉ loại khi
# "bị IT / bị admin" (đã xảy ra).
_NOT_OTHERS = r"(?<!sếp )(?<!tự )(?<!bị it )(?<!bị admin )"
_NOT_REGRANT = r"(?![^.!?\n]*\b(?:cấp lại|xin lại|cần lại|cho lại|mở lại|cấp cho em lại)\b)"
_NOT_REGRANT_FOLDED = r"(?![^.!?\n]*\b(?:cap lai|xin lai|can lai|cho lai|mo lai)\b)"
_REVOKE_VERB = r"(?:thu hồi|thu lại|vô hiệu hoá|vô hiệu hóa|vô hiệu|revoke|disable|deactivate|huỷ|hủy|xoá|xóa)"
# "đổi / thay" (mật khẩu) chỉ ở bản CÓ dấu — bỏ dấu "doi" trùng "đợi" ("không muốn đợi lâu") — soát tầng hiểu yêu cầu 12/11:
# "Em KHÔNG muốn đổi mật khẩu", trả lời "thôi đừng đổi mật khẩu nữa" lọt bộ dò.
_ACTION_VERB = r"(?:mở khoá|mở khóa|gia hạn|cấp lại|cấp|cài đặt|cài|đặt lại|reset|đổi|thay)"
_NEGATE_EN = (
    r"\b(?:don[’']?t|do not|no need to|never mind|nevermind|cancel that|please stop)\b[^.!?\n]{0,25}?"
    r"\b(?:renew|reset|unlock|install|grant|reissue|re-issue|extend|change)\b"
)
# Bản bỏ dấu: "huy" (huỷ) trùng TÊN người ("Nhờ cấp cho bạn Huy (nv021) quyền sửa…" — bộ đánh giá cong5) → bỏ khi có từ xưng hô đứng trước.
_HUY_FOLDED = r"(?<!ban )(?<!anh )(?<!chi )(?<!em )(?<!cho )(?<!a )(?<!c )(?<!ten )(?<!ong )(?<!ba )huy"
_ACTION_VERB_FOLDED = r"(?:mo khoa|gia han|cap lai|cap|cai dat|cai|dat lai|reset)"
_NO = r"(?:không|ko|k|kh|hông|hok)"  # teencode "ko / k" (soát 12/11 03:50)
_NO_FOLDED = r"(?:khong|ko|k|kh|hong|hok)"
# Phủ định một việc phụ rồi vẫn xin việc khác ("Em không cần cài gì nữa, chỉ cần cấp quyền đọc") — không phải huỷ.
# Xét cả phần sau của tin nhắn, kể cả câu sau ("Không cần reset mk đâu a, e nhớ ra r. Chỉ cần mở khoá tk thôi").
_NOT_ONLY = r"(?![^\n]*\bchỉ cần\b)"
# Bổ sung 12/11 02:30 (đo trên máy demo): "Rút / Bỏ / Gỡ quyền ghi …" → bot hỏi "xem, xin mới hay gia hạn?" lặp tới E4; "Hạ quyền … xuống
# chỉ đọc" → phiếu CẤP quyền đọc (người dùng vẫn giữ quyền ghi mà tưởng đã hạ). Chỉ khớp khi "quyền" đứng ngay sau động từ (cho chen
# "hết / bớt / toàn bộ"). "Trả lại quyền … CHO EM" là xin cấp lại — không khớp.
_REVOKE_PERM = (
    r"(?:rút lại|rút bớt|rút|tước|bỏ|gỡ bỏ|gỡ|hạ cấp|hạ|giảm bớt|giảm|thu hẹp|cắt|trả lại)\s+(?:hết\s+|bớt\s+|toàn bộ\s+)?quyền"
    r"(?![^.!?\n]{0,30}\bcho\s+(?:em|mình|tôi|tớ|anh|chị)\b)"
)
# Sự cố an ninh tài khoản (đo trên máy demo 12/11): "Em bị lộ mật khẩu email rồi, đặt lại giúp em" và "email bị hack, đổi mật khẩu gấp"
# → hệ thống TỰ đặt lại mật khẩu email và gửi mật khẩu tạm "qua email" — tức vào chính hộp thư đang bị chiếm. KB-GEN-008: nghi lộ /
# bị chiếm là sự cố an toàn thông tin, kỹ thuật viên xử lý trực tiếp. Chuyển người như báo mất máy.
# Ngắt / tắt VPN (đo 12/11 02:45, LLM thật): "Máy LAP-0342 hình như nhiễm mã độc, ngắt VPN của máy đó giúp em" → phiếu GIA HẠN chứng chỉ
# VPN; "Tắt VPN trên máy LAP-0610 giúp em" → phiếu CẤP LẠI quyền VPN (chứng chỉ máy này đang bị thu hồi). Không nhận câu hỏi cách làm
# ("làm sao tắt VPN", "cách tắt VPN"), việc đã / đang xảy ra ("bị ngắt VPN", "khi tắt VPN thì…"), bước tự sửa lỗi ("tắt VPN đi bật lại",
# "thử tắt VPN rồi bật lại", "phải tắt VPN mới in được"); không có "chặn" ("mạng công ty chặn VPN" là báo lỗi) và bản bỏ dấu không có
# "dung" ("dùng VPN").
_VPN_RETRY = r"(?![^.!?\n]{0,30}\b(?:bật lại|mở lại|kết nối lại|connect lại|vào lại|mới)\b)"
_DISABLE_VPN = (
    r"(?<!cách )(?<!sao )(?<!để )(?<!bị )(?<!đã )(?<!vừa )(?<!khi )(?<!lần )(?<!nếu )(?<!tự )(?<!thử )(?<!phải )(?<!cứ )"
    r"\b(?:ngắt|tắt hẳn|tắt luôn|tắt|cắt|dừng|ngừng|tạm dừng|tạm ngưng|ngưng|turn off)\s+(?:kết nối\s+|quyền\s+|truy cập\s+)?vpn\b"
    + _VPN_RETRY
)
_DISABLE_VPN_FOLDED = (
    r"(?<!cach )(?<!sao )(?<!de )(?<!bi )(?<!da )(?<!vua )(?<!khi )(?<!lan )(?<!neu )(?<!tu )(?<!thu )(?<!phai )(?<!cu )"
    r"\b(?:ngat|tat|ngung|tam dung|tam ngung|turn off)\s+(?:ket noi\s+|quyen\s+|truy cap\s+)?vpn\b"
    r"(?![^.!?\n]{0,30}\b(?:bat lai|mo lai|ket noi lai|connect lai|vao lai|moi)\b)"
)
# Chủ ngữ "người lạ": "có người / có ai (lạ, khác)", "ai đó", "người nào đó" + tối đa hai trợ từ ("đang cố", "đã", "định").
_WHO = (
    r"\b(?:có\s+(?:ai|người)|ai đó|người nào đó|kẻ nào đó|kẻ gian)\s+(?:lạ\s+|khác\s+)?(?:(?:đã|đang|cố|định|muốn|vừa)\s+){0,2}"
)
_WHO_FOLDED = r"\b(?:co\s+(?:ai|nguoi)|ai do|nguoi nao do|ke nao do|ke gian)\s+(?:la\s+|khac\s+)?(?:(?:da|dang|co|dinh|muon|vua)\s+){0,2}"
_MINE = r"(?:của\s+)?(?:em|mình|tôi|tớ|anh|chị)\b"
_MINE_FOLDED = r"(?:cua\s+)?(?:em|e|minh|toi|to|anh|chi)\b"
# Câu hỏi phòng ngừa ("để tránh bị hack", "làm sao để không bị lộ", "cài antivirus để máy khỏi dính virus") — không phải báo sự cố.
_NOT_PREVENT = r"(?<!tránh )(?<!không )(?<!khỏi )(?<!chống )(?<!phòng )(?<!ngừa )(?<!sợ )(?<!ngại )"  # "Em sợ bị hack nên muốn đổi mật khẩu"
# Đích của "lộ / rò rỉ / gửi nhầm": cả chứng chỉ / file cấu hình VPN ("gửi nhầm file .ovpn cho khách" — kiểm hộp đen 12/11).
_SECRET = r"(?:mật khẩu|mk|pass|password|otp|mã otp|mã xác minh|thông tin đăng nhập|chứng chỉ|cert|file\s+(?:cấu hình|\.?ovpn)|\.ovpn)"
_SECRET_FOLDED = r"(?:mat khau|mk|pass|password|otp|ma otp|ma xac minh|thong tin dang nhap|chung chi|cert|file\s+(?:cau hinh|\.?ovpn)|\.ovpn)"
# "tk e bị ng khác đăng nhập", "Tài khoản của em bị ai đó đăng nhập" (LLM thật 12/11: TỰ đặt lại mật khẩu AD).
_BY_OTHER = r"(?:người khác|ng khác|người lạ|ng lạ|ai đó|ai|kẻ gian|kẻ lạ|hacker|người ta|đứa nào)"
_BY_OTHER_FOLDED = r"(?:nguoi khac|ng khac|nguoi la|ng la|ai do|ke gian|ke la|hacker|nguoi ta)"
_COMPROMISED = (
    # "chiếm" chỉ khi kèm quyền / tài khoản: "ổ C bị chiếm hết dung lượng" không phải sự cố an ninh
    rf"{_NOT_PREVENT}\bbị\s+(?:hack|hách|hắc|xâm nhập|xâm phạm|chiếm đoạt|chiếm quyền|chiếm\s+(?:mất\s+)?(?:tài khoản|tk|email|mail|hộp thư)|"
    r"đánh cắp|lấy cắp|lừa|login\s+(?:từ|ở|tại)|đăng nhập\s+(?:từ|ở|tại|trái phép))\b"
    r"|\b(?:tài khoản|tk|email|mail|hộp thư)\b[^.!?\n]{0,30}?\bbị\s+(?:(?:người ta|ai đó|kẻ gian|người lạ|hacker)\s+)?chiếm\b"
    # "Đổi mật khẩu theo yêu cầu sau đợt diễn tập phishing của công ty" không phải sự cố (kiểm hộp đen 12/11)
    r"|(?<!diễn tập )(?<!tập huấn )(?<!đào tạo )(?<!thử nghiệm )(?<!mô phỏng )(?<!bài test )"
    r"\b(?:hacked|compromised|phishing|keylogger|trojan|ransomware)\b(?!\s+(?:test|simulation|training|drill))|\btiền chuộc\b"
    r"|(?<!tránh bị )(?<!không bị )(?<!khỏi bị )\blộ\s+(?:mất\s+)?(?:mật khẩu|mk|pass|password|thông tin đăng nhập|otp|mã xác minh)\b"
    # trật tự đảo: "Mật khẩu email của em bị lộ rồi" (soát 12/11 03:50)
    r"|\b(?:mật khẩu|mk|pass|password)\b[^.!?\n]{0,50}?(?<!không )(?<!không bị )(?<!ko )(?<!ko bị )(?<!dễ )(?<!dễ bị )(?<!phải )(?<!phải bị )(?<!tránh bị )(?<!khỏi bị )\b"
    r"(?:bị\s+)?lộ\b(?!\s+(?:ra|diện))"
    # "có ai/người …" phải kèm đích là mật khẩu (không phải mật khẩu wifi khách) hoặc tài khoản CỦA người gửi: "Có ai biết cách gia hạn
    # VPN không?", "có ai đăng nhập được VPN không?", "Có ai biết mật khẩu wifi khách không?" là câu hỏi thường, không khớp.
    rf"|{_WHO}(?:lấy được|lấy|biết|dò|đánh cắp|đổi)\s+(?:được\s+)?(?:mật khẩu|mk|pass)\b(?!\s+(?:wifi|wi-fi|wi fi|khách|máy in))"
    rf"|{_WHO}(?:đăng nhập|truy cập|vào|dùng|sử dụng)\s+(?:được\s+)?(?:\S+\s+){{0,2}}?(?:tài khoản|tk|email|mail|hộp thư)\s+(?:\S+\s+)?{_MINE}"
    r"|\bngười lạ\s+(?:(?:đã|đang|vừa)\s+)?(?:đăng nhập|truy cập|vào|dùng)\b"
    r"|\bđăng nhập lạ\b"
    # "Em nhận được thông báo đăng nhập từ thiết bị lạ"; KHÔNG nhận "Em đăng nhập từ máy lạ (máy mượn) được không?" (chính mình, câu hỏi)
    r"|(?<!em )(?<!mình )(?<!tôi )(?<!tớ )\bđăng nhập\s+(?:\S+\s+){0,3}?(?:thiết bị|máy|nơi|địa điểm|vị trí|ip|quốc gia)\s+lạ\b"
    r"(?![^.!?\n]{0,20}\bđược không\b)"
    r"|\b(?:mã\s+)?(?:otp|mã xác minh|mã xác thực)\s+lạ\b"
    # Máy nhiễm mã độc (KB-GEN-008: ngắt mạng, báo IT — kỹ thuật viên xử lý trực tiếp); chỉ xét khi có intent ghi, câu hỏi it_help không vào.
    rf"|{_NOT_PREVENT}\b(?:nhiễm|dính|bị)\s+(?:virus|vi rút|mã độc|malware|ransomware|trojan|mã hoá dữ liệu|mã hóa dữ liệu)\b"
    r"|\b(?:mật khẩu|mk|pass)\s+(?:\S+\s+){0,3}?vào\s+(?:trang|web|website|link|liên kết|đường link|form)\s+(?:\S+\s+)?"
    r"(?:lạ|giả|giả mạo|lừa đảo)\b"
    # nạn nhân lừa đảo: "em lỡ điền mật khẩu rồi" (KHÔNG nhận "lỡ nhập SAI mật khẩu"), thư / trang giả mạo, tài khoản tự gửi spam
    r"|\blỡ\s+(?:điền|nhập|đưa|cung cấp|gửi|khai|gõ|dán|share|chia sẻ|đăng|đọc|nói|báo)\s+(?:luôn\s+)?(?:mật khẩu|mk|pass|otp|mã otp|mã xác minh)\b"
    # "Em vô tình gửi mật khẩu VPN vào nhóm chat chung", "lỡ tay share file .ovpn" (kiểm hộp đen 12/11)
    rf"|\b(?:vô tình|lỡ tay|nhầm tay|sơ ý)\s+(?:gửi|đưa|share|chia sẻ|đăng|dán|post|forward|đọc|nói|báo|cung cấp)\s+(?:\S+\s+){{0,2}}?{_SECRET}\b"
    # "Laptop em tự nhiên chuột di chuyển lung tung, nghi bị điều khiển từ xa"
    rf"|{_NOT_PREVENT}\bbị\s+(?:ai\s+|người khác\s+|người lạ\s+|kẻ gian\s+)?(?:điều khiển|truy cập|remote|kiểm soát)\s+(?:máy\s+)?từ xa\b"
    r"|\b(?:email|mail|thư|tin nhắn|link|trang|web)\s+(?:\S+\s+)?(?:giả mạo|lừa đảo|giả danh)\b"
    r"|\btự\s+(?:động\s+)?gửi\s+(?:\S+\s+){0,3}?(?:spam|thư rác|mail lạ|email lạ|lừa đảo)\b"
    r"|\b(?:click|bấm|nhấn|nhấp|mở)\s+(?:nhầm\s+|phải\s+|lỡ\s+)?(?:vào\s+)?(?:link|liên kết|đường link|file|tệp)\s+(?:\S+\s+){0,3}?"
    r"(?:lạ|giả danh|giả mạo|lừa đảo)\b"
    # Bổ sung sau kiểm hộp đen 12/11 (dựa nửa DEV của 348 câu):
    rf"|{_NOT_PREVENT}\bbị\s+{_BY_OTHER}\s+(?:(?:đã|đang|vừa|cố)\s+)?(?:đăng nhập|truy cập|login|log in|dùng|sử dụng|lấy|chiếm|đổi|vào)\b"
    rf"|\b{_SECRET}\b[^.!?\n]{{0,50}}?(?<!không )(?<!không bị )(?<!ko bị )\b(?:bị\s+)?(?:rò rỉ|lọt ra ngoài|lộ ra ngoài)\b"
    rf"|\brò rỉ\s+(?:mất\s+)?{_SECRET}\b"
    rf"|\b(?:chứng chỉ|cert)\b[^.!?\n]{{0,50}}?(?<!không )(?<!không bị )(?<!ko bị )(?<!tránh bị )\b(?:bị\s+)?lộ\b(?!\s+diện)"
    rf"|\b(?:gửi|đưa|share|chia sẻ|đăng|dán|post|forward)\s+(?:nhầm|lộn)\s+(?:\S+\s+){{0,2}}?{_SECRET}\b"
    # thư lừa: "nhận một mail tên '…', em có mở ra và đăng nhập theo hướng dẫn"
    r"|\bnhận\s+(?:được\s+)?(?:một\s+|1\s+|cái\s+)?(?:mail|email|e-mail|thư|tin nhắn|sms)\b[^.!?\n]{0,80}?\b(?:mở|bấm|click|nhấn|ấn)\b"
    r"[^.!?\n]{0,40}?\b(?:đăng nhập|nhập mật khẩu|điền mật khẩu|nhập mk|điền mk)\b"
)
_COMPROMISED_FOLDED = (
    r"(?<!tranh )(?<!khong )(?<!khoi )(?<!chong )(?<!phong )(?<!ngua )(?<!so )(?<!ngai )\bbi\s+(?:hack|hach|hac|xam nhap|xam pham|chiem doat|chiem quyen|chiem\s+(?:mat\s+)?(?:tai khoan|tk|email|mail|hop thu)|danh cap|"
    r"lay cap|lua|login\s+(?:tu|o|tai))\b"
    r"|\b(?:tai khoan|tk|email|mail|hop thu)\b[^.!?\n]{0,30}?\bbi\s+(?:(?:nguoi ta|ai do|ke gian|nguoi la|hacker)\s+)?chiem\b"
    r"|(?<!dien tap )(?<!tap huan )(?<!dao tao )(?<!thu nghiem )(?<!mo phong )(?<!bai test )"
    r"\b(?:hacked|compromised|phishing|keylogger|trojan|ransomware)\b(?!\s+(?:test|simulation|training|drill))"
    r"|(?<!khong )\bbi\s+lo\s+(?:mat\s+)?(?:mat khau|mk|pass|password|otp)\b"
    r"|\b(?:mat khau|mk|pass|password)\b[^.!?\n]{0,30}?(?<!khong )\bbi\s+lo\b"
    r"|(?<!phong )(?<!khoi )(?<!tranh )(?<!chong )\b(?:nhiem|dinh)\s+(?:virus|vi rut|ma doc|malware|ransomware|trojan)\b"
    rf"|{_WHO_FOLDED}(?:lay duoc|lay|biet|do|doi)\s+(?:duoc\s+)?(?:mat khau|mk|pass)\b(?!\s+(?:wifi|wi-fi|wi fi|khach|may in))"
    rf"|{_WHO_FOLDED}(?:dang nhap|truy cap|vao|dung|su dung)\s+(?:duoc\s+)?(?:\S+\s+){{0,2}}?(?:tai khoan|tk|email|mail|hop thu)\s+(?:\S+\s+)?"
    rf"{_MINE_FOLDED}"
    # Bổ sung sau kiểm hộp đen 12/11 — bản bỏ dấu ("bi ng khac dang nhap", "mat khau bi ro ri", "gui nham file .ovpn")
    rf"|(?<!tranh )(?<!khong )(?<!khoi )\bbi\s+{_BY_OTHER_FOLDED}\s+(?:(?:da|dang|vua)\s+)?(?:dang nhap|truy cap|login|lay|chiem)\b"
    rf"|\b{_SECRET_FOLDED}\b[^.!?\n]{{0,50}}?(?<!khong )(?<!khong bi )(?<!ko bi )\b(?:bi\s+)?(?:ro ri|lot ra ngoai|lo ra ngoai)\b"
    rf"|\bro ri\s+(?:mat\s+)?{_SECRET_FOLDED}\b"
    rf"|\b(?:gui|dua|share|chia se|dang|dan|post|forward)\s+(?:nham|lon)\s+(?:\S+\s+){{0,2}}?{_SECRET_FOLDED}\b"
    # không có "lo" trần / "nhap": "lỡ nhập SAI mật khẩu" (bị khoá, xin mở) là luồng mở khoá thường gặp nhất
    rf"|\b(?:vo tinh|lo tay|nham tay|so y)\s+(?:gui|dua|share|chia se|dang|dan|post|forward|doc|noi|bao|cung cap)\s+"
    rf"(?:\S+\s+){{0,2}}?{_SECRET_FOLDED}\b"
    r"|(?<!tranh )(?<!khong )\bbi\s+(?:ai\s+|nguoi khac\s+|nguoi la\s+|ke gian\s+)?(?:dieu khien|truy cap|remote|kiem soat)\s+(?:may\s+)?tu xa\b"
)

_ACCENTED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    # "mất luôn cái điện thoại công ty", "mất cả laptop" (kiểm hộp đen 12/11)
    ("lost_device", rf"{_NOT_ANTI_LOSS}\b{_LOSS_VERB}\s+(?:luôn\s+|cả\s+)?(?:cái\s+|chiếc\s+|con\s+)?{_DEVICE}\b{_NOT_HOME}"),
    ("lost_device", _LOST_EN),
    ("lost_device", rf"\b{_DEVICE}\b[^.!?\n]{{0,30}}?(?:{_GONE})"),
    ("lost_device", (r"\bkhông\s+(?:còn\s+)?thấy\s+(?:cái\s+|chiếc\s+)?(?:laptop|điện thoại|đt|macbook|ipad|iphone|lap|[a-z]{2,4}-\d{3,5})\b"
                     r"(?:\s+(?:của\s+)?(?:em|mình|tôi|anh|chị))?\s*(?:đâu|nữa|$|[.!?])")),
    ("lost_device", rf"\b{_DEVICE}\b[^.!?\n]{{0,40}}?(?<!không )(?<!ko )(?<!chưa )\b{_LOSS_AFTER}\b{_LOSS_END}{_NOT_HOME}"),
    ("lost_device", r"\bkhông tìm thấy\s+(?:cái\s+|chiếc\s+|con\s+)?(?:laptop|điện thoại|đt|macbook|ipad|lap|[a-z]{2,4}-\d{3,5})\b"),
    ("revoke", rf"{_NOT_PAST}{_NOT_OTHERS}\b{_REVOKE_VERB}\s+(?:\S+\s+){{0,3}}?{_OBJECT}\b{_NOT_REGRANT}"),
    ("revoke", rf"{_NOT_PAST}{_NOT_OTHERS}\b{_REVOKE_PERM}\b{_NOT_REGRANT}"),
    # "Đổi quyền thư mục sales của em thành chỉ đọc" — như "hạ quyền"
    ("revoke", (rf"{_NOT_PAST}{_NOT_OTHERS}\b(?:đổi|chuyển|hạ)\s+quyền\b[^.!?\n]{{0,40}}?\b(?:thành|xuống|về|sang)\s+(?:chỉ\s+|quyền\s+)?"
                rf"(?:đọc|read)\b{_NOT_REGRANT}")),
    ("revoke", _DISABLE_VPN),
    # "Rút chứng chỉ VPN trên LAP-0610", "Block VPN của máy LAP-0610 lại" (không nhận "khách sạn block VPN" — phải kèm đích)
    ("revoke", rf"{_NOT_PAST}\brút\s+(?:\S+\s+){{0,2}}?(?:chứng chỉ|cert)\b{_NOT_REGRANT}"),
    ("revoke", r"\bblock\s+(?:\S+\s+){0,2}?vpn\s+(?:của|cho|trên|máy|giúp|lại|đi)\b"),
    # "Đóng tài khoản ERP của em", "Xoá / Gỡ / Bỏ em (ra) khỏi nhóm Finance / thư mục finance/Q3" — chỉ "tài khoản" sau "đóng" ("đóng
    # Outlook / email rồi mở lại" là thao tác sửa lỗi).
    ("revoke", rf"{_NOT_PAST}\bđóng\s+(?:hẳn\s+)?(?:tài khoản|tk)\b"),
    ("revoke", (rf"{_NOT_PAST}\b(?:xoá|xóa|gỡ|bỏ|rút|loại)\s+(?:\S+\s+){{0,2}}?(?:ra\s+)?khỏi\s+"
                r"(?:nhóm|group|thư mục|danh sách|quyền|vpn)\b")),
    # "khoá hẳn / luôn …" là xin khoá; "nó khoá luôn rồi", "tài khoản khoá hẳn rồi", "khoá luôn từ sáng" là KỂ trạng thái (soát 03:50)
    ("lock", (r"(?<!mở )(?<!bị )(?<!đã )(?<!nó )(?<!tự )\b(?:khoá|khóa)\s+(?:hẳn|luôn|ngay|tạm thời|giúp|giùm|hộ)\b"
              r"(?!\s+(?:rồi|r\b|từ|mất))")),
    # "Khoá tài khoản ERP của em lại giúp em" (đo 12/11: dựng hành động MỞ khoá, chỉ lớp LLM chặn) — tối đa 3 từ giữa, không vượt qua
    # "mở" / "tự" ("khoá tài khoản tự mở lại sau bao lâu?", "khoá tài khoản cứ tự bật lại" là câu hỏi, không xin khoá). "lock tk AD
    # của em lại", "Chặn tài khoản của nv006 lại" (chặn chỉ với tài khoản / email — "mạng chặn VPN" là báo lỗi).
    ("lock", (rf"(?<!mở )(?<!bị )(?<!đã )(?<!lỡ )(?<!tự )(?<!vừa )\b(?:khoá|khóa|lock)\s+(?:lại\s+)?{_OBJECT}\s+"
              r"(?:(?!mở\b|tự\b)\S+\s+){0,5}?(?:giúp|giùm|hộ|ngay|luôn|hẳn|lại|đi|gấp|tạm thời)\b")),
    ("lock", r"(?<!bị )(?<!đã )\bchặn\s+(?:lại\s+)?(?:tài khoản|tk|email|mail)\s+(?:(?!mở\b)\S+\s+){0,3}?(?:giúp|giùm|hộ|ngay|luôn|hẳn|lại|đi)\b"),
    # "Khoá tạm / tạm khoá / tạm ngưng tài khoản …" — KHÔNG nhận "Tài khoản bị tạm khoá do nhập sai, mở giúp em" (luồng mở khoá thường
    # gặp nhất — trước 03:50 mẫu "tạm khoá" trần bắt nhầm câu này).
    ("lock", (r"(?<!bị )(?<!đã )(?<!đang )\b(?:khoá tạm|khóa tạm|tạm khoá|tạm khóa|tạm ngưng|tạm dừng)\s+(?:thời\s+)?(?:lại\s+)?"
              r"(?:tài khoản|tk|email|mail|giúp|giùm|hộ|chứng chỉ|cert|vpn)\b")),
    # Kiểm hộp đen 12/11 (LLM thật: "Đóng băng tài khoản…", "lock my account please" → hỏi "đặt lại mật khẩu hay MỞ khoá?"):
    (
        "lock",
        r"(?<!bị )(?<!đã )\b(?:đóng băng|freeze|suspend|tạm đình chỉ|đình chỉ)\s+(?:\S+\s+){0,2}?(?:tài khoản|tk|account|email|mail|vpn)\b",
    ),
    ("lock", r"(?<!un)\block\s+(?:my\s+|the\s+|this\s+|our\s+|his\s+|her\s+)?(?:\S+\s+)?(?:account|acc|email|mailbox|vpn|user)\b"),
    # "Em xin khoá tài khoản email trong thời gian đi công tác", "Em muốn khoá tài khoản cũ", "nhờ IT khoá tk của bạn Hùng" — chen tối đa
    # 2 từ, không chen "mở" / "bị" ("muốn mở khoá", "muốn biết vì sao bị khoá").
    ("lock", (r"\b(?:muốn|xin|cần|nhờ|giúp|giùm|hãy|vui lòng|làm ơn|đề nghị|yêu cầu)\s+(?:(?!mở\b|bị\b)\S+\s+){0,2}?(?:khoá|khóa|lock)\s+"
              r"(?:lại\s+)?(?:\S+\s+)?(?:tài khoản|tk|account|email|mail|vpn)\b")),
    # chen tối đa 1 từ, không phải "phải" ("Em không muốn phải đổi mật khẩu thường xuyên, có cách nào không" là hỏi chính sách)
    ("negate", (rf"\b(?:đừng(?!\s+(?:quên|lo|ngại)\b)|thôi khỏi|khỏi cần|khỏi|{_NO}\s+muốn|chưa\s+(?:cần|muốn))\s+(?:(?!phải\b)\S+\s+)?"
                rf"{_ACTION_VERB}\b{_NOT_ONLY}")),
    ("negate", _NEGATE_EN),
    # "Không cần gia hạn VPN cho máy LAP-0342 nữa đâu" / "em không cần quyền đọc finance/Q3 nữa" — phải có "nữa" (không còn cần).
    ("negate", rf"\b{_NO}\s+cần\s+(?:\S+\s+)?(?:{_ACTION_VERB}|{_OBJECT})\b[^.!?\n]{{0,50}}?\bnữa\b{_NOT_ONLY}"),
    # "Ko cần reset mk đâu", "không cần đổi mật khẩu đâu" — "đâu" chỉ khi ngay sau "cần" là VIỆC; "ko cần quyền sửa đâu, đọc thôi là dc"
    # (đích là quyền) là ràng buộc của yêu cầu, không phải từ chối.
    ("negate", rf"\b{_NO}\s+cần\s+{_ACTION_VERB}\b[^.!?\n]{{0,50}}?\bđâu\b{_NOT_ONLY}"),
    # "Không cần cấp lại VPN, chứng chỉ cũ vẫn chạy" — "không cần + VIỆC" ĐẦU câu / mệnh đề (cho một chủ ngữ đứng trước); câu hỏi "có
    # cần … không" không bắt đầu bằng "không cần".
    ("negate", rf"(?:^|[.,!?;:]\s*)(?:(?:em|mình|tôi|tớ|anh|chị|e)\s+)?{_NO}\s+cần\s+{_ACTION_VERB}\b{_NOT_ONLY}"),
    # "Em không dùng VPN nữa, thu lại giúp em" — KHÔNG nhận "không dùng ĐƯỢC VPN nữa" / "không dùng VPN được nữa" (báo lỗi).
    ("negate", (rf"\b{_NO}\s+(?:dùng|xài|sử dụng)\s+(?:(?!được\b)\S+\s+){{0,2}}?{_OBJECT}\b(?:(?!được)[^.!?\n]){{0,30}}?"
                r"\bnữa\b")),
    # câu trả lời ở bước hỏi lại: "Em đổi ý rồi, không gia hạn nữa", "LAP-0417 nhưng không gia hạn đâu nhé", "LAP-0417, mà thôi khỏi"
    ("negate", rf"\b{_NO}\s+{_ACTION_VERB}\s+(?:(?!được\b)\S+\s+){{0,3}}?(?:nữa|đâu)\b"),
    ("negate", rf"\bthôi\s+khỏi\b|\bđổi ý\b|\bnhớ ra\s+(?:mật khẩu|mk|pass)\b|\b{_NO}\s+cần\s+nữa\b|\bđừng\s+(?:làm|xử lý|thực hiện)\b"),
    ("cancel", r"\b(?:huỷ|hủy|bỏ qua|rút lại|cancel)\s+(?:\S+\s+){0,3}?(?:yêu cầu|ticket|phiếu|request)\b"),
    ("cancel", r"\b(?:thôi|bỏ)\s+(?:cái\s+)?(?:yêu cầu|ticket|phiếu)\b"),
    # "cái yêu cầu xin quyền … e gửi sáng nay a huỷ giúp e nhé" (bộ kiểm mù 12/11)
    ("cancel", r"\b(?:yêu cầu|ticket|phiếu)\b[^.!?\n]{0,60}?\b(?:huỷ|hủy|rút lại|cancel)\s+(?:giúp|giùm|hộ|đi|luôn)\b"),
    # "Gỡ FortiClient VPN khỏi máy em" (intent vpn, không phải software) — "gỡ / xoá / tháo … (ra) khỏi máy" ở MỌI intent ghi;
    # "xoá chứng chỉ cũ khỏi máy rồi cấp lại" là xin làm thuận.
    ("uninstall", (rf"{_NOT_PAST}\b(?:gỡ bỏ|gỡ|xoá|xóa|tháo|delete|remove|uninstall)\s+(?:\S+\s+){{1,3}}?(?:ra\s+)?khỏi\s+"
                   r"(?:máy|laptop|pc|điện thoại|macbook)\b(?![^.!?\n]*\b(?:cài lại|cấp lại|cài mới|rồi cài)\b)")),
    ("compromised", _COMPROMISED),  # sau cùng: câu vừa xin khoá vừa nghi lộ vẫn mang nhãn "lock" như trước
)
_FOLDED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    ("lost_device", (rf"{fold(_NOT_ANTI_LOSS)}\b(?:lam mat|danh mat|bi mat|mat|that lac|danh roi|lam roi|roi mat|bo quen|de quen|bi trom|"
                     rf"bi danh cap|bi cuop|cuop giat|bi lay mat|lay mat)\s+(?:luon\s+|ca\s+)?(?:cai\s+|chiec\s+|con\s+)?{_DEVICE_FOLDED}\b"
                     r"(?![^.!?\n]{0,20}\bo nha\b)")),
    ("lost_device", (rf"\b{_DEVICE_FOLDED}\b[^.!?\n]{{0,40}}?(?<!khong )(?<!ko )(?<!chua )\b(?:bi mat|da mat|lam mat|that lac|bi trom|"
                     rf"bi danh cap|bi cuop|lay mat|bi lay mat)\b{fold(_LOSS_END)}(?![^.!?\n]{{0,20}}\bo nha\b)")),
    ("lost_device", rf"\b{_DEVICE_FOLDED}\b[^.!?\n]{{0,30}}?(?:{fold(_GONE)})"),
    ("revoke", (rf"{fold(_NOT_PAST)}{fold(_NOT_OTHERS)}\b(?:thu hoi|thu lai|vo hieu hoa|vo hieu|revoke|disable|{_HUY_FOLDED}|xoa)\s+(?:\S+\s+){{0,3}}?"
                rf"(?:vpn|chung chi|quyen|truy cap|tai khoan|tk|email|mail)\b{_NOT_REGRANT_FOLDED}")),
    # bỏ "bo quyen" ("toàn bộ quyền") và "go quyen" (gõ) — mất dấu là lẫn nghĩa
    ("revoke", (rf"{fold(_NOT_PAST)}{fold(_NOT_OTHERS)}\b(?:rut lai|rut bot|rut|tuoc|ha cap|ha|giam bot|giam|thu hep|cat|tra lai)\s+"
                rf"(?:het\s+|bot\s+|toan bo\s+)?quyen\b(?![^.!?\n]{{0,30}}\bcho\s+(?:em|e|minh|toi|to|anh|chi)\b){_NOT_REGRANT_FOLDED}")),
    ("revoke", _DISABLE_VPN_FOLDED),
    ("revoke", rf"{fold(_NOT_PAST)}\bdong\s+(?:han\s+)?(?:tai khoan|tk)\b"),
    ("lock", (r"(?<!mo )(?<!bi )(?<!no )(?<!tu )\bkhoa\s+(?:han|luon|tam thoi)\b(?!\s+(?:roi|r\b|tu|mat))")),
    ("lock", (r"(?<!mo )(?<!bi )(?<!da )(?<!tu )\b(?:khoa|lock)\s+(?:lai\s+)?(?:tk|tai khoan|email|mail|vpn)\s+(?:(?!mo\b|tu\b)\S+\s+){0,5}?"
              r"(?:giup|gium|ho|ngay|luon|han|lai|di|gap|tam thoi)\b")),
    ("lock", r"(?<!bi )(?<!da )(?<!dang )\b(?:khoa tam|tam khoa|tam ngung)\s+(?:thoi\s+)?(?:lai\s+)?(?:tk|tai khoan|email|mail|giup|chung chi|cert|vpn)\b"),
    ("lock", r"(?<!bi )(?<!da )\b(?:dong bang|freeze|suspend|dinh chi)\s+(?:\S+\s+){0,2}?(?:tai khoan|tk|account|email|mail|vpn)\b"),
    # bỏ dấu không có "can" (cần / cán) — "xin / nho / muon … khoa tk"
    ("lock", (r"\b(?:muon|xin|nho|giup|gium|hay|vui long|lam on|de nghi|yeu cau)\s+(?:(?!mo\b|bi\b)\S+\s+){0,2}?(?:khoa|lock)\s+"
              r"(?:lai\s+)?(?:\S+\s+)?(?:tai khoan|tk|account|email|mail|vpn)\b")),
    ("negate", (rf"\b(?:thoi khoi|khoi can|khoi|{_NO_FOLDED}\s+muon|chua\s+(?:can|muon))\s+(?:(?!phai\b)\S+\s+)?{_ACTION_VERB_FOLDED}\b"
                r"(?![^\n]*\bchi can\b)")),
    # "dung cap lai chung chi VPN nha" — "dung" (đừng / dùng) chỉ khi đứng NGAY trước việc ("dùng để gia hạn" có "de" chen giữa)
    ("negate", r"\bdung\s+(?:cap lai|gia han|reset|mo khoa|dat lai)\b(?![^.!?\n]*\bchi can\b)"),
    ("negate", (rf"\b{_NO_FOLDED}\s+can\s+(?:\S+\s+)?(?:{_ACTION_VERB_FOLDED[3:-1]}|vpn|chung chi|quyen|tai khoan|email)\b"
                r"[^.!?\n]{0,50}?\bnua\b(?![^.!?\n]*\bchi can\b)")),
    ("negate", rf"\bthoi\s+khoi\b|\bdoi y\b|\b{_NO_FOLDED}\s+can\s+nua\b"),
    ("cancel", rf"\b(?:{_HUY_FOLDED}|bo qua|rut lai|cancel)\s+(?:\S+\s+){{0,3}}?(?:yeu cau|ticket|phieu|request)\b"),
    ("cancel", r"\bthoi\s+(?:yeu cau|ticket|phieu)\b"),
    ("compromised", _COMPROMISED_FOLDED),
)  # fmt: skip
# Gỡ cài đặt: KHÔNG nhận câu hỏi cách làm ("cách gỡ Zoom"), bước phụ khi cài ("máy báo phải gỡ bản cũ trước", "Có cần gỡ bản cũ trước
# khi cài Office 365 không?"), dọn ổ đĩa ("Xoá bớt file trong ổ C") — soát 12/11 03:50.
_UNINSTALL_NOT = r"(?!\s*(?:lỗi|rối|khoá|khóa|cache|bộ nhớ đệm|file|tệp|dữ liệu|rác|bớt|lịch sử|bản cũ|phiên bản cũ))"
_UNINSTALL_ACCENTED: Final = (
    rf"{_NOT_PAST}(?<!cách )(?<!sao )(?<!phải )(?<!cần )\b(?:gỡ bỏ|gỡ cài đặt|bỏ cài đặt|huỷ cài đặt|hủy cài đặt|gỡ|uninstall|uninstal|"
    rf"remove|delete|xoá|xóa|tháo bỏ|loại bỏ)\b{_UNINSTALL_NOT}"
    r"|\bdọn\s+(?:\S+\s+){0,2}?khỏi\s+(?:máy|laptop|pc)\b"
    # "Tháo phần mềm UltraViewer ra khỏi máy em" (kiểm hộp đen 12/11 — LLM thật: phiếu duyệt CÀI UltraViewer); "tháo" trần là phần cứng
    r"|\btháo\s+(?:phần mềm|ứng dụng|app)\b|\btháo\s+(?:\S+\s+){1,3}?ra\s+khỏi\b"
    # "anh gỡ bớt mấy phần mềm không dùng như CCleaner" — "bớt" bị loại ở trên vì "xoá bớt file"; ở đây đích là phần mềm
    r"|\b(?:gỡ|xoá|xóa)\s+bớt\s+(?:mấy\s+|vài\s+|các\s+|những\s+|một số\s+)?(?:phần mềm|ứng dụng|app)\b"
)
_UNINSTALL_FOLDED: Final = (
    rf"{fold(_NOT_PAST)}(?<!cach )(?<!sao )(?<!phai )(?<!can )\b(?:go bo|go cai dat|bo cai dat|huy cai dat|go phan mem|go ung dung|"
    rf"uninstall|uninstal|remove|delete|xoa|thao bo|loai bo)\b{fold(_UNINSTALL_NOT)}"
    r"|\bgo\s+\S+\s+khoi\s+(?:may|laptop|pc)\b|\bdon\s+(?:\S+\s+){0,2}?khoi\s+(?:may|laptop|pc)\b"
    r"|\bthao\s+(?:phan mem|ung dung|app)\b|\bthao\s+(?:\S+\s+){1,3}?ra\s+khoi\b"
)

_RES: Final = tuple((k, re.compile(p)) for k, p in _ACCENTED)
_RES_FOLDED: Final = tuple((k, re.compile(p)) for k, p in _FOLDED)
_UNINSTALL_RES: Final = (re.compile(_UNINSTALL_ACCENTED), re.compile(_UNINSTALL_FOLDED))


def reverse_action_kind(text: str, intents: Collection[str]) -> ReverseKind | None:
    """Loại thao tác ngược đầu tiên khớp trong `text`, hoặc None. Chỉ xét khi có ít nhất một intent GHI; "gỡ cài đặt" chỉ khi có
    intent `software` (ở intent khác "gỡ" thường là "gỡ lỗi"). Không trả câu hay đoạn khớp — chỉ nhãn (audit không chép chữ người dùng)."""
    if not WRITE_INTENTS.intersection(intents):
        return None
    lowered = normalize_for_detect(text)
    folded = fold(lowered)
    for kind, pat in _RES:
        if pat.search(lowered):
            return kind
    for kind, pat in _RES_FOLDED:
        if pat.search(folded):
            return kind
    if "software" in intents and (_UNINSTALL_RES[0].search(lowered) or _UNINSTALL_RES[1].search(folded)):
        return "uninstall"
    return None
