"""B17–B18 thật (phase3 mục 11.4; PLAN-3h S11; chốt P1, P4, P6, P7, P8, Q-3h-2) — node gọi trực tiếp, `VpnExecutor` thật trên
registry ghi thật + hệ thống ghi VPN giả (đếm ở nơi nhận) + `transaction_log` trong bộ nhớ; AD giả sau registry đọc thật.

- [1] luật + Clock HIỆN HÀNH (P8); "đã duyệt" = state + BẢNG + hash — "state approved + DB pending → E5" ở cả giờ hành chính
  (luật hiện hành allow — M-3h-12) lẫn 20:00 (approval_required — M-3h-7); deny → E5 kể cả đã duyệt.
- [2] hash lệch/thiếu → E5 `action_plan_changed_since_approval`. [3] người gửi / người hưởng lợi không hợp lệ, AD lỗi → E5.
- [4–5] `begun` có sẵn → E7 `exec_interrupted`, 0 ghi; P4 → E2 `turn_budget_exceeded`, 0 `begun`, 0 ghi; lỗi ghi → E7
  `exec_failed` + `handoff_note` 4 phần (= `escalation_note`); `RefusingExecutor` → E7.
- [6] B18: tin `result` theo mẫu (P6), notify + hạn confirm qua `effects.once`, điểm log 7.
- Q-3h-2: `ExecutionResult.outputs` round-trip checkpoint (a), checkpoint cũ không có trường (b), khoá lạ/sai mẫu bị bỏ và không
  vào tin (c — M-3h-13).
- Chốt DỪNG 2: [0] NGHI-2 — ticket đã có `begun` (mọi lượt) → E7 TRƯỚC mọi bước kiểm lại (chạy lại sau khi đã ghi mà điều kiện
  đổi → E7, KHÔNG E5); Q-3h-7 — trường `requester.*` mà luật tham chiếu, AD mới khác bản chụp B1 → E5 `recheck_failed`.
- Chốt FAIL mục 7 (soát DỪNG 3b): lỗi SAU `begin` (đứt kết nối, 2xx hỏng / sai schema) và lỗi ở đoạn B18 sau khi đã ghi → E7
  `exec_interrupted` + câu "có thể đã gửi lệnh ghi…", audit `cause` = tên lớp lỗi, không POST lần 2, KHÔNG E9; cùng lỗi TRƯỚC
  `begun` → E9 như cũ; `CancelledError` không bị nuốt.
- Việc treo 21: `goto(S_CONFIRMING)` cuối B17 (ngoài try) lỗi SAU khi ghi thành công → boundary thấy `begun` → E7
  `execution_interrupted` + câu cảnh báo, không E9 (các ca boundary khác: `test_boundary_begun.py`).
"""

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import ormsgpack
import pytest
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.core.turn_budget import TurnBudgetExceeded, TurnDeadline, bind_turn_deadline
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.policy import Rule, referenced_facts
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_EXECUTING
from app.domain.ticket_state import ExecutionResult
from app.executor.errors import ExecutionInterrupted
from app.executor.vpn import VpnExecutor
from app.graph.builder import wrap_node
from app.graph.checkpoint import make_serde
from app.graph.context import RunContext, bind_run
from app.graph.fakes import RefusingExecutor
from app.graph.nodes import b17_execute
from app.risk.models import RuleVerdict
from app.settings import get_action_metadata, get_policy
from app.tools.models import AdUser
from langgraph.checkpoint.serde.jsonplus import EXT_PYDANTIC_V2
from tests.fakes.executor import FakeVpnWrites, MemoryTxLog, http_error
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user
from tests.unit.test_executor_vpn import AFTER_BEGIN, SECRET_BODY, fail_after_send

pytestmark = pytest.mark.asyncio

IN_HOURS = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN
AFTER_HOURS = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)  # thứ Ba 20:00 giờ VN
CANARY = "CANARY-B17-cau-nguoi-dung"
POINT7 = {"success", "steps_done", "failed_step", "rollback_status", "action_plan_hash_matched", "write_calls"}


def _requester(user: str = "nv001") -> RequesterContext:
    return RequesterContext(
        user_id=user, role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=IN_HOURS,
    )  # fmt: skip


