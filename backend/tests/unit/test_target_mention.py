"""be-target-guard (L-03) — hàm thuần `domain/target.py`: `mentions_other_target` / `mention_reason` (A, A1) và `target_check` (Q1 BE:
`unknown_key` chỉ tính khi khoá NGOÀI `spec.keys`). Không gọi LLM."""

import pytest
from app.domain.target import (
    RESOURCE_SLOTS,
    TARGET_QUESTION,
    mention_reason,
    mentions_other_target,
    target_check,
)
from app.settings import get_slots

BUG = "Nhờ IT đặt lại mật khẩu cho tài khoản dịch vụ svc-backup, đội sao lưu cần đăng nhập lại"
DEMO_SELF = "Mình quên mật khẩu tài khoản AD đăng nhập máy tính, đặt lại giúp mình với."

TRUE_CASES = [
    pytest.param(BUG, "nv001", id="cau-loi-nguyen-van"),
    pytest.param("reset mk AD giup nv003 voi", "nv001", id="khong-dau-nv003"),
    pytest.param("đặt lại mật khẩu cho an.nv", "nv001", id="username-an.nv"),
    pytest.param("reset mật khẩu cho svc_backup", "nv001", id="svc_backup"),
    pytest.param("reset mật khẩu cho svc-backup", "nv001", id="svc-backup"),
    pytest.param("tai khoan dich vu bi khoa, mo giup", "nv001", id="tai-khoan-dich-vu-khong-dau"),
    pytest.param("bạn ấy quên mật khẩu", "nv001", id="ban-ay"),
    pytest.param("đặt lại mật khẩu email <EMAIL_1> giúp mình", "nv001", id="mat-na-pii"),
    pytest.param("đặt lại mật khẩu AD cho chị Hoa", "nv001", id="cho-chi-Hoa"),
    pytest.param("dat lai mat khau AD cho chi Hoa", "nv001", id="cho-chi-Hoa-khong-dau"),
    pytest.param("mở khoá tài khoản cho đồng nghiệp phòng mình", "nv001", id="dong-nghiep"),
    pytest.param("cấp tài khoản cho nhân viên mới", "nv001", id="nhan-vien-moi"),
    pytest.param("đặt lại mật khẩu cho người khác trong phòng", "nv001", id="nguoi-khac"),
    pytest.param("reset password of the service account please", "nv001", id="service-account"),
    pytest.param("mở khoá hộ anh Nam", "nv001", id="ho-anh"),
    pytest.param("đây là tài khoản của sếp mình", "nv001", id="tai-khoan-cua-sep"),
    pytest.param("email của bạn nv005 ạ", "nv001", id="email-cua-ban-nv005"),
    pytest.param("gia hạn quyền thư mục public-reports cho hoa.bt", "nv001", id="A1-hoa.bt-van-bat"),
    pytest.param("chi ay quen mat khau roi", "nv001", id="chi-ay-khong-dau"),
    pytest.param("đặt lại mật khẩu NV003", "nv001", id="hoa-thuong-NV003"),
]  # fmt: skip

FALSE_CASES = [
    pytest.param(DEMO_SELF, "nv001", id="demo-tu-quen-mat-khau"),
    pytest.param("đặt lại mật khẩu tài khoản AD.", "nv001", id="tc01"),
    pytest.param("reset mk cho em", "nv001", id="cho-em"),
    pytest.param("Gia hạn quyền thư mục finance/public-reports thêm 30 ngày", "nv001", id="duong-dan-co-gach"),
    pytest.param("đặt lại mật khẩu cho mình, mã nv001", "nv001", id="tu-neu-nv001"),
    pytest.param("đặt lại mật khẩu cho NV001", "nv001", id="tu-neu-NV001-hoa"),
    pytest.param("mật khẩu e-mail bị quên", "nv001", id="e-mail"),
    pytest.param("VPN trên máy LAP-0342 không vào được", "nv001", id="ma-may-LAP-0342"),
    pytest.param("VPN báo lỗi 809", "nv001", id="loi-809"),
    pytest.param("cài lại giúp em, lỗi 0x800704c9", "nv001", id="ma-loi-hex"),
    pytest.param("mở file report.pdf không được, giúp tôi", "nv001", id="duoi-tep"),
    pytest.param("vào portal.demo-corp.com không đăng nhập được tài khoản của tôi", "nv001", id="ten-mien"),
    pytest.param("wi-fi tầng 3 không vào được, reset mật khẩu giúp em", "nv001", id="wi-fi"),
    pytest.param("giúp em mở khoá tài khoản của em", "nv001", id="cua-em"),
    pytest.param("tôi quên mật khẩu office365", "nv001", id="office365"),
    pytest.param("đặt lại mật khẩu [BÍ_MẬT_ĐÃ_ẨN] giúp mình", "nv001", id="mat-na-bi-mat"),
    pytest.param("đặt lại mật khẩu cho anh nhé", "nv001", id="cho-anh-khong-ten"),
    pytest.param("xin quyền đọc finance/Q3 30 ngày", "nv002", id="tc08"),
]  # fmt: skip


@pytest.mark.parametrize(("text", "requester"), TRUE_CASES)
def test_mentions_other_target_true(text: str, requester: str) -> None:
    assert mentions_other_target(text, requester) is True


