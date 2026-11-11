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
    # bổ sung 12/11 02:30 — câu đo trên máy demo (LLM thật): rút/bỏ/hạ quyền → hỏi lặp hoặc phiếu CẤP quyền; "khoá … lại" → dựng
    # hành động MỞ khoá; "không cần … nữa" → E3; lộ / bị hack → TỰ đặt lại mật khẩu email, mật khẩu tạm gửi vào hộp thư bị chiếm
    ("Rút quyền ghi thư mục hr/salaries của em, em chuyển bộ phận rồi", "access", "revoke"),
    ("Bỏ quyền đọc thư mục shared/templates của em đi", "access", "revoke"),
    ("Hạ quyền thư mục engineering/specs của em từ ghi xuống chỉ đọc thôi", "access", "revoke"),
    ("gỡ quyền ghi", "access", "revoke"),
    ("rut quyen ghi finance/Q3 cua em", "access", "revoke"),
    ("Khoá tài khoản ERP của em lại giúp em, em nghi bị lộ mật khẩu", "account", "lock"),
    ("khoá lại tài khoản email của em giúp", "account", "lock"),
    ("Không cần gia hạn VPN cho máy LAP-0342 nữa đâu, em sắp trả máy", "vpn", "negate"),
    ("Em không cần quyền đọc finance/Q3 nữa, gỡ giúp em", "access", "negate"),
    ("khong can gia han vpn nua", "vpn", "negate"),
    ("Em bị lộ mật khẩu email rồi, đặt lại giúp em", "account", "compromised"),
    ("Tài khoản email của em hình như bị hack, có người gửi mail lạ từ hộp thư em, đổi mật khẩu gấp giúp em", "account", "compromised"),
    ("Hình như có người lấy được mật khẩu AD của em, có đăng nhập lạ lúc 2h sáng", "account", "compromised"),
    ("có người đăng nhập vào tài khoản email của em lúc nửa đêm", "account", "compromised"),
    ("Em lỡ nhập mật khẩu vào trang web lạ trong email, đổi mật khẩu giúp em", "account", "compromised"),
    ("tài khoản email em bị chiếm mất rồi", "account", "compromised"),
    ("em bi lo mk email r, reset giup e", "account", "compromised"),
    ("tai khoan email bi hack roi doi mk gap", "account", "compromised"),
    ("co nguoi biet mk cua em roi", "account", "compromised"),
    ("my account was hacked, please reset", "account", "compromised"),
    ("Tài khoản AD bị khoá liên tục, chắc có người dò mật khẩu, mở giúp em", "account", "compromised"),
    ("Có người đang cố đăng nhập tài khoản email em", "account", "compromised"),
    ("ai đó đăng nhập vào email của em", "account", "compromised"), ("ai do dang nhap vao email cua em", "account", "compromised"),
    ("hình như ai đó biết mật khẩu của em", "account", "compromised"),
    ("Em nhận được thông báo đăng nhập từ thiết bị lạ", "account", "compromised"),
    ("em nhận được mã OTP lạ dù không đăng nhập", "account", "compromised"),
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
    # tự soát 12/11 trên bộ đánh giá (eval/probe cong5): mất PHỤ KIỆN, không phải mất máy
    ("Máy LAP-0342 của mình bị mất sạc, công ty có cấp lại không?", "vpn"),
    ("laptop em bị mất chuột với tai nghe", "software"),
    ("may tinh em bi mat sac roi", "vpn"),
    ("xoá cache Teams rồi cài lại Teams giúp em", "software"),
    # bổ sung 12/11 02:30 — câu thường gặp gần nghĩa với mẫu mới
    ("Em lỡ nhập sai mật khẩu nhiều lần nên bị khoá tài khoản, mở giúp em", "account"),
    ("Khoá tài khoản tự mở lại sau bao lâu vậy?", "account"), ("Sao khoá tài khoản cứ tự bật lại vậy?", "account"),
    ("Mở khoá tài khoản email giúp em, em bị khoá lại rồi", "account"),
    ("tài khoản bị khoá lại sau 5 lần nhập sai, mở giúp", "account"),
    ("cấp toàn bộ quyền đọc thư mục shared/templates cho em", "access"),
    ("cap toan bo quyen doc thu muc shared/templates cho em", "access"),
    ("Em bị rút quyền đọc finance/Q3 rồi, cấp lại giúp em", "access"),
    ("em đã gỡ quyền cũ, giờ xin quyền mới", "access"),
    ("Gia hạn quyền đọc finance/Q3 thêm 30 ngày", "access"),
    ("Mình cần quyền đọc và ghi để kiểm tra dữ liệu, không cần quyền xóa.", "access"),
    ("Tên đăng nhập là an.nv, quên mật khẩu rồi", "account"), ("ten dang nhap la an.nv, quen mat khau", "account"),
    ("Em cần đăng nhập lại mà quên mật khẩu", "account"),
    ("Em không cần phải nhập mật khẩu nữa sau khi đặt lại à?", "account"),
    ("Có ai biết cách gia hạn VPN không?", "vpn"), ("co ai biet cach gia han vpn khong", "vpn"),
    ("Có ai đăng nhập được VPN không, em không vào được", "vpn"), ("co ai dang nhap duoc vpn ko", "vpn"),
    ("Có ai hỗ trợ đặt lại mật khẩu email không?", "account"),
    ("ổ C bị chiếm hết dung lượng, gỡ bớt ứng dụng giúp em", "vpn"), ("o C bi chiem het dung luong", "vpn"),
    ("Mã OTP không về điện thoại, đặt lại mật khẩu giúp em", "account"), ("nhờ ai đó cài giúp em Zoom", "software"),
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


COMPROMISED = "Em bị lộ mật khẩu email rồi, đặt lại giúp em"


@pytest.mark.asyncio
async def test_b3_compromised_account_escalates_without_reset() -> None:
    """Đo 12/11 (LLM thật): câu này được TỰ đặt lại mật khẩu email, mật khẩu tạm gửi "qua email" — vào chính hộp thư đã lộ.
    KB-GEN-008: nghi lộ / bị chiếm là sự cố an toàn thông tin do kỹ thuật viên xử lý → E1, không dựng hành động."""
    v, row, h, _gw = await _run(lambda _: out(item("account", 0.95, span=COMPROMISED, action="reset_password",
                                                  slots={"account_type": "email"})), text=COMPROMISED)  # fmt: skip
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", "reverse_action_requested")
    assert row["detail"]["reverse_action"] == "compromised"
    assert v.get("intended_action") is None
    assert not [r for r in h.audit.rows if r["step"] in ("B6", "B11", "B12")]


@pytest.mark.asyncio
async def test_b3_reverse_row_passes_audit_check() -> None:
    """Soát 12/11: dòng B4 `reverse_action_requested` không có intent/độ tin cậy (rẽ trước khi chọn ý) — audit_check không được báo
    thiếu điểm 1 (trước đó mọi ticket D-84 đều bị báo thiếu)."""
    from app.audit.check import required

    _v, row, h, _gw = await _run(lambda _: out(item("vpn", 0.95, span=LOST, action="reissue_vpn_access")), text=LOST)
    rows = [r for r in h.audit.rows if r["ticket_id"] == row["ticket_id"]]
    assert [(m.point, m.fields) for m in required(row["ticket_id"], rows, final_state=None)] == []


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
