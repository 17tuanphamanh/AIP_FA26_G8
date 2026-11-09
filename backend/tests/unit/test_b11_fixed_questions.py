"""Q3 M1 (ĐP 09/11): câu hỏi CỐ ĐỊNH cho slot có danh sách giá trị (`account_type`, `action`, `permission_level`).

Bằng chứng (demo, ĐP đã đọc audit): "Tài khoản của em bị khoá … mở giúp em" → B11 hỏi bằng LLM chỉ với TÊN khoá `account_type` → LLM bịa
lựa chọn ("người dùng thường, quản trị, dịch vụ"). Nay: khi MỌI slot đang thiếu thuộc tập có danh sách giá trị → câu cố định khai ở
`config/slots.yaml` (`fixed_questions` từng intent), KHÔNG gọi LLM — như nhánh `TARGET_QUESTION`: vẫn output guard, `notify_user`, hạn
`clarify`, `effects.once` khoá theo lượt. Ghép tối đa 2 câu theo thứ tự thiếu. Còn slot tự do (mã máy, đường dẫn, số ngày…) → nhánh LLM.
"""

from typing import Any

import pytest
from app.domain.slots import FIXED_QUESTION_SLOTS, IntentSlots
from app.domain.states import S_CLARIFYING, S_ESCALATED
from app.graph.nodes import b11_slots
from app.settings import get_slots
from pydantic import ValidationError
from tests.unit.test_nodes_t20a import Nodes, b11_state

PID = "b11_clarify_question"

# Câu ĐP soạn (lời giao Q3 M1) — đúng từng chữ.
ACCOUNT_TYPE_Q = "Tài khoản bạn nói là tài khoản đăng nhập máy tính (Windows), email hay ERP?"
ACCOUNT_ACTION_Q = "Bạn cần mình đặt lại mật khẩu hay mở khoá tài khoản?"
VPN_ACTION_Q = "Bạn cần mình gia hạn chứng chỉ VPN, cấp lại quyền VPN hay chỉ kiểm tra tình trạng VPN?"
ACCESS_ACTION_Q = "Bạn cần xem quyền đang có, xin quyền mới hay gia hạn quyền đã có?"
PERMISSION_Q = "Bạn cần quyền chỉ đọc hay được chỉnh sửa?"

# Mỗi `action_type` của slots.yaml → cụm phải có trong câu hỏi `action` của intent đó (câu phủ đủ lựa chọn, không thêm lựa chọn lạ).
ACTION_WORDS = {
    "renew_vpn_cert": "gia hạn chứng chỉ VPN", "reissue_vpn_access": "cấp lại quyền VPN",
    "check_vpn_status": "kiểm tra tình trạng VPN", "reset_password": "đặt lại mật khẩu", "unlock_account": "mở khoá tài khoản",
    "install_software": "cài", "view_permissions": "xem quyền đang có", "grant_permission": "xin quyền mới",
    "extend_permission": "gia hạn quyền đã có",
}  # fmt: skip
# Giá trị hợp lệ của slot enum (value_rules) → cụm người dùng hiểu được trong câu hỏi.
VALUE_WORDS = {
    "account_type": {"ad": "Windows", "email": "email", "erp": "ERP"},
    "permission_level": {"read": "chỉ đọc", "write": "chỉnh sửa"},
}


class Block:
    """Output guard giả — chặn mọi câu (kiểm câu cố định cũng qua guard)."""

    def violation(self, text: str) -> str:
        return "canary"


async def _b11(n: Nodes, state: dict[str, Any], **over: Any) -> dict[str, Any]:
    return await n.run("b11_slots", b11_slots, state, **over)


# ---- bảng câu trong config ----------------------------------------------------------------------------------------------------


def test_fixed_slots_constant() -> None:
    assert FIXED_QUESTION_SLOTS == frozenset({"account_type", "action", "permission_level"})


@pytest.mark.parametrize("intent", sorted(get_slots().intents))
def test_every_value_list_slot_of_every_intent_has_a_question(intent: str) -> None:
    """Mọi slot enum khai báo của intent (required ∪ optional) có câu cố định; câu `action` nêu ĐỦ mọi `action_types`."""
    spec = get_slots().intents[intent]
    for slot in sorted(FIXED_QUESTION_SLOTS & spec.keys):
        assert spec.fixed_questions.get(slot), (intent, slot)
    if "action" in spec.keys:
        q = spec.fixed_questions["action"]
        for action in spec.action_types:
            assert ACTION_WORDS[action] in q, (intent, action, q)
    for slot, words in VALUE_WORDS.items():
        if slot in spec.keys:
            for word in words.values():
                assert word in spec.fixed_questions[slot], (intent, slot, word)
    assert set(spec.fixed_questions) <= FIXED_QUESTION_SLOTS & spec.keys


def test_dp_wording_exact() -> None:
    intents = get_slots().intents
    assert intents["account"].fixed_questions == {"account_type": ACCOUNT_TYPE_Q, "action": ACCOUNT_ACTION_Q}
    assert intents["vpn"].fixed_questions == {"action": VPN_ACTION_Q}
    assert intents["access"].fixed_questions == {"action": ACCESS_ACTION_Q, "permission_level": PERMISSION_Q}


def test_wording_voice() -> None:
    """Cùng giọng với prompt v3 (M2): xưng "mình", gọi "bạn" — không "chúng tôi", "anh/chị", "ạ", không đánh số."""
    for spec in get_slots().intents.values():
        for q in spec.fixed_questions.values():
            assert "bạn" in q.casefold(), q
            for banned in ("chúng tôi", "anh/chị", "quý khách", " ạ", "(1)", "tôi "):
                assert banned not in q, (banned, q)


