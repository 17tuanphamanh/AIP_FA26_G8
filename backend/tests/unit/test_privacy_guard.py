"""Privacy guard ở API (D-07, 2b-Q2): sau `POST /api/tickets` và `POST …/messages`, chuỗi bí mật không
nằm ở BẤT KỲ đâu — mọi "bảng" giả (ticket, audit, side effect, span, lượt, hạn, phiếu, escalation,
cảnh báo, security_events) và mọi blob checkpoint. Bản Postgres (quét information_schema) ở
`tests/integration/test_tickets_http_pg.py`.

Đối chứng: cùng luồng với guard KHÔNG che → phép quét phải thấy chuỗi (chứng minh quét không mù).
"""

from typing import Any

import pytest
from app.guard.privacy import RedactionResult
from tests.fakes.desk import SECRET, DeskEnv, desk_env


def _everything(env: DeskEnv) -> bytes:
    h = env.h
    tables: list[Any] = [
        h.tickets.rows, h.audit.rows, h.effects.rows, [vars(s) for s in h.spans.spans], h.turns.rows,
        h.deadlines.waits, h.approvals._table, h.escalations.rows, h.alerts.rows,
        [vars(e) for e in env.sink.events], h.notifier.sent,
    ]  # fmt: skip
    saver = h.saver
    checkpoint = [saver.storage, saver.writes, saver.blobs]
    return repr(tables).encode() + repr(checkpoint).encode()


async def _flow(env: DeskEnv) -> None:
    an = await env.token("an.nv")
    ticket = await env.create(an, text=f"mật khẩu VPN là {SECRET}")
    await env.drain()
    r = await env.client.post(f"/api/tickets/{ticket}/messages",
                              json={"text": f"máy LAP-1, pass {SECRET}"}, headers=an)  # fmt: skip
    assert r.status_code == 202
    await env.drain()


@pytest.mark.asyncio
async def test_secret_nowhere_after_ticket_and_message() -> None:
    async with desk_env(plan={"b11_slots": ["missing", "complete"]}) as env:
        await _flow(env)
        assert env.guard.calls == 2
        assert SECRET.encode() not in _everything(env)


class PassThrough:
    calls = 0

    async def redact(self, text: str) -> RedactionResult:
        return RedactionResult(text=text, secrets_found=0, pii_map_id=None, notices=[])


@pytest.mark.asyncio
async def test_scan_sees_secret_when_not_redacted() -> None:
    async with desk_env(plan={"b11_slots": ["missing", "complete"]}, guard=PassThrough()) as env:  # type: ignore[arg-type]
        await _flow(env)
        assert SECRET.encode() in _everything(env)
