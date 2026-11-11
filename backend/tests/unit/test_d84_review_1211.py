"""Soát 12/11 03:50 (subagent theo lệnh TA, "nêu ca chưa nghĩ tới"): 133 câu viết khác hẳn câu đã có — trước khi sửa bộ dò bỏ lọt
63/71 câu nên chuyển người và bắt nhầm 38/48 câu thường (gồm "Tài khoản bị tạm khoá do nhập sai, mở giúp em", "Tắt VPN đi bật lại
vẫn lỗi", "gửi mật khẩu tạm qua Zalo"). Sau sửa: bỏ lọt 2 (một câu địa chỉ Gmail bị che trước khi tới bộ dò — không làm được ở
đây; "Chỉ để quyền đọc thôi, bỏ ghi đi"), bắt nhầm 0. Test giữ cả hai chiều để lần sửa sau không làm hỏng lại."""

import pytest
from app.domain.personal_account import personal_account_mentioned
from app.domain.reverse_action import reverse_action_kind

# (câu, intent) — NÊN chuyển người (thao tác ngược, sự cố an ninh, tài khoản dịch vụ ngoài)
SHOULD_FLAG = [
    # bộ giữ lại thứ hai 04:42 (20 câu): bỏ lọt 1/10, bắt nhầm 1/10 — thêm vào đây
    ("pass mail cty của em lộ rồi", "account"),
    # bộ giữ lại 04:25 (30 câu ĐP viết, chưa dùng để sửa): đo được bỏ lọt 2/15, bắt nhầm 0/15 — hai câu lọt nay thêm vào đây
    ("tài khoản email bị người ta chiếm rồi anh ơi", "account"),
    ("Em bấm nhầm vào link lạ trong email rồi", "account"),
    # câu TRẢ LỜI ở bước hỏi lại (clarify_wait dùng cùng bộ dò)
    ("LAP-0417, mà thôi khỏi", "vpn"),
    ("LAP-0417 nhưng không gia hạn đâu nhé, chỉ check hạn thôi", "vpn"),
    ("LAP-0417, khoan đã đừng làm gì", "vpn"),
    ("email ạ, nhưng thôi đừng reset", "account"),
    ("Mật khẩu VPN của em bị lộ", "vpn"),
    ("pass email e bi lo", "account"),
    ("khoa tai khoan nv006 lai", "account"),
    ("tam khoa tk email cua e", "account"),
    ("go cai dat teamviewer", "software"),
    ("e lam mat dt roi, reset mk email gap giup e", "account"),
    (
        "Hôm qua em bị cướp giật điện thoại, trong đó có app xác thực, đặt lại mật khẩu giúp em",
        "account",
    ),
    ("LAP-0610 của em bị đánh cắp hôm qua, xử lý VPN máy đó giúp em", "vpn"),
    ("LAP-0610 bị trộm rồi, chứng chỉ VPN trên máy đó làm sao ạ", "vpn"),
    ("e mất con lap r, cert vpn trên đó xử lý sao ạ", "vpn"),
    ("Laptop công ty em bị kẻ gian lấy mất trong quán cà phê", "vpn"),
    (
        "em không tìm thấy laptop đâu nữa, chắc rơi ở sân bay, VPN trên máy đó còn dùng được",
        "vpn",
    ),
    ("Em bị móc túi mất điện thoại có cài Authenticator", "account"),
    ("may tinh cty cua e bi mat trom roi", "vpn"),
    ("laptop e bi lay mat roi, gia han cert vpn cho may moi", "vpn"),
    ("Mình để quên MacBook trên taxi, đổi mật khẩu AD giúp mình", "account"),
    ("Mật khẩu email của em bị lộ rồi, đặt lại giúp em", "account"),
    ("mk email cua e bi lo r, reset giup", "account"),
    (
        "Ai đó đã đổi mật khẩu email của em, em không vào được nữa, đặt lại giúp",
        "account",
    ),
    (
        "Có email phishing giả IT bảo em đăng nhập, em lỡ điền mật khẩu rồi, đổi giúp em",
        "account",
    ),
    (
        "Tài khoản email em đang tự gửi spam hàng loạt cho khách hàng, reset mk giúp",
        "account",
    ),
    ("Outlook của em tự gửi mail lừa đảo cho cả phòng", "account"),
    ("account của em bị login từ Trung Quốc lúc 3h sáng", "account"),
    ("Có người lạ đang dùng tk của em", "account"),
    ("tk e bi hach roi, doi mk giup", "account"),
    ("email của em bị xâm phạm, đổi mật khẩu giúp", "account"),
    ("em bi lua dua ma OTP cho nguoi goi tu xung IT", "account"),
    (
        "Em vừa click vào link lạ trong mail, giờ máy chạy rất chậm, đổi mk giúp em",
        "account",
    ),
    (
        "Máy em hiện popup đòi tiền chuộc, file bị đổi đuôi hết, cài lại Office giúp em",
        "software",
    ),
    ("Laptop có con trojan, cài lại phần mềm diệt virus giúp em", "software"),
    ("Máy em bị cài keylogger, em vừa gõ mật khẩu AD xong, đặt lại giúp em", "account"),
    ("nghi bị lộ pass AD, đổi giúp e", "account"),
    ("Em chuyển phòng rồi, gỡ hết quyền thư mục finance của em", "access"),
    ("Cho em trả lại quyền ghi thư mục hr/salaries", "access"),
    ("Đổi quyền thư mục sales của em thành chỉ đọc", "access"),
    ("em ko cần quyền ghi folder sales nữa", "access"),
    ("k cần gia hạn vpn nữa đâu", "vpn"),
    ("Cắt quyền truy cập ổ chung của em", "access"),
    ("Rút chứng chỉ VPN trên LAP-0610 giúp em", "vpn"),
    ("huy chung chi vpn may LAP-0610", "vpn"),
    ("xoa quyen truy cap thu muc finance cua nv004", "access"),
    ("revoke cert máy LAP-0610", "vpn"),
    ("turn off VPN trên máy LAP-0342 giúp em", "vpn"),
    ("Block VPN của máy LAP-0610 lại", "vpn"),
    ("Chặn tài khoản của nv006 lại, bạn ấy nghỉ rồi", "account"),
    ("Khoá tạm tài khoản AD của em trong lúc em đi công tác", "account"),
    ("lock tk AD của em lại", "account"),
    ("khoa tk email cua e lai giup", "account"),
    ("Em nghỉ phép 2 tháng, tạm ngưng tài khoản ERP giúp em", "account"),
    ("Disable tài khoản ERP của em", "account"),
    ("xoa zoom tren may em", "software"),
    ("go zoom khoi may LAP-0342", "software"),
    ("Bỏ cài đặt TeamViewer giúp em", "software"),
    ("Em không dùng Zoom nữa, dọn khỏi máy giúp", "software"),
    ("uninstal teamviewer giup e", "software"),
    ("Em đổi ý rồi, không gia hạn nữa", "vpn"),
    ("Khỏi reset mk nha, em nhớ ra rồi", "account"),
    ("Thôi, em nhớ ra mật khẩu rồi", "account"),
    ("Bỏ qua yêu cầu cài Zoom đi", "software"),
    ("cancel ticket giúp em", "software"),
    ("Huỷ giúp em cái ticket vừa tạo", "vpn"),
    ("Rút lại yêu cầu cấp quyền nhé", "access"),
    ("ko can nua a", "vpn"),
    ("Không cần cài nữa đâu", "software"),
    ("e k muốn gia hạn đâu", "vpn"),
    ("Đặt lại mk google giúp em", "account"),
    ("reset mật khẩu gg giúp em", "account"),
    ("Tài khoản Microsoft cá nhân của em bị khoá", "account"),
    ("Đặt lại mk tài khoản ngân hàng VCB giúp e", "account"),
    ("Tài khoản Youtube của em bị khoá", "account"),
    ("reset pass insta giúp e", "account"),
    ("quên mật khẩu mail cá nhân đuôi @yahoo.com", "account"),
    ("Mở khóa tài khoản Grab giúp em", "account"),
    ("quen mk g-mail", "account"),
]

