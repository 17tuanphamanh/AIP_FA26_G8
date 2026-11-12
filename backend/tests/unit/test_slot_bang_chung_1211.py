"""V6 soát 12/11 (agent 05, D-91): slot CHUẨN HOÁ do LLM điền phải có dấu vết trong câu — không thì bỏ `slot_not_in_text` và B11 hỏi.

Đo trên `eval/`: 143 slot chuẩn hoá có nhãn vàng — 0 ca thiếu dấu vết mà kịch bản không có câu trả lời cho câu hỏi đó.
"""

import pytest
from app.domain.slot_evidence import durations_in_text, lacks_evidence
from app.domain.slots import sanitize_slots
from app.settings import get_slots

SLOTS = get_slots()
ACCOUNT = frozenset({"reset_password", "unlock_account"})


# ---- ca tái hiện của agent 05 --------------------------------------------------------------------------------------------------


def test_duration_bia_bi_bo() -> None:
    clean, dropped = sanitize_slots(SLOTS.intents["access"], {"action": "extend_permission", "duration": "90",
                                                              "resource_path": "finance/public-reports"},
                                    text="Gia hạn quyền thư mục finance/public-reports giúp mình")  # fmt: skip
    assert "duration" not in clean and dropped["duration"] == "slot_not_in_text"
    assert clean["resource_path"] == "finance/public-reports"


def test_account_type_doan_bi_bo() -> None:
    clean, dropped = sanitize_slots(SLOTS.intents["account"], {"action": "reset_password", "account_type": "erp"},
                                    text="Đặt lại mật khẩu giúp mình với")  # fmt: skip
    assert "account_type" not in clean and dropped["account_type"] == "slot_not_in_text"
    assert clean["action"] == "reset_password"


def test_mo_khoa_ma_llm_tra_dat_lai_bi_bo() -> None:
    clean, dropped = sanitize_slots(SLOTS.intents["account"], {"action": "reset_password", "account_type": "email"},
                                    text="Tài khoản email của mình bị khoá, mở khoá giúp mình")  # fmt: skip
    assert "action" not in clean and dropped["action"] == "slot_not_in_text"
    assert clean["account_type"] == "email"


# ---- có dấu vết → giữ như cũ -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value", "text"),
    [
        ("account_type", "ad", "Đặt lại mật khẩu AD cho mình"),
        ("account_type", "ad", "quên mật khẩu đăng nhập máy tính"),
        ("account_type", "ad", "Nhờ IT đặt lại mật khẩu cho tài khoản dịch vụ svc-backup"),
        ("account_type", "ad", "Tôi không thể đăng nhập tài khoản công ty"),
        ("account_type", "ad", "Windows"),
        ("account_type", "email", "Quên mật khẩu email"),
        ("account_type", "email", "khong vao duoc outlook"),
        ("account_type", "erp", "tài khoản ERP bị khoá"),
        ("permission_level", "read", "Cho mình quyền đọc thư mục shared/templates"),
        ("permission_level", "read", "chỉ đọc thôi"),
        ("permission_level", "write", "cần quyền chỉnh sửa"),
        ("permission_level", "full", "toàn quyền thư mục"),
        ("duration", "30", "30 ngày"),
        ("duration", "30", "30"),
        ("duration", "30", "gia hạn thêm một tháng"),
        ("duration", "14", "2 tuần nhé"),
        ("duration", "15", "nửa tháng"),
        ("duration", "90", "3 thang"),
    ],
)  # fmt: skip
def test_co_dau_vet_thi_giu(key: str, value: str, text: str) -> None:
    assert lacks_evidence(key, value, text) is False


@pytest.mark.parametrize(
    ("key", "value", "text"),
    [
        ("account_type", "email", "Đặt lại mật khẩu AD cho mình"),
        ("account_type", "ad", "Đặt lại mật khẩu giúp mình với"),
        ("permission_level", "write", "Cho mình quyền đọc thư mục shared/templates"),
        ("permission_level", "read", "Mình cần quyền vào thư mục"),
        ("duration", "90", "30 ngày"),
        ("duration", "30", "gia hạn quyền finance/Q3"),
        ("duration", "abc", "30 ngày"),
    ],
)  # fmt: skip
def test_khong_dau_vet_hoac_trai_thi_bo(key: str, value: str, text: str) -> None:
    assert lacks_evidence(key, value, text) is True


@pytest.mark.parametrize(
    ("value", "text", "lacks"),
    [
        ("reset_password", "Tài khoản bị khoá, mở khoá giúp mình", True),
        ("unlock_account", "Quên mật khẩu, đặt lại giúp mình", True),
        ("unlock_account", "email của mình bị quản trị viên khoá từ hôm qua, mình không nhập sai mật khẩu, mở giúp mình với", False),
        ("reset_password", "tài khoản bị khoá do nhập sai, đặt lại mật khẩu giúp mình", False),
        ("reset_password", "không đăng nhập được", False),  # câu không nói rõ → giữ lựa chọn của LLM (C1: chỉ tả lỗi vẫn AUTO)
        ("unlock_account", "không đăng nhập được", False),
    ],
)  # fmt: skip
def test_action_chi_bo_khi_mau_thuan(value: str, text: str, lacks: bool) -> None:
    assert lacks_evidence("action", value, text, intent_actions=ACCOUNT) is lacks


def test_action_ngoai_account_khong_xet() -> None:
    assert lacks_evidence("action", "grant_permission", "gia hạn quyền", intent_actions=frozenset({"grant_permission"})) is False


def test_khoang_thoi_gian_doc_duoc() -> None:
    assert durations_in_text("gia hạn 30 ngày hoặc 1 tháng") == {30}
    assert durations_in_text("2 tuần") == {14}
    assert durations_in_text("một năm") == {365}
    assert durations_in_text("máy LAP-0342 quý Q3") == frozenset()
