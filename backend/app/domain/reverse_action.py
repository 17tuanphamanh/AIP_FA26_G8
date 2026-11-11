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
KB-GEN-008 coi là sự cố an toàn thông tin, kỹ thuật viên xử lý), mẫu rút / hạ quyền, "khoá … lại", "không cần … nữa". 03:55: "ngắt / tắt
VPN" (thành phiếu GIA HẠN / CẤP LẠI VPN), máy nhiễm mã độc (`compromised`).

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

_DEVICE = r"(?:laptop|máy tính|máy(?!\s*chủ)|điện thoại|thiết bị|macbook|ipad|ổ cứng|usb|thẻ nhân viên)"
_DEVICE_FOLDED = r"(?:laptop|may tinh|dien thoai|thiet bi|macbook|ipad|o cung|usb|the nhan vien)"  # bỏ "may" (máy/mấy)
_LOSS_VERB = r"(?:làm mất|đánh mất|bị mất|mất|thất lạc|đánh rơi|bỏ quên|để quên|bị trộm|bị ăn trộm|bị đánh cắp|bị cướp|bị giật)"
_LOSS_AFTER = r"(?:bị mất|đã mất|làm mất|thất lạc|bị trộm|bị ăn trộm|bị đánh cắp|bị cướp|bị giật|để quên|bỏ quên)"
# Sau "bị mất / thất lạc / bị trộm…" chỉ coi là BÁO MẤT MÁY khi tiếp theo là hết câu hoặc từ chỉ hoàn cảnh (rồi, trộm, ở, hôm…) —
# danh sách CHO PHÉP thay vì loại trừ: "máy bị mất kết nối", "bị mất sạc" (mất cục sạc), "mất 10 phút" đều không khớp (bộ đánh giá có
# "Máy LAP-0342 của mình bị mất sạc, công ty có cấp lại không?" — tự soát 12/11).
_LOSS_END = (
    r"(?=\s*(?:$|[.,!?;:)]|rồi|trộm|cắp|cướp|mất|ở|tại|trên|dưới|lúc|khi|hôm|tối|sáng|chiều|trưa|ngoài|trong|giữa|giúp|nên|mà|và|"
    r"với|thì|gấp|ngay|luôn|đâu|đó|này|ấy|cmnr|r\b))"
)
_OBJECT = r"(?:vpn|chứng chỉ|quyền|truy cập|tài khoản|tk|email|mail)"
# Việc ĐÃ xảy ra (người dùng kể lại, không xin làm): "em bị thu hồi quyền VPN, cấp lại giúp", "em đã xoá chứng chỉ cũ rồi cài lại",
# "em vừa gỡ Zoom" — bỏ qua. Lookbehind độ dài cố định nên tách từng cụm.
_NOT_PAST = r"(?<!bị )(?<!đã )(?<!vừa )(?<!mới )(?<!lỡ )(?<!nhầm )"
_REVOKE_VERB = r"(?:thu hồi|vô hiệu hoá|vô hiệu hóa|vô hiệu|revoke|disable|huỷ|hủy|xoá|xóa)"
_ACTION_VERB = r"(?:mở khoá|mở khóa|gia hạn|cấp lại|cấp|cài đặt|cài|đặt lại|reset)"
# Bổ sung 12/11 02:30 (đo trên máy demo): "Rút / Bỏ / Gỡ quyền ghi …" → bot hỏi "xem, xin mới hay gia hạn?" lặp tới E4; "Hạ quyền … xuống
# chỉ đọc" → phiếu CẤP quyền đọc (người dùng vẫn giữ quyền ghi mà tưởng đã hạ). Chỉ khớp khi "quyền" đứng ngay sau động từ.
_REVOKE_PERM = r"(?:rút lại|rút bớt|rút|tước|bỏ|gỡ bỏ|gỡ|hạ cấp|hạ|giảm bớt|giảm|thu hẹp)\s+quyền"
# Sự cố an ninh tài khoản (đo trên máy demo 12/11): "Em bị lộ mật khẩu email rồi, đặt lại giúp em" và "email bị hack, đổi mật khẩu gấp"
# → hệ thống TỰ đặt lại mật khẩu email và gửi mật khẩu tạm "qua email" — tức vào chính hộp thư đang bị chiếm. KB-GEN-008: nghi lộ /
# bị chiếm là sự cố an toàn thông tin, kỹ thuật viên xử lý trực tiếp. Chuyển người như báo mất máy.
# Ngắt / tắt VPN (đo 12/11 03:55, LLM thật): "Máy LAP-0342 hình như nhiễm mã độc, ngắt VPN của máy đó giúp em" → phiếu GIA HẠN chứng chỉ
# VPN; "Tắt VPN trên máy LAP-0610 giúp em" → phiếu CẤP LẠI quyền VPN (chứng chỉ máy này đang bị thu hồi). Không nhận câu hỏi cách làm
# ("làm sao tắt VPN", "cách tắt VPN"), việc đã / đang xảy ra ("bị ngắt VPN", "khi tắt VPN thì…"); không có "chặn" ("mạng công ty chặn
# VPN" là báo lỗi) và bản bỏ dấu không có "dung" ("dùng VPN").
_DISABLE_VPN = (
    r"(?<!cách )(?<!sao )(?<!để )(?<!bị )(?<!đã )(?<!vừa )(?<!khi )(?<!lần )(?<!nếu )(?<!tự )"
    r"\b(?:ngắt|tắt|cắt|dừng|ngừng|tạm dừng|tạm ngưng|ngưng)\s+(?:kết nối\s+|quyền\s+|truy cập\s+)?vpn\b"
)
_DISABLE_VPN_FOLDED = (
    r"(?<!cach )(?<!sao )(?<!de )(?<!bi )(?<!da )(?<!vua )(?<!khi )(?<!lan )(?<!neu )(?<!tu )"
    r"\b(?:ngat|tat|ngung|tam dung|tam ngung)\s+(?:ket noi\s+|quyen\s+|truy cap\s+)?vpn\b"
)
# Chủ ngữ "người lạ": "có người / có ai (lạ, khác)", "ai đó", "người nào đó" + tối đa hai trợ từ ("đang cố", "đã", "định").
_WHO = (
    r"\b(?:có\s+(?:ai|người)|ai đó|người nào đó|kẻ nào đó|kẻ gian)\s+(?:lạ\s+|khác\s+)?(?:(?:đã|đang|cố|định|muốn|vừa)\s+){0,2}"
)
_WHO_FOLDED = r"\b(?:co\s+(?:ai|nguoi)|ai do|nguoi nao do|ke nao do|ke gian)\s+(?:la\s+|khac\s+)?(?:(?:da|dang|co|dinh|muon|vua)\s+){0,2}"
_COMPROMISED = (
    # "chiếm" chỉ khi kèm quyền / tài khoản: "ổ C bị chiếm hết dung lượng" không phải sự cố an ninh
    r"\bbị\s+(?:hack|hách|hắc|xâm nhập|chiếm đoạt|chiếm quyền|chiếm\s+(?:mất\s+)?(?:tài khoản|tk|email|mail|hộp thư)|đánh cắp|lấy cắp|lừa)\b"
    r"|\b(?:tài khoản|tk|email|mail|hộp thư)\b[^.!?\n]{0,30}?\bbị\s+chiếm\b"
    r"|\b(?:hacked|compromised)\b"
    r"|\blộ\s+(?:mất\s+)?(?:mật khẩu|mk|pass|password|thông tin đăng nhập|otp|mã xác minh)\b"
    # "có ai/người …" phải kèm đích là mật khẩu hoặc tài khoản CỦA người gửi: "Có ai biết cách gia hạn VPN không?", "có ai đăng nhập
    # được VPN không?" là câu hỏi thường, không khớp.
    rf"|{_WHO}(?:lấy được|lấy|biết|dò|đánh cắp)\s+(?:được\s+)?(?:mật khẩu|mk|pass)\b"
    rf"|{_WHO}(?:đăng nhập|truy cập|vào)\s+(?:được\s+)?(?:vào\s+)?(?:tài khoản|tk|email|mail|hộp thư)\s+(?:\S+\s+)?"
    r"(?:của\s+)?(?:em|mình|tôi|tớ|anh|chị)\b"
    r"|\bngười lạ\s+(?:đã\s+)?(?:đăng nhập|truy cập|vào|dùng)\b"
    r"|\bđăng nhập lạ\b"
    r"|\bđăng nhập\s+(?:\S+\s+){0,3}?(?:thiết bị|máy|nơi|địa điểm|vị trí|ip|quốc gia)\s+lạ\b"
    r"|\b(?:mã\s+)?(?:otp|mã xác minh|mã xác thực)\s+lạ\b"
    # Máy nhiễm mã độc (KB-GEN-008: ngắt mạng, báo IT — kỹ thuật viên xử lý trực tiếp); chỉ xét khi có intent ghi, câu hỏi it_help không vào.
    r"|\b(?:nhiễm|dính|bị)\s+(?:virus|vi rút|mã độc|malware|ransomware|trojan|mã hoá dữ liệu|mã hóa dữ liệu)\b|\bransomware\b"
    r"|\b(?:mật khẩu|mk|pass)\s+(?:\S+\s+){0,3}?vào\s+(?:trang|web|website|link|liên kết|đường link|form)\s+(?:\S+\s+)?"
    r"(?:lạ|giả|giả mạo|lừa đảo)\b"
)
_COMPROMISED_FOLDED = (
    r"\bbi\s+(?:hack|xam nhap|chiem doat|chiem quyen|chiem\s+(?:mat\s+)?(?:tai khoan|tk|email|mail|hop thu)|danh cap|lay cap)\b"
    r"|\b(?:tai khoan|tk|email|mail|hop thu)\b[^.!?\n]{0,30}?\bbi\s+chiem\b"
    r"|\b(?:hacked|compromised)\b"
    r"|\bbi\s+lo\s+(?:mat\s+)?(?:mat khau|mk|pass|password|otp)\b"
    r"|\b(?:nhiem|dinh)\s+(?:virus|vi rut|ma doc|malware|ransomware|trojan)\b|\bransomware\b"
    rf"|{_WHO_FOLDED}(?:lay duoc|lay|biet|do)\s+(?:duoc\s+)?(?:mat khau|mk|pass)\b"
    rf"|{_WHO_FOLDED}(?:dang nhap|truy cap|vao)\s+(?:duoc\s+)?(?:vao\s+)?(?:tai khoan|tk|email|mail|hop thu)\s+(?:\S+\s+)?"
    r"(?:cua\s+)?(?:em|minh|toi|to|anh|chi)\b"
)