# (câu, intent) — câu thường, KHÔNG được chuyển người
MUST_PASS = [
    ("Email công ty em không nhận được thư từ Gmail của khách", "account"),
    ("Mật khẩu không bị lộ ra khi gõ chứ?", "account"),
    ("Làm sao để mật khẩu không bị lộ?", "account"),
    # tên người "Huy" trong bản bỏ dấu (bộ đánh giá cong5), câu hỏi phòng ngừa
    ("Nhờ cấp cho bạn Huy (nv021) quyền sửa thư mục marketing/campaign trong một tháng.", "access"),
    ("Nho cap cho ban Huy (nv021) quyen sua thu muc marketing", "access"),
    ("anh Huy gui yeu cau cap quyen roi", "access"),
    ("Em lỡ nhập sai mật khẩu nhiều lần nên bị khoá", "account"),
    ("Không tìm thấy máy in trong danh sách, cài driver giúp em", "software"),
    ("Em để quên laptop ở nhà, cấp VPN tạm cho máy mượn giúp em", "vpn"),
    ("Laptop em bị mất luôn icon VPN ở thanh taskbar", "vpn"),
    ("Máy tính bị mất ngay biểu tượng VPN sau khi update", "vpn"),
    ("Em bị mất quyền truy cập thư mục finance, cấp lại giúp", "access"),
    ("Máy em bị mất dữ liệu sau khi cập nhật, cài lại Office giúp", "software"),
    ("Tài khoản bị tạm khoá do nhập sai, mở giúp em", "account"),
    ("Mở khoá giúp em, tài khoản khoá hẳn rồi", "account"),
    ("Em gõ mật khẩu nhiều lần nên nó khoá luôn rồi, mở giúp em", "account"),
    ("Tài khoản em bị khoá, khoá luôn từ sáng tới giờ, mở giúp em", "account"),
    ("tk e bi khoa tam thoi, mo giup", "account"),
    ("Sếp thu hồi quyền ghi của em hôm qua, giờ em cần lại", "access"),
    ("Hệ thống tự thu hồi quyền sau 30 ngày à? gia hạn giúp em", "access"),
    ("Em bị IT hạ quyền xuống chỉ đọc, cấp lại quyền ghi giúp", "access"),
    ("Xoá chứng chỉ VPN cũ đi rồi cấp lại cái mới giúp em", "vpn"),
    ("Chứng chỉ VPN bị thu hồi rồi, cấp lại giúp em", "vpn"),
    ("Tắt VPN đi bật lại vẫn lỗi", "vpn"),
    ("Em đã thử tắt VPN rồi bật lại mà vẫn không vào được", "vpn"),
    ("Em phải tắt VPN mới in được, có cách nào không", "vpn"),
    ("ngắt vpn ra rồi kết nối lại vẫn báo lỗi 809", "vpn"),
    ("VPN cứ tắt rồi bật lại, gia hạn chứng chỉ giúp em", "vpn"),
    ("Xoá bớt file trong ổ C để có chỗ cài AutoCAD", "software"),
    ("Cài Zoom giúp em, máy báo phải gỡ bản cũ trước", "software"),
    ("Có cần gỡ bản cũ trước khi cài Office 365 không?", "software"),
    ("Hướng dẫn em cách gỡ Zoom với", "software"),
    ("Em xoá cache rồi mà Teams vẫn lỗi, cài lại giúp", "software"),
    ("Phần mềm Zoom bị lỗi, em gõ lệnh cài lại không được", "software"),
    ("Đừng quên cài Zoom giúp em nhé", "software"),
    ("Đừng quên gia hạn VPN cho em nhé", "vpn"),
    ("Em không cần cài gì nữa, chỉ cần cấp quyền đọc thư mục sales", "access"),
    ("Em không muốn cài lại Windows, chỉ cần cài Zoom", "software"),
    ("Đừng lo, cài Zoom giúp em là được", "software"),
    ("Phiếu yêu cầu cấp quyền của em đến đâu rồi?", "access"),
    ("Em hủy cuộc họp nên giờ rảnh, cài Zoom giúp em", "software"),
    ("Có ai biết mật khẩu wifi khách không?", "account"),
    ("co ai biet mk wifi tang 3 ko", "account"),
    ("Em có nên đổi mật khẩu định kỳ để tránh bị hack không?", "account"),
    ("Làm sao để không bị lộ mật khẩu?", "account"),
    ("Cài Kaspersky để phòng nhiễm virus giúp em", "software"),
    ("Cài antivirus để máy khỏi dính virus", "software"),
    ("Em đăng nhập từ máy lạ (máy mượn) được không?", "account"),
    ("Cài phần mềm chống mã độc cho em", "software"),
    ("Reset mk email công ty giúp em, gửi mật khẩu tạm qua Zalo cho em nhé", "account"),
    ("Đặt lại mật khẩu AD giúp em, em không có Zalo để nhận mã", "account"),
    (
        "Đăng nhập email công ty trên app Gmail của điện thoại báo sai mật khẩu, đặt lại giúp",
        "account",
    ),
    ("Em fb lại là mật khẩu AD vẫn bị khoá, mở giúp em", "account"),
    ("Không nhận được mã OTP qua Zalo khi đặt lại mật khẩu AD", "account"),
    (
        "Mở khoá tài khoản AD giúp em, em gọi hotline qua Messenger không ai nghe",
        "account",
    ),
    ("Đặt lại mật khẩu ERP giúp em, em cần đối soát đơn Shopee gấp", "account"),
]


def _flagged(text: str, intent: str) -> bool:
    return reverse_action_kind(
        text, {intent}
    ) is not None or personal_account_mentioned(text, {intent})


@pytest.mark.parametrize(("text", "intent"), SHOULD_FLAG)
def test_review_should_flag(text: str, intent: str) -> None:
    assert _flagged(text, intent)


@pytest.mark.parametrize(("text", "intent"), MUST_PASS)
def test_review_must_pass(text: str, intent: str) -> None:
    assert not _flagged(text, intent)
