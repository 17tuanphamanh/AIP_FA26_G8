"""B15 THẬT — chọn người duyệt, xung đột, đồng bộ `users`, điểm log 5 (Phase 4 chặng 4b DỪNG 2, PLAN-4b S11). Viết TỪ ĐẶC TẢ,
trước code: phase4 mục 3.1, 3.2 (bảng x1–x14b), 5.1 P2–P11, 5.2, 5.3 b3/b8, 5.6 #1–#8 (THẮNG khi lệch), 4.10 #11.

- Node gọi trực tiếp trên `GraphHarness` (khuôn `test_b17_execute.Env`): AD giả = registry THẬT trên `FakeAd` đọc
  `mock_services/seed.json` (`tests/fakes/ad_seed.py`); harness gộp `ROSTER_CHAIN` (l1_01 → l1_lead → it_mgr01, l1_02) — ca đổi trạng
  thái / lỗi / thiếu người làm TƯỜNG MINH (`set_status`, `fail_ids`, `roster_in_ad=False`, `seed_ad_records`). Người gửi lấy từ seed
  (nv003 probation) — không dùng `ad_user()` mặc định.
- Bảng 3.2 qua node: x1–x4, x7–x12, x14, x14b; graph `nodes="real"`: x1, x2, x13 (khuôn `test_hrule_4b_owner._graph`).
- b3 (FK `users`, không phiên), b8 (điểm log 5), Q-4b-5 (thiếu khoá HMAC), Q-4b-6 (sếp trung gian không ra role), TQ-7 (nhánh `peek`),
  4.10 #11 (mang khoá trượt username ma), P2 (probation, 404), P3 (cache + `B15_APPROVER`), hạn lượt, AST (P11 + P1 5.3).
"""

import ast
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from app.auth.models import SessionRecord, UserRecord
from app.auth.ports import AdUser as AuthAdUser
from app.auth.service import auth_config, lock_policy
from app.auth.user_sync import AuthApproverUsers
from app.auth.username_hash import stored_username
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.core.turn_budget import TurnDeadline, bind_turn_deadline
from app.domain.action import Action, FactValue
from app.domain.approval import Lookup, Roster
from app.domain.context import RequesterContext, role_from_groups
from app.domain.exit_codes import REASON_DETAILS
from app.domain.states import S_ASSESSING, S_ESCALATED, S_PENDING_APPROVAL
from app.domain.ticket_state import ChunkRef
from app.graph import effects
from app.graph.context import RunContext, bind_run
from app.graph.fakes import ApproverUsers, fake_risk
from app.graph.nodes import b12_assess, b15_prepare_approval
from app.graph.ports import ToolCaller, ToolResult
from app.rag.models import RetrievalResult
from app.risk.models import RuleVerdict
from app.settings import Settings, get_action_metadata, get_policy
from app.tools.models import AdUser
from tests.fakes.ad_seed import ROSTER_CHAIN, seed_ad, seed_ad_records
from tests.fakes.auth import InMemoryAuthStore
from tests.fakes.graph import HARNESS_USERNAME_KEY, Crash, GraphHarness
from tests.fakes.identity import fake_directory
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts
from tests.unit.test_side_effects_ast import find_violations

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN — trong giờ: x1 khớp R19, x2–x4 khớp R17, không R18
MARGIN = 2.0
META = get_action_metadata().of("vpn")
NODE_FILE = Path(__file__).resolve().parents[2] / "app" / "graph" / "nodes" / "b15_prepare_approval.py"

# Điểm log 5 (P10 + 5.6 #8): ĐÚNG các khoá này trong `detail`, giá trị thuộc tập đóng — không chữ tự do.
POINT5_DETAIL = frozenset({"backup_approver_id", "conflict_type", "choice_reason", "rejected_candidates", "sla_minutes",
                           "recovered"})  # fmt: skip
CONFLICT_TYPES = frozenset({"self", "boss_of_approver", "targets_approver"})
CHOICE_REASONS = frozenset({"normal", "conflict", "no_valid_l1"})
REJECT_REASONS = frozenset({"not_found", "inactive", "wrong_group", "self", "boss_of_approver", "targets_approver"})
# P11 + Q-4b-5 + nhánh hạn lượt: `reason_detail` hằng của B15 (event = CHÍNH chuỗi đó)
B15_REASONS = frozenset({"approval_target_unverified", "no_valid_approver", "approver_lookup_error",
                         "approver_sync_unavailable", "turn_budget_exceeded"})  # fmt: skip
ROSTER_ROWS = ("l1_01", "l1_02", "l1_lead", "it_mgr01")

type Rejected = tuple[tuple[str, str], ...]


# ---- dựng dữ liệu (seed.json) ------------------------------------------------------------------------------------------


def _rc(user_id: str) -> RequesterContext:
    """Bản chụp B1 của người gửi từ AD seed (nv003 = probation, l1_01/l1_lead = l1, it_mgr01 = manager)."""
    [rec] = seed_ad_records(NOW, [user_id])
    return RequesterContext.from_ad(AdUser.model_validate(rec), NOW)


def _action(requested_for: str, device_id: str, *, registered: bool, owner: bool | None = True) -> Action:
    """Như `test_approval_domain._action`: thuộc tính rủi ro từ `config/action_metadata.yaml`, đích `device:{id}`. `owner=None` →
    thiếu hẳn fact `device_owner_is_requester` (x12)."""
    m = META["renew_vpn_cert"]
    facts: dict[str, FactValue] = {"device_registered": registered}
    if owner is not None:
        facts["device_owner_is_requester"] = owner
    return Action(
        type="renew_vpn_cert", target=f"device:{device_id}", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": device_id}, facts=facts,
    )  # fmt: skip


