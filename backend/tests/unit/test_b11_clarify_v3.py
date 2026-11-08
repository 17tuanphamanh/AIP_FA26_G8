"""Q3 M2 (ĐP 09/11): prompt `b11_clarify_question` v3 — mô tả slot thiếu + giọng thống nhất.

Bằng chứng (demo): câu hỏi B11 lẫn giọng ("Chào bạn… chúng tôi", "Chào anh/chị… ạ", "giúp tôi"), hỏi kiểu biểu mẫu "(1)… (2)…", và LLM chỉ
thấy TÊN khoá slot nên tự bịa lựa chọn. v3: hai biến mới do CODE dựng (không chữ người dùng):
- `missing_desc`: từ bảng nhãn slot (`domain/slot_text`) — tên tiếng Việt + giải thích + ví dụ; slot `action` nêu đúng các việc của intent
  (nhãn `ACTION_LABELS`); `duration` ghi rõ "số ngày".
- `action_label`: nhãn tiếng Việt của `slots.action` nếu có, không thì "chưa rõ".
Quy tắc giọng trong prompt: xưng "mình", gọi "bạn"; cấm "chúng tôi", "tôi", "anh/chị", "quý khách", "ạ", "Xin cảm ơn"; không đánh số;
chỉ hỏi đúng thứ trong mô tả. GIỮ quy tắc `previous_reply` của v2. Chất lượng câu thật chỉ đo với LLM thật (mốc G).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from app.domain.messages import ACTION_LABELS
from app.domain.slot_text import (
    SLOT_HINTS,
    SLOT_LABELS,
    UNKNOWN_ACTION,
    describe_missing,
)
from app.domain.states import S_CLARIFYING
from app.graph.nodes import b11_slots
from app.llm.context import render
from app.llm.registry import PromptRegistry, load_prompts
from app.settings import get_slots
from tests.unit.test_nodes_t20a import Nodes, b11_state

PROMPTS = Path(__file__).resolve().parents[3] / "config" / "prompts"
SEED = Path(__file__).resolve().parents[3] / "mock_services" / "seed.json"
PID = "b11_clarify_question"
VARS = {"missing", "diagnostics_summary", "intent", "previous_reply", "missing_desc", "action_label", "user_request",
        "last_question"}  # Q11: v4 thêm 2 biến (xem test_b11_clarify_v4.py)
BANNED = ("chúng tôi", "tôi", "anh/chị", "quý khách", "ạ", "Xin cảm ơn")


@pytest.fixture(scope="module")
def registry() -> PromptRegistry:
    return load_prompts(PROMPTS)


def _all_slot_keys() -> set[str]:
    return {k for spec in get_slots().intents.values() for k in spec.keys}


# ---- prompt ---------------------------------------------------------------------------------------------------------------------


def test_v3_contract(registry: PromptRegistry) -> None:
    prompt = registry.get(PID)
    assert prompt.version == "4"  # Q11: quy tắc v3 dưới đây giữ nguyên ở v4; hợp đồng v4 ghim ở test_b11_clarify_v4.py
    assert (prompt.spec.role, prompt.spec.cache, prompt.spec.schema_name) == ("fast", "default", "QuestionOut")
    assert set(prompt.spec.allowed_vars) == VARS


def test_v3_voice_rules(registry: PromptRegistry) -> None:
    system = registry.get(PID).spec.system
    assert '"mình"' in system and '"bạn"' in system
    for word in BANNED:
        assert f'"{word}"' in system, word  # từng từ cấm được nêu đích danh
    assert "(1)" in system and "đánh số" in system
    assert "chỉ hỏi đúng" in system.casefold() and "lựa chọn" in system
    # v2 giữ nguyên
    assert "Mình chưa rõ ý bạn," in system and "KHÔNG chào" in system and "tối đa 2 câu" in system.casefold()
    for value in ("none", "usable", "unusable"):
        assert value in system
    assert "Không hỏi mật khẩu, mã OTP" in system


def test_v3_user_block_renders_new_vars(registry: PromptRegistry) -> None:
    desc = describe_missing(["duration"], action_choices=())
    variables: dict[str, Any] = {"missing": ["duration"], "diagnostics_summary": {"facts": {}, "devices": []}, "intent": "access",
                                 "previous_reply": "none", "missing_desc": desc, "action_label": "cấp quyền truy cập",
                                 "user_request": "xin quyền thư mục", "last_question": "(chưa có)"}  # fmt: skip
    user = render(registry.get(PID), variables, budget_in=4000).messages[1]["content"]
    assert "cấp quyền truy cập" in user and "số ngày" in user


# ---- bảng mô tả slot --------------------------------------------------------------------------------------------------------------


def test_every_slot_key_has_hint() -> None:
    keys = _all_slot_keys()
    assert keys <= set(SLOT_HINTS) and keys <= set(SLOT_LABELS)
    assert all(SLOT_HINTS[k][0].strip() for k in keys)


def test_duration_says_number_of_days() -> None:
    assert "số ngày" in describe_missing(["duration"], action_choices=())


def test_describe_missing_label_hint_example() -> None:
    desc = describe_missing(["device_id"], action_choices=())
    assert SLOT_LABELS["device_id"] in desc and SLOT_HINTS["device_id"][0] in desc and "(ví dụ: LAP-1234)" in desc


def test_examples_are_not_real_identifiers() -> None:
    """Ví dụ chỉ minh hoạ dạng: không trùng máy/người/thư mục/phần mềm có thật trong seed (không gợi ý đích — be-target-guard-2)."""
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    real = ({d["device_id"] for d in seed["devices"]} | {u["user_id"] for u in seed["users"]}
            | {r["path"] for r in seed["resources"]} | {c["name"] for c in seed["catalog"]})  # fmt: skip
    real_folded = {r.casefold() for r in real}
    for slot, (_, example) in SLOT_HINTS.items():
        assert example is None or example.casefold() not in real_folded, (slot, example)


@pytest.mark.parametrize("intent", ["vpn", "account", "access"])
def test_action_desc_lists_exactly_the_intents_actions(intent: str) -> None:
    spec = get_slots().intents[intent]
    labels = [ACTION_LABELS[a] for a in spec.action_types]
    desc = describe_missing(["action"], action_choices=labels)
    for label in labels:
        assert label in desc
    for action, label in ACTION_LABELS.items():
        if action not in spec.action_types:
            assert label not in desc, (intent, action)  # không nêu việc của intent khác


def test_describe_missing_is_pure_constants() -> None:
    """Chỉ phụ thuộc TÊN slot + nhãn hành động — không có tham số nào nhận chữ người dùng."""
    assert describe_missing(["device_id", "action"], action_choices=["a"]) == describe_missing(
        ["device_id", "action"], action_choices=["a"])
    assert describe_missing(["khoa_la"], action_choices=()).strip()  # khoá lạ → nhãn dự phòng, không lỗi


# ---- node ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_free_slot_passes_desc_and_action_label() -> None:
    n = Nodes()
    out = await n.run("b11_slots", b11_slots, b11_state("nv001", "access", {
        "action": "grant_permission", "resource_path": "finance/public-reports", "permission_level": "read"}))  # fmt: skip
    assert out["status"] == S_CLARIFYING
    [call] = n.gw.llm.calls_for(PID)
    assert set(call.variables) == VARS
    assert call.variables["action_label"] == ACTION_LABELS["grant_permission"]
    assert call.variables["missing_desc"] == describe_missing(["duration"], action_choices=())
    assert "số ngày" in call.variables["missing_desc"]
    content = str(call.rendered_messages[1]["content"])
    assert ACTION_LABELS["grant_permission"] in content and "số ngày" in content
    [row] = [r for r in n.audit.rows if r["event"] == "asked"]
    assert row["detail"]["prompt"] == f"{PID}@4"


@pytest.mark.asyncio
async def test_node_no_action_yet_label_unknown_and_actions_listed() -> None:
    """VPN thiếu cả máy (tự do) lẫn hành động → LLM; `action_label` = "chưa rõ", mô tả nêu đúng 3 việc VPN."""
    n = Nodes()
    out = await n.run("b11_slots", b11_slots, b11_state("nv002", "vpn", {}))
    assert out["status"] == S_CLARIFYING and out["missing_slots"] == ["device_id", "action"]
    [call] = n.gw.llm.calls_for(PID)
    assert call.variables["action_label"] == UNKNOWN_ACTION == "chưa rõ"
    desc = call.variables["missing_desc"]
    for action in get_slots().intents["vpn"].action_types:
        assert ACTION_LABELS[action] in desc
    assert SLOT_LABELS["device_id"] in desc


@pytest.mark.asyncio
async def test_node_desc_has_no_user_text() -> None:
    """Q11 đổi test này có chủ ý: từ v4 chữ người dùng ĐƯỢC vào prompt, nhưng chỉ qua `user_request`. Câu người dùng (có chuỗi đánh dấu)
    vẫn không lọt vào `missing_desc`/`action_label`/`diagnostics_summary`/các biến còn lại — những biến đó vẫn chỉ là hằng/enum do code dựng."""
    n = Nodes()
    marker = "CHU-NGUOI-DUNG-7781"
    await n.run("b11_slots", b11_slots, b11_state("nv002", "vpn", {}, redacted_request=f"VPN hỏng {marker}"))
    [call] = n.gw.llm.calls_for(PID)
    assert marker in call.variables["user_request"]
    assert marker not in repr({k: v for k, v in call.variables.items() if k != "user_request"})
