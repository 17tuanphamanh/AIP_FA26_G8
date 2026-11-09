"""Q2 M3 (ĐP 09/11) — tin kết quả `check_vpn_status` có vấn đề thì gợi ý bước tiếp (CHỈ câu chữ, không sinh hành động mới).

Bằng chứng (b): an.nv (LAP-0342, cert quá hạn 4 ngày) nhận "Chứng chỉ… đã hết hạn… Bạn xem thông tin này đã đủ chưa…" rồi dừng,
không biết phải nhắn gì tiếp. Câu gợi ý đứng SAU dòng trạng thái, TRƯỚC câu mời xác nhận cũ (giữ nguyên).
"""

import re
from pathlib import Path
from typing import Any

import pytest
from app.domain.action import FactValue
from app.domain.messages import result_text
from tests.unit._t24 import action

ME = "nv001"
CONFIRM = "Bạn xem thông tin này đã đủ chưa rồi xác nhận giúp mình nhé."
# ĐP 09/11 điểm 4: bỏ "(cần IT duyệt)" (gia hạn máy của mình trong giờ thường tự động — KB-VPN-004); chỉ đúng giao diện — lúc chờ
# xác nhận ô nhập là ghi chú, yêu cầu mới mở bằng mục "Yêu cầu mới" ở thanh bên (FE `auth/permissions.ts` CHAT_NAV).
EXPIRED = ('Chứng chỉ hết hạn là lý do máy không vào được VPN. Để gia hạn, bạn bấm "Yêu cầu mới" ở thanh bên và nhắn '
           '"gia hạn chứng chỉ VPN máy LAP-0342", mình sẽ xử lý.')  # fmt: skip
REVOKED = ('Chứng chỉ đã bị thu hồi nên máy không vào được VPN. Để xin cấp lại, bạn bấm "Yêu cầu mới" ở thanh bên và nhắn '
           '"cấp lại quyền VPN máy LAP-0342".')  # fmt: skip
UNREGISTERED = "Máy chưa đăng ký VPN nên chưa kết nối được; mình chuyển kỹ thuật viên nếu bạn cần đăng ký."
BASE: dict[str, FactValue] = {"device_registered": True, "device_owner_is_requester": True, "last_connection_ok": False}


def _text(facts: dict[str, Any], device: str = "LAP-0342") -> str:
    act = action("check_vpn_status", facts=facts, params={"device_id": device})
    return result_text(act, {}, act.facts, requester_id=ME)


def test_new_request_label_matches_fe_sidebar() -> None:
    fe = (Path(__file__).resolve().parents[3] / "frontend/src/auth/permissions.ts").read_text(encoding="utf-8")
    assert re.search(r'CHAT_NAV: NavItem = \{ to: "/chat", label: "Yêu cầu mới"', fe)
    assert '"Yêu cầu mới"' in EXPIRED and '"Yêu cầu mới"' in REVOKED
    assert "cần IT duyệt" not in EXPIRED + REVOKED


@pytest.mark.parametrize(("status", "phrase"), [
    ("expired", '"gia hạn chứng chỉ VPN máy của bạn"'), ("revoked", '"cấp lại quyền VPN máy của bạn"'),
])  # fmt: skip
def test_device_id_off_pattern_says_your_device(status: str, phrase: str) -> None:
    text = _text({**BASE, "cert_status": status}, device="lap 0342<b>")
    assert phrase in text and "lap 0342" not in text


def test_expired_suggests_renew_message_between_status_and_confirm() -> None:
    text = _text({**BASE, "cert_status": "expired", "cert_days_to_expiry": -4})
    assert text == (
        "Chứng chỉ VPN của máy LAP-0342: đã hết hạn, quá hạn 4 ngày. Lần kết nối gần nhất: không thành công. "
        f"{EXPIRED} {CONFIRM}"
    )


def test_revoked_suggests_reissue() -> None:
    text = _text({**BASE, "cert_status": "revoked"})
    assert REVOKED in text and EXPIRED not in text
    assert text.index("Lần kết nối gần nhất") < text.index(REVOKED) < text.index(CONFIRM)


def test_unregistered_device_suggests_technician() -> None:
    text = _text({**BASE, "device_registered": False, "cert_status": "none"})
    assert UNREGISTERED in text and text.endswith(CONFIRM)
    assert text.index(UNREGISTERED) < text.index(CONFIRM)


def test_unregistered_and_expired_both_sentences() -> None:
    text = _text({**BASE, "device_registered": False, "cert_status": "expired", "cert_days_to_expiry": -1})
    assert EXPIRED in text and UNREGISTERED in text


@pytest.mark.parametrize("facts", [
    {**BASE, "cert_status": "valid", "cert_days_to_expiry": 30, "last_connection_ok": True},
    {**BASE, "cert_status": "none"},
    {"cert_status": "valid"},  # thiếu device_registered → không suy là "chưa đăng ký"
])  # fmt: skip
def test_no_problem_no_suggestion(facts: dict[str, Any]) -> None:
    text = _text(facts)
    for s in (EXPIRED, REVOKED, UNREGISTERED):
        assert s not in text
    assert text.endswith(CONFIRM)
