"""Giới hạn body 64 KB (2b-3 Q5): 413 TRƯỚC mọi kiểm quyền, đếm byte ĐỌC THẬT (chunked không có
Content-Length vẫn bị chặn); không ghi gì."""

from collections.abc import AsyncIterator

import pytest
from app.domain.states import S_CLARIFYING
from tests.fakes.desk import DeskEnv, desk_env

LIMIT = 64 * 1024


def _json_of_size(n: int) -> bytes:
    """JSON hợp lệ dài đúng n byte: {"text": "aaa…"}."""
    head, tail = b'{"text": "', b'"}'
    return head + b"a" * (n - len(head) - len(tail)) + tail


async def _chunks(body: bytes, size: int = 4096) -> AsyncIterator[bytes]:
    for i in range(0, len(body), size):
        yield body[i : i + size]


def _writes(env: DeskEnv) -> tuple[int, int, int, int]:
    return (len(env.h.tickets.rows), len(env.h.audit.rows), env.denied(), env.guard.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/tickets", "/api/tickets/{t}/messages", "/api/tickets/{t}/confirm",
    "/api/approvals/1/decision",
])  # fmt: skip
async def test_body_over_64kb_413_on_every_post(path: str) -> None:
    async with desk_env(plan={"b11_slots": "missing"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        before = _writes(env)
        # KHÔNG token: 413 phải đến trước 401
        r = await env.client.post(path.format(t=ticket), content=_json_of_size(LIMIT + 1),
                                  headers={"content-type": "application/json"})  # fmt: skip
        assert r.status_code == 413
        assert _writes(env) == before


@pytest.mark.asyncio
async def test_chunked_over_64kb_413() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        body = _json_of_size(LIMIT + 1)
        r = await env.client.post("/api/tickets", content=_chunks(body),
                                  headers={**an, "content-type": "application/json"})  # fmt: skip
        assert "content-length" not in {k.lower() for k in r.request.headers}
        assert r.status_code == 413
        assert env.h.tickets.rows == {}


@pytest.mark.asyncio
async def test_exactly_64kb_passes_limit() -> None:
    async with desk_env(plan={"b11_slots": "missing"}) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        assert (await env.ticket(ticket, an))["status"] == S_CLARIFYING
        body = _json_of_size(LIMIT)
        r = await env.client.post(f"/api/tickets/{ticket}/messages", content=_chunks(body),
                                  headers={**an, "content-type": "application/json"})  # fmt: skip
        assert r.status_code == 422  # qua giới hạn byte; bị chặn ở max_length của text (4000)