_ACCENTED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    ("lost_device", rf"\b{_LOSS_VERB}\s+(?:cái\s+|chiếc\s+)?{_DEVICE}\b"),
    ("lost_device", rf"\b{_DEVICE}\b[^.!?\n]{{0,40}}?\b{_LOSS_AFTER}\b{_LOSS_END}"),
    ("revoke", rf"{_NOT_PAST}\b{_REVOKE_VERB}\s+(?:\S+\s+){{0,3}}?{_OBJECT}\b"),
    ("revoke", rf"{_NOT_PAST}\b{_REVOKE_PERM}\b"),
    ("revoke", _DISABLE_VPN),
    ("lock", r"(?<!mở )(?<!bị )(?<!đã )\b(?:khoá|khóa)\s+(?:hẳn|luôn|ngay|tạm thời|giúp|giùm|hộ)\b"),
    # "Khoá tài khoản ERP của em lại giúp em" (đo 12/11: dựng hành động MỞ khoá, chỉ lớp LLM chặn) — tối đa 3 từ giữa, không vượt qua
    # "mở" / "tự" ("khoá tài khoản tự mở lại sau bao lâu?", "khoá tài khoản cứ tự bật lại" là câu hỏi, không xin khoá).
    ("lock", (rf"(?<!mở )(?<!bị )(?<!đã )(?<!lỡ )(?<!tự )(?<!vừa )\b(?:khoá|khóa)\s+(?:lại\s+)?{_OBJECT}\s+(?:(?!mở\b|tự\b)\S+\s+){{0,3}}?"
              r"(?:giúp|giùm|hộ|ngay|luôn|hẳn|lại)\b")),
    ("lock", r"\btạm khoá\b|\btạm khóa\b"),
    ("negate", rf"\b(?:đừng|thôi khỏi|khỏi cần|không muốn)\s+(?:\S+\s+)?{_ACTION_VERB}\b"),
    # "Không cần gia hạn VPN cho máy LAP-0342 nữa đâu" / "em không cần quyền đọc finance/Q3 nữa" — phải có "nữa" (không còn cần).
    ("negate", rf"\bkhông cần\s+(?:\S+\s+)?(?:{_ACTION_VERB}|{_OBJECT})\b[^.!?\n]{{0,50}}?\bnữa\b"),
    ("cancel", r"\b(?:huỷ|hủy|thôi|bỏ)\s+(?:cái\s+)?(?:yêu cầu|ticket|phiếu)\b"),
    ("compromised", _COMPROMISED),  # sau cùng: câu vừa xin khoá vừa nghi lộ vẫn mang nhãn "lock" như trước
)
_FOLDED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    ("lost_device", (rf"\b(?:lam mat|danh mat|bi mat|mat|that lac|danh roi|bo quen|de quen|bi trom|bi danh cap|bi cuop)\s+"
                     rf"(?:cai\s+|chiec\s+)?{_DEVICE_FOLDED}\b")),
    ("lost_device", (rf"\b{_DEVICE_FOLDED}\b[^.!?\n]{{0,40}}?\b(?:bi mat|da mat|lam mat|that lac|bi trom|bi danh cap|bi cuop)\b"
                     rf"{fold(_LOSS_END)}")),
    ("revoke", (rf"{fold(_NOT_PAST)}\b(?:thu hoi|vo hieu hoa|vo hieu|revoke|disable)\s+(?:\S+\s+){{0,3}}?"
                r"(?:vpn|chung chi|quyen|truy cap|tai khoan|tk|email|mail)\b")),
    # bỏ "bo quyen" ("toàn bộ quyền") và "go quyen" (gõ) — mất dấu là lẫn nghĩa
    ("revoke", rf"{fold(_NOT_PAST)}\b(?:rut lai|rut bot|rut|tuoc|ha cap|ha|giam bot|giam|thu hep)\s+quyen\b"),
    ("revoke", _DISABLE_VPN_FOLDED),
    ("lock", r"(?<!mo )(?<!bi )\bkhoa\s+(?:han|luon|tam thoi)\b"),
    ("negate", r"\b(?:thoi khoi|khoi can|khong muon)\s+(?:\S+\s+)?(?:mo khoa|gia han|cap lai|cai dat|cai|dat lai|reset)\b"),
    ("negate", (r"\bkhong can\s+(?:\S+\s+)?(?:mo khoa|gia han|cap lai|cap|cai dat|cai|dat lai|reset|vpn|chung chi|quyen|tai khoan|"
                r"email)\b[^.!?\n]{0,50}?\bnua\b")),
    ("cancel", r"\b(?:huy|thoi)\s+(?:yeu cau|ticket|phieu)\b"),
    ("compromised", _COMPROMISED_FOLDED),
)  # fmt: skip
_UNINSTALL_ACCENTED: Final = rf"{_NOT_PAST}\b(?:gỡ bỏ|gỡ cài đặt|gỡ|uninstall|remove|xoá|xóa)\b(?!\s*(?:lỗi|rối|khoá|khóa|cache|bộ nhớ đệm|file tạm|tệp tạm|lịch sử))"
_UNINSTALL_FOLDED: Final = rf"{fold(_NOT_PAST)}\b(?:go bo|go cai dat|go phan mem|go ung dung|uninstall|remove)\b"

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
