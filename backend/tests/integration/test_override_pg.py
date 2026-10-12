"""SQL của ghi đè (TC23) trên Postgres 16 thật — Phase 4 chặng 4d DỪNG 1. Viết TỪ ĐẶC TẢ trước thân code: phase4 mục 7.1 P3, P4;
PLAN-4d mục 2.1 (port `ApprovalRepo.decision_trail/record_override`, `AuditWriter.record_new`), mục 3 (o8, dòng "PG"), Q-4d-2 = A,
TQ-3, TQ-4.

- `SqlApprovals.decision_trail(ticket_id)`: dòng `step='B13/B14' AND event='risk_decided'` MỚI NHẤT theo `log_id` (không theo
  `created_at`) → `detail->>'route'` + cột `policy_decision`; có `B10 deflected_info_only`; thiếu `detail.route` → None; dòng của
  ticket khác / bước khác không lẫn vào.
- `SqlApprovals.record_override(rec)`: đúng 1 dòng `step='OVERRIDE'` đủ cột của hợp đồng; lần 2 cùng người → False, vẫn 1 dòng
  (khoá chỉ theo ticket + người — M-4d-5); người khác → dòng thứ 2; dòng `tickets` trước = sau, so CẢ dòng (M-4d-1).
- `AuditWriter.record_new(row)` (o8 PG): True rồi False (một dòng); thiếu `idempotency_key` → `ValueError`, không ghi.

Database riêng cho module (`fresh_database`); ticket id ngẫu nhiên mỗi test. Dòng audit cho `decision_trail` INSERT tay (khuôn
`test_approvals_view_pg._audit`).
"""

import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.approval.store import SqlApprovals
from app.audit.writer import AuditWriter
from app.db.tickets import NewTicket, SqlTicketStore
from app.domain.override import DecisionTrail, OverrideRecord
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import APPROVER, REQUESTER, SESSION, scalar, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
OTHER = "l1-khac"


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)  # REQUESTER (nv-graph, employee) + phiên, APPROVER (l1-fake, l1)
    async with engine.begin() as conn:
        await conn.execute(text(f"INSERT INTO users (user_id, username, role) VALUES ('{OTHER}', 'graph.l1khac', 'l1') "
                                "ON CONFLICT DO NOTHING"))  # fmt: skip
    yield engine
    await engine.dispose()


def _key(ticket_id: str, overrider_id: str) -> str:
    return hashlib.sha256(("override:" + ticket_id + ":" + overrider_id).encode()).hexdigest()


async def _ticket(rw: AsyncEngine, *, final: bool = True) -> str:
    """Ticket thật qua `SqlTicketStore.create` (khuôn `test_approvals_view_pg`); `final` → đặt kết quả cuối như B20 đã đóng."""
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=T0),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    if final:
        await _exec(rw, "UPDATE tickets SET final_state = 'S_RESOLVED', close_reason = 'resolved_user_confirmed', "
                        "closed_at = :c, total_turns = 2, total_duration_seconds = 300 WHERE ticket_id = :t",
                    c=T0 + timedelta(minutes=5), t=ticket)  # fmt: skip
    return ticket


async def _exec(rw: AsyncEngine, sql: str, **params: Any) -> None:
    async with rw.begin() as conn:
        await conn.execute(text(sql), params)


async def _audit(
    rw: AsyncEngine, ticket: str, step: str, event: str, *, detail: dict[str, Any] | None = None,
    policy_decision: str | None = None, created_at: datetime = T0,
) -> int:  # fmt: skip
    async with rw.begin() as conn:
        log_id: Any = (await conn.execute(text(
            "INSERT INTO audit_logs (ticket_id, step, event, loop_seq, policy_decision, created_at, detail) "
            "VALUES (:t, :s, :e, 0, :p, :c, CAST(:d AS jsonb)) RETURNING log_id"
        ), {"t": ticket, "s": step, "e": event, "p": policy_decision, "c": created_at,
            "d": json.dumps(detail or {})})).scalar_one()  # fmt: skip
    return int(log_id)


async def _ticket_row(rw: AsyncEngine, ticket: str) -> dict[str, Any]:
    async with rw.connect() as conn:
        row = (await conn.execute(text("SELECT * FROM tickets WHERE ticket_id = :t"), {"t": ticket})).mappings().one()
    return dict(row)


