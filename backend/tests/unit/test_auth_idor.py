"""P6 test 3 — IDOR (TC30) qua router CHỈ có trong test (route thật gắn ở Phase 2/4, dùng lại đúng
các hàm `require` + `can_*` này):
- Nhân viên A đọc ticket của B → 404, GIỐNG HỆT id không tồn tại (status + body).
- L1-X duyệt phiếu giao cho L1-Y → 403.  - L2 gọi API duyệt → 403.
Mọi lần từ chối ghi `permission_denied` kèm route, perm, không kèm dữ liệu bản ghi.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

import pytest
from app.auth.authz import ApprovalParties, can_decide_approval, can_read_ticket
from app.auth.deps import deny, get_auth, require
from app.auth.models import Principal
from fastapi import APIRouter, Depends, HTTPException, Request
from tests.fakes.auth import EPOCH
from tests.unit.auth_helpers import AuthEnv, auth_env


@dataclass(frozen=True)
class _Ticket:
    ticket_id: str
    requester_id: str


@dataclass(frozen=True)
class _Approval:
    approval_id: str
    approver_id: str
    status: str
    deadline: datetime
    requester_id: str


TICKETS = {"t-b": _Ticket("t-b", "nv002"), "t-a": _Ticket("t-a", "nv001")}
APPROVALS = {"ap-y": _Approval("ap-y", "l1_02", "pending", EPOCH + timedelta(minutes=30), "nv002")}


def _router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/_test/tickets/{ticket_id}")
    async def read_ticket(
        ticket_id: str,
        request: Request,
        principal: Annotated[Principal, Depends(require("ticket:read:own"))],
    ) -> dict[str, str]:
        ticket = TICKETS.get(ticket_id)
        if ticket is None or not can_read_ticket(principal, ticket):
            if ticket is not None:
                await deny(request, principal, "ticket:read:any")
            raise HTTPException(404, "not_found")  # cùng một phản hồi cho cả hai trường hợp
        return {"ticket_id": ticket.ticket_id}

    @router.post("/api/_test/approvals/{approval_id}/decide")
    async def decide(
        approval_id: str,
        request: Request,
        principal: Annotated[Principal, Depends(require("approval:decide"))],
    ) -> dict[str, str]:
        a = APPROVALS.get(approval_id)
        if a is None:
            raise HTTPException(404, "not_found")
        parties = ApprovalParties(a.requester_id, None, ())
        if not can_decide_approval(principal, a, parties, now=get_auth(request).clock.now()):
            await deny(request, principal, "approval:decide")
            raise HTTPException(403, "forbidden")
        return {"status": "ok"}

    @router.put("/api/_test/policy")  # chỉ tầng 2, không có kiểm bản ghi phía sau
    async def edit_policy(
        principal: Annotated[Principal, Depends(require("policy:edit"))],
    ) -> dict[str, str]:
        return {"by": principal.user_id}

    return router


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env(extra_router=_router()) as e:
        yield e


def test_employee_reads_other_ticket_same_404_as_missing(env: AuthEnv) -> None:
    token = env.token("an.nv")  # A = nv001
    own = env.client.get("/api/_test/tickets/t-a", headers=env.bearer(token))
    other = env.client.get("/api/_test/tickets/t-b", headers=env.bearer(token))
    missing = env.client.get("/api/_test/tickets/khong-ton-tai", headers=env.bearer(token))
    assert own.status_code == 200
    assert other.status_code == missing.status_code == 404
    assert other.content == missing.content  # body giống từng byte
    assert other.headers.get("content-length") == missing.headers.get("content-length")
    [denied] = env.sink.of("permission_denied")
    assert denied.user_id == "nv001" and denied.route == "/api/_test/tickets/{ticket_id}"
    assert denied.detail == {"perm": "ticket:read:any"}  # không kèm ticket_id hay dữ liệu
    assert denied.ticket_id is None


def test_l1_can_read_any_ticket(env: AuthEnv) -> None:
    token = env.token("ha.lt")
    assert env.client.get("/api/_test/tickets/t-b", headers=env.bearer(token)).status_code == 200


def test_l1_x_cannot_decide_approval_assigned_to_l1_y(env: AuthEnv) -> None:
    token = env.token("ha.lt")  # L1-X = l1_01; phiếu giao cho l1_02
    r = env.client.post("/api/_test/approvals/ap-y/decide", headers=env.bearer(token))
    assert r.status_code == 403
    assert env.sink.of("permission_denied")[0].detail == {"perm": "approval:decide"}
    y = env.token("duc.pv")  # đúng người được giao → được
    assert env.client.post("/api/_test/approvals/ap-y/decide", headers=env.bearer(y)).status_code == 200


def test_l2_calling_approve_api_gets_403(env: AuthEnv) -> None:
    token = env.token("long.nh")
    r = env.client.post("/api/_test/approvals/ap-y/decide", headers=env.bearer(token))
    assert r.status_code == 403
    [denied] = env.sink.of("permission_denied")
    assert denied.route == "/api/_test/approvals/{approval_id}/decide"
    assert denied.detail == {"perm": "approval:decide"}


def test_employee_calling_approve_api_gets_403(env: AuthEnv) -> None:
    token = env.token("an.nv")
    assert env.client.post("/api/_test/approvals/ap-y/decide", headers=env.bearer(token)).status_code == 403


def test_no_token_is_401_not_403(env: AuthEnv) -> None:
    assert env.client.get("/api/_test/tickets/t-a").status_code == 401
    assert env.sink.of("permission_denied") == []


def test_require_alone_blocks_l1_from_policy_edit(env: AuthEnv) -> None:
    """Quy tắc gốc "L1 không được sửa policy" được chặn ở tầng 2, không nhờ kiểm bản ghi."""
    for username in ("ha.lt", "long.nh", "an.nv"):
        r = env.client.put("/api/_test/policy", headers=env.bearer(env.token(username)))
        assert r.status_code == 403, username
    assert [e.detail for e in env.sink.of("permission_denied")] == [{"perm": "policy:edit"}] * 3
    manager = env.manager_token()
    assert env.client.put("/api/_test/policy", headers=env.bearer(manager)).json() == {"by": "it_mgr01"}
