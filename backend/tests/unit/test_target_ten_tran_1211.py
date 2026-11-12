"""V5 soát 12/11 (agent 05, D-91): lưới L-03 nhận TÊN TRẦN và vai trò người khác.

Trước: chỉ "cho + kính ngữ + Tên" / "máy + kính ngữ + Tên". LLM bỏ sót `target_user` → "reset mật khẩu AD của Bình" thành đặt lại mật khẩu của
CHÍNH người gửi (R01 AUTO); "Cài Zoom cho Bình" → cài lên máy người gửi (R11 AUTO). Chiều an toàn: bắt nhầm chỉ thêm câu hỏi đích.
Đo trên 520 câu `eval/`: 0 câu đổi kết quả ở lưới account/access; 1 câu đổi ở lưới máy (câu account — lưới máy không áp).
"""

import pytest
from app.domain.target import device_mention_reason, mention_reason

ME = "nv001"

ACCOUNT_FLAG = [
    "reset mật khẩu AD của Bình giúp em",
    "mật khẩu AD của chị Bình bị quên rồi",
    "đặt lại mật khẩu AD giúp sếp em với",
    "đặt lại mật khẩu AD cho Bình",
    "reset mk AD hộ Bình nhé",
    "đặt lại mật khẩu AD cho trưởng phòng",
    "mở khoá tài khoản email giùm quản lý của em",
    "Xem quyền thư mục finance/public-reports của chị Lan",
    "Gia hạn quyền finance/Q3 30 ngày cho Hà",
    "dat lai mat khau AD cho Binh",
    "reset mk cua Lan giup em",
    "đặt lại mật khẩu cho giám đốc",
]
DEVICE_FLAG = [
    "Cài Zoom lên máy của Bình",
    "Cài Zoom cho Bình",
    "Cài Zoom cho máy của Bình nhé",
    "Gia hạn chứng chỉ VPN cho máy của Bình",
    "gia hạn VPN giúp Bình với",
    "cai zoom len may Binh",
    "cài Teams cho sếp",
]
PASS = [
    "Đặt lại mật khẩu AD cho mình",
    "Cài Zoom cho mình nhé",
    "mật khẩu của Outlook bị lỗi",
    "Cho mình quyền đọc thư mục shared/templates",
    "Cài Adobe Acrobat Pro lên máy mình",
    "gia hạn VPN cho máy Dell của em",
    "Cấp quyền đọc thư mục finance/public-reports cho mình",
    "Mật khẩu Windows của em hết hạn",
    "cài Microsoft Teams giúp em",
    "Mình cần quyền vào thư mục",
    "VPN công ty dùng cổng nào vậy?",
    "email của em bị khoá, mở giúp em",
    "quyền của Phòng Kế toán là gì",
    "Cài Zoom cho Máy tính của em",
    "đặt lại mật khẩu giúp Em với",
    "sếp đã nhắc em đổi mật khẩu định kỳ",
    "Cài Zoom cho Mac của em",
]


@pytest.mark.parametrize("text", ACCOUNT_FLAG)
def test_account_ten_tran_va_vai_tro_bi_bat(text: str) -> None:
    assert mention_reason(text, ME) is not None


@pytest.mark.parametrize("text", DEVICE_FLAG)
def test_may_ten_tran_bi_bat(text: str) -> None:
    assert device_mention_reason(text, ME, {}) == "phrase"


@pytest.mark.parametrize("text", PASS)
def test_cau_cua_chinh_minh_khong_bi_bat(text: str) -> None:
    assert mention_reason(text, ME) is None
    assert device_mention_reason(text, ME, {}) is None
