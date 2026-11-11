"""D-81 (chấm thử hệ thống thật 11/11, ca T4): xin mở khoá tài khoản CỦA CHÍNH MÌNH mà tài khoản KHÔNG bị khoá.

Trước: B11 dựng `unlock_account` → B12 không luật khớp (R02 cần `target_account_locked`) → B14 → phiếu duyệt → người duyệt duyệt →
thực thi lỗi → E6; tin chờ duyệt còn ghi "mở khoá tài khoản cho tài khoản của bạn". Nay: B11 (`_build`, SAU khi tra lại fact theo slot
cuối) thấy `target_account_locked is False` → KHÔNG dựng Action, bỏ slot `action`, hỏi câu CỐ ĐỊNH (`messages.not_locked_question`, không
LLM). Tài khoản người khác, tài khoản đang khoá, fact thiếu → luồng cũ.

Seed: `nv001` AD không khoá; `nv007` AD không khoá, email KHOÁ; `hr_head` AD khoá.
"""

from typing import Any

import pytest
from app.domain.action import Action
from app.domain.messages import (
    action_on,
    approval_pending_text,
    not_locked_question,
    rejection_text,
    target_phrase,
)
from app.domain.states import S_ASSESSING, S_CLARIFYING, S_ESCALATED
from app.settings import get_policy
from tests.unit.test_nodes_t20a import Nodes, b6_state, b11_state

PID = "b11_clarify_question"
NOT_LOCKED_AD = not_locked_question("ad")


async def _diagnosed(n: Nodes, user: str, slots: dict[str, str]) -> dict[str, Any]:
    out = await n.b6(b6_state(user, "account", slots))
    return out


def _row(n: Nodes, event: str) -> dict[str, Any]:
    [row] = [r for r in n.audit.rows if r["event"] == event]
    return dict(row["detail"])


# ---- B11: hỏi câu cố định thay vì dựng hành động ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_own_ad_not_locked_asks_fixed_question_no_action() -> None:
    n = Nodes()
    b6 = await _diagnosed(n, "nv001", {"action": "unlock_account", "account_type": "ad"})
    assert b6["facts"]["target_account_locked"] is False
    out = await n.b11(b11_state("nv001", "account", b6["slots"], facts=b6["facts"]))
    assert (out.get("status"), out.get("missing_slots")) == (S_CLARIFYING, ["action"])
    assert "intended_action" not in out or out["intended_action"] is None
    assert out["slots"] == {"account_type": "ad"}  # bỏ `action`, giữ loại tài khoản
    assert out["facts"]["target_account_locked"] is False
    assert n.h.notifier.sent == [("t1", NOT_LOCKED_AD, "answer")]
    assert n.gw.llm.calls_for(PID) == []  # câu cố định, không LLM
    detail = _row(n, "asked")
    assert (detail["unlock_not_locked"], detail["prompt"], detail["missing"]) == (True, None, ["action"])
    assert [w["kind"] for w in n.h.deadlines.waits] == ["clarify"]  # có hạn trả lời như mọi câu hỏi B11


@pytest.mark.asyncio
async def test_reply_reset_password_then_builds_reset() -> None:
    """Người dùng trả lời "đặt lại mật khẩu" → slot `action` mới → luồng thường (dựng `reset_password`)."""
    n = Nodes()
    out = await n.b11(b11_state("nv001", "account", {"account_type": "ad", "action": "reset_password"}, clarification_turns=1))
    assert out.get("status") == S_ASSESSING, n.audit.rows
    assert (out["intended_action"].type, out["intended_action"].target) == ("reset_password", "user:nv001")


@pytest.mark.asyncio
async def test_email_locked_but_ad_not_locked_checks_the_type_asked() -> None:
    """Fact theo loại tài khoản của slot cuối: email đang khoá → dựng mở khoá; AD không khoá → hỏi."""
    n = Nodes()
    out = await n.b11(b11_state("nv007", "account", {"action": "unlock_account", "account_type": "email"}))
    assert out.get("status") == S_ASSESSING, n.audit.rows
    assert out["intended_action"].type == "unlock_account"
    n2 = Nodes()
    out2 = await n2.b11(b11_state("nv007", "account", {"action": "unlock_account", "account_type": "ad"}))
    assert (out2.get("status"), out2.get("missing_slots")) == (S_CLARIFYING, ["action"])
    assert n2.h.notifier.sent == [("t1", NOT_LOCKED_AD, "answer")]