@pytest.mark.parametrize(("text", "requester"), FALSE_CASES)
def test_mentions_other_target_false(text: str, requester: str) -> None:
    assert mentions_other_target(text, requester) is False


def test_at_least_25_sentences() -> None:
    assert len(TRUE_CASES) + len(FALSE_CASES) >= 25


@pytest.mark.parametrize(
    ("text", "reason"),
    [(BUG, "identifier"), ("bạn ấy quên mật khẩu", "phrase"), ("cho chị Hoa", "phrase"), ("<SĐT_1>", "identifier")],
)
def test_mention_reason_is_closed_constant(text: str, reason: str) -> None:
    assert mention_reason(text, "nv001") == reason


def test_a1_exact_resource_slot_value_not_identifier() -> None:
    """A1 (chốt ĐP): token TRÙNG ĐÚNG (casefold) giá trị slot tài nguyên đã sạch → không tính; trùng một phần / khác → vẫn tính."""
    text = "gia hạn quyền thư mục public-reports thêm 30 ngày"
    assert mentions_other_target(text, "nv001") is True  # đối chứng: chưa có slot → "public-reports" là token định danh
    assert mentions_other_target(text, "nv001", ignore=["public-reports"]) is False
    assert mentions_other_target(text, "nv001", ignore=["PUBLIC-REPORTS"]) is False
    assert mentions_other_target("gia hạn quyền thư mục public-reports 30 ngày", "nv001", ignore=["public-reports"]) is False
    assert mentions_other_target(text, "nv001", ignore=["finance/public-reports"]) is True  # không tách đoạn `/`
    assert mentions_other_target(text, "nv001", ignore=["public-report"]) is True
    other = "gia hạn quyền thư mục public-reports cho hoa.bt"
    assert mentions_other_target(other, "nv001", ignore=["public-reports"]) is True
    assert RESOURCE_SLOTS == frozenset({"resource_path", "software_name", "device_id"})


ACCOUNT = get_slots().intents["account"]
ACCESS = get_slots().intents["access"]


def test_target_check_account_bug_case() -> None:
    """Ca lỗi: slots {account_type: ad} (không target) → bật `identifier`."""
    assert target_check("account", {"account_type": "ad", "action": "reset_password"}, {}, ACCOUNT.keys, BUG, "nv001") == (
        True, "identifier")  # fmt: skip


def test_target_check_self_sentence_no_flag() -> None:
    assert target_check("account", {"account_type": "ad"}, {}, ACCOUNT.keys, DEMO_SELF, "nv001") == (False, None)


def test_target_check_dropped_target_user_always_flags() -> None:
    """Q-T20a-4/6 cũ không yếu đi: `target_user` bị bỏ → `dropped` kể cả khi đã có `target_user` hợp lệ."""
    assert target_check("account", {}, {"target_user": "bad_value"}, ACCOUNT.keys, "x", "nv001")[1] == "dropped"
    assert target_check("account", {"target_user": "nv005"}, {"target_user": "unknown_key"}, ACCOUNT.keys, "x", "nv001")[1] == (
        "dropped")  # fmt: skip


def test_target_check_unknown_key_only_outside_spec_keys() -> None:
    """Q1 (BE duyệt): `unknown_key` chỉ tính khi khoá NGOÀI `spec.keys` (vd `account_name`); khoá đã khai báo không đang hỏi → không."""
    assert target_check("account", {}, {"account_name": "unknown_key"}, ACCOUNT.keys, "reset giúp", "nv001") == (
        False, "unknown_key")  # fmt: skip
    assert target_check("account", {}, {"action": "unknown_key"}, ACCOUNT.keys, "reset giúp", "nv001") == (False, None)


def test_target_check_valid_target_no_new_flag() -> None:
    """Đã có `target_user` hợp lệ → không bật vì câu (requested_for đã là đích); mention vẫn báo cho audit."""
    assert target_check("account", {"target_user": "nv004"}, {}, ACCOUNT.keys, "cho nv004", "nv001") == (True, None)


def test_target_check_other_intents_never_flag() -> None:
    assert target_check(None, {}, {"target_user": "bad_value"}, frozenset(), BUG, "nv001") == (False, None)
    # be-target-guard-2 (đổi CÓ CHỦ ĐÍCH): vpn/software giờ xét đích máy — khoá người/máy bị bỏ → `dropped`
    for intent in ("vpn", "software"):
        assert target_check(intent, {}, {"target_user": "bad_value"}, frozenset(), BUG, "nv001")[1] == "dropped"


def test_target_check_access_resource_slot_a1() -> None:
    slots = {"action": "extend_permission", "resource_path": "public-reports", "duration": "30"}
    text = "gia hạn quyền thư mục public-reports thêm 30 ngày"
    assert target_check("access", slots, {}, ACCESS.keys, text, "nv001") == (False, None)
    assert target_check("access", slots, {}, ACCESS.keys, "gia hạn quyền thư mục public-reports cho hoa.bt", "nv001") == (
        True, "identifier")  # fmt: skip


def test_target_question_fixed_text() -> None:
    assert TARGET_QUESTION == (
        "Bạn cần xử lý cho tài khoản của ai? Vui lòng ghi đúng mã tài khoản trong hệ thống (ví dụ: nv005). "
        "Nếu là tài khoản của chính bạn, hãy ghi mã nhân viên của bạn."
    )
