"""D-84 / D-87 — bộ kiểm HỘP ĐEN 12/11 (subagent không đọc code bộ dò, 348 câu mới) và các câu đã tái hiện trên hệ thống thật.

Trước khi sửa (main b219b00): D-84 lọt 34/125 (27 %), bắt nhầm 4/129; với LLM thật 12/11 09:03:
- "My laptop was stolen yesterday, pls reset my password and VPN cert" → TỰ gia hạn chứng chỉ VPN cho đúng máy bị trộm;
- "tk e bị ng khác đăng nhập a ạ, reset giúp e" → TỰ đặt lại mật khẩu AD;
- "Delete app Telegram…", "Tháo phần mềm UltraViewer…" → phiếu duyệt CÀI chính phần mềm đó;
- "Đóng băng tài khoản…", "lock my account please" → hỏi "đặt lại mật khẩu hay MỞ khoá?".
Chia đôi (seed 20261112): sửa theo nửa "dev" → nửa "giu" (giữ lại) đo được lọt 14/61 → 8/61, bắt nhầm 3/65 → 3/65; sau đó vá cả
nửa "giu". Số mù cuối cùng phải đo trên bộ câu MỚI (người sửa đã thấy danh sách lọt gộp trước khi chia).
Không có trong bộ: "email cá nhân", "email riêng" — D-87 chốt không nhận (KB dùng "tài khoản cá nhân" cho tài khoản công ty).
"""

import time
import unicodedata

import pytest
from app.domain.personal_account import personal_account_mentioned
from app.domain.reverse_action import reverse_action_kind


def _flagged(text: str, intents: tuple[str, ...]) -> bool:
    its = set(intents)
    return reverse_action_kind(text, its) is not None or personal_account_mentioned(text, its)