def _state(requester: str, action: Action, **over: Any) -> dict[str, Any]:
    device = str(action.params["device_id"])
    base: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_ASSESSING, "intent": "vpn", "reasoning_loops": 1,
        "requester_context": _rc(requester), "intended_action": action, "ctx_flags": {"target_is_other": False},
        "slots": {"device_id": device, "action": action.type}, "risk": fake_risk("HITL"),
        "redacted_request": f"gia hạn VPN cho máy {device}",
    }  # fmt: skip
    base.update(over)
    return base


def _x1() -> tuple[Action, dict[str, Any]]:
    """x1: nv003 (probation) xin gia hạn LAP-0501 — máy ĐÃ đăng ký của chính mình (R19)."""
    action = _action("nv003", "LAP-0501", registered=True)
    return action, _state("nv003", action)


def _user_row(store: InMemoryAuthStore, user_id: str) -> None:
    """Dòng `users` dựng tay (FK phiếu cũ ở TQ-7) — role từ nhóm AD seed."""
    [rec] = seed_ad_records(NOW, [user_id])
    role = role_from_groups(rec["groups"])
    assert role is not None
    store.users[user_id] = UserRecord(
        user_id=user_id, username=rec["username"], full_name=None, role=role, department=rec["department"],
        manager_id=None, employment_status="active", hired_at=None, is_privileged_account=False,
    )  # fmt: skip


class SpyDirectory:
    """`ToolCaller` bọc registry thật — ghi (tool, caller_step) mọi lời gọi của node (P3: `B15_APPROVER`)."""

    def __init__(self, inner: ToolCaller) -> None:
        self.inner = inner
        self.calls: list[tuple[str, str]] = []

    async def call(self, name: str, args: Mapping[str, Any], *, caller_step: str) -> ToolResult:
        self.calls.append((name, caller_step))
        return await self.inner.call(name, args, caller_step=caller_step)


class SpyApproverUsers:
    """Port `ApproverUsers` giả (Q-4b-5): `available` cố định, đếm `ensure`."""

    def __init__(self, available: bool) -> None:
        self._available = available
        self.ensured = 0

    @property
    def available(self) -> bool:
        return self._available

    async def ensure(self, ad_user: AuthAdUser, lookup: Lookup[AuthAdUser], *, now: datetime) -> None:
        self.ensured += 1


class Env:
    """Node B15 thật gọi trực tiếp (khuôn `test_b17_execute.Env`). Mỗi `run` = một "process" (`h.deps()` dựng registry mới)."""

    def __init__(
        self, requester: str = "nv003", *, roster: Roster | None = None, extra_ad: tuple[str, ...] = (),
        approver_users: ApproverUsers | None = None, roster_in_ad: bool = True, spy_directory: bool = False,
    ) -> None:  # fmt: skip
        self.clock = FakeClock(NOW)
        opts: dict[str, Any] = {}
        if roster is not None:
            opts["approvers"] = {"vpn": roster}
        if approver_users is not None:
            opts["approver_users"] = approver_users
        ad = seed_ad(NOW, [requester, *ROSTER_CHAIN]) if spy_directory else seed_ad(NOW, [requester])
        self.spy: SpyDirectory | None = None
        if spy_directory:  # directory tự dựng → harness KHÔNG gộp roster — đã gieo đủ ROSTER_CHAIN ở trên
            self.spy = SpyDirectory(fake_directory(ad, self.clock))
            opts["directory"] = self.spy
        self.h = GraphHarness(clock=self.clock, ad=ad, roster_in_ad=roster_in_ad, **opts)
        if extra_ad:
            self.h.ad.add(*seed_ad_records(NOW, extra_ad))

    @property
    def store(self) -> InMemoryAuthStore:
        assert self.h.auth_store is not None
        return self.h.auth_store

    @property
    def sla(self) -> int:
        return self.h.deps().approval_sla_minutes

    @contextmanager
    def bound(self, state: Mapping[str, Any]) -> Iterator[None]:
        with bind_run(RunContext(turn_id=str(state["turn_id"]), trace_id="0" * 32, audit=self.h.audit,
                                 effects=self.h.effects, spans=self.h.spans, clock=self.clock, txlog=self.h.txlog)):  # fmt: skip
            yield

    async def run(self, state: dict[str, Any], *, usable_s: float | None = None) -> dict[str, Any]:
        fn = b15_prepare_approval.make(self.h.deps())
        with self.bound(state):
            if usable_s is None:
                return cast(dict[str, Any], await fn(state))
            with bind_turn_deadline(TurnDeadline(self.clock.now() + timedelta(seconds=usable_s + MARGIN), MARGIN)):
                return cast(dict[str, Any], await fn(state))

    async def old_approval(
        self, state: dict[str, Any], *, approver: str, backup: str | None, conflict_type: str | None, deadline: datetime,
    ) -> str:  # fmt: skip
        """Phiếu CŨ tạo qua CÙNG khoá `effects.once("approval_create", step="B15")` của lượt — như lần chạy trước đã tạo rồi chết."""
        for uid in (approver, backup):
            if uid is not None:
                _user_row(self.store, uid)
        with self.bound(state):
            ref = await effects.once(
                state, "approval_create", self.h.approvals.create, "t1", approver, deadline,
                hash_action(state["intended_action"]), step="B15", backup_approver_id=backup,
                conflict_detected=conflict_type is not None, conflict_type=conflict_type,
            )  # fmt: skip
        assert ref is not None
        return str(ref)

    def row(self, event: str) -> dict[str, Any]:
        rows = self.h.audit.of("t1", event)
        assert len(rows) == 1, (event, self.h.audit.events("t1"))
        return rows[0]


def _crash_once() -> Callable[[Mapping[str, Any]], None]:
    armed = [True]

    def hook(_: Mapping[str, Any]) -> None:
        if armed:
            armed.clear()
            raise Crash("SIGKILL tại after_approval_create — phiếu đã có, chưa notify_approver (Q-4b-3)")

    return hook


def _rejected(pairs: Rejected) -> list[dict[str, str]]:
    return [{"user_id": u, "reason": r} for u, r in pairs]