def _action(action_type: str = "renew_vpn_cert", *, owner: bool = True, requested_for: str = "nv001") -> Action:
    meta = get_action_metadata().root["vpn"][action_type]
    return Action(
        type=action_type, target="device:LAP-0342", requested_for=requested_for, scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params={"device_id": "LAP-0342"},
        facts={"device_registered": True, "device_owner_is_requester": owner, "cert_status": "expired",
               "cert_days_to_expiry": -3, "last_connection_ok": False},
    )  # fmt: skip


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_EXECUTING, "intent": "vpn", "reasoning_loops": 1,
        "requester_context": _requester(), "intended_action": _action(), "ctx_flags": {"target_is_other": False},
        "redacted_request": f"gia hạn VPN cho máy LAP-0342 {CANARY}",
        "slots": {"device_id": "LAP-0342", "action": "renew_vpn_cert"},
    }  # fmt: skip
    base.update(over)
    return base


class Env:
    def __init__(self, at: datetime, *users: dict[str, Any]) -> None:
        self.clock = FakeClock(at)
        self.ad = FakeAd(*(users or (ad_user("nv001"),)))
        self.writes, self.txlog = FakeVpnWrites(self.clock), MemoryTxLog()
        self.h = GraphHarness(clock=self.clock, ad=self.ad, txlog=self.txlog)  # B17 bước 0 và executor đọc CÙNG txlog
        self.executor: Any = VpnExecutor(self.writes.registry(), self.txlog, self.clock, tz=get_policy().business_hours.tz)

    @contextmanager
    def run(self) -> Iterator[None]:
        with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=self.h.audit, effects=self.h.effects,
                                 spans=self.h.spans, clock=self.clock, txlog=self.txlog)):  # fmt: skip
            yield

    async def node(self, state: dict[str, Any], *, boundary: bool = False) -> dict[str, Any]:
        deps = self.h.deps()
        deps.executor = self.executor
        fn = b17_execute.make(deps)
        with self.run():
            return await (wrap_node("b17_execute", fn) if boundary else fn)(state)  # type: ignore[no-any-return]

    async def approval(self, action: Action, *, decide: str | None) -> str:
        a_id = await self.h.approvals.create("t1", "l1-fake", self.clock.now() + timedelta(minutes=30), hash_action(action))
        if decide is not None:
            await self.h.approvals.close(a_id, decide, self.clock.now(), decided_by="l1-fake", note="ok")
        return a_id

    def writes_total(self) -> int:
        return sum(self.writes.calls.values())

    def detail(self, event: str) -> dict[str, Any]:
        [row] = self.h.audit.of("t1", event)
        return dict(row["detail"])


def _approved_state(env_action: Action, a_id: str, **over: Any) -> dict[str, Any]:
    base = {"intended_action": env_action, "approval_id": a_id, "approval_result": "approved",
            "action_plan_hash": hash_action(env_action)}  # fmt: skip
    return _state(**{**base, **over})


# ---- [6] đường vui (TC02 — R20 allow, trong giờ) ------------------------------------------------------------------


async def test_tc02_auto_executes_once_then_b18_result() -> None:
    env = Env(IN_HOURS)
    out = await env.node(_state())
    assert (out["status"], out["next"]) == (S_CONFIRMING, "confirm_wait")
    assert env.writes.calls == {"renew_vpn_cert": 1}
    assert env.txlog.statuses() == [("renew_vpn_cert", "begun")]
    res = ExecutionResult.model_validate(out["execution"])
    assert res.success and res.action_plan_hash_matched is None and res.outputs["expires_on"] == "2027-09-29"
    [msg] = out["conversation"]
    assert (msg["role"], msg["kind"], msg["needs"]) == ("assistant", "result", "confirm")
    assert msg["text"] == ("Đã gia hạn chứng chỉ VPN cho máy LAP-0342, hiệu lực tới 29/09/2027. "
                           "Bạn thử kết nối lại rồi xác nhận giúp mình nhé.")  # fmt: skip
    assert env.h.notifier.count("t1") == 1 and msg["ref"] is not None
    assert env.h.effects.count("t1", "notify_user") == 1 and env.h.effects.count("t1", "deadline_set") == 1
    [wait] = [w for w in env.h.deadlines.waits if w["ticket_id"] == "t1"]
    assert (wait["kind"], wait["deadline"]) == ("confirm", IN_HOURS + timedelta(hours=48))
    detail = env.detail("executed_ok")
    assert POINT7 <= set(detail) and detail["write_calls"] == 1 and detail["success"] is True
    assert CANARY not in str(out) and CANARY not in str(env.h.audit.rows)
    assert env.ad.calls == 1  # [3] kiểm lại người (một người: gửi = hưởng lợi)