async def _override_rows(rw: AsyncEngine, ticket: str) -> list[dict[str, Any]]:
    async with rw.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT log_id, ticket_id, created_at, turn_id, loop_seq, step, event, from_status, to_status, original_decision, "
            "override_decision, overrider_id, note, detail, idempotency_key FROM audit_logs "
            "WHERE ticket_id = :t AND step = 'OVERRIDE' ORDER BY log_id"
        ), {"t": ticket})).mappings().all()  # fmt: skip
    return [dict(r) for r in rows]


def _rec(ticket: str, overrider: str = APPROVER, **over: Any) -> OverrideRecord:
    base: dict[str, Any] = {
        "ticket_id": ticket, "overrider_id": overrider, "original_decision": "HITL", "override_decision": "L2",
        "reason_code": "policy_gap", "note": "đã che [BÍ_MẬT_ĐÃ_ẨN]", "created_at": T0 + timedelta(minutes=10),
    }  # fmt: skip
    base.update(over)
    return OverrideRecord(**base)


# ---- decision_trail (P3, TQ-3) --------------------------------------------------------------------------------------------------


async def test_pg_decision_trail_latest_risk_decided_by_log_id(rw: AsyncEngine) -> None:
    """Hai `risk_decided` — dòng ghi SAU (log_id lớn hơn) có `created_at` SỚM hơn → vẫn là "mới nhất" (theo log_id). Dòng mồi ghi
    sau cùng: cùng event nhưng bước khác, và `risk_decided` của ticket KHÁC → không lẫn vào."""
    ticket, other = await _ticket(rw), await _ticket(rw)
    await _audit(rw, ticket, "B13/B14", "risk_decided", detail={"route": "AUTO"}, policy_decision="allow",
                 created_at=T0 + timedelta(minutes=5))  # fmt: skip
    await _audit(rw, ticket, "B13/B14", "risk_decided", detail={"route": "HITL"}, policy_decision="approval_required",
                 created_at=T0)  # fmt: skip
    await _audit(rw, ticket, "B12", "risk_decided", detail={"route": "AUTO"}, policy_decision="allow")
    await _audit(rw, other, "B13/B14", "risk_decided", detail={"route": "ESCALATE_L2"}, policy_decision="deny")
    trail = await SqlApprovals(rw).decision_trail(ticket)
    assert trail == DecisionTrail(risk_route="HITL", risk_policy_decision="approval_required", has_risk_decided=True,
                                  deflected=False)  # fmt: skip


