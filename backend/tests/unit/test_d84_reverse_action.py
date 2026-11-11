"""D-84 (kiểm thử máy demo 12/11, LLM thật): người dùng xin thao tác NGƯỢC — hệ thống không có thao tác đó.

Đo được trên máy demo: "mất laptop, thu hồi VPN" → phiếu CẤP LẠI VPN; "gỡ Zoom" → hành động CÀI Zoom; trả lời "thôi đừng gia hạn" → phiếu
GIA HẠN. Ban đêm chỉ thành phiếu duyệt nhờ R18 (ngoài giờ); trong giờ, luật allow tự làm — âm tính giả.

Hợp đồng:
- `reverse_action_kind` THUẦN, tất định, chỉ xét khi có intent GHI; trả nhãn loại, không trả chữ.
- B3: khớp → E1 `reverse_action_requested` (step B4), KHÔNG tới B6/B11, không slot, không hành động; audit chỉ có nhãn loại.
- clarify_wait: câu TRẢ LỜI khớp → E1 cùng lý do, không gọi `b11_extract_slots`, câu trả lời (đã che) vẫn vào `conversation`.
- Không khớp nhầm các câu thường gặp ("VPN bị mất kết nối", "tài khoản bị khoá, mở giúp", "mạng chặn VPN", "gỡ lỗi"…).
"""

from typing import Any

import pytest
from app.domain.exit_codes import REASON_DETAILS
from app.domain.reverse_action import WRITE_INTENTS, reverse_action_kind
from app.domain.states import S_CLARIFYING, S_ESCALATED
from tests.unit.test_b03_classify import _run, item, out
from tests.unit.test_b11_extract_question import _graph, _reply, _submit

# ---- bộ dò thuần ---------------------------------------------------------------------------------------------------------------

POSITIVE = [
    ("Em làm mất laptop LAP-0610 rồi, chặn/thu hồi VPN máy đó gấp giúp em", "vpn", "lost_device"),
    ("Laptop LAP-0342 của em bị mất trộm, thu hồi chứng chỉ VPN của máy đó giúp em", "vpn", "lost_device"),
    ("laptop em bị mất rồi, làm sao với VPN", "vpn", "lost_device"),
    ("em mat laptop roi, thu hoi vpn giup em", "vpn", "lost_device"),
    ("Em đánh rơi điện thoại, đặt lại mật khẩu email giúp em", "account", "lost_device"),
    ("điện thoại em bị trộm, reset mật khẩu giúp", "account", "lost_device"),
    ("Thu hồi quyền của nv004 vào thư mục finance/Q3", "access", "revoke"),
    ("vô hiệu hoá tài khoản của bạn nv006", "account", "revoke"),
    ("Email em bị khoá liên tục, chắc có người dò mật khẩu. ĐỪNG mở khoá, khoá hẳn hoặc kiểm tra giúp em", "account", "lock"),
    ("khoá tài khoản email giúp em, em nghi bị lộ", "account", "lock"),
    ("LAP-0417, à thôi đừng gia hạn, chỉ kiểm tra thôi", "vpn", "negate"),
    ("thoi khoi gia han", "vpn", "negate"),
    ("huỷ yêu cầu này giúp em", "vpn", "cancel"),
    ("Gỡ Zoom khỏi máy LAP-0342 giúp em", "software", "uninstall"),
    ("go bo zoom tren may em", "software", "uninstall"),
]

NEGATIVE = [
    ("VPN bị mất kết nối liên tục", "vpn"), ("máy em mất mạng hoài", "vpn"), ("laptop mất 10 phút mới lên", "vpn"),
    ("mấy hôm nay mất kết nối VPN", "vpn"), ("máy em mất hết icon", "vpn"), ("điện thoại em mất sóng nên không nhận SMS", "account"),
    ("tài khoản AD của em bị khoá rồi, mở giúp em", "account"), ("mở khoá tài khoản email giúp em", "account"),
    ("tk ad cua e bi khoa r, mo giup e voi", "account"), ("đổi mật khẩu rồi mà vẫn bị khoá tài khoản", "account"),
    ("mạng công ty chặn VPN, em không vào được", "vpn"), ("gỡ lỗi VPN giúp em", "vpn"),
    ("em dùng cài đặt mặc định mà VPN vẫn lỗi", "vpn"), ("Gia hạn chứng chỉ VPN giúp em", "vpn"),
    ("Cài 7-Zip lên máy LAP-0417 giúp mình", "software"), ("Cho mình quyền đọc thư mục shared/templates", "access"),
    ("quen mk ad r reset giup e", "account"), ("Mất bao lâu để cấp quyền?", "access"), ("Quên mật khẩu email", "account"),
    ("VPN báo lỗi 809 phải làm sao vậy bạn", "vpn"),
    # tự soát 12/11: việc ĐÃ xảy ra (kể lại) — người dùng xin làm thuận, không phải xin thao tác ngược
    ("em bị thu hồi quyền truy cập VPN, cấp lại giúp em", "vpn"),
    ("VPN không vào được, em đã xoá chứng chỉ cũ và cài lại ABC Connect", "vpn"),
    ("em đã gỡ Zoom rồi cài lại mà vẫn lỗi, cài lại giúp em", "software"),
    ("em vừa xoá nhầm quyền thư mục shared/templates, cấp lại giúp em", "access"),
    ("em bi thu hoi quyen vpn, cap lai giup em", "vpn"),
]  # fmt: skip