async def test_check_vpn_status_r16_no_write() -> None:
    env = Env(IN_HOURS)
    out = await env.node(_state(intended_action=_action("check_vpn_status")))
    assert out["status"] == S_CONFIRMING and env.writes_total() == 0 and env.txlog.rows == []
    [msg] = out["conversation"]
    assert "đã hết hạn, quá hạn 3 ngày" in msg["text"] and "không thành công" in msg["text"]
    assert env.detail("executed_ok")["write_calls"] == 0


# ---- [1] kiểm lại luật (P8) + "đã duyệt" = state + bảng + hash -----------------------------------------------------


@pytest.mark.parametrize("at", [IN_HOURS, AFTER_HOURS], ids=["allow-M-3h-12", "approval_required-M-3h-7"])
async def test_state_approved_db_pending_is_e5(at: datetime) -> None:
    env = Env(at)
    action = _action()
    a_id = await env.approval(action, decide=None)  # bảng vẫn pending
    out = await env.node(_approved_state(action, a_id))
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E5", "recheck_failed")
    assert env.writes_total() == 0 and env.txlog.rows == [] and env.ad.calls == 0
    detail = env.detail("recheck_failed")
    assert (detail["approval_state"], detail["approval_db"], detail["write_calls"]) == ("approved", "pending", 0)


@pytest.mark.parametrize("db", ["rejected", "timeout"])
async def test_state_approved_db_not_approved_is_e5(db: str) -> None:
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approval(action, decide=db)
    out = await env.node(_approved_state(action, a_id))
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E5", "recheck_failed") and env.writes_total() == 0


async def test_db_approved_but_state_not_is_e5() -> None:
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approval(action, decide="approved")
    out = await env.node(_approved_state(action, a_id, approval_result="timeout"))
    assert out["escalation_reason_detail"] == "recheck_failed" and env.writes_total() == 0


async def test_approved_state_without_approval_id_is_e5() -> None:
    env = Env(IN_HOURS)
    out = await env.node(_state(approval_result="approved", action_plan_hash=hash_action(_action())))
    assert out["escalation_reason_detail"] == "recheck_failed" and env.writes_total() == 0


