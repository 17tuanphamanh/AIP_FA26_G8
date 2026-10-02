"""Tiện ích e2e cổng 4 (Phase 4 chặng 4d, `test_gate4_hitl.py`) — CHỈ ghép trên `gate3_env` (không sửa nó): cùng `gate3`/`api`/
`calls`/`scalar`/`rows`, thêm các bước HITL dùng chung.

Ca HITL chuẩn (PLAN-4d 2.1 "e2e"): nv003 = `chau.hm` (probation) "gia hạn VPN cho máy LAP-0501" → R19 (mọi giờ) → phiếu giao `l1_01`
(`ha.lt`), dự phòng `l1_02` (`duc.pv`). Ghi đè bởi `duc.pv`. Đếm lời gọi GHI ở NƠI NHẬN (`/_admin/calls` của mock): mọi POST trừ
đăng nhập AD (`/ad/authenticate`) và lệnh điều khiển mock (`/_admin`).
"""

import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx
from app.audit.check import Report, SecretScanner, readonly_engine, run
from app.domain.states import S_CONFIRMING, S_PENDING_APPROVAL, S_REJECTED, S_RESOLVED
from app.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.e2e.gate3_env import Api, calls, rows, scalar
from tests.e2e.mock_server import MockServer
from tests.integration.pg import PgUrls

CHAU = "chau.hm"  # nv003 — probation → R19
APPROVER = "ha.lt"  # l1_01 — người duyệt chính của roster vpn
BACKUP = "duc.pv"  # l1_02 — dự phòng; người ghi đè chuẩn
HITL_TEXT = "gia hạn VPN cho máy LAP-0501"
OTHER_DEVICE_TEXT = "gia hạn VPN cho máy LAP-0417"  # máy của nv002 — không phải của người gửi
OVERRIDE_ROUTE = "/api/tickets/{ticket_id}/override"
CONFIG_DIR = Settings(_env_file=None).config_dir  # type: ignore[call-arg]
CONTROL_USER = "gate4-ctl"  # người gửi của ticket đối chứng cài bằng SQL (không qua API)
B3_FULL = {"layer": "model", "dropped_slot_keys": [], "intent": "vpn", "confidence": 0.92}


async def writes(mock: MockServer) -> int:
    """Lời gọi GHI mock đã nhận: mọi POST trừ `/ad/authenticate` (đăng nhập) và `/_admin` (điều khiển test)."""
    total = await calls(mock, "/", "POST")
    return total - await calls(mock, "/ad/authenticate", "POST") - await calls(mock, "/_admin", "POST")


async def execute(rw: AsyncEngine, sql: str, **params: Any) -> int:
    """Câu ghi trong MỘT transaction (commit) → số dòng bị ảnh hưởng."""
    async with rw.begin() as conn:
        return int((await conn.execute(text(sql), params)).rowcount)


async def approval_id(rw: AsyncEngine, ticket: str) -> str:
    return str(await scalar(rw, "SELECT approval_id FROM approvals WHERE ticket_id = :t", t=ticket))


async def pending_hitl(a: Api, text_: str = HITL_TEXT) -> tuple[str, str]:
    """Ca HITL chuẩn tới `S_PENDING_APPROVAL`: (ticket, approval_id). Phiếu giao l1_01, dự phòng l1_02, không xung đột."""
    ticket = await a.create(CHAU, text_)
    view = await a.view(ticket, CHAU)
    assert view["status"] == S_PENDING_APPROVAL, view
    assert await rows(a.parts.rw, "SELECT approver_id, backup_approver_id, conflict_detected, status FROM approvals "
                                  "WHERE ticket_id = :t", t=ticket) == [("l1_01", "l1_02", False, "pending")]  # fmt: skip
    return ticket, await approval_id(a.parts.rw, ticket)


async def decide(a: Api, aid: str, username: str, **body: Any) -> httpx.Response:
    return await a.post(f"/api/approvals/{aid}/decision", body or {"decision": "approved"}, username)


async def override(a: Api, ticket: str, username: str, **body: Any) -> httpx.Response:
    return await a.post(f"/api/tickets/{ticket}/override", body, username)


async def resolved_hitl(a: Api, mock: MockServer) -> str:
    """i1 (TC07-vpn): chờ duyệt → ha.lt duyệt (202) → gia hạn đúng 1 lời gọi ghi → `S_CONFIRMING` → chau.hm xác nhận → `S_RESOLVED`."""
    ticket, aid = await pending_hitl(a)
    before = await writes(mock)
    r = await decide(a, aid, APPROVER)
    assert r.status_code == 202, r.text
    assert (await a.view(ticket, CHAU))["status"] == S_CONFIRMING
    assert await writes(mock) == before + 1
    r = await a.confirm(ticket, CHAU, True)
    assert r.status_code == 202, r.text
    view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["close_reason"]) == (S_RESOLVED, "resolved_user_confirmed"), view
    return ticket