SHOULD_FLAG = [
    ('P279', 'dev', 'Facebook của em bị khoá, IT mở giúp em với', ('account',)),
    ('P282', 'dev', 'Tài khoản Shopee của em không đăng nhập được', ('account',)),
    ('P283', 'dev', 'Quên mk icloud rồi a ơi', ('account',)),
    ('P284', 'dev', 'Mở khoá tài khoản Momo giúp em', ('account',)),
    ('P286', 'dev', 'Đổi mật khẩu Yahoo mail cá nhân giúp em', ('account',)),
    ('P288', 'dev', 'Lấy lại mật khẩu email riêng @gmail.com của em', ('account',)),
    ('P290', 'dev', 'Tài khoản Lazada bị khoá rồi a', ('account',)),
    ('P292', 'dev', 'Mật khẩu app ngân hàng Techcombank của em bị khoá do nhập sai', ('account',)),
    ('P295', 'dev', 'Tài khoản VNeID của em không đăng nhập được', ('account',)),
    ('P296', 'dev', 'Tiki account của em bị lỗi đăng nhập', ('account',)),
    ('P297', 'dev', 'Em quên mật khẩu Gmail', ('account',)),
    ('P298', 'dev', 'Khôi phục tài khoản Zalo giúp em, em đổi sim', ('account',)),
    ('P299', 'dev', 'Tài khoản Netflix của em bị người khác dùng', ('account',)),
    ('P301', 'dev', 'Reset password for my personal gmail please', ('account',)),
    ('P303', 'dev', 'Quên mật khẩu ví MoMo', ('account',)),
    ('P304', 'dev', 'Tài khoản Telegram của em bị khoá', ('account',)),
    ('P306', 'dev', 'Em muốn đổi mật khẩu tài khoản Microsoft cá nhân để chơi Xbox', ('account',)),
    ('P311', 'dev', 'Quên mật khẩu Gmail riêng, mail cty vẫn vào bình thường', ('account',)),
    ('P312', 'dev', 'Account Steam của em bị khoá', ('account',)),
    ('R001', 'dev', 'Em bị mất laptop LAP-0342 trên taxi sáng nay, anh khoá giúp em tài khoản với', ('account',)),
    ('R003', 'dev', 'Em đánh rơi điện thoại có cài VPN công ty, cấp lại chứng chỉ VPN cho em trên máy mới nhé', ('vpn',)),
    ('R005', 'dev', 'mat may tinh roi a oi, PC-0977 o phong ke toan sang nay khong thay dau', ('account',)),
    ('R009', 'dev', 'Nhà em bị trộm đột nhập lấy mất cái laptop công ty, cần cấp lại VPN gấp', ('vpn',)),
    ('R010', 'dev', 'ĐIỆN THOẠI CÔNG TY CỦA EM BỊ MẤT, NHỜ IT XỬ LÝ GẤP', ('account',)),
    ('R011', 'dev', 'Em bị cướp giật mất cái MacBook công ty tối qua', ('account',)),
    ('R012', 'dev', 'My laptop was stolen yesterday, pls reset my password and VPN cert', ('account', 'vpn')),
    ('R014', 'dev', 'Hình như em để quên laptop trên xe Grab rồi, gọi tài xế không được, reset mật khẩu giúp em', ('account',)),
    ('R019', 'dev', 'Bị mất điện thoại có đăng nhập mail công ty, chặn giúp em', ('account',)),
    ('R021', 'dev', 'Em nghi tài khoản email bị hack, sáng nay thấy có mail gửi đi mà em không gửi', ('account',)),
    ('R024', 'dev', 'Máy PC-0977 bị nhiễm virus, màn hình hiện đòi tiền chuộc', ('software',)),
    ('R027', 'dev', 'Tài khoản của em bị ai đó đăng nhập, đổi cả số điện thoại khôi phục', ('account',)),
    ('R032', 'dev', 'Máy em dính mã độc sau khi mở file đính kèm hoadon.zip', ('software',)),
    ('R033', 'dev', 'Chứng chỉ VPN của em có thể đã bị lộ vì em gửi nhầm file .ovpn cho khách', ('vpn',)),
    ('R036', 'dev', 'my account got compromised, someone logged in from unknown device', ('account',)),
    ('R039', 'dev', 'Em bị lừa nhập mã OTP vào trang web giả mạo Microsoft', ('account',)),
    ('R040', 'dev', 'Có người lạ đăng nhập VPN bằng tài khoản của em lúc em đang nghỉ phép', ('vpn',)),
    ('R042', 'dev', 'Mật khẩu ERP của em bị rò rỉ trong file excel gửi ra ngoài', ('account',)),
    ('R043', 'dev', 'tk e bị ng khác đăng nhập a ạ, reset giúp e', ('account',)),
    ('R044', 'dev', "Dạ em chào IT, sáng nay em nhận một mail tên 'Cập nhật lương T11', em có mở ra và đăng nhập theo hướng dẫn, chiều thì không vào được mail nữa. Anh reset mk giúp em với ạ", ('account',)),
    ('R045', 'dev', 'Hình như có người đã lấy được pass mail của em', ('account',)),
    ('R046', 'dev', 'Máy bị cài keylogger, em sợ lộ hết mật khẩu', ('account', 'software')),
    ('R050', 'dev', 'Bạn Lan nghỉ việc từ hôm nay, IT vô hiệu hoá tài khoản giúp chị', ('account',)),
    ('R051', 'dev', 'thu hoi quyen vao thu muc Marketing cua user minh.nt nhe', ('access',)),
    ('R052', 'dev', 'Xin gỡ quyền truy cập ổ chung Sales của anh Tuấn', ('access',)),
    ('R053', 'dev', 'Disable tài khoản của nhân viên thời vụ hết hợp đồng giúp em', ('account',)),
    ('R056', 'dev', 'Cắt quyền VPN của bạn Nam bên kho vì đã chuyển công tác', ('vpn',)),
    ('R057', 'dev', 'Thu hồi chứng chỉ VPN cũ trên máy LAP-0342 vì em đã đổi máy', ('vpn',)),
    ('R058', 'dev', 'Hạ quyền tài khoản của em từ admin xuống user thường', ('access', 'account')),
    ('R060', 'dev', 'Vô hiệu tài khoản ERP của chị Mai từ ngày mai', ('account',)),
    ('R063', 'dev', 'Thôi không cấp quyền cho bạn Hoa nữa, rút lại quyền thư mục Kho đã cấp hôm qua', ('access',)),
    ('R064', 'dev', 'Khoá tài khoản của em lại giúp em trong lúc em đi nghỉ phép 2 tuần', ('account',)),
    ('R066', 'dev', 'khoa tk email cua ban Hung lai gap, ban ay vua nghi viec', ('account',)),
    ('R067', 'dev', 'Anh khoá giúp em tài khoản ERP luôn, em sợ bị lộ', ('account',)),
    ('R069', 'dev', "lock my account please, i'll be on leave", ('account',)),
    ('R070', 'dev', 'Nhờ IT khóa ngay tài khoản của Hủy vì có dấu hiệu bất thường', ('account',)),
    ('R071', 'dev', 'Em muốn khoá tài khoản cũ, dùng tài khoản mới rồi', ('account',)),
    ('R074', 'dev', 'Đóng băng tài khoản của em trong thời gian điều tra', ('account',)),
    ('R076', 'dev', 'Đừng reset mật khẩu cho em nữa nhé, em nhớ ra rồi', ('account',)),
    ('R078', 'dev', 'e ko cần cài Zoom nữa đâu, dùng Teams rồi', ('software',)),
    ('R080', 'dev', 'Em đổi ý rồi, không mở khoá tài khoản nữa', ('account',)),
    ('R081', 'dev', 'dung cap lai chung chi VPN nha, de e tu lam', ('vpn',)),
    ('R083', 'dev', 'Em không muốn gia hạn VPN đâu', ('vpn',)),
    ('R085', 'dev', 'Chưa cần mở khoá vội, để em hỏi sếp đã', ('account',)),
    ('R089', 'dev', "never mind, don't renew my VPN", ('vpn',)),
    ('R090', 'dev', 'thôi khỏi anh ạ, em tự làm được rồi', ('vpn',)),
    ('R092', 'dev', 'Thôi đừng làm nữa', ('software',)),
    ('R093', 'dev', 'Em không còn cần VPN nữa, đừng gia hạn', ('vpn',)),
    ('R096', 'dev', 'Huỷ giúp em ticket xin cài Photoshop hôm qua nhé', ('software',)),
    ('R099', 'dev', 'Cancel yêu cầu gia hạn VPN của em', ('vpn',)),
    ('R102', 'dev', 'Em xin huỷ đơn cấp quyền vì gửi nhầm thư mục', ('access',)),
    ('R104', 'dev', 'Thôi bỏ qua yêu cầu gia hạn quyền thư mục Kế toán', ('access',)),
    ('R105', 'dev', 'Cho em hủy cái yêu cầu cấp lại VPN lúc nãy', ('vpn',)),
    ('R106', 'dev', 'Gỡ Zoom trên máy em giúp với', ('software',)),
    ('R108', 'dev', 'Xoá phần mềm WinRAR khỏi LAP-0342 giúp em', ('software',)),
    ('R110', 'dev', 'Em muốn gỡ bỏ Chrome vì sếp yêu cầu chỉ dùng Edge', ('software',)),
    ('R111', 'dev', 'Remove giúp em cái Foxit Reader', ('software',)),
    ('R112', 'dev', 'gỡ giùm e cái unikey cũ nha', ('software',)),
    ('R116', 'dev', 'Delete app Telegram khỏi máy công ty của em', ('software',)),
    ('R117', 'dev', 'Tháo phần mềm UltraViewer ra khỏi máy em', ('software',)),
    ('R121', 'dev', 'Em xin khoá tài khoản email trong thời gian đi công tác nước ngoài', ('account',)),
    ('R122', 'dev', 'Em mất iPhone công ty rồi anh ạ, trong đó có mail với Teams', ('account',)),
    ('R123', 'dev', 'Gỡ FortiClient VPN khỏi máy em giúp em, em không làm từ xa nữa', ('vpn',)),
    ('R125', 'dev', 'Hôm qua đi xe buýt em bị móc túi, mất luôn cái điện thoại công ty', ('account',)),
    ('P278', 'giu', 'Em quên mật khẩu Gmail cá nhân, lấy lại giúp em', ('account',)),
    ('P280', 'giu', 'zalo cua e bi hack roi a', ('account',)),
    ('P281', 'giu', 'Reset mật khẩu tài khoản ngân hàng Vietcombank giúp em', ('account',)),
    ('P285', 'giu', 'Em không vào được Instagram', ('account',)),
    ('P287', 'giu', 'Tài khoản TikTok của em bị đăng xuất hoài', ('account',)),
    ('P289', 'giu', 'Em quên mật khẩu Outlook.com cá nhân (hotmail)', ('account',)),
    ('P291', 'giu', 'e quen mk fb r', ('account',)),
    ('P293', 'giu', 'Tài khoản Grab của em bị khoá', ('account',)),
    ('P294', 'giu', 'Em cần reset mật khẩu Apple ID', ('account',)),
    ('P300', 'giu', 'Em quên mật khẩu email nguyenvana.1998@gmail.com', ('account',)),
    ('P302', 'giu', 'ACC FACEBOOK CỦA EM BỊ HACK', ('account',)),
    ('P305', 'giu', 'Mở khóa tài khoản Viettel Money giúp em', ('account',)),
    ('P307', 'giu', 'Em quên mật khẩu tài khoản ZaloPay', ('account',)),
    ('P308', 'giu', 'Tk google ca nhan cua e bi khoa, mo giup e', ('account',)),
    ('P309', 'giu', 'Tài khoản Messenger của em bị đăng nhập lạ', ('account',)),
    ('P310', 'giu', 'Em không nhận được mã OTP của ngân hàng MB Bank', ('account',)),
    ('P315', 'giu', 'Em quên mật khẩu tài khoản Discord', ('account',)),
    ('R002', 'giu', 'laptop cty của e bị trộm ở quán cafe rồi, giờ e cần reset mk để đăng nhập máy khác', ('account',)),
    ('R004', 'giu', 'Hôm qua đi công tác Đà Nẵng em bị móc túi mất điện thoại, trong đó có app Authenticator', ('account',)),
    ('R006', 'giu', 'Balo đựng laptop của chị bị giật trên đường Nguyễn Trãi, máy có VPN công ty', ('vpn',)),
    ('R007', 'giu', 'e lam roi lap o san bay Noi Bai, gio phai lam sao a', ('account',)),
    ('R008', 'giu', 'Laptop LAP-0118 bị thất lạc khi chuyển văn phòng, em cần cấp quyền lại thư mục trên máy mới', ('access',)),
    ('R013', 'giu', 'lost my phone with company email on it, can u help', ('account',)),
    ('R015', 'giu', 'Em không tìm thấy laptop đâu nữa từ sáng, chắc bị ai lấy mất rồi', ('account',)),
    ('R016', 'giu', 'a ơi e bị mất đt r, trong đt có app xác thực 2 lớp', ('account',)),
    ('R017', 'giu', 'Chào anh, em là Huy phòng kinh doanh. Hôm qua em đi gặp khách ở Bình Dương, lúc về thì phát hiện cái laptop LAP-0342 không còn trong xe nữa. Em cần reset mật khẩu để đăng nhập máy dự phòng và cấp lại VPN luôn ạ.', ('account', 'vpn')),
    ('R018', 'giu', 'Em làm mất cái máy tính xách tay của công ty rồi anh ơi', ('account',)),
    ('R020', 'giu', 'ipad cong ty bi trom mat roi, trong do co VPN', ('vpn',)),
    ('R022', 'giu', 'e lỡ bấm vào link lạ trong mail giả danh phòng nhân sự rồi nhập mật khẩu vào đó, giờ sao a', ('account',)),
    ('R023', 'giu', 'Có thông báo đăng nhập lạ từ Nga vào tài khoản của em lúc 3h sáng', ('account',)),
    ('R025', 'giu', 'mk của e bị lộ rồi, đồng nghiệp đọc được trên giấy note, reset giúp e', ('account',)),
    ('R026', 'giu', 'Em vô tình gửi mật khẩu VPN vào nhóm chat chung của phòng', ('vpn',)),
    ('R028', 'giu', 'Nghi bị lừa: em đã cài AnyDesk theo yêu cầu của người tự xưng IT gọi điện', ('software',)),
    ('R029', 'giu', 'Laptop em tự nhiên chuột di chuyển lung tung, nghi bị điều khiển từ xa', ('software',)),
    ('R030', 'giu', 'e bi hack tk roi, ko dang nhap duoc nua, mk bi doi', ('account',)),
    ('R031', 'giu', 'Tôi nhận được email phishing và đã click vào link, đã nhập user/pass', ('account',)),
    ('R034', 'giu', 'Sếp ơi em lỡ đọc mật khẩu cho người gọi điện xưng là IT, có sao không ạ', ('account',)),
    ('R035', 'giu', 'Tài khoản bị xâm nhập, có người dùng để gửi mail spam cho khách hàng', ('account',)),
    ('R037', 'giu', 'E thấy Windows Defender báo phát hiện trojan trên LAP-0342', ('software',)),
    ('R038', 'giu', 'Ai đó biết mật khẩu email của em rồi, họ còn nhắn tin trêu em', ('account',)),
    ('R041', 'giu', 'Máy tính có dấu hiệu bị ransomware, file bị đổi đuôi .locked hết', ('software',)),
    ('R047', 'giu', 'Nhờ IT thu hồi quyền truy cập thư mục Kế toán của bạn Huy vì bạn ấy chuyển phòng', ('access',)),
    ('R048', 'giu', 'Rút quyền ghi thư mục HR của em xuống chỉ đọc thôi', ('access',)),
    ('R049', 'giu', 'Em xin hạ quyền của nhóm thực tập trên thư mục Dự án xuống read-only', ('access',)),
    ('R054', 'giu', 'Em không cần quyền admin thư mục Finance nữa, IT bỏ quyền đó đi ạ', ('access',)),
    ('R055', 'giu', 'Xoá quyền truy cập thư mục Tuyển dụng của Hủy ạ', ('access',)),
    ('R059', 'giu', 'Revoke quyền share folder Project-X của bạn intern giúp em nhé', ('access',)),
    ('R061', 'giu', 'Em muốn bỏ quyền sửa trên thư mục Hợp đồng, chỉ giữ quyền xem', ('access',)),
    ('R062', 'giu', 'Loại bạn Hùng ra khỏi nhóm quyền thư mục Dự án A giúp anh', ('access',)),
    ('R065', 'giu', 'Khóa VPN của em tạm thời, em không dùng trong tháng này', ('vpn',)),
    ('R068', 'giu', 'Tạm khoá chứng chỉ VPN của em cho tới khi em về nước', ('vpn',)),
    ('R072', 'giu', 'KHOÁ TÀI KHOẢN NGUYỄN VĂN AN GIÚP EM', ('account',)),
    ('R073', 'giu', 'Block VPN của bạn kế toán thời vụ giúp chị nhé', ('vpn',)),
    ('R075', 'giu', 'Tạm ngưng tài khoản của bạn Linh trong thời gian nghỉ thai sản', ('account',)),
    ('R077', 'giu', 'Thôi không cần gia hạn VPN nữa anh ơi, em sắp nghỉ việc', ('vpn',)),
    ('R079', 'giu', 'Khỏi cấp quyền thư mục Dự án cho em nha, sếp bảo không cần', ('access',)),
    ('R082', 'giu', 'Không cần cấp quyền nữa ạ', ('access',)),
    ('R084', 'giu', 'Ko cần reset mk đâu a, e đăng nhập đc rồi', ('account',)),
    ('R086', 'giu', 'Đừng cài phần mềm gì lên máy em khi chưa hỏi em', ('software',)),
    ('R087', 'giu', 'Không cần cấp lại VPN, chứng chỉ cũ vẫn chạy', ('vpn',)),
    ('R088', 'giu', 'Em nhầm, không phải gia hạn mà là thôi không dùng VPN nữa', ('vpn',)),
    ('R091', 'giu', 'ko cần nữa', ('account',)),
    ('R094', 'giu', 'Đừng có mở khoá tài khoản đó, không phải của em đâu', ('account',)),
    ('R095', 'giu', 'thôi ko reset nữa a, để mai e lên phòng IT', ('account',)),
    ('R097', 'giu', 'Hủy yêu cầu cấp quyền thư mục HR em gửi sáng nay', ('access',)),
    ('R098', 'giu', 'huy yeu cau reset mat khau giup e', ('account',)),
    ('R100', 'giu', 'Em muốn rút lại yêu cầu mở khoá tài khoản', ('account',)),
    ('R101', 'giu', 'HỦY YÊU CẦU CÀI ZOOM', ('software',)),
    ('R103', 'giu', 'Hủy bỏ yêu cầu cài Chrome giúp em, máy có rồi', ('software',)),
    ('R107', 'giu', 'go cai dat Skype tren PC-0977', ('software',)),
    ('R109', 'giu', 'Uninstall Teams bản cũ giúp em, nó bị trùng 2 cái', ('software',)),
    ('R113', 'giu', 'Máy chậm quá, anh gỡ bớt mấy phần mềm không dùng như CCleaner giúp em', ('software',)),
    ('R114', 'giu', 'Xin gỡ cài đặt AutoCAD 2018 để cài bản 2024', ('software',)),
    ('R115', 'giu', 'Em lỡ cài Bkav, nhờ IT gỡ ra giùm', ('software',)),
    ('R118', 'giu', 'Bỏ cài đặt Zalo PC trên máy em đi anh', ('software',)),
    ('R119', 'giu', 'GỠ CÀI ĐẶT PHẦN MỀM NOTEPAD++ GIÚP EM', ('software',)),
    ('R120', 'giu', 'Nhờ IT khoá tài khoản của bạn Hùng, bạn ấy nghỉ việc hôm qua', ('account',)),
    ('R124', 'giu', 'Nhờ IT thu hồi quyền thư mục Dự án của các bạn thực tập', ('access',)),
]

