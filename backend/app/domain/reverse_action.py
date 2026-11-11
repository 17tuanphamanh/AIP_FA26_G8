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

Mẫu viết cho bản CÓ DẤU (chữ thường) và bản BỎ DẤU (`fold`). Bản bỏ dấu BỎ các mẫu dễ trùng nghĩa khi mất dấu: "máy"/"mấy" (cùng "may"),
"đừng"/"dùng" (cùng "dung"), "gỡ"/"gõ" (cùng "go") — chỉ giữ dạng không lẫn. Loại trừ có chủ đích (test âm tính): "VPN bị mất kết nối",
"máy mất mạng", "laptop mất 10 phút", "tài khoản bị khoá", "mở khoá tài khoản", "mạng chặn VPN", "gỡ lỗi / gỡ rối".
"""

import re
from collections.abc import Collection
from typing import Final, Literal

from app.domain.target import fold

type ReverseKind = Literal["lost_device", "revoke", "lock", "negate", "cancel", "uninstall"]

# Intent có hành động GHI — chỉ ở các intent này mới có nguy cơ ánh xạ ngược. it_help / out_of_scope không dựng hành động.
WRITE_INTENTS: Final = frozenset({"vpn", "account", "access", "software"})

_DEVICE = r"(?:laptop|máy tính|máy(?!\s*chủ)|điện thoại|thiết bị|macbook|ipad|ổ cứng|usb|thẻ nhân viên)"
_DEVICE_FOLDED = r"(?:laptop|may tinh|dien thoai|thiet bi|macbook|ipad|o cung|usb|the nhan vien)"  # bỏ "may" (máy/mấy)
_LOSS_VERB = r"(?:làm mất|đánh mất|bị mất|mất|thất lạc|đánh rơi|bỏ quên|để quên|bị trộm|bị ăn trộm|bị đánh cắp|bị cướp|bị giật)"
_LOSS_AFTER = r"(?:bị mất|đã mất|làm mất|thất lạc|bị trộm|bị ăn trộm|bị đánh cắp|bị cướp|bị giật|để quên|bỏ quên)"
# "mất" theo sau là thứ KHÔNG phải thiết bị → không phải báo mất máy ("máy em bị mất kết nối", "laptop mất 10 phút mới lên")
_NOT_LOSS = (
    r"(?!\s*(?:kết nối|mạng|wi-?fi|internet|tín hiệu|điện|nguồn|âm thanh|tiếng|dữ liệu|file|tệp|quyền|mật khẩu|truy cập|vpn|sóng|"
    r"màn hình|hình|hết|nhiều|khoảng|thời gian|\d))"
)
_OBJECT = r"(?:vpn|chứng chỉ|quyền|truy cập|tài khoản|tk|email|mail)"
# Việc ĐÃ xảy ra (người dùng kể lại, không xin làm): "em bị thu hồi quyền VPN, cấp lại giúp", "em đã xoá chứng chỉ cũ rồi cài lại",
# "em vừa gỡ Zoom" — bỏ qua. Lookbehind độ dài cố định nên tách từng cụm.
_NOT_PAST = r"(?<!bị )(?<!đã )(?<!vừa )(?<!mới )(?<!lỡ )(?<!nhầm )"
_REVOKE_VERB = r"(?:thu hồi|vô hiệu hoá|vô hiệu hóa|vô hiệu|revoke|disable|huỷ|hủy|xoá|xóa)"
_ACTION_VERB = r"(?:mở khoá|mở khóa|gia hạn|cấp lại|cấp|cài đặt|cài|đặt lại|reset)"

_ACCENTED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    ("lost_device", rf"\b{_LOSS_VERB}\s+(?:cái\s+|chiếc\s+)?{_DEVICE}\b"),
    ("lost_device", rf"\b{_DEVICE}\b[^.!?\n]{{0,40}}?\b{_LOSS_AFTER}\b{_NOT_LOSS}"),
    ("revoke", rf"{_NOT_PAST}\b{_REVOKE_VERB}\s+(?:\S+\s+){{0,3}}?{_OBJECT}\b"),
    ("lock", r"(?<!mở )(?<!bị )(?<!đã )\b(?:khoá|khóa)\s+(?:hẳn|luôn|ngay|tạm thời|giúp|giùm|hộ)\b"),
    ("lock", rf"(?<!mở )(?<!bị )\b(?:khoá|khóa)\s+{_OBJECT}\s+(?:\S+\s+)?(?:giúp|giùm|hộ|ngay|luôn|hẳn|lại giúp)\b"),
    ("lock", r"\btạm khoá\b|\btạm khóa\b"),
    ("negate", rf"\b(?:đừng|thôi khỏi|khỏi cần|không muốn)\s+(?:\S+\s+)?{_ACTION_VERB}\b"),
    ("cancel", r"\b(?:huỷ|hủy|thôi|bỏ)\s+(?:cái\s+)?(?:yêu cầu|ticket|phiếu)\b"),
)
_FOLDED: Final[tuple[tuple[ReverseKind, str], ...]] = (
    ("lost_device", (rf"\b(?:lam mat|danh mat|bi mat|mat|that lac|danh roi|bo quen|de quen|bi trom|bi danh cap|bi cuop)\s+"
                     rf"(?:cai\s+|chiec\s+)?{_DEVICE_FOLDED}\b")),
    ("lost_device", (rf"\b{_DEVICE_FOLDED}\b[^.!?\n]{{0,40}}?\b(?:bi mat|da mat|lam mat|that lac|bi trom|bi danh cap|bi cuop)\b"
                     rf"{fold(_NOT_LOSS)}")),
    ("revoke", (rf"{fold(_NOT_PAST)}\b(?:thu hoi|vo hieu hoa|vo hieu|revoke|disable)\s+(?:\S+\s+){{0,3}}?"
                r"(?:vpn|chung chi|quyen|truy cap|tai khoan|tk|email|mail)\b")),
    ("lock", r"(?<!mo )(?<!bi )\bkhoa\s+(?:han|luon|tam thoi)\b"),
    ("negate", r"\b(?:thoi khoi|khoi can|khong muon)\s+(?:\S+\s+)?(?:mo khoa|gia han|cap lai|cai dat|cai|dat lai|reset)\b"),
    ("cancel", r"\b(?:huy|thoi)\s+(?:yeu cau|ticket|phieu)\b"),
)  # fmt: skip
_UNINSTALL_ACCENTED: Final = rf"{_NOT_PAST}\b(?:gỡ bỏ|gỡ cài đặt|gỡ|uninstall|remove|xoá|xóa)\b(?!\s*(?:lỗi|rối|khoá|khóa))"
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
