"""Kiểm thử 17/11 (TA, 27 ca nhân viên + trưởng phòng trên máy demo) — ba lỗi sửa bằng CODE (không đổi prompt, không đổi luật):

1. Mã nhân viên đã ghi trong câu ("… cho An (nv001)") mà B11 vẫn hỏi "tài khoản của ai" → `domain/target.sole_employee_code`: ĐÚNG MỘT mã
   `nvNNN` khác người gửi → dùng làm `target_user` (như người dùng trả lời câu hỏi); hai mã trở lên / chỉ có mã của chính mình → vẫn hỏi.
2. Máy in, "Chưa ổn" vòng 1: câu trả lời hứa "mình sẽ chuyển bạn cho kỹ thuật viên nhé" rồi lại hỏi Đã ổn / Chưa ổn — không chuyển thật.
   Vòng hỏi tiếp: hứa chuyển → E8 thật; tài liệu hết căn cứ → E8 (không phải E3 "chưa có thông tin"), ghi chú của vòng đó vào bàn giao.
3. "Kiểm tra giúp em chứng chỉ VPN trên máy LAP-0417 còn hạn không" ra E3 (KB không có số liệu từng máy), hoặc LLM trả lời "không có thông
   tin về hạn chứng chỉ" dù B6 đã biết (máy demo 17/11 tối) → câu HỎI trạng thái chứng chỉ máy của chính người gửi (`VPN_STATUS_QUESTION`,
   không phải câu hỏi cách làm, không động từ ghi) → B11 với `action=check_vpn_status` (chỉ đọc) NGAY sau `b10_need_type`. Câu báo lỗi
   (Q2 M1) không khớp mẫu → giữ nhánh cũ.
"""

from typing import Any

import pytest
from app.domain.messages import FOLLOWUP_PREFIX, followup_note
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.domain.target import sole_employee_code
from app.graph.nodes.b10_route import (
    promises_handoff,
    vpn_status_fallback,
    vpn_status_question,
)
from app.llm.providers.scripted import Reply
from tests.unit.test_b10_symptom import CHAU, TOP, _env, _node, _state

# ---- 1. mã nhân viên trong câu --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "requester", "expected"),
    [
        ("Cấp quyền chỉ đọc thư mục finance/public-reports trong 30 ngày cho An (nv001) bên phòng mình", "fin_head", "nv001"),
        ("Đặt lại mật khẩu email công ty cho Dũng (NV004) phòng mình", "sales_head", "nv004"),
        ("Kiểm tra giúp chị Lý Văn Em (nv006) còn quyền vào thư mục nào không", "hr_head", "nv006"),
        ("cấp quyền cho nv001 và nv002", "fin_head", None),  # hai mã → vẫn hỏi
        ("tôi là nv001, cấp quyền cho chị Lan", "nv001", None),  # chỉ mã của chính mình
        ("cấp quyền cho nv001, nhắc lại nv001", "fin_head", "nv001"),  # một mã lặp lại = một mã
        ("đặt lại mật khẩu cho anh.nv001x", "fin_head", None),  # dính chữ — không phải mã
        ("gửi tới nv001@demo-corp.local", "fin_head", None),  # địa chỉ email, không phải mã đứng riêng
        ("cấp quyền cho chị Lan trưởng phòng", "nv001", None),
    ],
)
def test_sole_employee_code(text: str, requester: str, expected: str | None) -> None:
    assert sole_employee_code(text, requester) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "asks"),
    [
        ("Đặt lại mật khẩu đăng nhập cho Bình (nv002) phòng mình", False),  # đúng một mã → dùng luôn
        ("Đặt lại mật khẩu đăng nhập cho chị Bình", True),  # không mã → hỏi như cũ
        ("Đặt lại mật khẩu cho nv002 hoặc nv005", True),  # hai mã → hỏi
    ],
)
async def test_b11_uses_code_in_text_instead_of_asking(text: str, asks: bool) -> None:
    from app.domain.action import Action
    from app.domain.states import S_ASSESSING
    from app.domain.target import TARGET_QUESTION
    from app.graph.nodes import b11_slots
    from tests.unit.test_target_guard import b11_state, node

    n = node()
    state = {**b11_state({"action": "reset_password", "account_type": "ad"}, flag=True), "redacted_request": text}
    out = await n.run("b11_slots", b11_slots, state)
    if asks:
        assert out["conversation"][-1]["text"] == TARGET_QUESTION and out.get("intended_action") is None
        return
    assert out["status"] == S_ASSESSING, (out.get("exit_code"), out.get("escalation_reason_detail"))
    action = Action.model_validate(out["intended_action"])
    assert (action.requested_for, action.target) == ("nv002", "user:nv002")
    detail = n.row("B11", "action_built")["detail"]
    assert (detail["target_from_text"], detail["target_required"]) == (True, False)


