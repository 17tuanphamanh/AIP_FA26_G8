"""c1 (3c, mục 6.4, 3-Q13) — `build_query`: nối `query_slots` chưa có trong câu; không nối lại mã đã có (khác
hoa/thường vẫn tính là có); không nối `device_id` (không phải query_slots)."""

from app.rag.query import build_query


def test_appends_missing_query_slot() -> None:
    q = build_query("VPN báo lỗi khi kết nối", None, {"error_code": "809"}, query_slots=["error_code"])
    assert q.text == "VPN báo lỗi khi kết nối 809"
    assert q.intent is None


def test_does_not_duplicate_slot_already_in_text_case_insensitive() -> None:
    q = build_query("Lỗi 809 khi kết nối VPN", "vpn", {"error_code": "809"}, query_slots=["error_code"])
    assert q.text == "Lỗi 809 khi kết nối VPN"
    q2 = build_query("Lỗi 809 khi kết nối VPN", "vpn", {"error_code": "  809  "}, query_slots=["error_code"])
    assert q2.text == "Lỗi 809 khi kết nối VPN"


def test_does_not_append_slot_outside_query_slots() -> None:
    q = build_query("Cài phần mềm mới", None, {"device_id": "LAP-001"}, query_slots=["error_code"])
    assert q.text == "Cài phần mềm mới"


def test_skips_missing_or_blank_slot_values() -> None:
    q = build_query("VPN không kết nối được", "vpn", {}, query_slots=["error_code"])
    assert q.text == "VPN không kết nối được"
    q2 = build_query("VPN không kết nối được", "vpn", {"error_code": "   "}, query_slots=["error_code"])
    assert q2.text == "VPN không kết nối được"


def test_intent_passed_through() -> None:
    assert build_query("x", "vpn", {}, query_slots=[]).intent == "vpn"
    assert build_query("x", None, {}, query_slots=[]).intent is None