@pytest.mark.parametrize(("text", "intent", "kind"), POSITIVE)
def test_detects_reverse_requests(text: str, intent: str, kind: str) -> None:
    assert reverse_action_kind(text, {intent}) == kind


@pytest.mark.parametrize(("text", "intent"), NEGATIVE)
def test_common_requests_not_flagged(text: str, intent: str) -> None:
    assert reverse_action_kind(text, {intent}) is None


@pytest.mark.parametrize("intents", [set(), {"it_help"}, {"out_of_scope"}])
def test_only_write_intents(intents: set[str]) -> None:
    """Không có intent ghi → không có gì để ánh xạ ngược (it_help "mất laptop phải làm sao" vẫn được trả lời KB-GEN-009)."""
    assert reverse_action_kind("Em làm mất laptop rồi, thu hồi VPN giúp em", intents) is None
    assert WRITE_INTENTS == {"vpn", "account", "access", "software"}


def test_uninstall_only_with_software_intent() -> None:
    assert reverse_action_kind("gỡ Zoom giúp em", {"vpn"}) is None
    assert reverse_action_kind("gỡ Zoom giúp em", {"vpn", "software"}) == "uninstall"


def test_reason_registered() -> None:
    assert "reverse_action_requested" in REASON_DETAILS


# ---- B3 qua graph --------------------------------------------------------------------------------------------------------------

LOST = "Em làm mất laptop LAP-0342 rồi, thu hồi VPN máy đó giúp em"


@pytest.mark.asyncio
async def test_b3_lost_device_escalates_e1_without_action() -> None:
    """LLM (giả) phân loại vpn + action_hint reissue như đo trên máy demo → B3 vẫn chặn: E1, không B6/B11, không hành động."""
    v, row, h, _gw = await _run(lambda _: out(item("vpn", 0.95, span=LOST, action="reissue_vpn_access",
                                                  slots={"device_id": "LAP-0342"})), text=LOST)  # fmt: skip
    assert v["status"] == S_ESCALATED and v["exit_code"] == "E1"
    assert v["escalation_reason_detail"] == "reverse_action_requested"
    assert v.get("intended_action") is None
    assert (row["step"], row["event"]) == ("B4", "reverse_action_requested")
    assert row["detail"]["reverse_action"] == "lost_device"
    assert LOST not in repr(row["detail"])  # audit chỉ nhãn, không chữ người dùng
    assert not [r for r in h.audit.rows if r["step"] in ("B6", "B11", "B12")]


@pytest.mark.asyncio
async def test_b3_multi_intent_with_reverse_part_escalates_whole_ticket() -> None:
    text = "Cài 7-Zip lên LAP-0342 và gỡ Zoom khỏi máy đó giúp em"
    v, row, _h, _gw = await _run(lambda _: out(item("software", 0.9, span="Cài 7-Zip lên LAP-0342"),
                                               item("software", 0.9, span="gỡ Zoom khỏi máy đó")), text=text)  # fmt: skip
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", "reverse_action_requested")
    assert row["detail"]["reverse_action"] == "uninstall"
    assert not v.get("is_parent")  # không tách ticket con


@pytest.mark.asyncio
async def test_b3_normal_request_unchanged() -> None:
    v, row, _h, _gw = await _run(lambda _: out(item("vpn", 0.95)))
    assert v["status"] != S_ESCALATED or v.get("escalation_reason_detail") != "reverse_action_requested"
    assert row["detail"]["reverse_action"] is None


# ---- clarify_wait --------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarify_reply_negating_action_escalates_without_extract() -> None:
    h, gw = _graph()
    v = await _submit(h)
    assert v["status"] == S_CLARIFYING
    v = await _reply(h, "LAP-0342, à thôi đừng gia hạn, chỉ kiểm tra thôi")
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", "reverse_action_requested")
    assert gw.llm.calls_for("b11_extract_slots") == []
    assert any(m.get("role") == "user" and "đừng gia hạn" in m["text"] for m in v["conversation"])  # câu trả lời (đã che) vẫn lưu
    assert v.get("intended_action") is None


@pytest.mark.asyncio
async def test_clarify_normal_reply_unchanged() -> None:
    h, gw = _graph()
    await _submit(h)
    v: dict[str, Any] = await _reply(h, "máy em là LAP-0342")
    assert v.get("escalation_reason_detail") != "reverse_action_requested"
    assert len(gw.llm.calls_for("b11_extract_slots")) == 1


def test_user_message_and_l2_note_declared() -> None:
    from app.settings import get_escalation_templates

    t = get_escalation_templates().of("E1")
    msg = t.user_message_for("reverse_action_requested", it_help=True)
    assert "kỹ thuật viên" in msg and "thu hồi" in msg and "không tự thực hiện" in msg
    assert "NGƯỢC" in t.next_for("reverse_action_requested")