# ---- 2. vòng hỏi tiếp sau "Chưa ổn" ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "promised"),
    [
        ("Bạn đã gỡ giấy nhưng máy vẫn báo kẹt, mình sẽ chuyển bạn cho kỹ thuật viên nhé.", True),
        ("Mình đã chuyển yêu cầu cho kỹ thuật viên.", True),
        ("Để mình chuyển ngay cho kỹ thuật viên hỗ trợ.", True),
        ("Nếu vẫn lỗi, hãy liên hệ bộ phận IT (máy lẻ 1234).", False),
        ("Chuyển sang chế độ SSTP rồi thử lại.", False),
    ],
)
def test_promises_handoff(text: str, promised: bool) -> None:
    assert promises_handoff(text) is promised


def _followup(**over: Any) -> dict[str, Any]:
    note = "Đã gỡ giấy nhưng máy vẫn báo kẹt"
    tail = FOLLOWUP_PREFIX + note
    base = _state(intent="it_help", redacted_request=f"Máy in tầng 3 báo kẹt giấy hoài\n{tail}", followup_round=1,
                  triage_reply_chars=len(tail), slots={}, facts={})  # fmt: skip
    return {**base, **over}


def test_followup_note_is_the_tail_without_prefix() -> None:
    assert followup_note(_followup()) == "Đã gỡ giấy nhưng máy vẫn báo kẹt"
    assert followup_note({"redacted_request": "x", "triage_reply_chars": 0}) == ""


@pytest.mark.asyncio
async def test_followup_answer_promising_handoff_escalates_e8_with_note() -> None:
    def answer(_: Any) -> Reply:
        return Reply({"answer_markdown": "Bạn đã gỡ giấy nhưng máy vẫn báo kẹt, mình sẽ chuyển bạn cho kỹ thuật viên nhé.",
                      "citations": [TOP[0].chunk_id], "steps": ["Liên hệ bộ phận IT"], "cannot_answer": False})  # fmt: skip

    h, _ = _env(answer=answer)
    out = await _node(h, _followup())
    assert (out["status"], out["exit_code"], out["user_feedback"]) == (S_ESCALATED, "E8", "Đã gỡ giấy nhưng máy vẫn báo kẹt")
    assert h.notifier.sent == []  # câu hứa suông KHÔNG gửi
    [row] = [r for r in h.audit.rows if r["step"] == "B10"]
    assert (row["event"], row["detail"]["followup_dead_end"]) == ("followup_unresolved", "answer_promises_handoff")


@pytest.mark.asyncio
async def test_followup_cannot_answer_is_e8_not_e3() -> None:
    def answer(_: Any) -> Reply:
        return Reply({"answer_markdown": "", "citations": [], "steps": [], "cannot_answer": True})

    h, _ = _env(answer=answer)
    out = await _node(h, _followup())
    assert (out["exit_code"], out.get("escalation_reason_detail")) == ("E8", None)


@pytest.mark.asyncio
async def test_first_round_answer_with_promise_is_sent_as_before() -> None:
    def answer(_: Any) -> Reply:
        return Reply({"answer_markdown": "Nếu vẫn kẹt, mình sẽ chuyển bạn cho kỹ thuật viên.", "citations": [TOP[0].chunk_id],
                      "steps": ["Mở nắp, gỡ giấy"], "cannot_answer": False})  # fmt: skip

    h, _ = _env(answer=answer)
    out = await _node(h, _followup(followup_round=0, triage_reply_chars=0))
    assert out["status"] != S_ESCALATED and len(h.notifier.sent) == 1  # vòng đầu không đổi hành vi


# ---- 3. câu hỏi trạng thái VPN máy của mình ---------------------------------------------------------------------------------------


STATUS_Q = "Kiểm tra giúp em chứng chỉ VPN trên máy LAP-0501 còn hạn không"


