"""T24 bảng 7.5 — test-first: tin kết quả B18 theo mẫu (phase5 7.1 P4, bảng 7.3) — ca m1–m3 + `person_phrase` + `permission_rows`.

`result_text(action, outputs, facts, *, requester_id, rows=())`: 6 mẫu mới + 3 mẫu VPN (chữ CŨ y nguyên — kỳ vọng chép từ
`test_b17_execute.py`). Giá trị `{…}` chỉ ghép khi qua mẫu; thiếu / sai mẫu → bỏ cụm (m2). `view_permissions` ≤ 10 dòng (m3).
`person_phrase(rf, requester)`: bằng người gửi → "bạn"; khớp `^[a-z0-9_]{3,64}$` → id; sai mẫu → "người được yêu cầu".
"""

from datetime import date
from typing import Any

import pytest
from app.domain.action import Action, FactValue
from app.domain.messages import (
    RESULT_ACTIONS,
    PermRow,
    permission_rows,
    person_phrase,
    result_text,
)
from tests.unit._t24 import TZ, action

ME = "nv001"
CONFIRM_LOGIN = "Bạn đăng nhập thử rồi xác nhận giúp mình nhé."
CONFIRM_OPEN = "Bạn mở thử rồi xác nhận giúp mình nhé."
CONFIRM_VIEW = "Bạn xem đã đủ chưa rồi xác nhận giúp mình nhé."
# Lô N (N10): đối tượng KHÁC người gửi → câu cho bên thứ ba; tài khoản dịch vụ → câu kiểm dịch vụ (mẫu đăng nhập).
CONFIRM_LOGIN_OTHER = "Bạn nhờ người dùng tài khoản này đăng nhập thử rồi xác nhận giúp mình nhé."
CONFIRM_LOGIN_SERVICE = "Bạn kiểm tra dịch vụ dùng tài khoản này đã đăng nhập lại được chưa rồi xác nhận giúp mình nhé."
CONFIRM_OPEN_OTHER = "Bạn nhờ người được yêu cầu mở thử rồi xác nhận giúp mình nhé."
CONFIRM_VIEW_OTHER = "Bạn xem danh sách quyền này đã đủ chưa rồi xác nhận giúp mình nhé."
CONFIRM_VPN_OTHER = "Bạn nhờ người dùng máy này kết nối lại rồi xác nhận giúp mình nhé."
SERVICE_FACTS: dict[str, FactValue] = {"target_user_status": "active", "target_is_service_account": True}


def _text(act: Action, outputs: dict[str, Any] | None = None, *, rows: Any = (), requester: str = ME) -> str:
    return result_text(act, outputs or {}, act.facts, requester_id=requester, rows=rows)


# ---- person_phrase ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rf", "requester", "expected"),
    [
        pytest.param("nv001", "nv001", "bạn", id="chinh-minh"),
        pytest.param("svc_backup", "nv001", "svc_backup", id="nguoi-khac"),
        pytest.param("nv005", "nv001", "nv005", id="nv005"),
        pytest.param("NV005<script>", "nv001", "người được yêu cầu", id="sai-mau"),
        pytest.param("ab", "nv001", "người được yêu cầu", id="qua-ngan"),
        pytest.param("", "nv001", "người được yêu cầu", id="rong"),
    ],
)
def test_m1_person_phrase(rf: str, requester: str, expected: str) -> None:
    assert person_phrase(rf, requester) == expected


def test_m1_result_actions_nine() -> None:
    assert frozenset({
        "renew_vpn_cert", "reissue_vpn_access", "check_vpn_status", "reset_password", "unlock_account", "install_software",
        "view_permissions", "grant_permission", "extend_permission",
    }) == RESULT_ACTIONS  # fmt: skip


