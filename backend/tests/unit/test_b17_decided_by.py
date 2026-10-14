"""B17 kiểm lại NGƯỜI ĐÃ DUYỆT (`decided_by`) — Phase 4 chặng 4b DỪNG 2 (PLAN-4b S11). Viết TỪ ĐẶC TẢ, trước code: phase4 mục 5.1
P13 (Q-4-P, G4-19), 5.3 b6/b7, 5.6 #1 (Q-4b-1: lỗi AD khi tra `decided_by` → E2; TQ-11: xét người gửi/người hưởng lợi TRƯỚC,
`decided_by` SAU, trong MỘT `gather`).

Khuôn `test_b17_execute.Env`: node B17 thật, `PlanExecutor` thật trên hệ thống ghi VPN giả (đếm ở nơi nhận), AD giả sau registry
đọc thật; harness gộp người trong roster (l1_01, l1_02, l1_lead, it_mgr01 — seed.json). Phiếu tạo bằng `h.approvals.create(...)`
(FK: người duyệt có dòng `users` giả — gieo tay) rồi `close(approved, decided_by=…)`. Đổi trạng thái / lỗi của người đã duyệt làm
TƯỜNG MINH (`set_status`, `fail_ids`, xoá khỏi AD, `seed_ad_records`).

- b6: người đã duyệt không còn hợp lệ (disabled / terminated / probation / không còn trong AD / sai nhóm, L2) → E5
  `approver_no_longer_valid`, 0 lời gọi ghi.
- b7: chỉ lời tra `decided_by` lỗi AD → E2 `approver_lookup_error`, 0 lời gọi ghi.
- `decided_by` None mà phiếu `approved` → E5 `recheck_failed` (`recheck="no_decided_by"`).
- Người đã duyệt hợp lệ (l1 hoặc manager) → thực thi; lời tra đúng 1 lần.
- Thứ tự (TQ-11): người gửi hỏng + `decided_by` hỏng → vẫn E5 `person_no_longer_valid` (nhánh cũ giữ nguyên).
- Đường AUTO (không qua duyệt) không tra `decided_by`.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from app.auth.models import UserRecord
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.context import RequesterContext, role_from_groups
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_EXECUTING
from app.executor.plan_executor import PlanExecutor
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b17_execute
from app.settings import get_action_metadata, get_policy
from tests.fakes.ad_seed import seed_ad_records
from tests.fakes.executor import FakeVpnWrites, MemoryTxLog
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user

pytestmark = pytest.mark.asyncio

IN_HOURS = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN — R20 allow (đường AUTO)
AFTER_HOURS = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)  # thứ Ba 20:00 giờ VN — R18 approval_required (đi qua duyệt)


def _requester(user: str = "nv001") -> RequesterContext:
    return RequesterContext(
        user_id=user, role="employee", department="finance", manager_id="fin_head", employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=IN_HOURS,
    )  # fmt: skip


def _action() -> Action:
    meta = get_action_metadata().root["vpn"]["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target="device:LAP-0342", requested_for="nv001", scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params={"device_id": "LAP-0342"},
        facts={"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired",
               "cert_days_to_expiry": -3, "last_connection_ok": False},
    )  # fmt: skip


def _state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_EXECUTING, "intent": "vpn", "reasoning_loops": 1,
        "requester_context": _requester(), "intended_action": _action(), "ctx_flags": {"target_is_other": False},
        "redacted_request": "gia hạn VPN cho máy LAP-0342", "slots": {"device_id": "LAP-0342", "action": "renew_vpn_cert"},
    }  # fmt: skip
    base.update(over)
    return base


class Env:
    """Khuôn `test_b17_execute.Env` (người gửi nv001 dựng bằng `ad_user` như khuôn B17); harness gộp roster (seed) vào AD giả."""

    def __init__(self, at: datetime, *users: dict[str, Any]) -> None:
        self.clock = FakeClock(at)
        self.ad = FakeAd(*(users or (ad_user("nv001"),)))
        self.writes, self.txlog = FakeVpnWrites(self.clock), MemoryTxLog()
        self.h = GraphHarness(clock=self.clock, ad=self.ad, txlog=self.txlog)
        self.executor: Any = PlanExecutor(self.writes.registry(), self.txlog, self.clock, tz=get_policy().business_hours.tz)

    @contextmanager
    def run(self) -> Iterator[None]:
        with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=self.h.audit, effects=self.h.effects,
                                 spans=self.h.spans, clock=self.clock, txlog=self.txlog)):  # fmt: skip
            yield

    async def node(self, state: dict[str, Any]) -> dict[str, Any]:
        deps = self.h.deps()
        deps.executor = self.executor
        fn = b17_execute.make(deps)
        with self.run():
            return cast(dict[str, Any], await fn(state))

    def _user_row(self, user_id: str) -> None:
        """Dòng `users` giả cho FK `approvals.approver_id` (MemoryApprovals kiểm như Postgres) — role từ nhóm AD seed."""
        assert self.h.auth_store is not None
        [rec] = seed_ad_records(IN_HOURS, [user_id])
        role = role_from_groups(rec["groups"])
        assert role is not None
        self.h.auth_store.users[user_id] = UserRecord(
            user_id=user_id, username=rec["username"], full_name=None, role=role, department=rec["department"],
            manager_id=None, employment_status="active", hired_at=None, is_privileged_account=False,
        )  # fmt: skip

    async def approved(self, action: Action, *, approver: str = "l1_01", decided_by: str | None = "l1_01") -> str:
        """Phiếu đã `approved` trong BẢNG (người duyệt giao = `approver`, người bấm = `decided_by`)."""
        self._user_row(approver)
        a_id = await self.h.approvals.create(
            "t1", approver, self.clock.now() + timedelta(minutes=30), hash_action(action),
            backup_approver_id=None, conflict_detected=False, conflict_type=None,
        )  # fmt: skip
        await self.h.approvals.close(a_id, "approved", self.clock.now(), decided_by=decided_by, note="ok")
        return a_id

    def writes_total(self) -> int:
        return sum(self.writes.calls.values())

    def detail(self, event: str) -> dict[str, Any]:
        [row] = self.h.audit.of("t1", event)
        return dict(row["detail"])


def _approved_state(action: Action, a_id: str) -> dict[str, Any]:
    return _state(intended_action=action, approval_id=a_id, approval_result="approved",
                  action_plan_hash=hash_action(action))  # fmt: skip


def _no_write(env: Env) -> None:
    assert env.writes_total() == 0 and env.txlog.rows == []


def _exit(out: dict[str, Any]) -> tuple[Any, Any, Any]:
    """(status, exit_code, reason_detail) — `.get` để đường "đi tiếp" (chưa kiểm) hiện ra trong thông báo đỏ, không KeyError."""
    return out.get("status"), out.get("exit_code"), out.get("escalation_reason_detail")


# ---- b6: người đã duyệt không còn hợp lệ → E5 approver_no_longer_valid ---------------------------------------------------


def _disabled(env: Env) -> None:
    env.h.ad.set_status("l1_01", "disabled")


def _terminated(env: Env) -> None:
    env.h.ad.set_status("l1_01", "terminated")


def _probation(env: Env) -> None:
    env.h.ad.set_status("l1_01", "probation")


def _gone(env: Env) -> None:
    del env.h.ad.users["l1_01"]  # không còn trong AD → 404 = không hợp lệ (không phải lỗi)


def _moved_to_l2(env: Env) -> None:
    env.h.ad.users["l1_01"]["groups"] = ["IT-Users", "IT-L2"]  # role l2: không phải l1, không phải manager


@pytest.mark.parametrize(
    "change",
    [_disabled, _terminated, _probation, _gone, _moved_to_l2],
    ids=["b6-disabled", "terminated", "probation", "khong-con-trong-AD", "doi-nhom-L2"],
)
async def test_b6_decided_by_no_longer_valid_is_e5_zero_writes(change: Callable[[Env], None]) -> None:
    """b6 (P13, Q-4-P, M-4b-10): phiếu `approved` bởi l1_01; SAU khi duyệt, l1_01 không còn hợp lệ (không active, hoặc nhóm AD không
    còn ra `l1`/`manager`, hoặc không còn trong AD) → B17 E5 `approver_no_longer_valid` (event cùng tên), 0 lời gọi ghi, 0 `begun`."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approved(action)
    change(env)
    out = await env.node(_approved_state(action, a_id))
    got = _exit(out)
    assert got == (S_ESCALATED, "E5", "approver_no_longer_valid"), (got, env.h.audit.events("t1"))
    assert len(env.h.audit.of("t1", "approver_no_longer_valid")) == 1
    _no_write(env)