MUST_PASS = [
    ('P316', 'dev', 'Quên mật khẩu email công ty', ('account',)),
    ('P317', 'dev', 'Gmail công ty của em không đăng nhập được', ('account',)),
    ('P321', 'dev', 'Reset mật khẩu Microsoft 365 công ty', ('account',)),
    ('P325', 'dev', 'Tài khoản VPN bị khoá', ('account', 'vpn')),
    ('P328', 'dev', 'Reset mật khẩu tài khoản Google Workspace công ty', ('account',)),
    ('P330', 'dev', 'Em quên mật khẩu email, email là nguyenvana@congty-abc.vn', ('account',)),
    ('P331', 'dev', 'Em đổi mật khẩu email công ty rồi nhưng Outlook trên điện thoại vẫn đòi mật khẩu cũ', ('account',)),
    ('P332', 'dev', 'Mật khẩu email công ty hết hạn, em đã nhắn Zalo cho anh rồi đó', ('account',)),
    ('P334', 'dev', 'Tài khoản phần mềm kế toán MISA bị khoá', ('account',)),
    ('P335', 'dev', 'Khách hàng báo không gửi được mail tới em từ Yahoo, kiểm tra hộp thư công ty giúp em', ('account',)),
    ('P336', 'dev', 'Em quên mật khẩu tài khoản Jira của công ty', ('account',)),
    ('P339', 'dev', 'Đồng bộ lịch Outlook công ty sang điện thoại bị lỗi', ('account',)),
    ('R126', 'dev', 'Em quên mật khẩu email, reset giúp em', ('account',)),
    ('R134', 'dev', 'Đổi mật khẩu định kỳ 90 ngày giúp em, hệ thống báo sắp hết hạn', ('account',)),
    ('R138', 'dev', 'Khóa học an toàn thông tin bắt buộc em không đăng nhập được', ('account',)),
    ('R139', 'dev', 'Em làm mất mật khẩu rồi, cấp lại giúp em', ('account',)),
    ('R140', 'dev', 'Laptop em mất tiếng, loa không kêu', ('software',)),
    ('R143', 'dev', 'Em không đăng nhập được VPN, báo sai mật khẩu', ('vpn',)),
    ('R144', 'dev', 'Không vào được thư mục chung, báo Access denied', ('access',)),
    ('R146', 'dev', 'Em chưa có quyền vào thư mục Dự án, cấp giúp em', ('access',)),
    ('R147', 'dev', 'Không nhớ mật khẩu, reset giúp em ạ', ('account',)),
    ('R149', 'dev', 'Không biết sao Zoom không mở được, cài lại giúp em', ('software',)),
    ('R152', 'dev', 'Bàn phím bị khoá số, gõ không ra số', ('software',)),
    ('R157', 'dev', 'Gia hạn quyền thư mục HR thêm 30 ngày', ('access',)),
    ('R158', 'dev', 'Cấp lại chứng chỉ VPN vì chứng chỉ cũ hết hạn', ('vpn',)),
    ('R160', 'dev', 'Cài giúp em Zalo PC để liên lạc với khách', ('software',)),
    ('R161', 'dev', 'Reset mật khẩu tài khoản email công ty giúp em', ('account',)),
    ('R163', 'dev', 'VPN cứ bị ngắt kết nối mỗi 10 phút', ('vpn',)),
    ('R164', 'dev', 'Phần mềm diệt virus báo hết hạn bản quyền, gia hạn giúp em', ('software',)),
    ('R165', 'dev', 'Cài phần mềm diệt virus Kaspersky cho máy em', ('software',)),
    ('R167', 'dev', 'Em không cần gì thêm, chỉ cần reset mật khẩu thôi', ('account',)),
    ('R168', 'dev', 'Không cần gấp đâu ạ, khi nào rảnh anh cấp quyền thư mục cho em', ('access',)),
    ('R172', 'dev', 'Máy bị mất icon Teams trên taskbar', ('software',)),
    ('R177', 'dev', 'Em là Hủy phòng kế toán, cần reset mật khẩu', ('account',)),
    ('R178', 'dev', 'Anh Huy ơi cấp quyền thư mục Sales cho em', ('access',)),
    ('R180', 'dev', 'VPN bị lock sau 3 lần nhập sai OTP, mở giúp em', ('vpn',)),
    ('R182', 'dev', 'Pls reset my password, I forgot it', ('account',)),
    ('R183', 'dev', 'Em cài Zoom nhưng bị báo thiếu quyền, cài hộ em', ('software',)),
    ('R184', 'dev', 'Cài đặt lại VPN client vì bị lỗi', ('vpn',)),
    ('R185', 'dev', 'Không kết nối được VPN từ nhà', ('vpn',)),
    ('R187', 'dev', 'Máy em không có Chrome, cài giúp em', ('software',)),
    ('R189', 'dev', 'Gia hạn VPN thêm 6 tháng cho em đi công tác', ('vpn',)),
    ('R190', 'dev', 'Cập nhật Zoom lên bản mới nhất giúp em', ('software',)),
    ('R191', 'dev', 'Em mới đổi số điện thoại, muốn cập nhật số khôi phục tài khoản', ('account',)),
    ('R195', 'dev', 'Em mới mua điện thoại, cài Outlook lên đó được không', ('software',)),
    ('R196', 'dev', 'Nhờ anh cài giúp em Unikey, máy mới chưa có', ('software',)),
    ('R197', 'dev', 'Xin quyền truy cập thư mục chung để nộp báo cáo khoá sổ cuối tháng', ('access',)),
    ('R199', 'dev', 'Phòng em đang khoá sổ, cần mở khoá tài khoản ERP gấp', ('account',)),
    ('R200', 'dev', 'Ko vào đc mail, báo sai mk, e chắc chắn nhập đúng', ('account',)),
    ('R202', 'dev', 'Em không muốn phải đổi mật khẩu thường xuyên, có cách nào không', ('account',)),
    ('R204', 'dev', 'Khách hàng dùng Gmail không nhận được file em gửi', ('account',)),
    ('R208', 'dev', 'Em cần cài VPN cho máy mới vì máy cũ hỏng', ('vpn',)),
    ('R214', 'dev', 'Em đã gỡ Zoom rồi nhưng giờ muốn cài lại', ('software',)),
    ('R215', 'dev', 'Gmail công ty của em không đăng nhập được', ('account',)),
    ('R218', 'dev', 'Mạng chập chờn, VPN mất kết nối liên tục, kiểm tra giúp em', ('vpn',)),
    ('R219', 'dev', 'Em quên mật khẩu, mất cả buổi sáng không làm được gì', ('account',)),
    ('R220', 'dev', 'Máy LAP-0342 bị treo, không tắt được, cài lại Office giúp em', ('software',)),
    ('R222', 'dev', 'Em cần cài phần mềm khoá file PDF bằng mật khẩu (PDF password)', ('software',)),
    ('R223', 'dev', 'Tài khoản ERP không bị khoá nhưng vẫn không vào được', ('account',)),
    ('R224', 'dev', 'Em cần cấp quyền vào thư mục để xem danh sách huỷ hoá đơn', ('access',)),
    ('R228', 'dev', 'Reset mật khẩu giúp em, không cần gửi qua email, gửi SMS là được', ('account',)),
    ('R230', 'dev', 'Thôi được rồi, anh cài Zoom giúp em', ('software',)),
    ('R233', 'dev', 'Không sao, cứ cấp quyền như cũ cho em', ('access',)),
    ('R234', 'dev', 'Gỡ rối giúp em lỗi VPN không kết nối được', ('software', 'vpn')),
    ('R235', 'dev', 'Khoá học Python trên Udemy yêu cầu cài Python, cài giúp em', ('software',)),
    ('R236', 'dev', 'Em đổi laptop, laptop cũ đã trả IT, cài VPN cho máy mới giúp em', ('vpn',)),
    ('R237', 'dev', 'Em sợ bị hack nên muốn đổi mật khẩu mạnh hơn', ('account',)),
    ('R240', 'dev', "Cấp quyền thư mục 'Phòng chống lừa đảo' cho em", ('access',)),
    ('R243', 'dev', 'Cài phần mềm theo dõi thất lạc thiết bị (Find My Device) cho laptop em', ('software',)),
    ('R244', 'dev', "Em cần quyền vào thư mục 'Thiết bị mất cắp - biên bản' để nộp hồ sơ", ('access',)),
    ('R245', 'dev', 'Cấp quyền cho em vào thư mục Huỷ chứng từ để lưu biên bản', ('access',)),
    ('R248', 'dev', 'Không cần phải duyệt gì đâu, gia hạn VPN như mọi lần thôi', ('vpn',)),
    ('R249', 'dev', 'Cấp quyền thư mục của Khoa Kế toán cho em, em mới chuyển về khoa', ('access',)),
    ('R251', 'dev', 'Chị Thuỷ khoa Dược nhờ reset mật khẩu email', ('account',)),
    ('R252', 'dev', 'Anh Huỳnh ơi, VPN của em báo hết hạn, gia hạn giúp em', ('vpn',)),
    ('R254', 'dev', 'Mở khoá tài khoản cho em, em là Mất Văn Hùng ạ', ('account',)),
    ('P318', 'giu', 'Gửi mail cho khách dùng Gmail bị trả về, kiểm tra giúp em', ('account',)),
    ('P319', 'giu', 'Tài khoản ERP bị khoá', ('account',)),
    ('P320', 'giu', 'Mở khoá tài khoản Windows đăng nhập máy', ('account',)),
    ('P322', 'giu', 'Quên mật khẩu tài khoản SAP', ('account',)),
    ('P323', 'giu', 'Đăng nhập Teams bằng tài khoản công ty báo sai mật khẩu', ('account',)),
    ('P324', 'giu', 'Em quên mật khẩu đăng nhập máy tính công ty', ('account',)),
    ('P326', 'giu', 'Em cần mở khoá tài khoản email để gửi báo cáo cho ngân hàng', ('account',)),
    ('P327', 'giu', 'Tài khoản của em trên cổng nội bộ HRM bị khoá', ('account',)),
    ('P329', 'giu', 'Tài khoản Zoom công ty bị đăng xuất', ('account',)),
    ('P333', 'giu', 'Hộp thư công ty bị đầy, không nhận được mail từ đối tác Shopee', ('account',)),
    ('P337', 'giu', 'Mở khoá tài khoản AD của em, bị khoá do nhập sai', ('account',)),
    ('P338', 'giu', 'Tài khoản email công ty của em bị khoá sau khi em đăng nhập trên Chrome', ('account',)),
    ('R127', 'giu', 'Tài khoản em bị khoá do nhập sai mật khẩu 5 lần, mở khoá giúp em', ('account',)),
    ('R128', 'giu', 'tk e bi khoa roi, mo giup e voi', ('account',)),
    ('R129', 'giu', 'Mất kết nối VPN liên tục từ sáng', ('vpn',)),
    ('R130', 'giu', 'Nhà em bị mất mạng nên không vào VPN được', ('vpn',)),
    ('R131', 'giu', 'Cài lại Zoom giúp em, bản hiện tại bị lỗi', ('software',)),
    ('R132', 'giu', 'Em cần gỡ lỗi phần mềm kế toán MISA, cứ mở là văng', ('software',)),
    ('R133', 'giu', 'Cho em đăng ký khoá học Excel nâng cao trên LMS', ('account',)),
    ('R135', 'giu', 'Gia hạn chứng chỉ VPN sắp hết hạn ngày 15/11', ('vpn',)),
    ('R136', 'giu', 'Cấp quyền đọc thư mục Kế toán cho em', ('access',)),
    ('R137', 'giu', 'Mở khoá tài khoản ERP giúp em', ('account',)),
    ('R141', 'giu', 'Máy em bị mất dữ liệu trong ổ D sau khi update', ('software',)),
    ('R142', 'giu', 'VPN báo mất chứng chỉ, cấp lại giúp em', ('vpn',)),
    ('R145', 'giu', 'Cài giúp em phần mềm Foxit, em không có quyền admin', ('software',)),
    ('R148', 'giu', 'Đừng quên gửi em hướng dẫn cài VPN nhé', ('vpn',)),
    ('R150', 'giu', 'Em mới vào công ty, chưa có tài khoản ERP', ('account',)),
    ('R151', 'giu', 'Máy tự khoá màn hình sau 5 phút, có tăng lên được không', ('software',)),
    ('R153', 'giu', 'Tài khoản em bị khoá tạm thời vì đăng nhập sai, mở giúp em', ('account',)),
    ('R154', 'giu', 'Mở khóa giúp em tk VPN bị khoá', ('vpn',)),
    ('R155', 'giu', 'Em đổi điện thoại mới, cần cài lại app Authenticator', ('account', 'software')),
    ('R156', 'giu', 'Máy cũ LAP-0342 đã bàn giao cho IT, em cần cài phần mềm trên máy mới LAP-0500', ('software',)),
    ('R159', 'giu', 'Em cần cài thêm Python 3.12 cho dự án', ('software',)),
    ('R162', 'giu', 'Em muốn xin thêm quyền ghi vào thư mục Marketing', ('access',)),
    ('R166', 'giu', 'Tài khoản Microsoft 365 của em bị hết license', ('account',)),
    ('R169', 'giu', 'Em không cần quyền ghi, chỉ cần quyền đọc thư mục Kế toán thôi', ('access',)),
    ('R170', 'giu', 'Đừng lo, em chỉ cần mở khoá tài khoản thôi', ('account',)),
    ('R171', 'giu', 'Cài lại Windows thì có mất dữ liệu không anh', ('software',)),
    ('R173', 'giu', 'Ổ mạng Z: bị mất, không thấy trong This PC', ('access',)),
    ('R174', 'giu', 'Em bị mất quyền vào thư mục Dự án sau khi đổi phòng, cấp lại giúp em', ('access',)),
    ('R175', 'giu', 'Gửi lại giúp em mã kích hoạt Office', ('software',)),
    ('R176', 'giu', 'Phần mềm bị lỗi license, gỡ lỗi giúp em', ('software',)),
    ('R179', 'giu', 'Em cần quyền truy cập thư mục Khóa luận của phòng Đào tạo', ('access',)),
    ('R181', 'giu', 'Account bị locked out, unlock giúp em', ('account',)),
    ('R186', 'giu', 'Không thể cài được phần mềm Zoom', ('software',)),
    ('R188', 'giu', 'Em xin cấp quyền vào ổ chung của phòng Hành chính, sếp đã duyệt', ('access',)),
    ('R192', 'giu', 'Em muốn đổi mật khẩu vì mật khẩu cũ khó nhớ quá', ('account',)),
    ('R193', 'giu', 'Mật khẩu sắp hết hạn, gia hạn giúp em', ('account',)),
    ('R194', 'giu', 'Tài khoản bị vô hiệu hoá do không đăng nhập 90 ngày, kích hoạt lại giúp em', ('account',)),
    ('R198', 'giu', "Em cần quyền vào thư mục 'Khoá sổ T10' gấp", ('access',)),
    ('R201', 'giu', 'MẬT KHẨU CỦA EM HẾT HẠN, ĐỔI GIÚP EM', ('account',)),
    ('R203', 'giu', 'Gửi mail cho khách hàng có địa chỉ Yahoo bị trả về', ('account',)),
    ('R205', 'giu', 'Tài khoản email công ty @congty-abc.vn quên mật khẩu', ('account',)),
    ('R206', 'giu', 'Em cần gia hạn tài khoản thực tập sinh thêm 1 tháng', ('account',)),
    ('R207', 'giu', 'Cài lại máy LAP-0342 giúp em vì bị lỗi Windows', ('software',)),
    ('R209', 'giu', 'Em mất 2 tiếng mà chưa cài được Zoom', ('software',)),
    ('R210', 'giu', 'Mất bao lâu thì được cấp quyền thư mục ạ', ('access',)),
    ('R211', 'giu', 'Phần mềm Teams bị đăng xuất liên tục', ('software',)),
    ('R212', 'giu', 'Em ko dùng được VPN, nó báo lỗi 809', ('vpn',)),
    ('R213', 'giu', 'Em không thấy nút cài đặt trong Software Center', ('software',)),
    ('R216', 'giu', 'Em cần gửi mail cho khách dùng Gmail nhưng bị trả về', ('account',)),
    ('R217', 'giu', 'Cấp quyền truy cập thư mục Dự án cho bạn Huy mới vào', ('access',)),
    ('R221', 'giu', "Cho em xin quyền vào thư mục 'Thu hồi công nợ'", ('access',)),
    ('R225', 'giu', 'Máy em không có lỗi gì, chỉ cần cài thêm Zoom thôi', ('software',)),
    ('R226', 'giu', 'Cài giúp em phần mềm ghi âm cuộc họp, em hay quên nội dung', ('software',)),
    ('R227', 'giu', 'Gia hạn VPN giúp em, đừng để hết hạn giữa tuần nhé', ('vpn',)),
    ('R229', 'giu', 'Cấp quyền thư mục Kế toán cho em, không cần quyền ghi đâu', ('access',)),
    ('R231', 'giu', 'Thôi thì anh gia hạn VPN 3 tháng cũng được', ('vpn',)),
    ('R232', 'giu', 'Thôi em không đợi nữa, reset luôn giúp em', ('account',)),
    ('R238', 'giu', 'Đổi mật khẩu theo yêu cầu sau đợt diễn tập phishing của công ty', ('account',)),
    ('R239', 'giu', 'Máy em không bị virus đâu, chỉ chậm thôi, cài thêm phần mềm dọn rác giúp em', ('software',)),
    ('R241', 'giu', 'Em không bị mất máy, chỉ quên mật khẩu thôi', ('account',)),
    ('R242', 'giu', 'Mở khoá tài khoản giúp em, không có ai hack đâu, em nhập sai thôi', ('account',)),
    ('R246', 'giu', 'Em nhập sai mã OTP 3 lần nên bị khoá, mở giúp em', ('account',)),
    ('R247', 'giu', 'Đừng ngại, anh cứ gia hạn VPN cho em 1 năm luôn', ('vpn',)),
    ('R250', 'giu', 'Bác sĩ khoa Nội cần cài phần mềm đọc phim X-quang', ('software',)),
    ('R253', 'giu', 'Em là Lộ phòng hành chính, quên mật khẩu email', ('account',)),
]

