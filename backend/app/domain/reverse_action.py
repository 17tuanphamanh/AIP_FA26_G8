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
from collections.abc import Collection
from typing import Final, Literal

from app.domain.target import fold

type ReverseKind = Literal["lost_device", "compromised", "revoke", "lock", "negate", "cancel", "uninstall"]

# Intent có hành động GHI — chỉ ở các intent này mới có nguy cơ ánh xạ ngược. it_help / out_of_scope không dựng hành động.
WRITE_INTENTS: Final = frozenset({"vpn", "account", "access", "software"})

_DEVICE = r"(?:laptop|máy tính|máy(?!\s*chủ)|điện thoại|đt|thiết bị|macbook|ipad|ổ cứng|usb|thẻ nhân viên|lap|[a-z]{2,4}-\d{3,5})"
# bỏ "may" (máy/mấy); "dt" = "đt" (điện thoại); mã máy (LAP-0610) cũng là thiết bị
_DEVICE_FOLDED = r"(?:laptop|may tinh|dien thoai|dt|thiet bi|macbook|ipad|o cung|usb|the nhan vien|lap|[a-z]{2,4}-\d{3,5})"
_LOSS_VERB = (
    r"(?:làm mất|đánh mất|bị mất|mất|thất lạc|đánh rơi|bỏ quên|để quên|bị trộm|bị ăn trộm|bị đánh cắp|bị cướp giật|bị cướp|bị giật|"
    r"cướp giật|bị lấy mất|lấy mất|bị móc túi mất|bị móc túi)"
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
_OBJECT = r"(?:vpn|chứng chỉ|cert|quyền|truy cập|tài khoản|tk|email|mail)"
# Việc ĐÃ xảy ra (người dùng kể lại, không xin làm): "em bị thu hồi quyền VPN, cấp lại giúp", "em đã xoá chứng chỉ cũ rồi cài lại",
# "em vừa gỡ Zoom" — bỏ qua. Lookbehind độ dài cố định nên tách từng cụm.
_NOT_PAST = r"(?<!bị )(?<!đã )(?<!vừa )(?<!mới )(?<!lỡ )(?<!nhầm )"
# Người KHÁC / hệ thống đã làm ("Sếp thu hồi quyền ghi của em", "Hệ thống tự thu hồi quyền", "Em bị IT hạ quyền") và câu có xin LẠI
# ("… rồi cấp lại cái mới", "giờ em cần lại") — đó là xin làm thuận (soát 12/11 03:50).
_NOT_OTHERS = r"(?<!sếp )(?<!tự )(?<!it )(?<!admin )"
_NOT_REGRANT = r"(?![^.!?\n]*\b(?:cấp lại|xin lại|cần lại|cho lại|mở lại|cấp cho em lại)\b)"
_NOT_REGRANT_FOLDED = r"(?![^.!?\n]*\b(?:cap lai|xin lai|can lai|cho lai|mo lai)\b)"
_REVOKE_VERB = r"(?:thu hồi|thu lại|vô hiệu hoá|vô hiệu hóa|vô hiệu|revoke|disable|huỷ|hủy|xoá|xóa)"
_ACTION_VERB = r"(?:mở khoá|mở khóa|gia hạn|cấp lại|cấp|cài đặt|cài|đặt lại|reset)"
# Bản bỏ dấu: "huy" (huỷ) trùng TÊN người ("Nhờ cấp cho bạn Huy (nv021) quyền sửa…" — bộ đánh giá cong5) → bỏ khi có từ xưng hô đứng trước.
_HUY_FOLDED = r"(?<!ban )(?<!anh )(?<!chi )(?<!em )(?<!cho )(?<!a )(?<!c )(?<!ten )(?<!ong )(?<!ba )huy"
_ACTION_VERB_FOLDED = r"(?:mo khoa|gia han|cap lai|cap|cai dat|cai|dat lai|reset)"
_NO = r"(?:không|ko|k|kh|hông|hok)"  # teencode "ko / k" (soát 12/11 03:50)
_NO_FOLDED = r"(?:khong|ko|k|kh|hong|hok)"
# Phủ định một việc phụ rồi vẫn xin việc khác ("Em không cần cài gì nữa, chỉ cần cấp quyền đọc") — không phải huỷ.
_NOT_ONLY = r"(?![^.!?\n]*\bchỉ cần\b)"
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
_NOT_PREVENT = r"(?<!tránh )(?<!không )(?<!khỏi )(?<!chống )(?<!phòng )(?<!ngừa )"
_COMPROMISED = (
    # "chiếm" chỉ khi kèm quyền / tài khoản: "ổ C bị chiếm hết dung lượng" không phải sự cố an ninh
    rf"{_NOT_PREVENT}\bbị\s+(?:hack|hách|hắc|xâm nhập|xâm phạm|chiếm đoạt|chiếm quyền|chiếm\s+(?:mất\s+)?(?:tài khoản|tk|email|mail|hộp thư)|"
    r"đánh cắp|lấy cắp|lừa|login\s+(?:từ|ở|tại)|đăng nhập\s+(?:từ|ở|tại|trái phép))\b"
    r"|\b(?:tài khoản|tk|email|mail|hộp thư)\b[^.!?\n]{0,30}?\bbị\s+(?:(?:người ta|ai đó|kẻ gian|người lạ|hacker)\s+)?chiếm\b"
    r"|\b(?:hacked|compromised|phishing|keylogger|trojan|ransomware)\b|\btiền chuộc\b"
    r"|(?<!tránh bị )(?<!không bị )(?<!khỏi bị )\blộ\s+(?:mất\s+)?(?:mật khẩu|mk|pass|password|thông tin đăng nhập|otp|mã xác minh)\b"
    # trật tự đảo: "Mật khẩu email của em bị lộ rồi" (soát 12/11 03:50)
    r"|\b(?:mật khẩu|mk|pass|password)\b[^.!?\n]{0,30}?(?<!không )(?<!không bị )\b(?:bị\s+)?lộ\b(?!\s+(?:ra|diện))"
    # "có ai/người …" phải kèm đích là mật khẩu (không phải mật khẩu wifi khách) hoặc tài khoản CỦA người gửi: "Có ai biết cách gia hạn
    # VPN không?", "có ai đăng nhập được VPN không?", "Có ai biết mật khẩu wifi khách không?" là câu hỏi thường, không khớp.
    rf"|{_WHO}(?:lấy được|lấy|biết|dò|đánh cắp|đổi)\s+(?:được\s+)?(?:mật khẩu|mk|pass)\b(?!\s+(?:wifi|wi-fi|wi fi|khách|máy in))"
    rf"|{_WHO}(?:đăng nhập|truy cập|vào|dùng|sử dụng)\s+(?:được\s+)?(?:vào\s+)?(?:tài khoản|tk|email|mail|hộp thư)\s+(?:\S+\s+)?{_MINE}"
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
    r"|\blỡ\s+(?:điền|nhập|đưa|cung cấp|gửi|khai|gõ)\s+(?:luôn\s+)?(?:mật khẩu|mk|pass|otp|mã otp|mã xác minh)\b"
    r"|\b(?:email|mail|thư|tin nhắn|link|trang|web)\s+(?:\S+\s+)?(?:giả mạo|lừa đảo)\b"
    r"|\btự\s+(?:động\s+)?gửi\s+(?:\S+\s+){0,3}?(?:spam|thư rác|mail lạ|email lạ|lừa đảo)\b"
    r"|\b(?:click|bấm|nhấn|nhấp|mở)\s+(?:nhầm\s+|phải\s+|lỡ\s+)?(?:vào\s+)?(?:link|liên kết|đường link|file|tệp)\s+(?:đính kèm\s+)?lạ\b"
)
_COMPROMISED_FOLDED = (
    r"(?<!tranh )(?<!khong )(?<!khoi )(?<!chong )(?<!phong )(?<!ngua )\bbi\s+(?:hack|hach|hac|xam nhap|xam pham|chiem doat|chiem quyen|chiem\s+(?:mat\s+)?(?:tai khoan|tk|email|mail|hop thu)|danh cap|"
    r"lay cap|lua|login\s+(?:tu|o|tai))\b"
    r"|\b(?:tai khoan|tk|email|mail|hop thu)\b[^.!?\n]{0,30}?\bbi\s+(?:(?:nguoi ta|ai do|ke gian|nguoi la|hacker)\s+)?chiem\b"
    r"|\b(?:hacked|compromised|phishing|keylogger|trojan|ransomware)\b"
    r"|(?<!khong )\bbi\s+lo\s+(?:mat\s+)?(?:mat khau|mk|pass|password|otp)\b"
    r"|\b(?:mat khau|mk|pass|password)\b[^.!?\n]{0,30}?(?<!khong )\bbi\s+lo\b"
    r"|(?<!phong )(?<!khoi )(?<!tranh )(?<!chong )\b(?:nhiem|dinh)\s+(?:virus|vi rut|ma doc|malware|ransomware|trojan)\b"
    rf"|{_WHO_FOLDED}(?:lay duoc|lay|biet|do|doi)\s+(?:duoc\s+)?(?:mat khau|mk|pass)\b(?!\s+(?:wifi|wi-fi|wi fi|khach|may in))"
    rf"|{_WHO_FOLDED}(?:dang nhap|truy cap|vao|dung|su dung)\s+(?:duoc\s+)?(?:vao\s+)?(?:tai khoan|tk|email|mail|hop thu)\s+(?:\S+\s+)?"
    rf"{_MINE_FOLDED}"
)

_ACCENTED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    ("lost_device", rf"\b{_LOSS_VERB}\s+(?:cái\s+|chiếc\s+|con\s+)?{_DEVICE}\b{_NOT_HOME}"),
    ("lost_device", rf"\b{_DEVICE}\b[^.!?\n]{{0,40}}?\b{_LOSS_AFTER}\b{_LOSS_END}{_NOT_HOME}"),
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
              r"(?:(?!mở\b|tự\b)\S+\s+){0,3}?(?:giúp|giùm|hộ|ngay|luôn|hẳn|lại|đi)\b")),
    ("lock", r"(?<!bị )(?<!đã )\bchặn\s+(?:lại\s+)?(?:tài khoản|tk|email|mail)\s+(?:(?!mở\b)\S+\s+){0,3}?(?:giúp|giùm|hộ|ngay|luôn|hẳn|lại|đi)\b"),
    # "Khoá tạm / tạm khoá / tạm ngưng tài khoản …" — KHÔNG nhận "Tài khoản bị tạm khoá do nhập sai, mở giúp em" (luồng mở khoá thường
    # gặp nhất — trước 03:50 mẫu "tạm khoá" trần bắt nhầm câu này).
    ("lock", (r"(?<!bị )(?<!đã )(?<!đang )\b(?:khoá tạm|khóa tạm|tạm khoá|tạm khóa|tạm ngưng|tạm dừng)\s+(?:thời\s+)?(?:lại\s+)?"
              r"(?:tài khoản|tk|email|mail|giúp|giùm|hộ)\b")),
    ("negate", rf"\b(?:đừng(?!\s+(?:quên|lo|ngại)\b)|thôi khỏi|khỏi cần|khỏi|{_NO}\s+muốn)\s+(?:\S+\s+)?{_ACTION_VERB}\b{_NOT_ONLY}"),
    # "Không cần gia hạn VPN cho máy LAP-0342 nữa đâu" / "em không cần quyền đọc finance/Q3 nữa" — phải có "nữa" (không còn cần).
    ("negate", rf"\b{_NO}\s+cần\s+(?:\S+\s+)?(?:{_ACTION_VERB}|{_OBJECT})\b[^.!?\n]{{0,50}}?\bnữa\b{_NOT_ONLY}"),
    # "Em không dùng VPN nữa, thu lại giúp em" — KHÔNG nhận "không dùng ĐƯỢC VPN nữa" / "không dùng VPN được nữa" (báo lỗi).
    ("negate", (rf"\b{_NO}\s+(?:dùng|xài|sử dụng)\s+(?:(?!được\b)\S+\s+){{0,2}}?{_OBJECT}\b(?:(?!được)[^.!?\n]){{0,30}}?"
                r"\bnữa\b")),
    # câu trả lời ở bước hỏi lại: "Em đổi ý rồi, không gia hạn nữa", "LAP-0417 nhưng không gia hạn đâu nhé", "LAP-0417, mà thôi khỏi"
    ("negate", rf"\b{_NO}\s+{_ACTION_VERB}\s+(?:(?!được\b)\S+\s+){{0,3}}?(?:nữa|đâu)\b"),
    ("negate", rf"\bthôi\s+khỏi\b|\bđổi ý\b|\bnhớ ra\s+(?:mật khẩu|mk|pass)\b|\b{_NO}\s+cần\s+nữa\b|\bđừng\s+(?:làm|xử lý|thực hiện)\b"),
    ("cancel", r"\b(?:huỷ|hủy|bỏ qua|rút lại|cancel)\s+(?:\S+\s+){0,3}?(?:yêu cầu|ticket|phiếu|request)\b"),
    ("cancel", r"\b(?:thôi|bỏ)\s+(?:cái\s+)?(?:yêu cầu|ticket|phiếu)\b"),
    ("compromised", _COMPROMISED),  # sau cùng: câu vừa xin khoá vừa nghi lộ vẫn mang nhãn "lock" như trước
)
_FOLDED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    ("lost_device", (rf"\b(?:lam mat|danh mat|bi mat|mat|that lac|danh roi|bo quen|de quen|bi trom|bi danh cap|bi cuop|cuop giat|"
                     rf"bi lay mat|lay mat)\s+(?:cai\s+|chiec\s+|con\s+)?{_DEVICE_FOLDED}\b(?![^.!?\n]{{0,20}}\bo nha\b)")),
    ("lost_device", (rf"\b{_DEVICE_FOLDED}\b[^.!?\n]{{0,40}}?\b(?:bi mat|da mat|lam mat|that lac|bi trom|bi danh cap|bi cuop|lay mat|"
                     rf"bi lay mat)\b{fold(_LOSS_END)}(?![^.!?\n]{{0,20}}\bo nha\b)")),
    ("revoke", (rf"{fold(_NOT_PAST)}{fold(_NOT_OTHERS)}\b(?:thu hoi|thu lai|vo hieu hoa|vo hieu|revoke|disable|{_HUY_FOLDED}|xoa)\s+(?:\S+\s+){{0,3}}?"
                rf"(?:vpn|chung chi|quyen|truy cap|tai khoan|tk|email|mail)\b{_NOT_REGRANT_FOLDED}")),
    # bỏ "bo quyen" ("toàn bộ quyền") và "go quyen" (gõ) — mất dấu là lẫn nghĩa
    ("revoke", (rf"{fold(_NOT_PAST)}{fold(_NOT_OTHERS)}\b(?:rut lai|rut bot|rut|tuoc|ha cap|ha|giam bot|giam|thu hep|cat|tra lai)\s+"
                rf"(?:het\s+|bot\s+|toan bo\s+)?quyen\b(?![^.!?\n]{{0,30}}\bcho\s+(?:em|e|minh|toi|to|anh|chi)\b){_NOT_REGRANT_FOLDED}")),
    ("revoke", _DISABLE_VPN_FOLDED),
    ("revoke", rf"{fold(_NOT_PAST)}\bdong\s+(?:han\s+)?(?:tai khoan|tk)\b"),
    ("lock", (r"(?<!mo )(?<!bi )(?<!no )(?<!tu )\bkhoa\s+(?:han|luon|tam thoi)\b(?!\s+(?:roi|r\b|tu|mat))")),
    ("lock", (r"(?<!mo )(?<!bi )(?<!da )(?<!tu )\b(?:khoa|lock)\s+(?:lai\s+)?(?:tk|tai khoan|email|mail|vpn)\s+(?:(?!mo\b|tu\b)\S+\s+){0,3}?"
              r"(?:giup|gium|ho|ngay|luon|han|lai|di)\b")),
    ("lock", r"(?<!bi )(?<!da )(?<!dang )\b(?:khoa tam|tam khoa|tam ngung)\s+(?:thoi\s+)?(?:lai\s+)?(?:tk|tai khoan|email|mail|giup)\b"),
    ("negate", (rf"\b(?:thoi khoi|khoi can|khoi|{_NO_FOLDED}\s+muon)\s+(?:\S+\s+)?{_ACTION_VERB_FOLDED}\b"
                r"(?![^.!?\n]*\bchi can\b)")),
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
    rf"remove|xoá|xóa)\b{_UNINSTALL_NOT}"
    r"|\bdọn\s+(?:\S+\s+){0,2}?khỏi\s+(?:máy|laptop|pc)\b"
)
_UNINSTALL_FOLDED: Final = (
    rf"{fold(_NOT_PAST)}(?<!cach )(?<!sao )(?<!phai )(?<!can )\b(?:go bo|go cai dat|bo cai dat|huy cai dat|go phan mem|go ung dung|"
    rf"uninstall|uninstal|remove|xoa)\b{fold(_UNINSTALL_NOT)}"
    r"|\bgo\s+\S+\s+khoi\s+(?:may|laptop|pc)\b|\bdon\s+(?:\S+\s+){0,2}?khoi\s+(?:may|laptop|pc)\b"
)

_RES: Final = tuple((k, re.compile(p)) for k, p in _ACCENTED)
_RES_FOLDED: Final = tuple((k, re.compile(p)) for k, p in _FOLDED)
_UNINSTALL_RES: Final = (re.compile(_UNINSTALL_ACCENTED), re.compile(_UNINSTALL_FOLDED))


def reverse_action_kind(text: str, intents: Collection[str]) -> ReverseKind | None:
    """Loại thao tác ngược đầu tiên khớp trong `text`, hoặc None. Chỉ xét khi có ít nhất một intent GHI; "gỡ cài đặt" chỉ khi có
    intent `software` (ở intent khác "gỡ" thường là "gỡ lỗi"). Không trả câu hay đoạn khớp — chỉ nhãn (audit không chép chữ người dùng)."""
    if not WRITE_INTENTS.intersection(intents):
        return None
    lowered = text.lower()
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