async def test_b6_decided_by_is_l2_user_is_e5() -> None:
    """b6 / L2 không bao giờ là người duyệt: `decided_by` = l2_01 (active, nhóm IT-L2 — thêm bằng `seed_ad_records`) → E5
    `approver_no_longer_valid`, 0 ghi."""
    env = Env(AFTER_HOURS)
    env.h.ad.add(*seed_ad_records(AFTER_HOURS, ["l2_01"]))
    action = _action()
    a_id = await env.approved(action, decided_by="l2_01")
    out = await env.node(_approved_state(action, a_id))
    assert _exit(out) == (S_ESCALATED, "E5", "approver_no_longer_valid")
    _no_write(env)


# ---- b7: lỗi AD CHỈ ở lời tra decided_by → E2 --------------------------------------------------------------------------------


async def test_b7_ad_error_on_decided_by_only_is_e2_approver_lookup_error() -> None:
    """b7 (Q-4b-1, 5.6 #1): người gửi tra được, CHỈ lời tra `decided_by` lỗi (HTTP 500 sau retry, `fail_ids`) → E2
    `approver_lookup_error` (event cùng tên) — KHÔNG E5 như nhánh người gửi; 0 lời gọi ghi."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approved(action)
    env.h.ad.fail_ids.add("l1_01")
    out = await env.node(_approved_state(action, a_id))
    got = _exit(out)
    assert got == (S_ESCALATED, "E2", "approver_lookup_error"), (got, env.h.audit.events("t1"))
    assert len(env.h.audit.of("t1", "approver_lookup_error")) == 1
    assert env.h.audit.of("t1", "person_no_longer_valid") == []
    _no_write(env)


# ---- decided_by None mà approved → E5 recheck_failed ------------------------------------------------------------------------


async def test_p13_approved_without_decided_by_is_e5_recheck_failed() -> None:
    """P13: phiếu `approved` trong bảng nhưng `decided_by` None (không biết ai duyệt) → E5 `recheck_failed`, `detail.recheck =
    "no_decided_by"`, 0 lời gọi ghi."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approved(action, decided_by=None)
    out = await env.node(_approved_state(action, a_id))
    got = _exit(out)
    assert got == (S_ESCALATED, "E5", "recheck_failed"), (got, env.h.audit.events("t1"))
    assert env.detail("recheck_failed")["recheck"] == "no_decided_by"
    _no_write(env)


