"""D-102 (kiểm thử 17/11): câu nêu hai đối tượng cùng loại nối liền → B11 hỏi câu CỐ ĐỊNH làm cái nào trước (không làm một, bỏ một).

Ba lớp: hàm nhận diện (`domain/multi_object`), node B11 (hỏi, bỏ slot, không LLM, chỉ lượt đầu), chuỗi B3→B11→trả lời→B12 (dựng
hành động cho ĐÚNG đối tượng người dùng chọn, không hỏi lại lần hai).
"""

from typing import Any

import pytest
from app.domain.action import Action
from app.domain.multi_object import multi_object, multi_object_question
from app.domain.states import S_ASSESSING, S_CLARIFYING
from app.domain.target import TARGET_QUESTION
from app.graph.nodes import b11_slots
from tests.unit._t20b import classify, item, make_flow
from tests.unit.test_target_guard import b11_state, node

PREFIXES = ("LAP", "PC")


@pytest.mark.parametrize(
    ("intent", "text", "slots", "kind", "names"),
    [
        ("access", "Cấp quyền đọc thư mục shared/templates cho nv005 và nv007", {}, "target_user", ("nv005", "nv007")),
        ("account", "Đặt lại mật khẩu cho Bình (nv002) và Chi (nv005)", {}, "target_user", ("nv002", "nv005")),
        ("account", "Đặt lại mật khẩu cho nv002, nv005", {}, "target_user", ("nv002", "nv005")),
        ("software", "Cài giúp em Zoom và 7-Zip lên máy LAP-0342 với ạ", {}, "software_name", ("Zoom", "7-Zip")),
        ("software", "Cài Zoom, VS Code và 7-Zip", {}, "software_name", ("Zoom", "Visual Studio Code", "7-Zip")),
        ("software", "Cài Zoom và cả phần mềm 7-Zip", {}, "software_name", ("Zoom", "7-Zip")),
        ("software", "Cài Notepad++ và 7zip", {}, "software_name", ("Notepad++", "7-Zip")),
        ("software", "Cài Zoom and FooApp", {"software_name": "Zoom and FooApp"}, "software_name", ()),  # tên lạ: không nêu tên
        ("vpn", "Gia hạn VPN cho LAP-0342 và PC-0977", {}, "device_id", ("LAP-0342", "PC-0977")),
        ("access", "Cấp quyền đọc Finance/Q3 và shared/templates", {}, "resource_path", ("Finance/Q3", "shared/templates")),
    ],
)
def test_detects_joined_objects(intent: str, text: str, slots: dict[str, str], kind: str, names: tuple[str, ...]) -> None:
    found = multi_object(intent, text, slots, device_prefixes=PREFIXES)
    assert found is not None and (found.kind, found.names) == (kind, names)


@pytest.mark.parametrize(
    ("intent", "text", "slots"),
    [
        ("account", "Tôi là nv001, đặt lại mật khẩu cho nv005", {}),  # tự giới thiệu, không phải hai đích
        ("access", "Cấp cho nv005 quyền giống nv007", {}),  # hai mã rời nhau
        ("account", "Đặt lại mật khẩu cho nv002 hoặc nv005", {}),  # "hoặc": chỉ cần một — luồng cũ (TARGET_QUESTION)
        ("account", "Đặt lại mật khẩu cho nv005 và nv005", {}),  # trùng mã
        ("software", "Cài Zoom nhưng bị lỗi trên Chrome", {}),
        ("software", "Cài Zoom hoặc Teams cũng được", {}),
        ("software", "Cài Microsoft Office 365", {}),  # một tên dài, không đếm thêm "office"
        ("software", "Cài Notepad++", {"software_name": "Notepad++"}),  # "+" trong tên, không phải liên từ
        ("software", "Cài Zoom lên LAP-0342", {}),
        ("vpn", "Máy LAP-0342 của em, máy cũ PC-0977 đã trả", {}),
        ("access", "Cấp quyền read/write cho shared/templates đến 30/11", {}),  # read/write, ngày — không phải thư mục
        ("account", "Đặt lại mật khẩu AD và email cho nv005", {}),  # một mã
        ("vpn", "Cài Zoom và 7-Zip", {}),  # tên phần mềm chỉ xét ở intent software
    ],
)
def test_no_false_alarm(intent: str, text: str, slots: dict[str, str]) -> None:
    assert multi_object(intent, text, slots, device_prefixes=PREFIXES) is None


def test_question_is_fixed_text() -> None:
    found = multi_object("software", "Cài Zoom và 7-Zip", {}, device_prefixes=PREFIXES)
    assert found is not None
    assert multi_object_question(found) == (
        "Mỗi yêu cầu mình chỉ xử lý một phần mềm. Bạn muốn cài phần mềm nào trước: Zoom hay 7-Zip? "
        "Phần mềm còn lại bạn gửi một yêu cầu riêng nhé."
    )