# Đã tái hiện trên hệ thống thật (LLM thật) 12/11 09:03 — bản trước sửa TỰ LÀM hoặc hiểu ngược.
LIVE_REPRO = [
    ("My laptop was stolen yesterday, pls reset my password and VPN cert", ("account", "vpn"), "lost_device"),
    ("tk e bị ng khác đăng nhập a ạ, reset giúp e", ("account",), "compromised"),
    ("Delete app Telegram khỏi máy công ty của em", ("software",), "uninstall"),
    ("Tháo phần mềm UltraViewer ra khỏi máy LAP-0417 của em", ("software",), "uninstall"),
    ("Đóng băng tài khoản của em trong thời gian điều tra", ("account",), "lock"),
    ("lock my account please, i'll be on leave", ("account",), "lock"),
]

# Soát tầng hiểu yêu cầu 12/11: phủ định với "đổi / thay mật khẩu" lọt bộ dò (B11 hỏi loại tài khoản → trả lời có "email" → đặt lại).
DOI_MAT_KHAU = [
    "Em KHÔNG muốn đổi mật khẩu AD, chỉ hỏi chính sách thôi",
    "thôi đừng đổi mật khẩu email nữa",
    "không cần đổi mật khẩu đâu, em nhớ ra rồi",
    "AD, mà thôi đừng đổi mật khẩu nữa",
]