async def rejected_hitl(a: Api, note: str = "không đủ điều kiện gia hạn") -> str:
    """i2 (TC08-vpn): chờ duyệt → ha.lt từ chối có note → `S_REJECTED` (`rejected_by_approver`)."""
    ticket, aid = await pending_hitl(a)
    r = await decide(a, aid, APPROVER, decision="rejected", note=note)
    assert r.status_code == 202, r.text
    view = await a.view(ticket, CHAU)
    assert (view["final_state"], view["close_reason"]) == (S_REJECTED, "rejected_by_approver"), view
    return ticket


async def ticket_row(rw: AsyncEngine, ticket: str) -> dict[str, Any]:
    async with rw.connect() as conn:
        row = (await conn.execute(text("SELECT * FROM tickets WHERE ticket_id = :t"), {"t": ticket})).mappings().one()
    return dict(row)


async def override_rows(rw: AsyncEngine, ticket: str) -> list[dict[str, Any]]:
    async with rw.connect() as conn:
        found = (await conn.execute(text(
            "SELECT created_at, turn_id, from_status, to_status, original_decision, override_decision, overrider_id, note, "
            "detail, idempotency_key FROM audit_logs WHERE ticket_id = :t AND step = 'OVERRIDE' ORDER BY log_id"
        ), {"t": ticket})).mappings().all()  # fmt: skip
    return [dict(r) for r in found]


async def side_counts(rw: AsyncEngine, ticket: str) -> tuple[int, ...]:
    """Những bảng ghi đè KHÔNG được đụng (P4, S1): lượt, checkpoint, phiếu, side effect, escalation, transaction_log."""
    return tuple((await rows(rw, (
        "SELECT (SELECT count(*) FROM turns WHERE ticket_id = :t), (SELECT count(*) FROM checkpoints WHERE thread_id = :t), "
        "(SELECT count(*) FROM checkpoint_writes WHERE thread_id = :t), (SELECT count(*) FROM approvals WHERE ticket_id = :t), "
        "(SELECT count(*) FROM side_effects WHERE ticket_id = :t), (SELECT count(*) FROM escalations WHERE ticket_id = :t), "
        "(SELECT count(*) FROM transaction_log WHERE ticket_id = :t)"
    ), t=ticket))[0])  # fmt: skip


def scanner(canaries: Sequence[str]) -> SecretScanner:
    return SecretScanner.from_config(CONFIG_DIR, canaries=tuple(canaries))


async def audit_report(pg: PgUrls, tickets: Sequence[str], canaries: Sequence[str]) -> Report:
    """`audit_check.run` qua ĐÚNG đường chỉ đọc (`readonly_engine`, DSN app_rw — TQ-6)."""
    engine = readonly_engine(pg.role("app_rw"))
    try:
        return await run(engine, tickets=list(tickets), scanner=scanner(canaries))
    finally:
        await engine.dispose()


async def control_ticket(rw: AsyncEngine) -> str:
    """Ticket ĐỐI CHỨNG cài thẳng bằng SQL (không qua API/graph) — chỉ dùng cho bước "không mù" của i16/i17."""
    ticket = f"tk-ctl-{uuid4().hex[:8]}"
    await execute(rw, f"INSERT INTO users (user_id, username, role) VALUES ('{CONTROL_USER}', 'gate4.ctl', 'employee') "
                      "ON CONFLICT DO NOTHING")  # fmt: skip
    await execute(rw, "INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request) "
                      "VALUES (:t, :u, 'employee', 'đối chứng audit_check')", t=ticket, u=CONTROL_USER)  # fmt: skip
    return ticket


async def plant_row(rw: AsyncEngine, ticket: str, step: str, event: str, detail: dict[str, Any], **cols: Any) -> int:
    """Một dòng `audit_logs` INSERT tay → `log_id`."""
    names = ["ticket_id", "step", "event", "loop_seq", "detail", *cols]
    values = [":ticket_id", ":step", ":event", "0", "CAST(:detail AS jsonb)", *(f":{c}" for c in cols)]
    sql = f"INSERT INTO audit_logs ({', '.join(names)}) VALUES ({', '.join(values)}) RETURNING log_id"
    async with rw.begin() as conn:
        log_id: Any = (await conn.execute(text(sql), {"ticket_id": ticket, "step": step, "event": event,
                                                 "detail": json.dumps(detail), **cols})).scalar_one()  # fmt: skip
    return int(log_id)