async def test_after_hours_approved_executes() -> None:
    """R18 (approval_required) + đã duyệt đủ 3 điều kiện → thực thi; `action_plan_hash_matched=True`."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approval(action, decide="approved")
    out = await env.node(_approved_state(action, a_id))
    assert out["status"] == S_CONFIRMING and env.writes.calls == {"renew_vpn_cert": 1}
    assert ExecutionResult.model_validate(out["execution"]).action_plan_hash_matched is True


async def test_auto_path_now_after_hours_is_e5() -> None:
    """P8: AUTO lúc B12 (trong giờ) nhưng tới B17 đã 20:00 → R18 approval_required, chưa duyệt → E5, 0 ghi."""
    env = Env(AFTER_HOURS)
    out = await env.node(_state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E5", "recheck_failed")
    assert env.detail("recheck_failed")["matched_rule_id"] == "R18" and env.writes_total() == 0


async def test_no_rule_matches_now_and_not_approved_is_e5() -> None:
    env = Env(IN_HOURS)
    out = await env.node(_state(intended_action=_action(owner=False)))
    assert out["escalation_reason_detail"] == "recheck_failed" and env.writes_total() == 0


async def test_deny_is_e5_even_if_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    env = Env(IN_HOURS)
    action = _action()
    a_id = await env.approval(action, decide="approved")
    verdict = RuleVerdict(matched=True, decision="deny", rule_id="R12", all_matched=["R12"], description="Cấm")
    monkeypatch.setattr(b17_execute, "evaluate", lambda action, ctx: verdict)
    out = await env.node(_approved_state(action, a_id))
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E5", "recheck_failed") and env.writes_total() == 0


# ---- [2] hash -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("plan_hash", ["0" * 64, None], ids=["lech", "thieu"])
async def test_hash_mismatch_or_missing_is_e5(plan_hash: str | None) -> None:
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approval(action, decide="approved")
    out = await env.node(_approved_state(action, a_id, action_plan_hash=plan_hash))
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E5", "action_plan_changed_since_approval")
    assert env.writes_total() == 0 and env.txlog.rows == []


# ---- [3] người gửi / người hưởng lợi ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("users", "down"),
    [((ad_user("nv001", employment_status="disabled"),), False),
     ((ad_user("nv001", employment_status="terminated"),), False),
     ((ad_user("nv999"),), False),  # nv001 không còn trong AD → 404
     ((ad_user("nv001"),), True)],  # AD lỗi
    ids=["disabled", "terminated", "khong-con", "ad-loi"],
)  # fmt: skip
async def test_requester_no_longer_valid_is_e5(users: tuple[dict[str, Any], ...], down: bool) -> None:
    env = Env(IN_HOURS, *users)
    env.ad.down = down
    out = await env.node(_state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E5", "person_no_longer_valid")
    detail = env.detail("person_no_longer_valid")
    assert (detail["user_id"], detail["role"], detail["ad_error"]) == ("nv001", "requester", down)
    assert env.writes_total() == 0 and env.txlog.rows == []


async def test_beneficiary_terminated_is_e5() -> None:
    """D-15 (sửa): người gửi active, người hưởng lợi terminated — ca đi qua duyệt (không luật nào khớp nhưng đã duyệt)."""
    env = Env(IN_HOURS, ad_user("nv001"), ad_user("nv002", employment_status="terminated"))
    action = _action(requested_for="nv002")
    a_id = await env.approval(action, decide="approved")
    out = await env.node(_approved_state(action, a_id))
    assert out["escalation_reason_detail"] == "person_no_longer_valid"
    assert (env.detail("person_no_longer_valid")["role"], env.ad.calls) == ("beneficiary", 2)
    assert env.writes_total() == 0


# ---- [4–5] executor ---------------------------------------------------------------------------------------------------


async def test_begun_exists_is_e7_exec_interrupted_zero_writes() -> None:
    env = Env(IN_HOURS)
    await env.txlog.begin("t1", "T1", "renew_vpn_cert")
    out = await env.node(_state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_interrupted")
    assert out["escalation_note"] == b17_execute.INTERRUPTED_NOTE
    assert "có thể đã gửi lệnh ghi — L2 kiểm trên hệ thống đích trước khi làm tay" in out["escalation_note"]
    assert env.writes_total() == 0 and env.detail("exec_interrupted")["write_calls"] == 0


# ---- [0] chốt DỪNG 2 NGHI-2: `begun` của ticket (mọi lượt) → E7 TRƯỚC mọi bước kiểm lại ------------------------------


def _disable_requester(env: Env) -> None:
    env.ad.users["nv001"] = ad_user("nv001", employment_status="disabled")


def _to_after_hours(env: Env) -> None:
    env.clock.advance(AFTER_HOURS - IN_HOURS)


@pytest.mark.parametrize("change", [_to_after_hours, _disable_requester], ids=["qua-gio-R18", "nguoi-gui-bi-khoa"])
async def test_nghi2_rerun_after_write_is_e7_not_e5(change: Any) -> None:
    """Chạy B17 lần 1 → đã ghi. Điều kiện đổi (lần kiểm lại sẽ ra E5) rồi B17 chạy lại cùng lượt → E7 `exec_interrupted`, KHÔNG
    E5 (E5 khiến L2 hiểu là "chưa làm" → làm tay lần 2). Không đọc AD, không ghi thêm."""
    env = Env(IN_HOURS)
    first = await env.node(_state())
    assert first["status"] == S_CONFIRMING and env.writes.calls == {"renew_vpn_cert": 1}
    ad_calls = env.ad.calls
    change(env)
    out = await env.node(_state())
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E7", "exec_interrupted")
    assert out["escalation_note"] == b17_execute.INTERRUPTED_NOTE
    assert env.writes.calls == {"renew_vpn_cert": 1} and env.ad.calls == ad_calls
    assert env.h.audit.of("t1", "recheck_failed") == [] and env.h.audit.of("t1", "person_no_longer_valid") == []
    assert env.detail("exec_interrupted")["stage"] == "txlog_before_recheck"


async def test_nghi2_begun_of_other_turn_is_e7_before_recheck() -> None:
    """`begun` của lượt khác (vd lượt trước chết sau lời gọi ghi, recover cấp lượt mới) — kể cả khi đi qua duyệt mà bảng lệch
    (bình thường → E5) → vẫn E7; không đọc bảng duyệt, không đọc AD."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approval(action, decide=None)  # bảng pending — kiểm lại sẽ ra E5
    await env.txlog.begin("t1", "T0", "renew_vpn_cert")
    out = await env.node(_approved_state(action, a_id))
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_interrupted")
    assert env.writes_total() == 0 and env.ad.calls == 0