@pytest.mark.parametrize(("cid", "part", "text", "intents"), SHOULD_FLAG, ids=[r[0] for r in SHOULD_FLAG])
def test_hopden_should_flag(cid: str, part: str, text: str, intents: tuple[str, ...]) -> None:
    assert _flagged(text, intents)


@pytest.mark.parametrize(("cid", "part", "text", "intents"), MUST_PASS, ids=[r[0] for r in MUST_PASS])
def test_hopden_must_pass(cid: str, part: str, text: str, intents: tuple[str, ...]) -> None:
    assert not _flagged(text, intents)


@pytest.mark.parametrize(("text", "intents", "kind"), LIVE_REPRO)
def test_live_repro_flagged_with_kind(text: str, intents: tuple[str, ...], kind: str) -> None:
    assert reverse_action_kind(text, set(intents)) == kind


@pytest.mark.parametrize("text", DOI_MAT_KHAU)
def test_negated_password_change_is_negate(text: str) -> None:
    assert reverse_action_kind(text, {"account"}) == "negate"


def _variants(text: str) -> dict[str, str]:
    full = "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else ("\u3000" if c == " " else c) for c in text)
    return {
        "nfd": unicodedata.normalize("NFD", text),
        "upper": text.upper(),
        "fullwidth": full,
        "zwsp_inword": "\u200b".join(text),
        "nbsp": text.replace(" ", "\u00a0"),
        "double_space": text.replace(" ", "  "),
    }


