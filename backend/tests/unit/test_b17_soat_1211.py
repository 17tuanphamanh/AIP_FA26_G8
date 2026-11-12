"""B17 — soát executor 12/11 (TA duyệt sửa lõi): ba khe giữa lúc quyết định và lúc ghi.

- N2 `[0b]`: ticket KHÁC của cùng người gửi, cùng intent, còn escalation E7 MỞ mà lệnh ghi có thể đã tới đích → E5
  `recheck_failed` (`prior_write_unconfirmed`), 0 lời gọi ghi. Trước: người dùng xin lại → ghi lần 2 (2 SMS đặt lại mật khẩu, mật khẩu
  tạm lần 1 mất hiệu lực; chứng chỉ mới lần 1 bị thu hồi).
- N1 `[3c]`: ca ĐÃ QUA DUYỆT — đọc lại các fact luật dùng; khác bản chụp → E5 `recheck_failed` (`facts_changed`). Trước: an ninh khoá lại
  tài khoản / thu hồi chứng chỉ trong lúc chờ duyệt → B17 vẫn mở khoá / gia hạn. Ca AUTO (B11 → B12 → B17 cùng lượt) không đọc lại.
- D-15 mở rộng: AD `account.enabled=False` mà HR còn `active` → E5 `person_no_longer_valid`.

Khuôn: `test_b17_llm_auto.Env` (node B17 thật, `PlanExecutor` thật, hệ thống ghi giả đếm ở nơi nhận).
"""

from datetime import timedelta
from typing import Any

import pytest
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.final import FinalSummary
from app.domain.states import S_ESCALATED, S_EXECUTING
from app.graph.nodes import b17_execute
from app.tools.specs import RECHECK_STEP, REGISTRY, TOOL_MAP
from tests.fakes.identity import ad_user
from tests.unit._t24 import action as t24_action
from tests.unit.test_b17_llm_auto import (
    COLLEAGUE,
    IN_HOURS,
    ME,
    Env,
    _access_grant,
    _approved,
    _assert_e5_recheck_zero_writes,
    _assert_executed,
    _base_state,
)

pytestmark = pytest.mark.asyncio


def _assert_e5_prior_zero_writes(env: Env, out: dict[str, Any]) -> None:
    """Như `_assert_e5_recheck_zero_writes` nhưng transaction_log có sẵn dòng `begun` của ticket TRƯỚC (`t0`) — ticket này không thêm dòng."""
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E5", "recheck_failed")
    assert env.writes_total() == 0 and [r for r in env.txlog.rows if r["ticket_id"] != "t0"] == []
    assert env.rows("executed_ok") == []


def _reset_own() -> Action:
    """R01: đặt lại mật khẩu AD của chính mình (AUTO)."""
    return t24_action("reset_password", rf=ME, params={"account_type": "ad"},
                      facts={"target_user_status": "active", "target_account_privilege": "standard_user",
                             "target_is_service_account": False})  # fmt: skip


async def _prior_e7(
    env: Env, *, intent: str = "account", reason: str = "exec_failed", requester: str = ME, closed: bool = False,
    exit_code: str = "E7", begun: bool = True,
) -> None:
    """Ticket `t0` đã kết thúc E7 (lệnh ghi có thể đã tới đích — `begun` trong transaction_log), escalation còn mở (hoặc đã đóng)."""
    at = env.clock.now() - timedelta(hours=1)
    if begun:
        await env.txlog.begin("t0", "T0", "reset_password")
    env.h.tickets.register("t0", at, requester_id=requester)
    await env.h.tickets.finalize_once("t0", FinalSummary(
        final_state=S_ESCALATED, exit_code=exit_code, block_reason=None, close_reason=None, resolution_path=None,
        aggregate_status=None, auto_closed=False, intent=intent, slots=None, total_turns=1, total_duration_seconds=5,
        closed_at=at,
    ))  # fmt: skip
    await env.h.escalations.create(
        ticket_id="t0", exit_code=exit_code, reason_detail=reason, handoff_note={}, is_deny_case=False, created_at=at
    )
    if closed:
        env.h.escalations.rows[-1]["closed_at"] = env.clock.now()