# ---- node B11 ------------------------------------------------------------------------------------------------------------------


def _software_state(text: str, *, turns: int = 0) -> dict[str, Any]:
    st = b11_state({"software_name": "Zoom", "device_id": "LAP-0342"}, flag=False, turns=turns)
    return {**st, "intent": "software", "redacted_request": text}


@pytest.mark.asyncio
async def test_b11_asks_fixed_question_drops_slot_no_llm() -> None:
    """Không script `b11_clarify_question` (gọi LLM là ScriptExhausted → E9): câu cố định, slot `software_name` bỏ, máy giữ."""
    n = node()
    out = await n.run("b11_slots", b11_slots, _software_state("Cài giúp em Zoom và 7-Zip lên máy LAP-0342"))
    assert (out["status"], out["next"]) == (S_CLARIFYING, "clarify_wait"), (out.get("exit_code"), out.get("escalation_reason_detail"))
    assert out["conversation"][-1]["text"].startswith("Mỗi yêu cầu mình chỉ xử lý một phần mềm.")
    assert "Zoom hay 7-Zip" in out["conversation"][-1]["text"]
    assert out["missing_slots"][0] == "software_name" and out.get("intended_action") is None
    assert out["slots"] == {"device_id": "LAP-0342"} and out["clarification_turns"] == 1
    detail = n.row("B11", "asked")["detail"]
    assert (detail["multi_object"], detail["prompt"]) == ("software_name", None)


@pytest.mark.asyncio
async def test_b11_account_two_codes_takes_precedence_over_target_question() -> None:
    n = node()
    st = {**b11_state({"action": "reset_password", "account_type": "ad"}, flag=True),
          "redacted_request": "Đặt lại mật khẩu AD cho nv005 và nv007"}  # fmt: skip
    out = await n.run("b11_slots", b11_slots, st)
    text = out["conversation"][-1]["text"]
    assert text != TARGET_QUESTION and "nv005 hay nv007" in text
    assert out["missing_slots"] == ["target_user"]


@pytest.mark.asyncio
async def test_b11_not_rechecked_after_first_turn() -> None:
    """Lượt sau (đã hỏi một lần): câu gốc vẫn có hai tên nhưng không hỏi lại — đi tiếp như luồng cũ (không lặp)."""
    n = node()
    out = await n.run("b11_slots", b11_slots, _software_state("Cài giúp em Zoom và 7-Zip lên máy LAP-0342", turns=1))
    assert out["status"] == S_ASSESSING, (out.get("exit_code"), out.get("escalation_reason_detail"))
    assert Action.model_validate(out["intended_action"]).type == "install_software"
    assert n.row("B11", "action_built")["detail"]["multi_object"] is None


# ---- chuỗi B3 → B11 → trả lời → B12 --------------------------------------------------------------------------------------------


def _reply_slot(key: str) -> Any:
    return lambda variables: {key: str(variables["text"]).strip()}


@pytest.mark.asyncio
async def test_chain_software_two_names_asks_once_then_installs_chosen() -> None:
    text = "Cài giúp em Zoom và 7-Zip lên máy LAP-0342 với ạ"
    f = make_flow(classify(item("software", text, action="install_software",
                                slots={"software_name": "Zoom", "device_id": "LAP-0342"})),
                  extract=_reply_slot("software_name"))  # fmt: skip
    r = await f.submit(text)
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events(f.parent)
    asked = (await f.assistant_msgs())[-1]["text"]
    assert "Zoom hay 7-Zip" in asked
    assert f.h.executor.calls[f.parent] == 0
    r = await f.deliver(f.parent, S_CLARIFYING, {"kind": "user_reply", "text": "7-Zip"})
    v = await f.values(f.parent)
    action = Action.model_validate(v["intended_action"])
    assert action.type == "install_software" and str(action.params.get("software_name")).casefold() == "7-zip", action
    assert sum("Mỗi yêu cầu mình chỉ xử lý" in m["text"] for m in await f.assistant_msgs()) == 1


@pytest.mark.asyncio
async def test_chain_account_two_codes_builds_for_chosen_only() -> None:
    text = "Đặt lại mật khẩu AD cho nv005 và nv007 giúp mình"
    f = make_flow(classify(item("account", text, action="reset_password", slots={"account_type": "ad", "target_user": "nv005"})),
                  extract=_reply_slot("target_user"))  # fmt: skip
    r = await f.submit(text)
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events(f.parent)
    assert "nv005 hay nv007" in (await f.assistant_msgs())[-1]["text"]
    await f.deliver(f.parent, S_CLARIFYING, {"kind": "user_reply", "text": "nv007"})
    v = await f.values(f.parent)
    action = Action.model_validate(v["intended_action"])
    assert (action.requested_for, action.target) == ("nv007", "user:nv007")
    assert f.h.executor.calls[f.parent] == 0  # đích là người khác: không tự thực thi
