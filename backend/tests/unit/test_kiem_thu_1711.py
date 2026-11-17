"""Kiểm thử 17/11 (TA, 27 ca nhân viên + trưởng phòng trên máy demo) — ba lỗi sửa bằng CODE (không đổi prompt, không đổi luật):

1. Mã nhân viên đã ghi trong câu ("… cho An (nv001)") mà B11 vẫn hỏi "tài khoản của ai" → `domain/target.sole_employee_code`: ĐÚNG MỘT mã
   `nvNNN` khác người gửi → dùng làm `target_user` (như người dùng trả lời câu hỏi); hai mã trở lên / chỉ có mã của chính mình → vẫn hỏi.
2. Máy in, "Chưa ổn" vòng 1: câu trả lời hứa "mình sẽ chuyển bạn cho kỹ thuật viên nhé" rồi lại hỏi Đã ổn / Chưa ổn — không chuyển thật.
   Vòng hỏi tiếp: hứa chuyển → E8 thật; tài liệu hết căn cứ → E8 (không phải E3 "chưa có thông tin"), ghi chú của vòng đó vào bàn giao.
3. "Kiểm tra giúp em chứng chỉ VPN trên máy LAP-0417 còn hạn không" ra E3 (KB không có số liệu từng máy) → câu hỏi VPN về máy của chính
   người gửi đã có fact chứng chỉ → B11 với `action=check_vpn_status` (chỉ đọc). Nhánh báo lỗi Q2 M1 (`symptom`) giữ E3 như cũ.
"""

from typing import Any

import pytest
from app.domain.messages import FOLLOWUP_PREFIX
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.domain.target import sole_employee_code
from app.graph.nodes.b10_route import (
    followup_note,
    promises_handoff,
    vpn_status_fallback,
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


def test_vpn_status_fallback_conditions() -> None:
    ok = {"intent": "vpn", "slots": {"device_id": "LAP-0417", "action": "check_vpn_status"}, "facts": dict(CHAU)}
    assert vpn_status_fallback(ok)
    assert vpn_status_fallback({**ok, "slots": {"device_id": "LAP-0417"}})
    for bad in (
        {**ok, "intent": "access"},
        {**ok, "slots": {"device_id": "LAP-0417", "action": "renew_vpn_cert"}},  # B3 nhận hành động GHI → không ép
        {**ok, "slots": {"action": "check_vpn_status"}},  # chưa có mã máy
        {**ok, "facts": {**CHAU, "device_owner_is_requester": False}},  # máy người khác
        {**ok, "facts": {k: v for k, v in CHAU.items() if k != "cert_status"}},
        {**ok, "followup_round": 1},
    ):
        assert not vpn_status_fallback(bad), bad


@pytest.mark.asyncio
async def test_vpn_status_question_without_kb_goes_to_check_not_e3() -> None:
    def answer(_: Any) -> Reply:
        return Reply({"answer_markdown": "", "citations": [], "steps": [], "cannot_answer": True})

    h, _ = _env(need="info", answer=answer)
    state = _state(redacted_request="Kiểm tra giúp em chứng chỉ VPN trên máy LAP-0501 còn hạn không",
                   slots={"device_id": "LAP-0501", "action": "check_vpn_status"})  # fmt: skip
    out = await _node(h, state)
    assert (out["status"], out["next"], out["need_type"]) == (S_RETRIEVING, "b11_slots", "action")
    assert out["slots"] == {"device_id": "LAP-0501", "action": "check_vpn_status"}
    assert "exit_code" not in out and h.notifier.sent == []


@pytest.mark.asyncio
async def test_symptom_path_without_kb_still_e3() -> None:
    def answer(_: Any) -> Reply:
        return Reply({"answer_markdown": "", "citations": [], "steps": [], "cannot_answer": True})

    h, _ = _env(need="action", answer=answer)  # Q2 M1: báo lỗi, chưa nêu hành động, chứng chỉ còn hạn → nhánh info
    out = await _node(h, _state())
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E3")