def _detail(env: Env) -> dict[str, Any]:
    rows = env.rows("recheck_failed")
    assert len(rows) == 1, rows
    detail: dict[str, Any] = rows[0]["detail"]
    return detail


# ---- N2 -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["exec_failed", "exec_interrupted", "execution_interrupted"])
async def test_n2_open_e7_same_requester_same_intent_blocks_second_write(reason: str) -> None:
    env = Env(IN_HOURS)
    await _prior_e7(env, reason=reason)
    out = await env.b17(_base_state(_reset_own(), other=False, status=S_EXECUTING))
    _assert_e5_prior_zero_writes(env, out)
    assert _detail(env)["recheck"] == "prior_write_unconfirmed"
    assert _detail(env)["prior_ticket_id"] == "t0"
    assert "t0" in out["escalation_note"]


@pytest.mark.parametrize(
    "prior",
    [
        pytest.param({"closed": True}, id="L2-da-dong"),
        pytest.param({"intent": "vpn"}, id="khac-intent"),
        pytest.param({"requester": COLLEAGUE}, id="nguoi-khac"),
        pytest.param({"reason": "recheck_failed", "exit_code": "E5"}, id="E5-chua-ghi"),
        pytest.param({"begun": False}, id="txlog-trong-chua-gui-lenh-ghi"),  # E11 (soát 12/11, agent 12 L1)
    ],
)
async def test_n2_other_cases_still_execute(prior: dict[str, Any]) -> None:
    env = Env(IN_HOURS)
    await _prior_e7(env, **prior)
    action = _reset_own()
    out = await env.b17(_base_state(action, other=False, status=S_EXECUTING))
    _assert_executed(env, out, action)


async def test_n2_old_escalation_outside_window_does_not_block() -> None:
    env = Env(IN_HOURS)
    await _prior_e7(env)
    env.h.escalations.rows[-1]["created_at"] = env.clock.now() - b17_execute.WRITE_DOUBT_WINDOW - timedelta(minutes=1)
    action = _reset_own()
    _assert_executed(env, await env.b17(_base_state(action, other=False, status=S_EXECUTING)), action)


# ---- N1 -------------------------------------------------------------------------------------------------------------


async def _approved_state(env: Env, action: Action) -> dict[str, Any]:
    state = _base_state(action, other=False, status=S_EXECUTING)
    a_id = await _approved(env, action)
    state.update(approval_id=a_id, approval_result="approved", action_plan_hash=hash_action(action))
    return state


async def test_n1_fact_changed_while_waiting_approval_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bản chụp `resource_sensitivity=low` lúc duyệt; đọc lại thấy `high` → không cấp, 0 lời gọi ghi."""
    env = Env(IN_HOURS)
    action = _access_grant()
    reads: list[list[tuple[str, dict[str, str]]]] = []

    def calls(state: Any, requester_id: str) -> list[tuple[str, dict[str, str]]]:
        out = [("ad_get_user", {"user_id": requester_id})]  # tool đọc có sẵn trong harness — nội dung không dùng
        reads.append(out)
        return out

    monkeypatch.setattr(b17_execute, "fact_recheck_calls", calls)
    monkeypatch.setattr(b17_execute, "fresh_facts", lambda state, results, rid: {**action.facts, "resource_sensitivity": "high"})
    out = await env.b17(await _approved_state(env, action))
    _assert_e5_recheck_zero_writes(env, out)
    assert _detail(env)["recheck"] == "facts_changed"
    assert _detail(env)["fields"] == ["resource_sensitivity"]
    assert len(reads) == 1


async def test_n1_unwatched_fact_change_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chỉ so fact luật dùng (+ `cert_status`) — fact khác (số ngày còn hạn, lần kết nối cuối) đổi theo thời gian không chặn."""
    env = Env(IN_HOURS)
    action = _access_grant()
    monkeypatch.setattr(b17_execute, "fact_recheck_calls", lambda state, rid: [("ad_get_user", {"user_id": rid})])
    monkeypatch.setattr(b17_execute, "fresh_facts", lambda state, results, rid: {**action.facts, "last_connection_ok": False})
    _assert_executed(env, await env.b17(await _approved_state(env, action)), action)


