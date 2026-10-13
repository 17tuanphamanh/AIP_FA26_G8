"""B17 so `hash_action(action)` với hash của PHIẾU (`approvals.action_plan_hash`) — Phase 4 chặng 4d P7 (Việc treo 29, phase4 mục 6.5
#10, 7.1 P7). Viết TỪ ĐẶC TẢ trước thân code: PLAN-4d mục 2.1 "B17 (P7)", mục 3 h1–h3, TQ-9, TQ-10.

Khuôn `test_b17_execute.Env` / `test_b17_decided_by.Env`: node B17 THẬT, `PlanExecutor` thật trên hệ thống ghi VPN giả (đếm ở nơi
nhận), AD giả sau registry đọc thật; harness gộp roster (l1_01…) vào AD và gieo dòng `users` của người duyệt (FK phiếu). Phiếu tạo
bằng `h.approvals.create(..., hash_action(action), ...)` rồi `close(approved, decided_by=l1_01)`; đổi hash PHIẾU bằng
`h.approvals._table[aid]["action_plan_hash"]` (bản giả của `UPDATE approvals SET action_plan_hash = …`).

- h1: phiếu `approved`, state khớp hash, hash phiếu ≠ `hash_action(action)` → E5 `action_plan_changed_since_approval` (event cùng tên,
  bước B17), `detail.hash_source = "approval"`, `detail.action_plan_hash_matched = False`, `detail.write_calls = 0`; 0 lời gọi ghi,
  0 dòng `begun`. Lớp 2 đặt NGAY sau `approvals.get` (TQ-9) → chưa tra AD.
- h2 (đối chứng): hash phiếu khớp → thực thi như cũ, `action_plan_hash_matched = True`.
- h3: lệch hash STATE (lớp 1) → nhánh cũ, detail KHÔNG có khoá `hash_source` (test cũ ghim detail lớp 1).
"""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_EXECUTING
from app.domain.ticket_state import ExecutionResult
from app.executor.plan_executor import PlanExecutor
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b17_execute
from app.settings import get_action_metadata, get_policy
from tests.fakes.executor import FakeVpnWrites, MemoryTxLog
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import FakeAd, ad_user

pytestmark = pytest.mark.asyncio

IN_HOURS = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN — R20 allow
AFTER_HOURS = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)  # thứ Ba 20:00 giờ VN — R18 approval_required
APPROVER = "l1_01"
CHANGED = "action_plan_changed_since_approval"
OTHER_HASH = hashlib.sha256(b"ke hoach khac sau khi duyet").hexdigest()


def _requester() -> RequesterContext:
    return RequesterContext(
        user_id="nv001", role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=IN_HOURS,
    )  # fmt: skip


def _action(device: str = "LAP-0342") -> Action:
    meta = get_action_metadata().root["vpn"]["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target=f"device:{device}", requested_for="nv001", scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params={"device_id": device},
        facts={"device_registered": True, "device_owner_is_requester": True, "cert_status": "expired",
               "cert_days_to_expiry": -3, "last_connection_ok": False},
    )  # fmt: skip


def _state(action: Action, a_id: str, *, state_hash: str | None) -> dict[str, Any]:
    return {
        "ticket_id": "t1", "turn_id": "T1", "status": S_EXECUTING, "intent": "vpn", "reasoning_loops": 1,
        "requester_context": _requester(), "intended_action": action, "ctx_flags": {"target_is_other": False},
        "redacted_request": "gia hạn VPN cho máy LAP-0342", "slots": {"device_id": "LAP-0342", "action": "renew_vpn_cert"},
        "approval_id": a_id, "approval_result": "approved", "action_plan_hash": state_hash,
    }  # fmt: skip


class Env:
    def __init__(self, at: datetime) -> None:
        self.clock = FakeClock(at)
        self.ad = FakeAd(ad_user("nv001"))
        self.writes, self.txlog = FakeVpnWrites(self.clock), MemoryTxLog()
        self.h = GraphHarness(clock=self.clock, ad=self.ad, txlog=self.txlog, approver_id=APPROVER)
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

    async def approved(self, action: Action) -> str:
        """Phiếu `approved` trong BẢNG, hash phiếu = `hash_action(action)` lúc tạo (như B15)."""
        a_id = await self.h.approvals.create(
            "t1", APPROVER, self.clock.now() + timedelta(minutes=30), hash_action(action),
            backup_approver_id=None, conflict_detected=False, conflict_type=None,
        )  # fmt: skip
        await self.h.approvals.close(a_id, "approved", self.clock.now(), decided_by=APPROVER, note="ok")
        return a_id

    def writes_total(self) -> int:
        return sum(self.writes.calls.values())

    def rows(self, event: str) -> list[dict[str, Any]]:
        return self.h.audit.of("t1", event)


def _exit(out: dict[str, Any]) -> tuple[Any, Any, Any]:
    return out.get("status"), out.get("exit_code"), out.get("escalation_reason_detail")