@pytest.mark.asyncio
async def test_own_locked_still_builds_unlock() -> None:
    n = Nodes()
    out = await n.b11(b11_state("hr_head", "account", {"action": "unlock_account", "account_type": "ad"}))
    assert out.get("status") == S_ASSESSING, n.audit.rows
    assert out["intended_action"].type == "unlock_account"
    assert _row(n, "action_built")["unlock_not_locked"] is False


@pytest.mark.asyncio
async def test_other_persons_account_keeps_old_flow() -> None:
    """Tài khoản người khác không khoá: không đổi (Action dựng, B12/B14/người duyệt quyết) — D-81 chỉ thu hẹp ca của chính mình."""
    n = Nodes()
    out = await n.b11(b11_state("nv001", "account", {"action": "unlock_account", "account_type": "ad", "target_user": "nv007"}))
    assert out.get("status") == S_ASSESSING, n.audit.rows
    assert out["intended_action"].target == "user:nv007"
    assert n.h.notifier.sent == []


@pytest.mark.asyncio
async def test_reset_password_on_unlocked_account_unchanged() -> None:
    n = Nodes()
    out = await n.b11(b11_state("nv001", "account", {"action": "reset_password", "account_type": "ad"}))
    assert out.get("status") == S_ASSESSING
    assert out["intended_action"].type == "reset_password"


@pytest.mark.asyncio
async def test_turns_exhausted_escalates_e4_instead_of_asking() -> None:
    """Vẫn đòi mở khoá sau đủ lượt hỏi → E4 `clarification_exhausted` (kỹ thuật viên), không hỏi thêm, không dựng hành động."""
    n = Nodes()
    turns = get_policy().constants.MAX_CLARIFICATION_TURNS
    out = await n.b11(b11_state("nv001", "account", {"action": "unlock_account", "account_type": "ad"}, clarification_turns=turns))
    assert (out.get("status"), out.get("exit_code"), out.get("escalation_reason_detail")) == (
        S_ESCALATED, "E4", "clarification_exhausted")  # fmt: skip
    assert n.h.notifier.sent == []


# ---- câu chữ --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account_type", "expected"),
    [("ad", "tài khoản đăng nhập (AD) của bạn"), ("email", "tài khoản email của bạn"), (None, "tài khoản của bạn"),
     ("la", "tài khoản của bạn")],
)  # fmt: skip
def test_not_locked_question_text(account_type: str | None, expected: str) -> None:
    text = not_locked_question(account_type)
    assert text.startswith(f"Mình đã kiểm tra: {expected} hiện không bị khoá")
    assert "đặt lại mật khẩu" in text and text.endswith("?")


@pytest.mark.parametrize(
    ("label", "phrase", "expected"),
    [
        ("mở khoá tài khoản", "tài khoản của bạn", "mở khoá tài khoản của bạn"),
        ("mở khoá tài khoản", "tài khoản nv007", "mở khoá tài khoản nv007"),
        ("đặt lại mật khẩu", "tài khoản của bạn", "đặt lại mật khẩu cho tài khoản của bạn"),
        ("gia hạn chứng chỉ VPN", "máy LAP-0342", "gia hạn chứng chỉ VPN cho máy LAP-0342"),
    ],
)  # fmt: skip
def test_action_on_does_not_repeat_tai_khoan(label: str, phrase: str, expected: str) -> None:
    assert action_on(label, phrase) == expected


def test_pending_and_rejection_texts_for_unlock_read_naturally() -> None:
    action = Action.model_construct(type="unlock_account", target="user:nv001")
    phrase = target_phrase(action, "nv001")
    pending = approval_pending_text("unlock_account", phrase)
    rejected = rejection_text("unlock_account", phrase, "other", None)
    assert pending.startswith("Yêu cầu mở khoá tài khoản của bạn cần được duyệt")
    assert rejected.startswith("Yêu cầu mở khoá tài khoản của bạn chưa được duyệt.")
    assert "tài khoản cho tài khoản" not in pending + rejected