async def _assert_queued(
    env: Env, out: dict[str, Any], action: Action, *, approver: str, backup: str | None, conflict_type: str | None,
    reason: str, rejected: Rejected,
) -> str:  # fmt: skip
    """Nhánh thường: đúng 1 phiếu, báo ĐÚNG người duyệt, state + điểm log 5 (P10, 5.6 #8, Q-4b-4)."""
    assert (out["status"], out["next"]) == (S_PENDING_APPROVAL, "approval_wait"), env.h.audit.events("t1")
    aid = str(out["approval_id"])
    assert out["action_plan_hash"] == hash_action(action)
    a = await env.h.approvals.get(aid)
    assert a is not None
    got = (a.approver_id, a.backup_approver_id, a.conflict_detected, a.conflict_type)
    assert got == (approver, backup, conflict_type is not None, conflict_type), got
    assert a.deadline == NOW + timedelta(minutes=env.sla)
    assert env.h.deadlines.approvals[aid]["action_plan_hash"] == hash_action(action)
    assert env.h.approvals.count("t1") == 1 and env.h.approvals.notified == [(aid, approver)]
    assert env.h.effects.count("t1", "approval_create") == 1 and env.h.effects.count("t1", "notify_approver") == 1
    row = env.row("queued")
    assert row["step"] == "B15"
    assert (row["approver_id"], row["deadline"], row["conflict_detected"]) == (approver, a.deadline, conflict_type is not None)
    assert row["action_plan_hash"] == hash_action(action)
    assert set(row["detail"]) == POINT5_DETAIL, row["detail"]
    assert row["detail"] == {
        "backup_approver_id": backup, "conflict_type": conflict_type, "choice_reason": reason,
        "rejected_candidates": _rejected(rejected), "sla_minutes": env.sla, "recovered": False,
    }  # fmt: skip
    return aid


