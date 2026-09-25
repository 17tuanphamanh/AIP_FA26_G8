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
