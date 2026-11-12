"""K3 soát 12/11 (agent 16 V22): "Em đang có quyền gì" — B3 đã nhận `slots.action = view_permissions` nhưng `b10_need_type` trả `info`
→ B10 trả lời từ KB-ACS-005 (liệt kê MỌI thư mục, không phải quyền của người gửi). Nay: `need_type == "info"` mà slot `action` là
`view_permissions` → đi nhánh hành động như `need_type == "action"` (→ B11 → M5 như mọi hành động; không bỏ policy).
Gọi LLM y như cũ (vẫn gọi `b10_need_type`, không thêm/bớt lời gọi) — chỉ đổi đường đi sau đó; audit ghi `need_type_override`.
Ca khác không đổi: câu hỏi KB thường (không slot action) → trả lời KB; slot action GHI (vd `grant_permission`) mà LLM nói info → giữ
nguyên như trước (ngoài phạm vi K3).
"""

from typing import Any

import pytest
from app.domain.states import S_CONFIRMING, S_RETRIEVING
from tests.unit.test_b10_symptom import _env, _node, _row, _state

pytestmark = pytest.mark.asyncio

ASK = "Em đang có quyền gì"


def _ask(**over: Any) -> dict[str, Any]:
    return _state(redacted_request=ASK, intent="access", facts={}, **over)


async def test_slot_xem_quyen_ma_llm_noi_info_van_di_nhanh_hanh_dong() -> None:
    h, gw = _env(need="info")
    out = await _node(h, _ask(slots={"action": "view_permissions"}))
    assert (out["status"], out["next"], out["need_type"]) == (S_RETRIEVING, "b11_slots", "action")
    assert [c.prompt_id for c in gw.llm.calls] == ["b10_need_type"]  # không gọi b10_answer
    assert h.notifier.sent == []
    row = _row(h)
    assert (row["event"], row["detail"]["need_type"], row["detail"]["need_type_override"]) == (
        "needs_action", "info", "view_permissions_slot",
    )  # fmt: skip


async def test_cau_hoi_kb_thuong_khong_doi() -> None:
    h, gw = _env(need="info")
    out = await _node(h, _ask(slots={}))
    assert (out["status"], out["next"], out["need_type"]) == (S_CONFIRMING, "confirm_wait", "info")
    assert [c.prompt_id for c in gw.llm.calls] == ["b10_need_type", "b10_answer"]
    assert "need_type_override" not in _row(h)["detail"]


@pytest.mark.parametrize("action", ["grant_permission", "extend_permission", "reset_password", "check_vpn_status"])
async def test_slot_hanh_dong_khac_khong_bi_ep(action: str) -> None:
    h, _ = _env(need="info")
    out = await _node(h, _ask(slots={"action": action}))
    assert out["need_type"] == "info" and "need_type_override" not in _row(h)["detail"]


async def test_llm_noi_action_van_nhu_cu() -> None:
    h, _ = _env(need="action")
    out = await _node(h, _ask(slots={"action": "view_permissions"}))
    assert (out["next"], out["need_type"]) == ("b11_slots", "action")
    assert "need_type_override" not in _row(h)["detail"]