@pytest.mark.parametrize(
    ("text", "status"),
    [
        (STATUS_Q, True),
        ("Chứng chỉ VPN máy LAP-0342 của em còn hạn không ạ?", True),
        ("chứng chỉ vpn của em hết hạn chưa", True),
        ("Khi nào chứng chỉ VPN của em hết hạn?", True),
        ("Khi nào chứng chỉ VPN máy LAP-0417 của mình hết hạn?", True),  # máy demo 17/11 22:40 (7 từ chen giữa)
        ("Bao giờ thì cái chứng chỉ VPN trên laptop LAP-0417 của mình hết hạn vậy?", True),
        ("chứng chỉ còn mấy ngày nữa hết hạn", True),
        ("Kiểm tra trạng thái VPN máy LAP-0342", True),
        ("Xem giúp em hạn chứng chỉ VPN", True),
        ("còn hạn k", True),
        ("VPN của em không kết nối được, cứ báo lỗi 809", False),  # Q2 M1: báo lỗi
        ("VPN còn hạn mà vẫn báo lỗi 809", False),  # "còn hạn" không kèm từ hỏi = mô tả
        ("Làm sao biết chứng chỉ VPN còn hạn không?", False),  # hỏi CÁCH làm → KB
        ("Chứng chỉ VPN hết hạn thì làm sao?", False),
        ("chứng chỉ vpn hết hạn rồi, cấp lại giúp mk", False),  # nhờ làm
        ("Gia hạn chứng chỉ VPN giúp em, còn hạn không cũng gia hạn luôn", False),  # động từ ghi
        ("Khi nào hết hạn thì làm sao gia hạn?", False),
    ],
)
def test_vpn_status_question(text: str, status: bool) -> None:
    assert vpn_status_question(text) is status


def test_vpn_status_fallback_conditions() -> None:
    ok = {"intent": "vpn", "redacted_request": STATUS_Q, "slots": {"device_id": "LAP-0417", "action": "check_vpn_status"},
          "facts": dict(CHAU)}  # fmt: skip
    assert vpn_status_fallback(ok)
    assert vpn_status_fallback({**ok, "slots": {"device_id": "LAP-0417"}})
    assert vpn_status_fallback({**ok, "slots": {"device_id": "LAP-0417", "action": "renew_vpn_cert"}})  # B6 tự suy từ chứng chỉ hết hạn
    for bad in (
        {**ok, "intent": "access"},
        {**ok, "redacted_request": "VPN của em không kết nối được, cứ báo lỗi 809"},  # câu báo lỗi
        {**ok, "slots": {"device_id": "LAP-0417", "action": "install_software"}},
        {**ok, "slots": {"action": "check_vpn_status"}},  # chưa có mã máy
        {**ok, "facts": {**CHAU, "device_owner_is_requester": False}},  # máy người khác
        {**ok, "facts": {k: v for k, v in CHAU.items() if k != "cert_status"}},
        {**ok, "followup_round": 1},
    ):
        assert not vpn_status_fallback(bad), bad


@pytest.mark.asyncio
@pytest.mark.parametrize("need", ["info", "action"])
@pytest.mark.parametrize("action", [None, "check_vpn_status", "renew_vpn_cert"])
async def test_vpn_status_question_goes_to_check_before_answer(need: str, action: str | None) -> None:
    """KB CÓ bài (câu trả lời KB hợp lệ) mà vẫn đi kiểm tra: KB không có hạn chứng chỉ từng máy — máy demo 17/11 trả lời "không có thông
    tin" dù B6 đã biết. Không gọi `b10_answer`, không gửi tin."""
    h, gw = _env(need=need)
    slots = {"device_id": "LAP-0501"} | ({"action": action} if action else {})
    out = await _node(h, _state(redacted_request=STATUS_Q, slots=slots))
    assert (out["status"], out["next"], out["need_type"]) == (S_RETRIEVING, "b11_slots", "action")
    assert out["slots"] == {"device_id": "LAP-0501", "action": "check_vpn_status"}
    assert "exit_code" not in out and h.notifier.sent == []
    [row] = [r for r in h.audit.rows if r["step"] == "B10"]
    assert (row["event"], row["detail"]["need_type_override"]) == ("needs_action", "vpn_status_question")
    assert gw.llm.calls_for("b10_answer") == []


@pytest.mark.asyncio
async def test_vpn_how_to_question_still_answers_from_kb() -> None:
    h, _ = _env(need="info")
    out = await _node(h, _state(redacted_request="Làm sao biết chứng chỉ VPN còn hạn không?", slots={"device_id": "LAP-0501"}))
    assert out["status"] != S_ESCALATED and out.get("next") != "b11_slots" and len(h.notifier.sent) == 1


@pytest.mark.asyncio
async def test_symptom_path_without_kb_still_e3() -> None:
    def answer(_: Any) -> Reply:
        return Reply({"answer_markdown": "", "citations": [], "steps": [], "cannot_answer": True})

    h, _ = _env(need="action", answer=answer)  # Q2 M1: báo lỗi, chưa nêu hành động, chứng chỉ còn hạn → nhánh info
    out = await _node(h, _state())
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E3")


# ---- 4. vòng hỏi tiếp mà B3 phân loại lại ra ngoài phạm vi (máy demo 17/11 tối, hoa.bt Outlook) ----------------------------------