async def test_nghi2_begun_of_other_ticket_does_not_block() -> None:
    env = Env(IN_HOURS)
    await env.txlog.begin("t0", "T1", "renew_vpn_cert")
    out = await env.node(_state())
    assert out["status"] == S_CONFIRMING and env.writes.calls == {"renew_vpn_cert": 1}


async def test_nghi2_step0_runs_even_without_intended_action() -> None:
    """Bước 0 đứng TRƯỚC cả việc đọc `intended_action` — state hỏng sau khi đã ghi vẫn ra E7 (không E9 mất dấu lời gọi ghi)."""
    env = Env(IN_HOURS)
    await env.txlog.begin("t1", "T1", "renew_vpn_cert")
    out = await env.node(_state(intended_action=None), boundary=True)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_interrupted")


# ---- [3] Q-3h-7: trường requester.* mà luật tham chiếu — AD mới khác bản chụp B1 → E5 ---------------------------------


async def test_q3h7_watched_fields_from_repo_policy() -> None:
    assert b17_execute.watched_requester_fields() == ("employment_status",)


async def test_q3h7_referenced_facts_reads_nested_groups() -> None:
    """Soát lại DỪNG 2: trường nằm trong nhóm `any` lồng trong `all` vẫn được gom; nguồn khác không lẫn vào."""
    rule = Rule.model_validate({
        "id": "R98", "type": "deny", "intent": "vpn", "action": "check_vpn_status", "description": "lồng",
        "conditions": {"all": [
            {"fact": "action.facts.device_registered", "op": "is_true"},
            {"any": [{"fact": "requester.role", "op": "eq", "value": "l2"},
                     {"all": [{"fact": "requester.is_privileged_account", "op": "is_true"},
                              {"fact": "ctx.target_is_other", "op": "is_true"}]}]},
        ]},
    })  # fmt: skip
    assert referenced_facts([rule], "requester") == {"role", "is_privileged_account"}
    assert referenced_facts([rule], "ctx") == {"target_is_other"}


async def test_q3h7_active_at_b1_probation_now_is_e5() -> None:
    """Bản chụp B1 `active` (R19 trượt, R20 allow) — AD lúc B17 trả `probation` → E5 `recheck_failed`, 0 ghi, 0 `begun`."""
    env = Env(IN_HOURS, ad_user("nv001", employment_status="probation"))
    out = await env.node(_state())
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E5", "recheck_failed")
    detail = env.detail("recheck_failed")
    assert (detail["recheck"], detail["fields"], detail["rebuilt"]) == ("requester_changed", ["employment_status"], True)
    assert env.writes_total() == 0 and env.txlog.rows == []


async def test_q3h7_ad_same_as_snapshot_proceeds() -> None:
    env = Env(IN_HOURS, ad_user("nv001", employment_status="active"))
    out = await env.node(_state())
    assert out["status"] == S_CONFIRMING and env.writes.calls == {"renew_vpn_cert": 1}
    assert env.h.audit.of("t1", "recheck_failed") == []


async def test_q3h7_unwatched_field_change_proceeds() -> None:
    """Phòng ban đổi nhưng không luật nào tham chiếu `requester.department` → đi tiếp (chỉ trường luật dùng)."""
    env = Env(IN_HOURS, ad_user("nv001", department="sales"))
    out = await env.node(_state())
    assert out["status"] == S_CONFIRMING and env.writes.calls == {"renew_vpn_cert": 1}


def _extra_rule_policy(*facts: tuple[str, str, Any]) -> Any:
    rule = Rule.model_validate({
        "id": "R99", "type": "deny", "intent": "vpn", "action": "check_vpn_status", "description": "chỉ để test Q-3h-7",
        "conditions": {"all": [{"fact": f, "op": op, "value": v} for f, op, v in facts]},
    })  # fmt: skip
    policy = get_policy()
    return policy.model_copy(update={"rules": (*policy.rules, rule)})


async def test_q3h7_fields_follow_policy_department(monkeypatch: pytest.MonkeyPatch) -> None:
    """Luật (lúc dựng node) tham chiếu thêm `requester.department` → phòng ban đổi trong AD → E5, `fields` nêu đúng trường."""
    monkeypatch.setattr(b17_execute, "get_policy", lambda: _extra_rule_policy(("requester.department", "eq", "zzz")))
    env = Env(IN_HOURS, ad_user("nv001", department="sales"))
    out = await env.node(_state(requester_context=_requester().model_copy(update={"department": "finance"})))
    assert out["escalation_reason_detail"] == "recheck_failed"
    assert env.detail("recheck_failed")["fields"] == ["department"] and env.writes_total() == 0