@pytest.mark.parametrize(
    "bad",
    [{"device_id": "Máy nào?"}, {"permission_level": "Quyền gì?"}, {"action": ""}],
    ids=["slot-tu-do", "slot-khong-khai-bao", "cau-rong"],
)
def test_fixed_questions_validated(bad: dict[str, str]) -> None:
    """Khoá ngoài tập slot enum, slot không khai báo trong intent, câu rỗng → lỗi schema (không khởi động)."""
    raw = get_slots().intents["vpn"].model_dump(mode="json")
    raw["fixed_questions"] = bad
    with pytest.raises(ValidationError):
        IntentSlots.model_validate(raw)


@pytest.mark.parametrize(
    ("intent", "missing", "expected"),
    [
        ("account", ["account_type"], ACCOUNT_TYPE_Q),
        ("account", ["account_type", "action"], f"{ACCOUNT_TYPE_Q} {ACCOUNT_ACTION_Q}"),
        ("access", ["permission_level", "action"], f"{PERMISSION_Q} {ACCESS_ACTION_Q}"),
        ("vpn", ["action"], VPN_ACTION_Q),
        ("vpn", ["device_id", "action"], None),  # còn slot tự do → LLM
        ("access", ["resource_path", "permission_level", "duration"], None),
        ("account", [], None),
    ],
)  # fmt: skip
def test_fixed_question_of_missing(intent: str, missing: list[str], expected: str | None) -> None:
    assert get_slots().intents[intent].fixed_question(missing) == expected


def test_fixed_question_at_most_two_sentences() -> None:
    spec = IntentSlots(required=("action", "account_type"), optional=("permission_level",), action_types=("x",),
                       fixed_questions={"action": "A?", "account_type": "B?", "permission_level": "C?"})  # fmt: skip
    assert spec.fixed_question(["permission_level", "action", "account_type"]) == "C? A?"


# ---- node B11 -------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a06_unlock_missing_account_type_fixed_question_no_llm() -> None:
    """Ca A06: mở khoá tài khoản, chưa rõ loại (AD của nv007 KHÔNG khoá — không suy được, xem M3) → câu cố định `account_type`,
    0 lời gọi LLM, notify (needs=answer) + hạn clarify như nhánh LLM; audit `prompt` None."""
    n = Nodes()
    out = await _b11(n, b11_state("nv007", "account", {"action": "unlock_account"}, facts={"target_account_locked": False}))
    assert (out.get("status"), out.get("missing_slots"), out.get("clarification_turns")) == (
        S_CLARIFYING, ["account_type"], 1), n.audit.rows
    assert n.gw.llm.calls_for(PID) == []
    assert n.h.notifier.sent == [("t1", ACCOUNT_TYPE_Q, "answer")]
    [q] = out["conversation"]
    assert (q["kind"], q["text"], q["needs"]) == ("question", ACCOUNT_TYPE_Q, "answer")
    [wait] = n.h.deadlines.waits
    assert wait["kind"] == "clarify"
    [row] = [r for r in n.audit.rows if r["event"] == "asked"]
    assert row["detail"]["prompt"] is None and row["detail"]["missing"] == ["account_type"]


@pytest.mark.asyncio
async def test_account_missing_both_joins_two_sentences_in_order() -> None:
    n = Nodes()
    out = await _b11(n, b11_state("nv007", "account", {}))
    assert out["missing_slots"] == ["account_type", "action"]
    assert n.h.notifier.sent == [("t1", f"{ACCOUNT_TYPE_Q} {ACCOUNT_ACTION_Q}", "answer")]
    assert n.gw.llm.calls_for(PID) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "slots", "expected"),
    [
        ("vpn", {"device_id": "LAP-0342"}, VPN_ACTION_Q),
        ("access", {"resource_path": "finance/Q3"}, ACCESS_ACTION_Q),
        ("access", {"action": "grant_permission", "resource_path": "finance/public-reports", "duration": "30"}, PERMISSION_Q),
    ],
)  # fmt: skip
async def test_other_intents_fixed_question(intent: str, slots: dict[str, str], expected: str) -> None:
    n = Nodes()
    out = await _b11(n, b11_state("nv001", intent, slots))
    assert out.get("status") == S_CLARIFYING, n.audit.rows
    assert n.h.notifier.sent == [("t1", expected, "answer")]
    assert n.gw.llm.calls_for(PID) == []


@pytest.mark.asyncio
async def test_free_slot_still_uses_llm() -> None:
    """Thiếu `duration` (slot tự do) → nhánh LLM như cũ."""
    n = Nodes()
    out = await _b11(n, b11_state("nv001", "access", {"action": "grant_permission", "resource_path": "finance/public-reports",
                                                      "permission_level": "read"}))  # fmt: skip
    assert out["status"] == S_CLARIFYING
    assert len(n.gw.llm.calls_for(PID)) == 1


@pytest.mark.asyncio
async def test_output_guard_blocks_fixed_question_zero_messages() -> None:
    """Câu cố định cũng qua output guard: vi phạm → E3 `output_guard_block`, 0 tin, 0 hạn (như nhánh cũ)."""
    n = Nodes()
    out = await _b11(n, b11_state("nv007", "account", {"action": "unlock_account"}), output_guard=Block())
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E3", "output_guard_block")
    assert n.h.notifier.sent == [] and n.h.deadlines.waits == []


@pytest.mark.asyncio
async def test_last_turn_still_e4() -> None:
    n = Nodes()
    turns = n.h.deps().constants.MAX_CLARIFICATION_TURNS
    out = await _b11(n, b11_state("nv007", "account", {"action": "unlock_account"}, clarification_turns=turns))
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E4") and n.h.notifier.sent == []