# ---- m1: 6 mẫu mới -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("act", "outputs", "expected"),
    [
        pytest.param(action("reset_password", rf=ME, params={"account_type": "ad"}),
                     {"delivered_via": "sms", "sent_to": "0900***001", "expires_in_minutes": "15"},
                     "Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của bạn. Mật khẩu tạm đã gửi qua SMS tới số 0900***001, "
                     "hiệu lực 15 phút, chỉ dùng một lần; bạn sẽ được yêu cầu đổi mật khẩu khi đăng nhập. "
                     f"{CONFIRM_LOGIN}", id="reset-chinh-minh"),
        pytest.param(action("reset_password", rf="svc_backup", params={"account_type": "ad"}, facts=SERVICE_FACTS),
                     {"delivered_via": "sms", "sent_to": "0900***101", "expires_in_minutes": "15"},
                     "Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của svc_backup. Mật khẩu tạm đã gửi qua SMS tới số "
                     "0900***101, hiệu lực 15 phút, chỉ dùng một lần; người dùng tài khoản này sẽ được yêu cầu đổi mật khẩu "
                     f"ở lần đăng nhập tới. {CONFIRM_LOGIN_SERVICE}", id="reset-svc_backup"),
        pytest.param(action("reset_password", rf="nv005", params={"account_type": "erp"}), {"delivered_via": "sms"},
                     "Đã đặt lại mật khẩu tài khoản ERP của nv005. Mật khẩu tạm đã gửi qua SMS tới số điện thoại đã đăng ký, "
                     "chỉ dùng một lần; người dùng tài khoản này sẽ được yêu cầu đổi mật khẩu ở lần đăng nhập tới. "
                     f"{CONFIRM_LOGIN_OTHER}", id="reset-sms-nguoi-khac"),
        pytest.param(action("reset_password", rf="nv005", params={"account_type": "email"}), {"delivered_via": "email"},
                     "Đã đặt lại mật khẩu tài khoản email của nv005. Hệ thống tài khoản xác nhận mật khẩu tạm được gửi qua "
                     "email; người dùng tài khoản này sẽ được yêu cầu đổi mật khẩu ở lần đăng nhập tới. "
                     f"{CONFIRM_LOGIN_OTHER}", id="reset-email-nguoi-khac"),
        pytest.param(action("reset_password", rf="svc_backup", params={"account_type": "ad"}, facts=SERVICE_FACTS), {},
                     "Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của svc_backup. Người dùng tài khoản này sẽ được yêu cầu "
                     f"đổi mật khẩu ở lần đăng nhập tới. {CONFIRM_LOGIN_SERVICE}", id="reset-mac-dinh-svc"),
        pytest.param(action("reset_password", rf="nv005", params={"account_type": "ad"}), {},
                     "Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của nv005. Người dùng tài khoản này sẽ được yêu cầu đổi mật "
                     f"khẩu ở lần đăng nhập tới. {CONFIRM_LOGIN_OTHER}", id="reset-nguoi-khac"),
        pytest.param(action("reset_password", rf=ME, params={"account_type": "ad"}), {},
                     f"Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của bạn. Bạn cần đổi mật khẩu ở lần đăng nhập tới. "
                     f"{CONFIRM_LOGIN}", id="reset-thieu-delivered"),
        pytest.param(action("reset_password", rf=ME, params={"account_type": "erp"}), {"delivered_via": "sms"},
                     "Đã đặt lại mật khẩu tài khoản ERP của bạn. Mật khẩu tạm đã gửi qua SMS tới số điện thoại đã đăng ký, "
                     f"chỉ dùng một lần; bạn sẽ được yêu cầu đổi mật khẩu khi đăng nhập. {CONFIRM_LOGIN}",
                     id="reset-erp-sms-thieu-so"),
        pytest.param(action("reset_password", rf=ME, params={"account_type": "email"}), {"delivered_via": "email"},
                     "Đã đặt lại mật khẩu tài khoản email của bạn. Hệ thống tài khoản xác nhận mật khẩu tạm được gửi qua "
                     f"email; bạn cần đổi mật khẩu ở lần đăng nhập tới. {CONFIRM_LOGIN}", id="reset-email"),
        pytest.param(action("unlock_account", rf=ME, params={"account_type": "email"}), {},
                     f"Đã mở khoá tài khoản email của bạn. {CONFIRM_LOGIN}", id="unlock-email"),
        pytest.param(action("unlock_account", rf="nv005", params={"account_type": "ad"}), {},
                     f"Đã mở khoá tài khoản đăng nhập (AD) của nv005. {CONFIRM_LOGIN_OTHER}", id="unlock-ad-nguoi-khac"),
        pytest.param(action("unlock_account", rf="svc_backup", params={"account_type": "ad"}, facts=SERVICE_FACTS), {},
                     f"Đã mở khoá tài khoản đăng nhập (AD) của svc_backup. {CONFIRM_LOGIN_SERVICE}", id="unlock-svc"),
        pytest.param(action("unlock_account", rf="nv005", params={"account_type": "ad"},
                            facts={"target_is_service_account": False}), {},
                     f"Đã mở khoá tài khoản đăng nhập (AD) của nv005. {CONFIRM_LOGIN_OTHER}", id="unlock-khong-phai-svc"),
        pytest.param(action("install_software", params={"device_id": "LAP-0342", "software_name": "zoom"}),
                     {"software": "zoom", "version": "6.1"},
                     f"Đã cài Zoom phiên bản 6.1 lên máy LAP-0342. {CONFIRM_OPEN}", id="install-du"),
        pytest.param(action("install_software", params={"device_id": "LAP-0342", "software_name": "zoom"}),
                     {"software": "zoom"}, f"Đã cài Zoom lên máy LAP-0342. {CONFIRM_OPEN}", id="install-thieu-version"),
        pytest.param(action("install_software", params={"device_id": "LAP-0342", "software_name": "zoom"}), {},
                     f"Đã cài Zoom lên máy LAP-0342. {CONFIRM_OPEN}", id="install-thieu-outputs"),  # Q-T24-7: tên từ params
        pytest.param(action("install_software", params={"device_id": "LAP-0342", "software_name": "Zoom Pro"}),
                     {"software": "zoom", "version": "6.1"},
                     f"Đã cài phần mềm phiên bản 6.1 lên máy LAP-0342. {CONFIRM_OPEN}", id="install-params-sai-mau"),
        pytest.param(action("install_software", params={"device_id": "lap 0342; rm", "software_name": "zoom"}),
                     {"software": "zoom", "version": "6.1"},
                     f"Đã cài Zoom phiên bản 6.1 lên máy của bạn. {CONFIRM_OPEN}", id="install-device-sai-mau"),
        pytest.param(action("grant_permission", params={"resource_path": "finance/public-reports", "permission_level": "read",
                                                        "duration_days": 30}),
                     {"level": "read", "expires_on": "2026-11-12"},
                     "Đã cấp quyền đọc thư mục finance/public-reports cho bạn, hiệu lực tới 12/11/2026. "
                     f"{CONFIRM_OPEN}", id="grant-du"),
        pytest.param(action("grant_permission"), {"expires_on": "2026-11-12"},
                     "Đã cấp quyền thư mục finance/public-reports cho bạn, hiệu lực tới 12/11/2026. "
                     f"{CONFIRM_OPEN}", id="grant-thieu-level"),
        pytest.param(action("grant_permission"), {"level": "read"},
                     f"Đã cấp quyền đọc thư mục finance/public-reports cho bạn. {CONFIRM_OPEN}", id="grant-thieu-han"),
        pytest.param(action("grant_permission", rf="nv005"), {"level": "write", "expires_on": "2026-11-12"},
                     "Đã cấp quyền ghi thư mục finance/public-reports cho nv005, hiệu lực tới 12/11/2026. "
                     f"{CONFIRM_OPEN_OTHER}", id="grant-nguoi-khac"),
        pytest.param(action("extend_permission", rf="nv005", params={"resource_path": "finance/Q3", "duration_days": 30}), {},
                     f"Đã gia hạn quyền thư mục finance/Q3 của nv005. {CONFIRM_OPEN_OTHER}", id="extend-nguoi-khac"),
        pytest.param(action("install_software", rf="nv005", params={"device_id": "LAP-0342", "software_name": "zoom"}), {},
                     f"Đã cài Zoom lên máy LAP-0342. {CONFIRM_OPEN_OTHER}", id="install-nguoi-khac"),
        pytest.param(action("extend_permission", params={"resource_path": "finance/Q3", "duration_days": 30}),
                     {"level": "read", "expires_on": "2026-11-12"},
                     f"Đã gia hạn quyền thư mục finance/Q3 của bạn tới 12/11/2026. {CONFIRM_OPEN}", id="extend-du"),
        pytest.param(action("extend_permission", params={"resource_path": "finance/Q3", "duration_days": 30}), {},
                     f"Đã gia hạn quyền thư mục finance/Q3 của bạn. {CONFIRM_OPEN}", id="extend-thieu-han"),
    ],
)  # fmt: skip
def test_m1_templates_new_actions(act: Action, outputs: dict[str, str], expected: str) -> None:
    """m1 / bảng 7.3: chữ CHÍNH XÁC từng mẫu; thiếu giá trị → bỏ cụm."""
    assert _text(act, outputs) == expected