async def test_q3h7_tenure_does_not_drift_with_waiting_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """`tenure_days` dựng lại tại mốc `captured_at` của B1 — chờ 30 ngày không làm "đổi" (chỉ đổi khi `hired_at` đổi)."""
    monkeypatch.setattr(b17_execute, "get_policy", lambda: _extra_rule_policy(("requester.tenure_days", "lt", 0)))
    captured = IN_HOURS - timedelta(days=30)
    snap = RequesterContext.from_ad(AdUser.model_validate(ad_user("nv001")), captured)
    env = Env(IN_HOURS, ad_user("nv001"))
    out = await env.node(_state(requester_context=snap))
    assert out["status"] == S_CONFIRMING and env.writes.calls == {"renew_vpn_cert": 1}
    env2 = Env(IN_HOURS, ad_user("nv001", hired_at=date(2025, 6, 1)))
    out2 = await env2.node(_state(requester_context=snap))
    assert env2.detail("recheck_failed")["fields"] == ["tenure_days"] and out2["exit_code"] == "E5"


async def test_q3h7_unmappable_groups_is_e5() -> None:
    """Nhóm AD không còn ra role (`from_ad` từ chối) → không dựng lại được bản chụp → E5 (chặt), không E9."""
    env = Env(IN_HOURS, ad_user("nv001", groups=("Other",)))
    out = await env.node(_state(), boundary=True)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E5", "recheck_failed")
    assert env.detail("recheck_failed")["rebuilt"] is False and env.writes_total() == 0


async def test_q3h7_make_refuses_unknown_requester_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b17_execute, "referenced_facts", lambda rules, source: frozenset({"khong_co"}))
    with pytest.raises(RuntimeError, match="khong_co"):
        b17_execute.make(GraphHarness().deps())