def _env_b03(*b03: Any) -> tuple[Any, Any]:
    """Như `test_q13a_hoi_tiep.env` nhưng kịch bản `b03_classify` theo từng vòng."""
    from datetime import timedelta

    from app.core.clock import FakeClock
    from tests.fakes.graph import GraphHarness
    from tests.fakes.identity import ad_user
    from tests.fakes.llm import make_gateway
    from tests.fixtures.llm.vpn import vpn_scripts
    from tests.unit.test_q12_it_help import NOT_ATTACK, SESSION, _rag
    from tests.unit.test_q13a_hoi_tiep import _answer

    clock = FakeClock()
    gw = make_gateway({**vpn_scripts(action=None), "b02_injection_judge": [Reply(NOT_ATTACK)] * 4,  # type: ignore[dict-item]
                       "b03_classify": list(b03), "b10_answer": _answer}, clock=clock)  # fmt: skip
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=_rag(), enable_kb_followup=True)
    h.identity.add_session(SESSION, "nv001", expires_at=clock.now() + timedelta(days=365))
    h.ad.users["nv001"] = ad_user("nv001")
    return h, gw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("second", "why"),
    [
        ([], "out_of_scope"),  # không ý nào (câu ghi chú trần)
        ([{"type": "out_of_scope"}], "out_of_scope"),
        ([{"confidence": 0.3}], "intent_low_confidence"),
    ],
)
async def test_followup_reclassified_out_of_scope_is_e8_with_note(second: list[dict[str, Any]], why: str) -> None:
    from tests.unit.test_q12_it_help import it, out
    from tests.unit.test_q13a_hoi_tiep import submit, unresolved

    items = [it(**({"type_": x["type"]} if "type" in x else {}), **({"confidence": x["confidence"]} if "confidence" in x else {}))
             for x in second]  # fmt: skip
    h, _ = _env_b03(out(it()), out(*items))
    await submit(h)
    v = await unresolved(h, "mạng vẫn vào được, em khởi động lại máy rồi, thư vẫn kẹt")
    assert (v["status"], v["exit_code"]) == (S_ESCALATED, "E8")
    assert v["user_feedback"] == "mạng vẫn vào được, em khởi động lại máy rồi, thư vẫn kẹt"
    [row] = h.audit.of("t1", "followup_unresolved")
    assert (row["step"], row["detail"]["followup_dead_end"]) == ("B4", why)
    assert h.audit.of("t1", "intent_out_of_scope") == [] and h.audit.of("t1", "intent_low_confidence") == []


@pytest.mark.asyncio
async def test_first_round_out_of_scope_still_e1() -> None:
    from tests.unit.test_q12_it_help import it, out
    from tests.unit.test_q13a_hoi_tiep import submit

    h, _ = _env_b03(out(it("out_of_scope")))
    v = await submit(h)
    assert (v["status"], v["exit_code"]) == (S_ESCALATED, "E1")  # vòng đầu: E1 như cũ
    assert h.audit.of("t1", "followup_unresolved") == []


# ---- 5. tin chờ duyệt nêu lý do (D-100 (7)) ------------------------------------------------------------------------------------------


def test_every_approval_rule_has_a_user_reason() -> None:
    import json
    from pathlib import Path

    from app.domain.messages import APPROVAL_REASONS

    rules = json.loads((Path(__file__).resolve().parents[3] / "config" / "policy.json").read_text(encoding="utf-8"))["rules"]
    approval = {r["id"] for r in rules if r["type"] == "approval_required"}
    assert approval == set(APPROVAL_REASONS)  # luật cần duyệt mới → phải khai lý do cho người gửi
    for text in APPROVAL_REASONS.values():
        assert text and not text.endswith(".") and len(text) <= 80


def test_approval_pending_text_with_reason() -> None:
    from app.domain.messages import APPROVAL_PENDING_TAIL, approval_pending_text

    assert approval_pending_text("renew_vpn_cert", "máy LAP-0342", "R18") == (
        "Yêu cầu gia hạn chứng chỉ VPN cho máy LAP-0342 cần được duyệt theo quy định của công ty vì yêu cầu gửi ngoài giờ hành chính. "
        "Mình đã gửi phiếu duyệt; có kết quả mình báo bạn tại đây."
    )
    assert approval_pending_text("renew_vpn_cert", "máy LAP-0342", None).endswith(APPROVAL_PENDING_TAIL)  # HITL do AI: câu cũ
    assert approval_pending_text("renew_vpn_cert", "máy LAP-0342", "R99").endswith(APPROVAL_PENDING_TAIL)