VIEW_ROWS: tuple[PermRow, ...] = (("finance/Q3", "read", date(2026, 11, 2)), ("finance/public-reports", "read", None))


def test_m1_view_permissions_rows() -> None:
    assert _text(action("view_permissions"), rows=VIEW_ROWS) == (
        "Quyền truy cập hiện có của bạn: finance/Q3 (read, hết hạn 02/11/2026); finance/public-reports (read, không thời hạn). "
        f"{CONFIRM_VIEW}"
    )


def test_m1_view_permissions_other_person() -> None:
    text = _text(action("view_permissions", rf="nv005"), rows=VIEW_ROWS[:1])
    assert text == f"Quyền truy cập hiện có của nv005: finance/Q3 (read, hết hạn 02/11/2026). {CONFIRM_VIEW_OTHER}"


def test_m1_view_permissions_no_rows() -> None:
    assert _text(action("view_permissions"), rows=()) == (
        f"Quyền truy cập hiện có của bạn: chưa thấy quyền nào. {CONFIRM_VIEW}"
    )


def test_m1_view_permissions_unreadable() -> None:
    assert _text(action("view_permissions"), rows=None) == (
        "Mình chưa đọc được danh sách quyền truy cập của bạn. Bạn liên hệ IT để kiểm lại rồi xác nhận giúp mình nhé."
    )