def _assert_refused(
    env: Env, out: dict[str, Any], *, code: str, reason_detail: str, stage: str, rejected: Rejected | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Nhánh E của B15 (P11): goto(S_ESCALATED → b20_audit, step B15, event = reason_detail); 0 phiếu, 0 thông báo."""
    got = (out["status"], out["next"], out["exit_code"], out["escalation_reason_detail"])
    assert got == (S_ESCALATED, "b20_audit", code, reason_detail), (got, env.h.audit.events("t1"))
    assert env.h.approvals.count("t1") == 0 and env.h.approvals.notified == []
    assert env.h.effects.count("t1", "approval_create") == 0 and env.h.effects.count("t1", "notify_approver") == 0
    assert env.h.audit.of("t1", "queued") == []
    row = env.row(reason_detail)
    assert (row["step"], row["exit_code"]) == ("B15", code)
    assert row["detail"]["stage"] == stage
    if rejected is not None:
        assert row["detail"]["rejected_candidates"] == _rejected(rejected)
    return row


# ---- Bảng 3.2 qua node ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ca:
    requester: str
    device: str
    registered: bool
    approver: str | None  # None = E5 no_valid_approver
    backup: str | None = None
    conflict_type: str | None = None
    reason: str = "normal"
    rejected: Rejected = ()
    status: tuple[tuple[str, str], ...] = ()  # `h.ad.set_status` TƯỜNG MINH (như /_admin/users/{id}/status)
    roster: Roster | None = None
    extra_ad: tuple[str, ...] = ()  # người thêm vào AD giả qua `seed_ad_records`
    requested_for: str | None = None  # None = chính người gửi


# fmt: off
BANG_3_2 = [
    pytest.param(Ca("nv003", "LAP-0501", True, "l1_01", "l1_02"), id="x1-nv003-R19-l1_01-backup-l1_02-normal"),
    pytest.param(Ca("l1_01", "PC-0124", False, "it_mgr01", None, "self", "conflict", (("l1_01", "self"),)),
                 id="x2-TC19-l1_01-tu-gui-self-truong-BP"),
    pytest.param(Ca("l1_lead", "LAP-0700", False, "it_mgr01", None, "boss_of_approver", "conflict",
                    (("l1_01", "boss_of_approver"),)), id="x3-l1_lead-sep-truc-tiep-truong-BP"),
    pytest.param(Ca("it_mgr01", "LAP-0900", False, None,
                    rejected=(("l1_01", "boss_of_approver"), ("it_mgr01", "self"))),
                 id="x4-it_mgr01-sep-chuoi-head-self-E5-no_valid_approver"),
    pytest.param(Ca("nv003", "LAP-0501", True, "l1_02", "it_mgr01", rejected=(("l1_01", "inactive"),),
                    status=(("l1_01", "disabled"),)), id="x7-l1_01-disabled-l1_02-backup-it_mgr01"),
    pytest.param(Ca("nv003", "LAP-0501", True, "it_mgr01", None, None, "no_valid_l1",
                    (("l1_01", "inactive"), ("l1_02", "inactive")),
                    status=(("l1_01", "disabled"), ("l1_02", "disabled"))),
                 id="x8-het-L1-hop-le-truong-BP-no_valid_l1"),
    pytest.param(Ca("nv003", "LAP-0501", True, "l1_02", "it_mgr01", rejected=(("l2_01", "wrong_group"),),
                    roster=Roster(primary="l2_01", backup="l1_02", head="it_mgr01"), extra_ad=("l2_01",)),
                 id="x10-primary-l2_01-wrong_group-L2-khong-duyet"),
    pytest.param(Ca("nv003", "LAP-0501", True, "it_mgr01", None, "targets_approver", "conflict",
                    (("l1_01", "targets_approver"),), requested_for="l1_01"),
                 id="x11-requested_for-l1_01-targets_approver"),
]
# fmt: on


@pytest.mark.parametrize("ca", BANG_3_2)
async def test_x_table_3_2_real_node(ca: Ca) -> None:
    """Bảng 3.2 (phase4) qua node B15 THẬT: xung đột → Trưởng BP (M-4b-1), Trưởng BP xung đột → E5 (M-4b-2, M-4b-3), người
    chính không hợp lệ → dự phòng (M-4b-4), L2 không bao giờ duyệt. `rejected_candidates` theo thứ tự đánh giá như
    `test_approval_domain.py`. Mỗi người tra AD ≤ 1 lần trong một lần chạy (P3)."""
    env = Env(ca.requester, roster=ca.roster, extra_ad=ca.extra_ad)
    for uid, st in ca.status:
        env.h.ad.set_status(uid, st)
    action = _action(ca.requested_for or ca.requester, ca.device, registered=ca.registered)
    out = await env.run(_state(ca.requester, action))
    if ca.approver is None:
        _assert_refused(env, out, code="E5", reason_detail="no_valid_approver", stage="choose", rejected=ca.rejected)
    else:
        await _assert_queued(env, out, action, approver=ca.approver, backup=ca.backup, conflict_type=ca.conflict_type,
                             reason=ca.reason, rejected=ca.rejected)  # fmt: skip
        assert "l2_01" not in env.store.users  # L2 không bao giờ là người duyệt / dự phòng
    assert env.h.ad.calls_by and max(env.h.ad.calls_by.values()) == 1, env.h.ad.calls_by


async def test_x_table_node_rows_cover_spec() -> None:
    """Quy ước 3.9: bảng không rỗng — các dòng 3.2 chạy qua node ở file này."""
    ids = {str(p.id).split("-")[0] for p in BANG_3_2}
    assert ids == {"x1", "x2", "x3", "x4", "x7", "x8", "x10", "x11"}


@pytest.mark.parametrize("fail", ["l1_01", "l1_lead"], ids=["nguoi-duyet-chinh", "giua-chuoi-quan-ly-P4"])
async def test_x9_ad_error_at_approver_lookup_via_hook_is_e2(fail: str) -> None:
    """x9 (M-4b-5): AD lỗi 500 khi tra người duyệt — bơm bằng hook `before_approver_lookup` NGAY trước khi B15 tra (không bơm từ
    đầu). → E2 `approver_lookup_error`, 0 phiếu, không dòng `users` nào của roster; KHÔNG coi là "không hợp lệ" rồi chọn người khác."""
    env = Env()
    env.h.scenario.on("t1", "before_approver_lookup", lambda _: env.h.ad.fail_ids.add(fail))
    _, state = _x1()
    out = await env.run(state)
    _assert_refused(env, out, code="E2", reason_detail="approver_lookup_error", stage="lookup")
    assert env.h.ad.calls_by[fail] >= 1  # lỗi thật sự đã xảy ra ở lời tra (hook đã chạy trước lời tra)
    assert not set(ROSTER_ROWS) & set(env.store.users)  # E2 trước `ensure`


@pytest.mark.parametrize("owner", [None, False], ids=["owner-thieu", "owner-false"])
async def test_x12_device_target_owner_not_true_e5_before_any_ad_call(owner: bool | None) -> None:
    """x12 / P6 (M-4b-8): đích `device:…` mà `facts.device_owner_is_requester is not True` → E5 `approval_target_unverified`,
    TRƯỚC mọi lời gọi AD (0 lời gọi), 0 phiếu, 0 dòng `users` mới."""
    env = Env()
    action = _action("nv003", "LAP-0501", registered=True, owner=owner)
    users_before = set(env.store.users)
    out = await env.run(_state("nv003", action))
    _assert_refused(env, out, code="E5", reason_detail="approval_target_unverified", stage="target_guard")
    assert env.h.ad.calls == 0
    assert set(env.store.users) == users_before


async def test_x14_rerun_after_kill_one_approval_notifies_old_approver_no_ad() -> None:
    """x14 (TC33, Q-4b-3, M-4b-9 = bỏ `peek` + báo người vừa chọn): giết process tại hook `after_approval_create` (phiếu đã có,
    chưa báo); tắt `l1_01` trong AD giữa hai lần chạy; chạy lại node CÙNG state/lượt → đúng 1 phiếu, đúng 1 `notify_approver` cho
    `a.approver_id` (l1_01 — người của phiếu cũ, KHÔNG phải l1_02 nếu chọn lại), 0 lời gọi AD ở lần chạy lại."""
    env = Env()
    _, state = _x1()
    env.h.scenario.on("t1", "after_approval_create", _crash_once())
    with pytest.raises(Crash):
        await env.run(state)
    assert env.h.approvals.count("t1") == 1 and env.h.approvals.notified == []
    [aid] = list(env.h.deadlines.approvals)
    assert env.h.deadlines.approvals[aid]["approver_id"] == "l1_01"
    env.h.ad.set_status("l1_01", "disabled")
    calls = env.h.ad.calls
    out = await env.run(state)
    assert (out["status"], out["next"], out["approval_id"]) == (S_PENDING_APPROVAL, "approval_wait", aid)
    assert env.h.approvals.count("t1") == 1
    assert env.h.approvals.notified == [(aid, "l1_01")]
    assert env.h.effects.count("t1", "approval_create") == 1 and env.h.effects.count("t1", "notify_approver") == 1
    assert env.h.ad.calls == calls
    detail = env.row("queued")["detail"]
    assert (detail["recovered"], detail["rejected_candidates"]) == (True, None)


async def test_x14b_rerun_with_ad_down_keeps_old_approval_not_e2() -> None:
    """x14b (P9 `peek`, M-4b-13): như x14 nhưng AD lỗi TOÀN BỘ lúc chạy lại → vẫn `S_PENDING_APPROVAL` với phiếu cũ, KHÔNG E2
    (phiếu mồ côi), 0 lời gọi AD ở lần chạy lại."""
    env = Env()
    _, state = _x1()
    env.h.scenario.on("t1", "after_approval_create", _crash_once())
    with pytest.raises(Crash):
        await env.run(state)
    [aid] = list(env.h.deadlines.approvals)
    env.h.ad.down = True
    calls = env.h.ad.calls
    out = await env.run(state)
    assert (out["status"], out["approval_id"]) == (S_PENDING_APPROVAL, aid)
    assert out.get("exit_code") is None and env.h.audit.of("t1", "approver_lookup_error") == []
    assert env.h.ad.calls == calls
    assert env.h.approvals.count("t1") == 1 and env.h.approvals.notified == [(aid, "l1_01")]


# ---- Graph nodes="real" (x1, x2, x13) --------------------------------------------------------------------------------------


def _rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-VPN-004", version=1, seq=0, title="T", heading_path="H",
                     score=0.99, excerpt="x")  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False))  # fmt: skip


async def _graph(requester: str, text: str) -> tuple[GraphHarness, dict[str, Any]]:
    """Khuôn `test_hrule_4b_owner._graph`: B1 → … → B12 → B15 THẬT (sau S12), VPN giả đọc seed, ScriptedLLM `vpn_scripts`. Người
    gửi lấy từ AD seed (`seed_ad`), harness gộp `ROSTER_CHAIN`."""
    clock = FakeClock(NOW)
    gw = make_gateway(vpn_scripts(), clock=clock)  # type: ignore[arg-type]
    h = GraphHarness(clock=clock, nodes="real", llm=gw.client, rag=_rag(), ad=seed_ad(NOW, [requester]))
    h.identity.add_session(f"s-{requester}", requester, expires_at=clock.now() + timedelta(days=365))
    h.tickets.register("t1", clock.now(), requester_id=requester)
    values = (await h.runner.submit("t1", session_id=f"s-{requester}", redacted_request=text)).values
    return h, cast(dict[str, Any], values)


def _only_approval(h: GraphHarness) -> str:
    [aid] = [a for a, row in h.deadlines.approvals.items() if row["ticket_id"] == "t1"]
    return aid


@pytest.mark.parametrize(
    ("requester", "text", "rule", "approver", "backup", "conflict_type", "reason"),
    [
        pytest.param("nv003", "gia hạn VPN cho máy LAP-0501", "R19", "l1_01", "l1_02", None, "normal", id="x1-graph"),
        pytest.param("l1_01", "gia hạn VPN cho máy PC-0124", "R17", "it_mgr01", None, "self", "conflict",
                     id="x2-graph-TC19"),
    ],
)  # fmt: skip
async def test_x1_x2_graph_real_nodes_reach_pending_with_spec_approver(
    requester: str, text: str, rule: str, approver: str, backup: str | None, conflict_type: str | None, reason: str
) -> None:
    """x1/x2 qua CẢ graph (`nodes="real"`, S12: B15 thật nằm trong `builder.REAL_NODE_MODULES`): luật đúng (R19/R17) → B15 → phiếu
    giao đúng người theo bảng 3.2, điểm log 5 có `choice_reason`. Trước S12 graph còn B15 GIẢ (`l1-fake`) → đỏ ở người duyệt."""
    h, v = await _graph(requester, text)
    assert v["status"] == S_PENDING_APPROVAL, h.audit.events("t1")
    [risk] = h.audit.of("t1", "risk_decided")
    assert (risk["matched_rule_id"], risk["policy_decision"]) == (rule, "approval_required")
    a = await h.approvals.get(_only_approval(h))
    assert a is not None
    assert (a.approver_id, a.backup_approver_id, a.conflict_type) == (approver, backup, conflict_type)
    [row] = [r for r in h.audit.of("t1", "queued") if r["step"] == "B15"]
    assert row["approver_id"] == approver and row["detail"]["choice_reason"] == reason
    assert h.approvals.notified == [(a.approval_id, approver)]


async def test_x13_graph_deny_rule_never_reaches_b15(monkeypatch: pytest.MonkeyPatch) -> None:
    """x13 / cổng 4 "deny không tạo phiếu" (1.3, G4-20): luật `deny` tiêm qua monkeypatch (khuôn `test_b12_assess:158`, KHÔNG thêm
    vào policy.json) → B12 E5, không vào B15: 0 phiếu, 0 thông báo, không dòng audit nào của step B15."""
    verdict = RuleVerdict(matched=True, decision="deny", rule_id="R12", all_matched=["R12", "R19", "R20"], description="Cấm")
    monkeypatch.setattr(b12_assess, "evaluate", lambda action, ctx: verdict)
    h, v = await _graph("nv003", "gia hạn VPN cho máy LAP-0501")
    assert (v["status"], v["exit_code"]) == (S_ESCALATED, "E5"), h.audit.events("t1")
    [risk] = h.audit.of("t1", "risk_decided")
    assert risk["policy_decision"] == "deny"
    assert not [e for e in h.audit.events("t1") if e[0] == "B15"]
    assert h.approvals.count("t1") == 0 and h.approvals.notified == []


# ---- b3: người duyệt chưa có dòng `users` --------------------------------------------------------------------------------


async def test_b3_approver_without_users_row_gets_row_and_chain_no_session() -> None:
    """b3 (Q-4-N, P5, M-4b-12): l1_01/l1_02 chưa từng đăng nhập (bảng `users` giả chỉ có người duyệt GIẢ) → B15 `ensure` TRƯỚC khi
    tạo phiếu (FK như Postgres) → phiếu tạo được; `users` có người duyệt + chuỗi quản lý (l1_lead, it_mgr01) + dự phòng; KHÔNG
    phiên mới, không sự kiện bảo mật."""
    env = Env()
    assert not set(ROSTER_ROWS) & set(env.store.users)
    sessions_before = dict(env.store.sessions)
    action, state = _x1()
    out = await env.run(state)
    await _assert_queued(env, out, action, approver="l1_01", backup="l1_02", conflict_type=None, reason="normal",
                         rejected=())  # fmt: skip
    users = env.store.users
    assert set(ROSTER_ROWS) <= set(users)
    got = {u: (users[u].role, users[u].manager_id) for u in ROSTER_ROWS}
    assert got == {"l1_01": ("l1", "l1_lead"), "l1_02": ("l1", "it_mgr01"), "l1_lead": ("l1", "it_mgr01"),
                   "it_mgr01": ("manager", None)}  # fmt: skip
    assert env.store.sessions == sessions_before == {}
    assert env.store.sink.events == []


# ---- b8: điểm log 5 ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requester", "device", "registered"),
    [pytest.param("nv003", "LAP-0501", True, id="x1-normal"), pytest.param("l1_01", "PC-0124", False, id="x2-conflict")],
)
async def test_b8_point5_columns_not_null_closed_values_no_free_text(requester: str, device: str, registered: bool) -> None:
    """b8 (P10, 5.6 #4 Q-4b-4, M-4b-14): cột `approver_id, deadline, conflict_detected, action_plan_hash` không NULL; cột
    `intended_action` là dict JSON của Action có `type` + `target`; `detail` ĐÚNG khoá P10 + `recovered`, mọi giá trị thuộc tập đóng /
    là user_id — không chữ tự do."""
    env = Env(requester)
    action = _action(requester, device, registered=registered)
    out = await env.run(_state(requester, action))
    assert out["status"] == S_PENDING_APPROVAL
    row = env.row("queued")
    for col in ("approver_id", "deadline", "conflict_detected", "action_plan_hash", "intended_action"):
        assert row.get(col) is not None, col
    assert isinstance(row["deadline"], datetime) and isinstance(row["conflict_detected"], bool)
    assert row["action_plan_hash"] == hash_action(action) and len(row["action_plan_hash"]) == 64
    intended = row["intended_action"]
    assert isinstance(intended, dict)
    assert (intended["type"], intended["target"]) == ("renew_vpn_cert", f"device:{device}")
    d = row["detail"]
    assert set(d) == POINT5_DETAIL
    assert d["choice_reason"] in CHOICE_REASONS
    assert d["conflict_type"] is None or d["conflict_type"] in CONFLICT_TYPES
    assert d["backup_approver_id"] is None or d["backup_approver_id"] in ROSTER_ROWS
    assert isinstance(d["sla_minutes"], int) and not isinstance(d["sla_minutes"], bool) and d["sla_minutes"] == env.sla
    assert d["recovered"] is False
    assert isinstance(d["rejected_candidates"], list)
    for item in d["rejected_candidates"]:
        assert set(item) == {"user_id", "reason"} and item["reason"] in REJECT_REASONS and item["user_id"] in ROSTER_ROWS


# ---- Q-4b-5: thiếu khoá HMAC → E2 trước `ensure` ---------------------------------------------------------------------------


async def test_q4b5_approver_users_unavailable_e2_before_ensure_and_ad() -> None:
    """Q-4b-5 (5.6 #5): `approver_users.available` False → E2 `approver_sync_unavailable` TRƯỚC `ensure`: 0 phiếu, 0 `ensure`, 0 lời
    gọi AD của B15 (không tra rồi mới bỏ)."""
    spy = SpyApproverUsers(available=False)
    env = Env(approver_users=spy)
    _, state = _x1()
    out = await env.run(state)
    _assert_refused(env, out, code="E2", reason_detail="approver_sync_unavailable", stage="sync_unavailable")
    assert spy.ensured == 0 and env.h.ad.calls == 0


async def test_q4b5_real_auth_approver_users_without_sync_unavailable() -> None:
    """Q-4b-5 với bản THẬT: `AuthApproverUsers(None)` (process thiếu `JWT_SIGNING_KEY`) → cùng E2, 0 phiếu, 0 dòng `users` mới."""
    env = Env(approver_users=AuthApproverUsers(None))
    users_before = set(env.store.users)
    _, state = _x1()
    out = await env.run(state)
    _assert_refused(env, out, code="E2", reason_detail="approver_sync_unavailable", stage="sync_unavailable")
    assert env.h.ad.calls == 0 and set(env.store.users) == users_before


# ---- Q-4b-6: sếp trung gian không ra role vẫn nằm trong chuỗi ---------------------------------------------------------------


async def test_q4b6_intermediate_boss_without_role_still_boss_of_approver() -> None:
    """Q-4b-6 (5.6 #6): `l1_lead` có IT-L1 + IT-Manager (hai nhóm đặc quyền → không ra role) — chuỗi của B15 lấy từ AD, KHÔNG lọc
    theo role: it_mgr01 gửi → l1_01 vẫn bị loại `boss_of_approver` (it_mgr01 ∈ l1_lead → it_mgr01), head = chính người gửi →
    E5 `no_valid_approver`, không giao cho l1_01."""
    env = Env("it_mgr01")
    env.h.ad.users["l1_lead"]["groups"] = ["IT-Users", "IT-L1", "IT-Manager"]
    action = _action("it_mgr01", "LAP-0900", registered=False)
    out = await env.run(_state("it_mgr01", action))
    _assert_refused(env, out, code="E5", reason_detail="no_valid_approver", stage="choose",
                    rejected=(("l1_01", "boss_of_approver"), ("it_mgr01", "self")))  # fmt: skip


# ---- AD không có roster / P2 -----------------------------------------------------------------------------------------------


async def test_roster_not_in_ad_e5_all_not_found() -> None:
    """`roster_in_ad=False` (harness KHÔNG gộp ROSTER_CHAIN): không ai trong roster có trong AD → 404 = không hợp lệ (`not_found`),
    KHÔNG phải lỗi → E5 `no_valid_approver`, rejected đủ 3 người theo thứ tự đánh giá (chứng minh harness không che lỗi)."""
    env = Env(roster_in_ad=False)
    _, state = _x1()
    out = await env.run(state)
    _assert_refused(env, out, code="E5", reason_detail="no_valid_approver", stage="choose",
                    rejected=(("l1_01", "not_found"), ("l1_02", "not_found"), ("it_mgr01", "not_found")))  # fmt: skip


async def test_p2_primary_deleted_from_ad_is_not_found_not_e2() -> None:
    """P2: l1_01 bị xoá khỏi AD (404) → rejected `not_found`, đi tiếp người dự phòng; không E2."""
    env = Env()
    del env.h.ad.users["l1_01"]
    action, state = _x1()
    out = await env.run(state)
    await _assert_queued(env, out, action, approver="l1_02", backup="it_mgr01", conflict_type=None, reason="normal",
                         rejected=(("l1_01", "not_found"),))  # fmt: skip
    assert env.h.audit.of("t1", "approver_lookup_error") == []


async def test_p2_primary_probation_is_inactive() -> None:
    """P2: người duyệt `probation` không duyệt được → rejected `inactive` → l1_02."""
    env = Env()
    env.h.ad.set_status("l1_01", "probation")
    action, state = _x1()
    out = await env.run(state)
    await _assert_queued(env, out, action, approver="l1_02", backup="it_mgr01", conflict_type=None, reason="normal",
                         rejected=(("l1_01", "inactive"),))  # fmt: skip


# ---- P3: cache một lần chạy + bước B15_APPROVER; hạn lượt ------------------------------------------------------------------


async def test_p3_each_person_looked_up_once_per_run_including_chain_and_ensure() -> None:
    """P3 + 5.6 #8 (TQ-3): trong MỘT lần chạy, mỗi người (kể cả chuỗi quản lý mà `ensure` cần) tra AD đúng 1 lần — l1_01, l1_02,
    l1_lead, it_mgr01 đều phải được tra (dòng `users` của họ lấy từ AD)."""
    env = Env()
    _, state = _x1()
    out = await env.run(state)
    assert out["status"] == S_PENDING_APPROVAL
    assert set(ROSTER_ROWS) <= set(env.h.ad.calls_by)
    assert all(n == 1 for n in env.h.ad.calls_by.values()), env.h.ad.calls_by


async def test_p3_all_b15_ad_calls_use_step_b15_approver() -> None:
    """P3: mọi lời tra AD của B15 đi qua registry `ad_get_user` với `caller_step="B15_APPROVER"` (kể cả lời tra chuỗi trong `ensure`)."""
    env = Env(spy_directory=True)
    _, state = _x1()
    out = await env.run(state)
    assert out["status"] == S_PENDING_APPROVAL
    assert env.spy is not None and len(env.spy.calls) >= len(ROSTER_ROWS)
    assert set(env.spy.calls) == {("ad_get_user", "B15_APPROVER")}


async def test_turn_budget_exhausted_at_approver_lookup_e2() -> None:
    """Hạn cả lượt (phase3 9.0): hết hạn khi B15 tra AD → E2 `turn_budget_exceeded` (stage `turn_budget`), 0 phiếu, không gửi lời
    gọi AD nào."""
    env = Env()
    _, state = _x1()
    out = await env.run(state, usable_s=0.0)
    _assert_refused(env, out, code="E2", reason_detail="turn_budget_exceeded", stage="turn_budget")
    assert env.h.ad.calls == 0


# ---- TQ-7: nhánh peek suy choice_reason từ phiếu cũ --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("approver", "backup", "conflict_type", "reason"),
    [
        pytest.param("l1_01", "l1_02", None, "normal", id="normal"),
        pytest.param("it_mgr01", None, "self", "conflict", id="conflict"),
        pytest.param("it_mgr01", None, None, "no_valid_l1", id="no_valid_l1-approver-la-head"),
    ],
)
async def test_tq7_peek_branch_point5_derived_from_old_approval(
    approver: str, backup: str | None, conflict_type: str | None, reason: str
) -> None:
    """TQ-7 (5.6 #8): phiếu cũ đã có ở khoá `approval_create` của lượt → nhánh `peek`: KHÔNG chọn người / tra AD / ensure; điểm log 5
    lấy từ PHIẾU (người duyệt, hạn, xung đột); `choice_reason` suy tất định (`conflict_detected` → conflict; `approver_id == head` →
    no_valid_l1; còn lại normal); `recovered=True`, `rejected_candidates=None`. AD tắt hẳn → phải 0 lời gọi."""
    env = Env()
    env.h.ad.down = True
    action, state = _x1()
    deadline = NOW + timedelta(minutes=7)  # khác now + SLA: cột `deadline` phải là hạn của phiếu cũ
    aid = await env.old_approval(state, approver=approver, backup=backup, conflict_type=conflict_type, deadline=deadline)
    out = await env.run(state)
    assert (out["status"], out["next"], out["approval_id"]) == (S_PENDING_APPROVAL, "approval_wait", aid)
    assert out["action_plan_hash"] == hash_action(action)
    row = env.row("queued")
    assert (row["approver_id"], row["deadline"], row["conflict_detected"]) == (approver, deadline, conflict_type is not None)
    assert row["action_plan_hash"] == hash_action(action)
    assert row["detail"] == {
        "backup_approver_id": backup, "conflict_type": conflict_type, "choice_reason": reason,
        "rejected_candidates": None, "sla_minutes": env.sla, "recovered": True,
    }  # fmt: skip
    assert env.h.approvals.count("t1") == 1 and env.h.approvals.notified == [(aid, approver)]
    assert env.h.ad.calls == 0


# ---- 4.10 #11: mang khoá trượt username ma khi B15 tạo dòng ---------------------------------------------------------------


async def test_4_10_11_ghost_lock_carried_to_approver_row_created_by_b15() -> None:
    """4.10 #11 (Q-4a-6 sau khi tách `user_sync`): `ha.lt` (l1_01) chưa có dòng `users`, sai mật khẩu ĐỦ ngưỡng trong cửa sổ — lưu
    dạng username MA (HMAC khoá harness) qua sink của `h.auth_store` → B15 `ensure` tạo dòng l1_01 → `locked_until` = lần sai cuối +
    thời gian khoá (policy/Settings mặc định, như harness dựng `AdUserSync`)."""
    env = Env()
    lock = lock_policy(auth_config(Settings(_env_file=None), get_policy().constants))  # type: ignore[call-arg]
    ghost = stored_username("ha.lt", known=False, key=HARNESS_USERNAME_KEY)
    for i in range(lock.max_failures):
        if i:
            env.clock.advance(timedelta(minutes=1))
        await env.store.sink.record("login_failed", username_attempted=ghost)
    last = env.clock.now()
    env.clock.advance(timedelta(minutes=1))
    assert "l1_01" not in env.store.users
    _, state = _x1()
    out = await env.run(state)
    assert out["status"] == S_PENDING_APPROVAL
    me = await env.store.get_user("l1_01")
    assert me is not None and me.locked_until == last + lock.lockout
    other = await env.store.get_user("l1_02")
    assert other is not None and other.locked_until is None  # đối chứng: không có lần sai nào


# ---- Q-4b-8 = A: `ensure` ngoài `effects.once` — `role_changed` tự hết điều kiện sau lần đầu ------------------------------------
# Agent chính viết (chốt Q-4b-8, sau soát S14) — không phải test-writer.


async def test_q4b8_ensure_role_changed_once_then_no_repeat() -> None:
    """Q-4b-8 = A (ngoại lệ B8/5.5): `l1_01` có dòng `users` role CŨ `employee` (khác AD: IT-L1 → `l1`), `token_version=3`, một phiên
    đang sống. Ticket t1 → B15 `ensure` (AdUserSync dùng chung với đăng nhập): đúng 1 `role_changed` employee → l1, `token_version`
    3 → 4, phiên bị thu hồi. Ticket t2 (lượt khác — KHÔNG phải nhánh `peek`, `ensure` chạy lại thật, cùng AD): 0 `role_changed`
    mới, `token_version` giữ 4. Người khác trong roster (dòng mới) không phát `role_changed`."""
    env = Env()
    env.store.users["l1_01"] = UserRecord(
        user_id="l1_01", username="ha.lt", full_name=None, role="employee", department="it", manager_id=None,
        employment_status="active", hired_at=None, is_privileged_account=False, token_version=3,
    )  # fmt: skip
    env.store.sessions["s-l1"] = SessionRecord(
        session_id="s-l1", user_id="l1_01", token_family_id=uuid4(), refresh_token_hash="h-l1", created_at=NOW,
        expires_at=NOW + timedelta(hours=8),
    )  # fmt: skip
    action, state = _x1()
    out = await env.run(state)
    assert out["status"] == S_PENDING_APPROVAL
    changed = env.store.sink.of("role_changed")
    assert [(e.user_id, e.detail) for e in changed] == [("l1_01", {"from": "employee", "to": "l1"})]
    me = env.store.users["l1_01"]
    assert (me.role, me.token_version) == ("l1", 4)
    session = env.store.sessions["s-l1"]
    assert session.revoked_at is not None and session.revoke_reason == "admin"

    out2 = await env.run(_state("nv003", action, ticket_id="t2", turn_id="T2"))
    assert out2["status"] == S_PENDING_APPROVAL
    assert env.h.approvals.count("t2") == 1  # lượt 2 tạo phiếu mới → `ensure` đã chạy lại thật (không phải `peek`)
    assert len(env.store.sink.of("role_changed")) == 1
    assert env.store.users["l1_01"].token_version == 4


# ---- AST: P11 hằng reason_detail; P1 5.3 side effect chỉ qua effects.once -----------------------------------------------


def _b15_tree() -> ast.Module:
    return ast.parse(NODE_FILE.read_text(encoding="utf-8"), str(NODE_FILE))


async def test_p11_ast_reason_details_are_constant_strings() -> None:
    """P11: trong `graph/nodes/b15_prepare_approval.py` mọi `escalation_reason_detail=` là chuỗi HẰNG (literal hoặc hằng module)
    thuộc `REASON_DETAILS`; đủ 5 giá trị của B15 (không quét rỗng)."""
    tree = _b15_tree()
    consts = {
        n.targets[0].id: n.value.value for n in tree.body
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
        and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
    }  # fmt: skip
    found: list[str] = []
    for node in ast.walk(tree):
        for kw in node.keywords if isinstance(node, ast.Call) else []:
            if kw.arg != "escalation_reason_detail":
                continue
            v = kw.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                found.append(v.value)
            elif isinstance(v, ast.Name) and v.id in consts:
                found.append(consts[v.id])
            else:
                found.append(f"<khong-phai-hang:{ast.unparse(v)}>")
    assert [v for v in found if v not in REASON_DETAILS] == []
    assert B15_REASONS <= set(found), sorted(set(found))


async def test_p1_ast_approvals_side_effects_only_as_effects_once_fn() -> None:
    """P1 5.3 (test AST `SIDE_EFFECT_FUNCS`): `approvals.create` / `approvals.notify_approver` chỉ xuất hiện ở vị trí `fn` của
    `effects.once(state, kind, fn, …)` với kind `approval_create` / `notify_approver` (không quét rỗng)."""
    src = NODE_FILE.read_text(encoding="utf-8")
    assert find_violations(src, NODE_FILE.name) == []
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and ast.unparse(node.func).endswith("once") and len(node.args) >= 3
                and isinstance(node.args[1], ast.Constant)):  # fmt: skip
            fn = ast.unparse(node.args[2])  # vd `deps.approvals.create` → `approvals.create`
            pairs.add((str(node.args[1].value), ".".join(fn.split(".")[-2:])))
    assert ("approval_create", "approvals.create") in pairs, pairs
    assert ("notify_approver", "approvals.notify_approver") in pairs, pairs
