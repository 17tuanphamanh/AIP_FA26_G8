"""P6 test 1 — deny-by-default: mọi route của app thật có `require()`, trừ 3 route miễn (P6 mục 5.2).
Route mới quên gắn kiểm tra → test này đỏ trên CI."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.auth.deps import REQUIREMENT_ATTR, require
from app.main import create_app
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from tests.unit.auth_helpers import auth_settings

EXEMPT = {"/api/auth/login", "/api/auth/refresh", "/api/health"}


@dataclass(frozen=True)
class RouteAuth:
    path: str
    methods: frozenset[str]
    requirements: tuple[Any, ...]  # (perm, roles, recent_login) của từng require() tìm thấy


def _requirements(dependant: Dependant) -> Iterator[Any]:
    for dep in dependant.dependencies:
        marker = getattr(dep.call, REQUIREMENT_ATTR, None)
        if marker is not None:
            yield marker
        yield from _requirements(dep)


def route_auth(app: FastAPI) -> Iterator[RouteAuth]:
    """Mọi APIRoute kể cả trong router lồng nhau — FastAPI ≥ 0.140 bọc router đã include thành
    `_IncludedRouter`, nên phải đi qua `iter_route_contexts` (dependant đã gộp dependency của router)."""
    for ctx in iter_route_contexts(app.routes):
        if isinstance(ctx.original_route, APIRoute):
            yield RouteAuth(str(ctx.path), frozenset(ctx.methods or ()),
                            tuple(_requirements(ctx.dependant)))  # fmt: skip


def _unguarded(app: FastAPI) -> list[str]:
    return sorted(
        f"{sorted(c.methods)} {c.path}"
        for c in route_auth(app)
        if not c.requirements and c.path not in EXEMPT
    )


def test_every_route_declares_require() -> None:
    app = create_app(auth_settings(), health_checks={})
    contexts = list(route_auth(app))
    assert {c.path for c in contexts} >= EXEMPT | {"/api/auth/me", "/api/admin/users/{user_id}/revoke"}
    assert _unguarded(app) == []


TICKET_ROUTES = {  # 2b-3 — mỗi route có đúng permission này (không chỉ "có require nào đó")
    ("POST", "/api/tickets"): "ticket:create",
    ("GET", "/api/tickets"): "ticket:read:own",  # P3 "Gần đây": danh sách của chính người gọi
    ("GET", "/api/tickets/{ticket_id}"): "ticket:read:own",
    ("POST", "/api/tickets/{ticket_id}/hide"): "ticket:read:own",  # P3 menu ⋯ "Xóa" = ẩn khỏi "Gần đây" của chính người gọi
    ("POST", "/api/tickets/{ticket_id}/messages"): "ticket:message",
    ("POST", "/api/tickets/{ticket_id}/confirm"): "ticket:confirm",
    ("POST", "/api/approvals/{approval_id}/decision"): "approval:decide",
    ("GET", "/api/approvals"): "approval:decide",  # 4c P5 hộp thư
    ("GET", "/api/approvals/{approval_id}"): "approval:decide",  # 4c P6 xem phiếu
}


def test_ticket_and_approval_routes_are_scanned_with_their_permission() -> None:
    app = create_app(auth_settings(), health_checks={})
    found = {(m, c.path): c.requirements for c in route_auth(app) for m in c.methods}
    for key, perm in TICKET_ROUTES.items():
        assert key in found, f"quét không thấy {key}"
        assert found[key] == ((perm, None, False),), key


def test_exempt_routes_really_have_no_require() -> None:
    # Miễn có chủ đích, không phải vì test quét sót.
    app = create_app(auth_settings(), health_checks={})
    for c in route_auth(app):
        if c.path in EXEMPT:
            assert c.requirements == (), c.path


def test_scan_catches_a_forgotten_route() -> None:
    app = create_app(auth_settings(), health_checks={})
    router = APIRouter()

    @router.get("/api/quen-gan-quyen")
    async def forgotten() -> dict[str, str]:
        return {}

    @router.get("/api/co-quyen", dependencies=[Depends(require("ticket:read:any"))])
    async def guarded() -> dict[str, str]:
        return {}

    app.include_router(router)
    assert _unguarded(app) == ["['GET'] /api/quen-gan-quyen"]


def test_admin_revoke_uses_role_constant_and_reauth() -> None:
    from app.auth.permissions import ADMIN_REVOKE_ROLES

    app = create_app(auth_settings(), health_checks={})
    [ctx] = [c for c in route_auth(app) if c.path == "/api/admin/users/{user_id}/revoke"]
    assert ctx.requirements == ((None, ADMIN_REVOKE_ROLES, True),)


def test_override_route_requires_permission_and_reauth() -> None:
    """4d P1 (o9): ghi đè = `decision:override` + đăng nhập lại ≤ 10 phút ([Chốt] P6 §4, P10 §3.2) — bỏ `recent_login` là đỏ."""
    app = create_app(auth_settings(), health_checks={})
    found = {(m, c.path): c.requirements for c in route_auth(app) for m in c.methods}
    assert found[("POST", "/api/tickets/{ticket_id}/override")] == (("decision:override", None, True),)