# ---- người đã duyệt hợp lệ → thực thi, tra đúng 1 lần -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("approver", "decided_by"),
    [pytest.param("l1_01", "l1_01", id="l1-hop-le"), pytest.param("it_mgr01", "it_mgr01", id="manager-hop-le-it_mgr01")],
)
async def test_p13_valid_decided_by_proceeds_and_is_looked_up_once(approver: str, decided_by: str) -> None:
    """P13: người đã duyệt còn hợp lệ — l1 (l1_01) hoặc manager (it_mgr01, Trưởng BP duyệt ca xung đột) → đi tiếp như cũ (thực thi
    đúng 1 lần); lời tra AD của người đã duyệt xảy ra đúng 1 lần (bước `B17_RECHECK`)."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approved(action, approver=approver, decided_by=decided_by)
    out = await env.node(_approved_state(action, a_id))
    assert out["status"] == S_CONFIRMING, env.h.audit.events("t1")
    assert env.writes.calls == {"renew_vpn_cert": 1}
    assert env.h.ad.calls_by[decided_by] == 1
    assert env.h.audit.of("t1", "approver_no_longer_valid") == []


# ---- thứ tự (TQ-11): người gửi trước, decided_by sau, MỘT gather ------------------------------------------------------------


def _requester_disabled(env: Env) -> None:
    env.h.ad.users["nv001"] = ad_user("nv001", employment_status="disabled")


@pytest.mark.parametrize(
    "decided_by_change",
    [_disabled, lambda env: env.h.ad.fail_ids.add("l1_01")],
    ids=["decided_by-disabled", "decided_by-AD-loi"],
)
async def test_tq11_requester_invalid_wins_over_decided_by(decided_by_change: Callable[[Env], None]) -> None:
    """TQ-11 / Q-4b-1: người gửi hỏng (disabled) VÀ người đã duyệt hỏng (disabled hoặc AD lỗi) → vẫn E5 `person_no_longer_valid`
    (nhánh cũ, xét TRƯỚC), không E5 `approver_no_longer_valid` / E2 `approver_lookup_error`. Ba người tra trong CÙNG một `gather` →
    `decided_by` VẪN được tra (≥ 1 lời gọi ở nơi nhận) dù người gửi đã hỏng. 0 lời gọi ghi."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approved(action)
    _requester_disabled(env)
    decided_by_change(env)
    out = await env.node(_approved_state(action, a_id))
    got = _exit(out)
    assert got == (S_ESCALATED, "E5", "person_no_longer_valid"), (got, env.h.audit.events("t1"))
    assert env.h.audit.of("t1", "approver_no_longer_valid") == []
    assert env.h.audit.of("t1", "approver_lookup_error") == []
    assert env.h.ad.calls_by["l1_01"] >= 1
    _no_write(env)


# ---- đường AUTO: không tra decided_by -------------------------------------------------------------------------------------------


async def test_p13_auto_path_does_not_look_up_decided_by() -> None:
    """P13 "khi `via_approval`": đường AUTO (R20 allow trong giờ, không phiếu) → chỉ tra người gửi; không ai trong roster bị tra."""
    env = Env(IN_HOURS)
    out = await env.node(_state())
    assert out["status"] == S_CONFIRMING and env.writes.calls == {"renew_vpn_cert": 1}
    assert dict(env.h.ad.calls_by) == {"nv001": 1}
