"""T24 bảng 7.5 — test ghim N7 (phase5 7.1 P9): `approval_wait._rejected` khi state KHÔNG có `requester_context` → coi đích là
"người khác" CHỈ ở chữ (không đổi hành vi): `reset_password` `user:nv001` → tin "… cho tài khoản nv001 …", không "của bạn".

Khuôn `test_target_phrase.test_m2_b16_rejects_grant_permission_folder_phrase` (B16 thật trong harness, B15 giả).
`requester_context` bị gỡ bằng `aupdate_state(..., None)` (checkpoint không xoá được khoá — None = "không có bản chụp").
"""

import pytest
from app.core.hashing import hash_action
from app.domain.states import S_PENDING_APPROVAL, S_REJECTED
from app.graph.late_event import deliver_event
from tests.fakes.graph import GraphHarness
from tests.unit._t24 import action
from tests.unit.test_b16_approval_wait import _event, _pending

pytestmark = pytest.mark.asyncio


async def test_n7_rejection_without_requester_context_says_account_id() -> None:
    h = GraphHarness()
    act = action("reset_password", rf="nv001", target="user:nv001", params={"account_type": "ad"})
    await _pending(h, action=act)
    await h.runner.graph.aupdate_state(
        h.runner.config("t1"), {"requester_context": None, "intended_action": act, "action_plan_hash": hash_action(act)}
    )
    note = "tài khoản dịch vụ, cần trưởng bộ phận duyệt"
    await deliver_event(h.runner, "t1", S_PENDING_APPROVAL, _event(h, "rejected", reason_code="policy_violation", note=note))
    snap = await h.runner.snapshot("t1")
    assert snap.values["status"] == S_REJECTED
    [msg] = [m for m in snap.values["conversation"] if m.get("kind") == "rejection"]
    assert "tài khoản nv001" in msg["text"], msg["text"]
    assert "của bạn" not in msg["text"]
    assert msg["text"].startswith("Yêu cầu đặt lại mật khẩu cho tài khoản nv001 chưa được duyệt. Lý do: trái chính sách.")