@pytest.mark.parametrize(("text", "intents", "kind"), LIVE_REPRO)
@pytest.mark.parametrize("variant", ["nfd", "upper", "fullwidth", "zwsp_inword", "nbsp", "double_space"])
def test_unicode_variants_still_flagged(text: str, intents: tuple[str, ...], kind: str, variant: str) -> None:
    """Kiểm hộp đen: full-width lọt 121/121, zero-width trong từ lọt 111/121 trước khi chuẩn hoá NFKC trong bộ dò."""
    assert reverse_action_kind(_variants(text)[variant], set(intents)) == kind


@pytest.mark.parametrize(
    "text",
    ["Em không bị mất máy, chỉ quên mật khẩu thôi", "Gmail công ty của em không đăng nhập được",
     "Đổi mật khẩu theo yêu cầu sau đợt diễn tập phishing của công ty", "Em sợ bị hack nên muốn đổi mật khẩu mạnh hơn",
     "Cài phần mềm theo dõi thất lạc thiết bị (Find My Device) cho laptop em", "lỡ nhập sai mật khẩu nhiều lần, mở khoá giúp em",
     "lo nhap sai mat khau nhieu lan, mo khoa giup em", "Em không muốn đợi lâu, cấp VPN gấp giúp em",
     "xin cấp quyền thư mục Marketing cho e, ko cần quyền sửa đâu, đọc thôi là dc"],
)
def test_near_misses_not_flagged(text: str) -> None:
    assert not _flagged(text, ("account", "access", "software", "vpn"))


def test_long_input_bounded_time() -> None:
    """Soát bảo mật 12/11: lookahead tới hết câu là bậc hai; NFKC có thể nở chữ thô 4 000 ký tự thành ~38 000 → chỉ dò 8 000 ký tự."""
    worst = "xoá tk " * 284 + "\ufdfa" * 2000 + " cấp lại"
    start = time.perf_counter()
    reverse_action_kind(worst, {"account", "vpn", "software", "access"})
    personal_account_mentioned(worst, {"account"})
    assert time.perf_counter() - start < 1.0