# ---- m1: VPN chữ cũ ------------------------------------------------------------------------------------------------------------


def test_m1_vpn_renew_text_unchanged() -> None:
    """Chữ cũ (`test_b17_execute.test_tc02_auto_executes_once_then_b18_result`) qua chữ ký mới."""
    assert _text(action("renew_vpn_cert"), {"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"}) == (
        "Đã gia hạn chứng chỉ VPN cho máy LAP-0342, hiệu lực tới 29/09/2027. Bạn thử kết nối lại rồi xác nhận giúp mình nhé."
    )


def test_m1_vpn_renew_without_expiry_unchanged() -> None:
    """Chữ cũ (`test_b17_execute.test_q3h2_c_bad_outputs_dropped_and_not_in_message`)."""
    assert _text(action("renew_vpn_cert"), {"serial": "VPN-NEW-0001"}) == (
        "Đã gia hạn chứng chỉ VPN cho máy LAP-0342. Bạn thử kết nối lại rồi xác nhận giúp mình nhé."
    )


def test_n10_vpn_other_person() -> None:
    """Lô N (N10): VPN cho máy của người khác → câu xác nhận cho bên thứ ba (chỉ đổi câu cuối)."""
    assert _text(action("renew_vpn_cert", rf="nv005"), {"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"}) == (
        f"Đã gia hạn chứng chỉ VPN cho máy LAP-0342, hiệu lực tới 29/09/2027. {CONFIRM_VPN_OTHER}"
    )
    assert _text(action("reissue_vpn_access", rf="nv005"), {}).endswith(f". {CONFIRM_VPN_OTHER}")


def test_n10_service_flag_on_self_keeps_old_text() -> None:
    """Lô N (N10): tự yêu cầu cho mình → câu cũ y nguyên, kể cả khi fact dịch vụ bật (chỉ ca người khác mới đổi)."""
    act = action("unlock_account", params={"account_type": "ad"}, facts=SERVICE_FACTS)
    assert _text(act) == f"Đã mở khoá tài khoản đăng nhập (AD) của bạn. {CONFIRM_LOGIN}"


def test_m1_vpn_check_status_unchanged() -> None:
    """Chữ cũ (`test_b17_execute.test_check_vpn_status_r16_no_write`): facts cert hết hạn 3 ngày, lần kết nối cuối lỗi."""
    text = _text(action("check_vpn_status"))
    assert "đã hết hạn, quá hạn 3 ngày" in text and "không thành công" in text


def test_m1_vpn_reissue_has_template() -> None:
    """Mẫu reissue có (không rơi về câu chung / không ném); chữ chính xác không có trong test cũ được phép đọc → chỉ kiểm định danh."""
    text = _text(action("reissue_vpn_access"), {"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"})
    assert "LAP-0342" in text and "29/09/2027" in text