async def test_p4_budget_is_e2_before_begun() -> None:
    """P4 (M-3h-11): còn < 5 s dùng được → E2 `turn_budget_exceeded`, 0 dòng `begun`, 0 lời gọi ghi."""
    env = Env(IN_HOURS)
    with bind_turn_deadline(TurnDeadline(env.clock.now() + timedelta(seconds=6), 2.0)):
        out = await env.node(_state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E2", "turn_budget_exceeded")
    assert env.txlog.rows == [] and env.writes_total() == 0


async def test_write_error_is_e7_with_handoff() -> None:
    env = Env(IN_HOURS)
    env.writes.faults["renew_vpn_cert"] = lambda: http_error(500)
    out = await env.node(_state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_failed")
    res = ExecutionResult.model_validate(out["execution"])
    assert (res.success, res.failed_step, res.rollback_status) == (False, "renew_vpn_cert", "none_needed")
    assert out["escalation_note"] == res.handoff_note
    for part in ("Đã làm:", "Lỗi ở bước:", "Hoàn tác:", "L2 cần làm tay:"):
        assert part in (res.handoff_note or "")
    assert env.writes.calls == {"renew_vpn_cert": 1} and env.detail("exec_failed")["write_calls"] == 1


async def test_device_not_registered_409_is_e7_not_e9() -> None:
    """Bẫy mục 5: 409 `device_not_registered` là DỮ LIỆU → E7 `exec_failed` có handoff, không E9."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approval(action, decide="approved")
    env.writes.faults["renew_vpn_cert"] = lambda: http_error(409, "device_not_registered")
    out = await env.node(_approved_state(action, a_id), boundary=True)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_failed")
    assert "http_409" in out["escalation_note"]


async def test_refusing_executor_is_e7() -> None:
    env = Env(IN_HOURS)
    env.executor = RefusingExecutor(MemoryTxLog())
    out = await env.node(_state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_failed") and env.writes_total() == 0


class _Raises:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def execute(self, ticket_id: str, turn_id: str, action: Action) -> ExecutionResult:
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "code", "reason"),
    [(ExecutionInterrupted("x"), "E7", "exec_interrupted"), (TurnBudgetExceeded("x"), "E2", "turn_budget_exceeded"),
     (KeyError("PLAN"), "E9", None)],
    ids=["interrupted", "budget", "bug-E9"],
)  # fmt: skip
async def test_executor_exceptions_mapping(exc: BaseException, code: str, reason: str | None) -> None:
    env = Env(IN_HOURS)
    env.executor = _Raises(exc)
    out = await env.node(_state(), boundary=True)
    assert out["exit_code"] == code and out.get("escalation_reason_detail") in (reason, "unhandled_exception")


# ---- Q-3h-2: ExecutionResult.outputs ------------------------------------------------------------------------------------

_BASE: dict[str, Any] = {"success": True, "steps_done": ["renew_vpn_cert"], "failed_step": None, "rollback_status": "none_needed",
         "rollback_details": [], "action_plan_hash_matched": None, "handoff_note": None}  # fmt: skip


async def test_q3h2_a_outputs_round_trip_checkpoint() -> None:
    serde = make_serde()
    res = ExecutionResult(**_BASE, outputs={"serial": "VPN-NEW-0001", "expires_on": "2027-09-29"})
    assert serde.loads_typed(serde.dumps_typed(res)) == res


async def test_q3h2_b_old_checkpoint_without_outputs_loads() -> None:
    """Checkpoint ghi TRƯỚC 3h (ExecutionResult chưa có `outputs`) — giải mã ra đúng model, `outputs == {}`."""
    inner = ormsgpack.packb((ExecutionResult.__module__, "ExecutionResult", dict(_BASE), "model_validate_json"))
    loaded = make_serde().loads_typed(("msgpack", ormsgpack.packb(ormsgpack.Ext(EXT_PYDANTIC_V2, inner))))
    assert isinstance(loaded, ExecutionResult) and loaded.outputs == {} and loaded.success


@pytest.mark.parametrize(
    "outputs",
    [{"note": "xin chào", "serial": "VPN-NEW-0001"}, {"expires_on": "29/09/2027"}, {"expires_on": "2027-02-30"},
     {"serial": "VPN-NEW-0001 <b>"}, {"expires_on": "2027-09-29 <script>"}, {"serial": 12345}],
    ids=["khoa-la", "ngay-sai-dang", "ngay-khong-co", "serial-rac", "ngay-rac", "serial-so"],
)  # fmt: skip
async def test_q3h2_c_bad_outputs_dropped_and_not_in_message(outputs: dict[str, Any]) -> None:
    """M-3h-13: khoá lạ / sai mẫu → BỎ ngay ở model; tin B18 không chứa gì từ đó."""
    res = ExecutionResult(**_BASE, outputs=outputs)
    assert set(res.outputs) <= {"serial"} and all(v == "VPN-NEW-0001" for v in res.outputs.values())
    env = Env(IN_HOURS)

    class _Returns:
        async def execute(self, ticket_id: str, turn_id: str, action: Action) -> ExecutionResult:
            return ExecutionResult(**_BASE, outputs=outputs)

    env.executor = _Returns()
    out = await env.node(_state(), boundary=True)
    assert out["status"] == S_CONFIRMING
    [msg] = out["conversation"]
    assert msg["text"] == "Đã gia hạn chứng chỉ VPN cho máy LAP-0342. Bạn thử kết nối lại rồi xác nhận giúp mình nhé."


async def test_s12_worker_refusing_executor_with_begun_is_exec_interrupted() -> None:
    """Soát S12 NGHI-3 (đường worker): `RefusingExecutor` có txlog + `begun` sẵn → E7 `exec_interrupted`, 0 ghi. Lớp thứ hai:
    txlog của node (bước 0) để trống — `begun` chỉ có trong txlog của executor."""
    env = Env(IN_HOURS)
    executor_log = MemoryTxLog()
    await executor_log.begin("t1", "T1", "renew_vpn_cert")
    env.executor = RefusingExecutor(executor_log)
    out = await env.node(_state())
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_interrupted") and env.writes_total() == 0
    # soát lại DỪNG 2 NGHI-c: nhánh lớp thứ hai (`except ExecutionInterrupted`) giữ đúng câu chốt + 0 lời gọi ghi
    assert out["escalation_note"] == b17_execute.INTERRUPTED_NOTE
    detail = env.detail("exec_interrupted")
    assert detail["write_calls"] == 0 and "stage" not in detail and detail["matched_rule_id"] == "R20"


# ---- Chốt FAIL mục 7 (soát DỪNG 3b) ---------------------------------------------------------------------------------------

MAY_HAVE_WRITTEN = "có thể đã gửi lệnh ghi — L2 kiểm trên hệ thống đích trước khi làm tay"


@pytest.mark.parametrize("kind", AFTER_BEGIN)
async def test_fail7_error_after_begin_is_e7_warning_not_e9(kind: str) -> None:
    env = Env(IN_HOURS)
    fail_after_send(env.writes, kind)
    out = await env.node(_state(), boundary=True)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_interrupted")
    assert out["escalation_note"] == b17_execute.INTERRUPTED_NOTE and MAY_HAVE_WRITTEN in out["escalation_note"]
    detail = env.detail("exec_interrupted")
    assert (detail["cause"], detail["write_calls"]) == (kind, 1)  # chỉ tên lớp lỗi
    assert SECRET_BODY not in repr(env.h.audit.rows) and env.h.audit.of("t1", "unhandled_exception") == []
    assert env.writes.calls == {"renew_vpn_cert": 1}
    rerun = await env.node(_state(), boundary=True)  # recover chạy lại B17: bước 0 thấy begun → E7, không POST lần 2
    assert rerun["exit_code"] == "E7" and env.writes.calls == {"renew_vpn_cert": 1}


@pytest.mark.parametrize("where", ["txlog.begin", "ad_recheck"])
@pytest.mark.parametrize(
    "exc", [httpx.ReadError("x"), httpx.RemoteProtocolError("x"), ValueError("x")], ids=["ReadError", "RemoteProtocol", "json"]
)  # fmt: skip
async def test_fail7_same_errors_before_begun_are_e9(where: str, exc: Exception) -> None:
    env = Env(IN_HOURS)
    if where == "ad_recheck":
        env.ad.crash = exc  # lỗi ở bước [3] (đọc AD) — trước executor
    else:

        async def begin(*_: object) -> None:
            raise exc

        object.__setattr__(env.txlog, "begin", begin)  # thay method trên instance (khuôn test_gate3)
    out = await env.node(_state(), boundary=True)
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E9")
    assert env.writes_total() == 0 and env.txlog.rows == []


async def test_fail7_cancelled_after_begin_propagates_through_node() -> None:
    env = Env(IN_HOURS)
    env.writes.faults["renew_vpn_cert"] = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await env.node(_state(), boundary=True)
    assert env.writes.calls == {"renew_vpn_cert": 1} and env.h.audit.of("t1", "exec_interrupted") == []


async def test_fail7_b18_error_after_successful_write_is_e7_not_e9() -> None:
    """Ghi xong, gửi tin kết quả (B18) lỗi → E7 kèm câu cảnh báo và `execution`; không bao giờ E9 "xử lý thủ công"."""
    env = Env(IN_HOURS)

    async def notify_fails(*_: object) -> str:
        raise RuntimeError(SECRET_BODY)

    object.__setattr__(env.h.notifier, "notify_user", notify_fails)  # thay method trên instance
    out = await env.node(_state(), boundary=True)
    assert (out["exit_code"], out["escalation_reason_detail"]) == ("E7", "exec_interrupted")
    assert MAY_HAVE_WRITTEN in out["escalation_note"] and out["execution"].success
    detail = env.detail("exec_interrupted")
    assert (detail["stage"], detail["cause"], detail["write_calls"]) == ("b18", "RuntimeError", 1)
    assert SECRET_BODY not in repr(env.h.audit.rows) and env.writes.calls == {"renew_vpn_cert": 1}


async def test_t21_final_goto_error_after_write_is_e7_not_e9() -> None:
    """Việc treo 21: ghi xong, B18 xong, `goto(S_CONFIRMING)` cuối B17 (ngoài try) lỗi — audit sập → boundary thấy `begun` →
    E7 `execution_interrupted` + câu cảnh báo; không E9, chạy lại B17 không POST lần 2."""
    env = Env(IN_HOURS)
    real = env.h.audit.record

    async def record(row: Mapping[str, Any], **kw: Any) -> bool:
        if row["event"] == "executed_ok":
            raise RuntimeError("audit sập")
        return await real(row, **kw)

    env.h.audit.record = record  # type: ignore[method-assign]
    out = await env.node(_state(), boundary=True)
    assert (out["status"], out["exit_code"], out["escalation_reason_detail"]) == (S_ESCALATED, "E7", "execution_interrupted")
    assert MAY_HAVE_WRITTEN in out["escalation_note"]
    [row] = env.h.audit.of("t1", "unhandled_exception")
    assert (row["step"], row["exit_code"], row["detail"]["begun"]) == ("b17_execute", "E7", True)
    assert env.writes.calls == {"renew_vpn_cert": 1} and env.h.notifier.count("t1") == 1
    rerun = await env.node(_state(), boundary=True)  # recover chạy lại B17: bước 0 → E7, không POST lần 2
    assert rerun["exit_code"] == "E7" and env.writes.calls == {"renew_vpn_cert": 1}
