"""E12 (soát 20 agent 12/11 — agent 15, 20): audit ghi AI đã duyệt và duyệt ĐÚNG hành động nào.

- B16 `approved` / `rejected`: `detail.approver_id` = người đã bấm (server đặt vào sự kiện, không phải người được giao — có thể là
  người dự phòng). `approved` thêm `detail.action_plan_hash` = hash hành động đã duyệt.
- B18 `executed_ok`: `detail.approver_id` = `approvals.decided_by` (đường AUTO: None) và `detail.action_plan_hash` = hash hành động ĐÃ
  thực thi — đối chiếu được với dòng B16 mà không cần mở bảng `approvals`.
Chỉ định danh + hash (không chữ người dùng). Timeout không có người duyệt → không có khoá này.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.states import S_EXECUTING
from app.graph.nodes import b17_execute
from tests.fakes.graph import GraphHarness
from tests.unit._t24 import action as t24_action
from tests.unit.test_b16_approval_wait import APPROVER as B16_APPROVER
from tests.unit.test_b16_approval_wait import _b16, _decide, _event, _pending
from tests.unit.test_b17_llm_auto import (
    APPROVER,
    IN_HOURS,
    ME,
    Env,
    _access_grant,
    _approved,
    _assert_executed,
    _base_state,
)

pytestmark = pytest.mark.asyncio

BACKUP = "l1_02"


async def test_b16_approved_ghi_nguoi_duyet_va_hash() -> None:
    h = GraphHarness()
    await _pending(h)
    approved_hash = (await h.runner.snapshot("t1")).values["action_plan_hash"]
    h.clock.advance(timedelta(seconds=30))
    await _decide(h, _event(h, "approved", approver_id=BACKUP, decided_as="backup"))
    row = _b16(h)
    assert row["event"] == "approved"
    assert (row["detail"]["approver_id"], row["detail"]["action_plan_hash"]) == (BACKUP, approved_hash)
    assert approved_hash


async def test_b16_rejected_ghi_nguoi_duyet() -> None:
    h = GraphHarness()
    await _pending(h)
    await _decide(h, _event(h, "rejected", reason_code="policy_violation", note="không hợp lệ"))
    d = _b16(h)["detail"]
    assert d["approver_id"] == B16_APPROVER and "action_plan_hash" not in d


async def test_b16_timeout_khong_co_nguoi_duyet() -> None:
    h = GraphHarness()
    await _pending(h)
    await _decide(h, {"kind": "timeout"})
    assert "approver_id" not in _b16(h)["detail"]


async def test_b18_qua_duyet_ghi_nguoi_duyet_va_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b17_execute, "fact_recheck_calls", lambda state, rid: [])  # như đối chứng c9 (fact viết tay)
    env = Env(IN_HOURS)
    action = _access_grant()
    state = _base_state(action, other=action.requested_for != ME, status=S_EXECUTING)
    a_id = await _approved(env, action)
    state.update(approval_id=a_id, approval_result="approved", action_plan_hash=hash_action(action))
    out = await env.b17(state)
    _assert_executed(env, out, action)
    [row] = env.rows("executed_ok")
    assert (row["detail"]["approver_id"], row["detail"]["action_plan_hash"]) == (APPROVER, hash_action(action))


@pytest.mark.parametrize(
    "make",
    [lambda: t24_action("reset_password", rf=ME, params={"account_type": "ad"},
                        facts={"target_user_status": "active", "target_account_privilege": "standard_user",
                               "target_is_service_account": False})],
    ids=["luat-allow"],
)  # fmt: skip
async def test_b18_auto_khong_nguoi_duyet_van_co_hash(make: Callable[[], Action]) -> None:
    env = Env(IN_HOURS)
    action = make()
    out = await env.b17(_base_state(action, other=False, status=S_EXECUTING))
    _assert_executed(env, out, action)
    [row] = env.rows("executed_ok")
    assert row["detail"]["approver_id"] is None and row["detail"]["action_plan_hash"] == hash_action(action)