# ---- m2: outputs / params sai mẫu không vào tin ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("act", "outputs", "expected", "absent"),
    [
        pytest.param(action("install_software"), {"software": "zoom", "version": "1.0; rm -rf"},
                     f"Đã cài Zoom lên máy LAP-0342. {CONFIRM_OPEN}", "rm -rf", id="version-rac"),
        pytest.param(action("install_software"), {"software": "Zoom Pro; x", "version": "6.1"},
                     f"Đã cài Zoom phiên bản 6.1 lên máy LAP-0342. {CONFIRM_OPEN}", "Zoom Pro", id="software-rac"),
        # Q-T24-7 = A (duyệt MẪU B DỪNG 1): `version` chỉ số + dấu chấm; `{software}` lấy từ `params` (tên đã chuẩn hoá) dù tool trả khác
        pytest.param(action("install_software"), {"software": "zoom", "version": "pay.evil-site.com"},
                     f"Đã cài Zoom lên máy LAP-0342. {CONFIRM_OPEN}", "evil-site", id="version-ten-mien"),
        pytest.param(action("install_software"), {"software": "photoshop", "version": "6.1"},
                     f"Đã cài Zoom phiên bản 6.1 lên máy LAP-0342. {CONFIRM_OPEN}", "photoshop", id="software-tool-tra-khac"),
        pytest.param(action("grant_permission"), {"level": "admin", "expires_on": "2026-11-12"},
                     "Đã cấp quyền thư mục finance/public-reports cho bạn, hiệu lực tới 12/11/2026. "
                     f"{CONFIRM_OPEN}", "admin", id="level-la"),
        pytest.param(action("grant_permission"), {"level": "read", "expires_on": "2026-13-45"},
                     f"Đã cấp quyền đọc thư mục finance/public-reports cho bạn. {CONFIRM_OPEN}", "2026-13-45", id="ngay-rac"),
        pytest.param(action("grant_permission", params={"resource_path": "finance/../hr", "permission_level": "read",
                                                        "duration_days": 30}),
                     {"level": "read", "expires_on": "2026-11-12"},
                     "Đã cấp quyền đọc thư mục được yêu cầu cho bạn, hiệu lực tới 12/11/2026. "
                     f"{CONFIRM_OPEN}", "..", id="path-dot-dot"),
        pytest.param(action("extend_permission", params={"resource_path": "../../etc/passwd", "duration_days": 30}),
                     {"expires_on": "2026-11-12"},
                     f"Đã gia hạn quyền thư mục được yêu cầu của bạn tới 12/11/2026. {CONFIRM_OPEN}", "passwd",
                     id="extend-path-rac"),
        pytest.param(action("reset_password", params={"account_type": "ad"}), {"delivered_via": "email<script>"},
                     "Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của bạn. Bạn cần đổi mật khẩu ở lần đăng nhập tới. "
                     f"{CONFIRM_LOGIN}", "<script>", id="delivered-rac"),
    ],
)  # fmt: skip
def test_m2_bad_values_dropped(act: Action, outputs: dict[str, str], expected: str, absent: str) -> None:
    """m2 (M-T24-6): `result_text` TỰ lọc `outputs` theo mẫu P4 và định danh `params` theo mẫu — sai mẫu bị bỏ, không vào tin."""
    text = _text(act, outputs)
    assert absent not in text
    assert text == expected


# ---- m3: view_permissions ≤ 10 dòng; permission_rows ------------------------------------------------------------------------


def test_m3_view_permissions_caps_at_ten_rows() -> None:
    rows = tuple((f"finance/f{i:02d}", "read", None) for i in range(12))
    text = _text(action("view_permissions"), rows=rows)
    assert text.count("(read") == 10
    for i in range(10):
        assert f"finance/f{i:02d}" in text
    assert "finance/f10" not in text and "finance/f11" not in text


def _raw_row(path: Any, level: Any = "read", expires_at: str | None = None) -> dict[str, Any]:
    return {"path": path, "level": level, "granted_at": "2026-09-01T03:00:00+00:00", "expires_at": expires_at,
            "status": "active"}  # fmt: skip


def test_m3_permission_rows_local_date() -> None:
    """`expires_at` đổi sang NGÀY theo `tz` của policy (18:30Z ngày 1 = 01:30 ngày 2 giờ VN); None = không thời hạn."""
    raw = [_raw_row("finance/Q3", expires_at="2026-11-01T18:30:00+00:00"), _raw_row("finance/public-reports")]
    assert permission_rows(raw, TZ) == (("finance/Q3", "read", date(2026, 11, 2)), ("finance/public-reports", "read", None))


def test_m3_permission_rows_drop_bad_rows() -> None:
    """Dòng path sai mẫu / level lạ / không phải dict bị bỏ; dòng tốt giữ nguyên thứ tự."""
    raw = [_raw_row("../etc/passwd"), _raw_row("finance/Q3", level="admin"), "khong-phai-dict", 42,
           _raw_row("finance/public-reports", level="write")]  # fmt: skip
    assert permission_rows(raw, TZ) == (("finance/public-reports", "write", None),)


@pytest.mark.parametrize("raw", [None, "abc", {"path": "finance/Q3"}, 7], ids=["none", "chuoi", "dict", "so"])
def test_m3_permission_rows_not_a_list_is_none(raw: object) -> None:
    assert permission_rows(raw, TZ) is None


def test_m3_permission_rows_empty_list() -> None:
    assert permission_rows([], TZ) == ()
