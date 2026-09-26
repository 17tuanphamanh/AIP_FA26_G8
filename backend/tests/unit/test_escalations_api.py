"""`GET /api/escalations/queue` (P9 mục 7): chỉ `escalation:handle` (l1, l2), sắp theo priority từ seed,
bỏ ticket cha, giới hạn `limit`."""

from collections.abc import Iterator

import pytest
from app.core.clock import FakeClock
from tests.fakes.auth import EPOCH
from tests.fakes.graph import MemoryEscalations, MemoryTickets, MemoryTurns
from tests.unit.auth_helpers import AuthEnv, auth_env


@pytest.fixture
def queue() -> MemoryEscalations:
    tickets = MemoryTickets(MemoryTurns())
    for t in ("a", "b", "c", "d", "parent"):
        tickets.register(t, EPOCH, is_parent=t == "parent")
    return MemoryEscalations(tickets)


@pytest.fixture
def env(queue: MemoryEscalations) -> Iterator[AuthEnv]:
    with auth_env(clock=FakeClock(EPOCH), escalations=queue) as e:
        yield e


async def _fill(queue: MemoryEscalations) -> None:
    for ticket, code in (("a", "E1"), ("b", "E7"), ("c", "E9"), ("d", "E2"), ("parent", "E7")):
        await queue.create(ticket_id=ticket, exit_code=code, reason_detail=None,
                           handoff_note={"request": "x"}, is_deny_case=False, created_at=EPOCH)  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize("username", ["ha.lt", "long.nh"])  # l1, l2
async def test_l1_l2_read_queue_sorted_without_parents(
    env: AuthEnv, queue: MemoryEscalations, username: str
) -> None:
    await _fill(queue)
    r = env.client.get("/api/escalations/queue", headers=env.bearer(env.token(username)))
    assert r.status_code == 200
    body = r.json()
    assert [i["ticket_id"] for i in body] == ["b", "c", "d", "a"]  # E7(1) < E9(4)=E2(4) < E1(6)
    assert body[0]["label"] == "Rất cao" and body[0]["handoff_note"] == {"request": "x"}


def test_employee_and_manager_are_forbidden(env: AuthEnv) -> None:
    r = env.client.get("/api/escalations/queue", headers=env.bearer(env.token("an.nv")))
    assert r.status_code == 403
    r = env.client.get("/api/escalations/queue", headers=env.bearer(env.manager_token()))
    assert r.status_code == 403  # manager không có escalation:handle (P6 5.1)
    assert len(env.sink.of("permission_denied")) == 2


@pytest.mark.parametrize("limit", ["0", "201", "x"])
def test_limit_validated(env: AuthEnv, limit: str) -> None:
    r = env.client.get(f"/api/escalations/queue?limit={limit}",
                       headers=env.bearer(env.token("ha.lt")))  # fmt: skip
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_limit_applies(env: AuthEnv, queue: MemoryEscalations) -> None:
    await _fill(queue)
    r = env.client.get("/api/escalations/queue?limit=2", headers=env.bearer(env.token("ha.lt")))
    assert [i["ticket_id"] for i in r.json()] == ["b", "c"]