async def test_pg_decision_trail_only_b10_deflected(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    await _audit(rw, ticket, "B3", "intent_classified", detail={"layer": "model"})
    await _audit(rw, ticket, "B10", "deflected_info_only", detail={})
    assert await SqlApprovals(rw).decision_trail(ticket) == DecisionTrail(None, None, False, True)


async def test_pg_decision_trail_risk_and_b10(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    await _audit(rw, ticket, "B13/B14", "risk_decided", detail={"route": "AUTO"}, policy_decision="allow")
    await _audit(rw, ticket, "B10", "deflected_info_only")
    assert await SqlApprovals(rw).decision_trail(ticket) == DecisionTrail("AUTO", "allow", True, True)


async def test_pg_decision_trail_without_detail_route(rw: AsyncEngine) -> None:
    """Node giả B12 (A9): `risk_decided` không có `detail.route` → `risk_route` None, cột `policy_decision` vẫn đọc."""
    ticket = await _ticket(rw)
    await _audit(rw, ticket, "B13/B14", "risk_decided", detail={"matched_rule_id": "R12"}, policy_decision="deny")
    assert await SqlApprovals(rw).decision_trail(ticket) == DecisionTrail(None, "deny", True, False)


async def test_pg_decision_trail_nothing(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    await _audit(rw, ticket, "B3", "intent_classified")
    assert await SqlApprovals(rw).decision_trail(ticket) == DecisionTrail(None, None, False, False)


# ---- record_override (P4, S1, S5) -----------------------------------------------------------------------------------------------


async def test_pg_record_override_one_row_idempotent_per_person_tickets_unchanged(rw: AsyncEngine) -> None:
    """P4 + M-4d-1 + M-4d-5: lần 1 → True, đúng 1 dòng đủ cột (from/to NULL, `turn_id` NULL, `detail={reason_code}`, khoá =
    sha256 công thức); lần 2 CÙNG người (giờ khác, quyết định khác) → False, vẫn 1 dòng, dòng cũ giữ nguyên; người khác → True, 2
    dòng. Dòng `tickets` trước = sau (cả dòng)."""
    ticket = await _ticket(rw)
    before = await _ticket_row(rw, ticket)
    store = SqlApprovals(rw)
    first = _rec(ticket)
    assert await store.record_override(first) is True
    [row] = await _override_rows(rw, ticket)
    assert {k: row[k] for k in row if k != "log_id"} == {
        "ticket_id": ticket, "created_at": first.created_at, "turn_id": None, "loop_seq": 0, "step": "OVERRIDE",
        "event": "override_recorded", "from_status": None, "to_status": None, "original_decision": "HITL",
        "override_decision": "L2", "overrider_id": APPROVER, "note": "đã che [BÍ_MẬT_ĐÃ_ẨN]",
        "detail": {"reason_code": "policy_gap"}, "idempotency_key": _key(ticket, APPROVER),
    }  # fmt: skip

    again = _rec(ticket, override_decision="AUTO", reason_code="other", note="đổi ý", created_at=T0 + timedelta(minutes=20))
    assert await store.record_override(again) is False
    assert await _override_rows(rw, ticket) == [row]

    second = _rec(ticket, OTHER, note=None, reason_code="too_risky_for_auto")
    assert await store.record_override(second) is True
    rows = await _override_rows(rw, ticket)
    assert [(r["overrider_id"], r["idempotency_key"], r["note"]) for r in rows] == [
        (APPROVER, _key(ticket, APPROVER), "đã che [BÍ_MẬT_ĐÃ_ẨN]"), (OTHER, _key(ticket, OTHER), None)]  # fmt: skip
    assert await _ticket_row(rw, ticket) == before


async def test_pg_record_override_does_not_touch_other_tables(rw: AsyncEngine) -> None:
    """S1: ghi đè không tạo lượt, không side effect, không phiếu, không escalation; chỉ đúng một dòng audit mới."""
    ticket = await _ticket(rw)
    counts = (
        "SELECT (SELECT count(*) FROM turns WHERE ticket_id = :t), (SELECT count(*) FROM side_effects WHERE ticket_id = :t), "
        "(SELECT count(*) FROM approvals WHERE ticket_id = :t), (SELECT count(*) FROM escalations WHERE ticket_id = :t), "
        "(SELECT count(*) FROM audit_logs WHERE ticket_id = :t)"
    )
    async with rw.connect() as conn:
        before = tuple((await conn.execute(text(counts), {"t": ticket})).one())
    assert await SqlApprovals(rw).record_override(_rec(ticket)) is True
    async with rw.connect() as conn:
        after = tuple((await conn.execute(text(counts), {"t": ticket})).one())
    assert after == (*before[:4], before[4] + 1)


# ---- AuditWriter.record_new (o8 PG) --------------------------------------------------------------------------------------------


def _row(ticket: str, key: str | None, **over: Any) -> dict[str, Any]:
    """Dòng 12 khoá của hợp đồng 2.1 — dựng tay (không qua `audit_row`) để o8 chỉ kiểm writer."""
    row: dict[str, Any] = {
        "ticket_id": ticket, "created_at": T0, "step": "OVERRIDE", "event": "override_recorded", "from_status": None,
        "to_status": None, "original_decision": "HITL", "override_decision": "L2", "overrider_id": APPROVER, "note": None,
        "detail": {"reason_code": "policy_gap"}, "idempotency_key": key,
    }  # fmt: skip
    row.update(over)
    if key is None:
        del row["idempotency_key"]
    return row


async def test_o8_pg_record_new_true_then_false_one_row(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    key = _key(ticket, APPROVER)
    writer = AuditWriter(rw)
    assert await writer.record_new(_row(ticket, key)) is True
    assert await writer.record_new(_row(ticket, key, override_decision="AUTO", created_at=T0 + timedelta(minutes=1))) is False
    rows = await _override_rows(rw, ticket)
    assert [(r["idempotency_key"], r["override_decision"]) for r in rows] == [(key, "L2")]


async def test_o8_pg_record_new_without_key_value_error_nothing_written(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    with pytest.raises(ValueError):
        await AuditWriter(rw).record_new(_row(ticket, None))
    assert await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t", t=ticket) == 0
