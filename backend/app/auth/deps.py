"""FastAPI dependency: tầng 1 (AuthN, Bearer) và tầng 2 (RBAC) của P6 mục 2, 5.2.

Deny-by-default: MỌI route khai báo `Depends(require(...))`, trừ `/api/auth/login`,
`/api/auth/refresh`, `/api/health` — test quét route đỏ nếu quên (P6 test 1).

- `require()`                    — chỉ cần đăng nhập (logout, me…)
- `require("ticket:read:any")`   — cần permission trong PERMS
- `require(roles=ADMIN_REVOKE_ROLES, recent_login=True)` — theo vai trò + xác nhận lại 10 phút

Bị từ chối ở tầng 2 → 403 + `security_events(permission_denied)` kèm route, perm (không kèm dữ liệu).
Auth chưa cấu hình (thiếu JWT_SIGNING_KEY / SVC_AGENT_TOKEN) → 503.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import Principal
from app.auth.permissions import ALL_PERMISSIONS
from app.auth.service import AuthError, AuthService
from app.domain.context import Role

REQUIREMENT_ATTR = "__auth_requirement__"  # test quét route tìm dấu này
_bearer = HTTPBearer(auto_error=False)


def get_auth(request: Request) -> AuthService:
    service: AuthService | None = getattr(request.app.state, "auth", None)
    if service is None:
        raise HTTPException(503, "auth_unavailable")
    return service


def route_of(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "path", request.url.path))


async def current_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    auth = get_auth(request)
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})
    try:
        return await auth.validate_access(creds.credentials)
    except AuthError as e:
        raise HTTPException(e.status, e.detail, headers={"WWW-Authenticate": "Bearer"}) from None


async def deny(request: Request, principal: Principal, perm: str | None, **detail: Any) -> None:
    """Ghi `permission_denied` (tầng 2 và 3) — không kèm dữ liệu bản ghi."""
    await get_auth(request).sink.record(
        "permission_denied",
        user_id=principal.user_id,
        route=route_of(request),
        detail={"perm": perm, **detail} if perm else detail,
    )


def require(
    perm: str | None = None,
    *,
    roles: frozenset[Role] | None = None,
    recent_login: bool = False,
) -> Callable[..., Awaitable[Principal]]:
    if perm is not None and perm not in ALL_PERMISSIONS:
        raise ValueError(f"permission lạ: {perm!r}")  # gõ nhầm tên quyền = lỗi lúc import

    async def dependency(
        request: Request, principal: Annotated[Principal, Depends(current_principal)]
    ) -> Principal:
        if perm is not None and not principal.has(perm):
            await deny(request, principal, perm)
            raise HTTPException(403, "forbidden")
        if roles is not None and principal.role not in roles:
            await deny(request, principal, perm, reason="role")
            raise HTTPException(403, "forbidden")
        if recent_login and not await get_auth(request).recently_logged_in(principal):
            await deny(request, principal, perm, reason="reauth_required")
            raise HTTPException(403, "reauth_required")
        return principal

    setattr(dependency, REQUIREMENT_ATTR, (perm, roles, recent_login))
    return dependency