# ---- h1: hash phiếu bị đổi --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("at", [AFTER_HOURS, IN_HOURS], ids=["20h-R18", "10h-R20"])
async def test_h1_approval_hash_changed_is_e5_hash_source_approval_zero_writes(at: datetime) -> None:
    """h1 (P7, M-4d-10): state khớp hash (lớp 1 qua) nhưng hash PHIẾU khác `hash_action(action)` → E5
    `action_plan_changed_since_approval`; detail `hash_source="approval"`, `action_plan_hash_matched=False`, `write_calls=0`;
    0 lời gọi ghi, 0 `begun`; chưa tra AD (lớp 2 ngay sau `approvals.get` — TQ-9)."""
    env = Env(at)
    action = _action()
    a_id = await env.approved(action)
    env.h.approvals._table[a_id]["action_plan_hash"] = OTHER_HASH
    out = await env.node(_state(action, a_id, state_hash=hash_action(action)))
    got = _exit(out)
    assert got == (S_ESCALATED, "E5", CHANGED), (got, env.h.audit.events("t1"))
    [row] = env.rows(CHANGED)
    assert row["step"] == "B17"
    detail = dict(row["detail"])
    assert detail["hash_source"] == "approval"
    assert detail["action_plan_hash_matched"] is False
    assert detail["write_calls"] == 0
    assert env.writes_total() == 0 and env.txlog.rows == []
    assert env.ad.calls == 0
    assert env.rows("executed_ok") == []


async def test_h1_approval_hash_empty_is_e5() -> None:
    """Biến thể h1: hash phiếu rỗng (bản ghi hỏng) cũng là lệch → E5, 0 ghi."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approved(action)
    env.h.approvals._table[a_id]["action_plan_hash"] = ""
    out = await env.node(_state(action, a_id, state_hash=hash_action(action)))
    assert _exit(out) == (S_ESCALATED, "E5", CHANGED)
    assert env.writes_total() == 0 and env.txlog.rows == []


async def test_h1_approval_hash_of_other_action_is_e5() -> None:
    """Biến thể h1 (đúng kịch bản G4-13): phiếu được duyệt cho hành động A (máy LAP-0342), state + hành động đang chạy là B (máy
    LAP-0999) với hash state = hash(B) → lớp 1 qua, lớp 2 bắt: E5, 0 ghi."""
    env = Env(AFTER_HOURS)
    approved_action, running = _action("LAP-0342"), _action("LAP-0999")
    a_id = await env.approved(approved_action)
    out = await env.node(_state(running, a_id, state_hash=hash_action(running)))
    assert _exit(out) == (S_ESCALATED, "E5", CHANGED)
    [row] = env.rows(CHANGED)
    assert row["detail"]["hash_source"] == "approval"
    assert env.writes_total() == 0 and env.txlog.rows == []


# ---- h2: hash phiếu khớp (đối chứng) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("at", [AFTER_HOURS, IN_HOURS], ids=["20h-R18", "10h-R20"])
async def test_h2_approval_hash_matches_executes_as_before(at: datetime) -> None:
    """h2: hash phiếu = hash state = `hash_action(action)` → thực thi đúng 1 lần như cũ, `action_plan_hash_matched=True`."""
    env = Env(at)
    action = _action()
    a_id = await env.approved(action)
    out = await env.node(_state(action, a_id, state_hash=hash_action(action)))
    assert out["status"] == S_CONFIRMING, env.h.audit.events("t1")
    assert env.writes.calls == {"renew_vpn_cert": 1}
    assert ExecutionResult.model_validate(out["execution"]).action_plan_hash_matched is True
    assert env.rows(CHANGED) == []


# ---- h3: lệch hash STATE → nhánh lớp 1 giữ nguyên ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state_hash", "approval_hash"),
    [("0" * 64, None), (None, None), ("0" * 64, OTHER_HASH)],
    ids=["state-lech", "state-thieu", "ca-hai-lech"],
)
async def test_h3_state_hash_mismatch_old_branch_without_hash_source(state_hash: str | None, approval_hash: str | None) -> None:
    """h3 (TQ-9): hash STATE lệch/thiếu (kể cả khi hash phiếu cũng lệch) → nhánh lớp 1 như trước: E5
    `action_plan_changed_since_approval`, detail KHÔNG có `hash_source`; 0 lời gọi ghi."""
    env = Env(AFTER_HOURS)
    action = _action()
    a_id = await env.approved(action)
    if approval_hash is not None:
        env.h.approvals._table[a_id]["action_plan_hash"] = approval_hash
    out = await env.node(_state(action, a_id, state_hash=state_hash))
    assert _exit(out) == (S_ESCALATED, "E5", CHANGED)
    [row] = env.rows(CHANGED)
    assert "hash_source" not in row["detail"]
    assert env.writes_total() == 0 and env.txlog.rows == []