async def test_n1_same_facts_after_approval_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    env = Env(IN_HOURS)
    action = _access_grant()
    monkeypatch.setattr(b17_execute, "fact_recheck_calls", lambda state, rid: [("ad_get_user", {"user_id": rid})])
    monkeypatch.setattr(b17_execute, "fresh_facts", lambda state, results, rid: dict(action.facts))
    _assert_executed(env, await env.b17(await _approved_state(env, action)), action)


async def test_n1_auto_path_does_not_reread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ca AUTO (luật allow, không qua duyệt): B11 vừa đọc fact trong CÙNG lượt — không đọc lại."""

    def boom(*_: Any) -> list[tuple[str, dict[str, str]]]:
        raise AssertionError("ca AUTO không được đọc lại fact")

    monkeypatch.setattr(b17_execute, "fact_recheck_calls", boom)
    env = Env(IN_HOURS)
    action = _reset_own()
    _assert_executed(env, await env.b17(_base_state(action, other=False, status=S_EXECUTING)), action)


def test_watched_facts_cover_policy_and_cert_status() -> None:
    watched = b17_execute.watched_action_facts()
    assert {"target_lock_reason", "target_account_locked", "device_owner_is_requester", "device_registered",
            "resource_sensitivity", "software_prohibited", "cert_status"} <= watched  # fmt: skip
    assert "cert_days_to_expiry" not in watched and "last_connection_ok" not in watched


def test_fact_recheck_calls_mirror_b11() -> None:
    """VPN: tool nhận `device_id` (như B11 `vpn.target_calls`); thiếu máy → không gọi; intent khác: `module.target_calls`."""
    vpn_state = {"intent": "vpn", "slots": {"device_id": "LAP-0342"}}
    assert [t for t, _ in b17_execute.fact_recheck_calls(vpn_state, ME)] == ["check_device_registered", "check_vpn_cert_expiry"]
    assert b17_execute.fact_recheck_calls({"intent": "vpn", "slots": {}}, ME) == []
    account = b17_execute.fact_recheck_calls({"intent": "account", "slots": {"account_type": "ad"}}, ME)
    assert {t for t, _ in account} == set(TOOL_MAP["account"])


def test_diag_tools_readable_at_recheck_but_never_b17() -> None:
    for names in TOOL_MAP.values():
        for name in names:
            assert RECHECK_STEP in REGISTRY[name].allowed_steps
            assert "B17" not in REGISTRY[name].allowed_steps  # nhãn "B17" chỉ dành cho tool ghi
    assert all(RECHECK_STEP not in s.allowed_steps for s in REGISTRY.values() if s.kind == "write")


# ---- D-15 mở rộng ---------------------------------------------------------------------------------------------------


async def test_ad_disabled_while_hr_active_blocks() -> None:
    me = ad_user(ME)
    me["account"]["enabled"] = False  # AD đã tắt, HR vẫn `active`
    env = Env(IN_HOURS, me, ad_user(COLLEAGUE), ad_user("nv004"))
    out = await env.b17(_base_state(_reset_own(), other=False, status=S_EXECUTING))
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E5", "person_no_longer_valid")
    assert env.writes_total() == 0
    row = env.rows("person_no_longer_valid")[0]["detail"]
    assert row["ad_disabled"] is True and row["employment_status"] == "active"
