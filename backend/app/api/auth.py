"""Router xác thực (P6 mục 8). Mỏng: gọi `AuthService`, đặt cookie, đổi `AuthError` → HTTP.

Cookie:
- `refresh`: `HttpOnly; Secure; SameSite=Strict; Path=/api/auth` — JS không đọc được.
- `csrf`: `Secure; SameSite=Strict; Path=/`, KHÔNG HttpOnly — JS đọc để gửi header `X-CSRF-Token`
  ở `/api/auth/refresh` (double submit).
"""

from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import get_auth, require
from app.auth.models import IssuedTokens, Principal
from app.auth.permissions import ADMIN_REVOKE_ROLES
from app.auth.service import AuthError, ip_prefix
from app.auth.tokens import csrf_matches

router = APIRouter()

REFRESH_COOKIE = "refresh"
CSRF_COOKIE = "csrf"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_PATH = "/api/auth"


class LoginIn(BaseModel):
    # extra="ignore": trường lạ như `role` trong body bị bỏ qua — role chỉ lấy từ nhóm AD (bất biến 11).
    model_config = ConfigDict(extra="ignore")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    otp: str | None = Field(default=None, max_length=16)


async def auth_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthError)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def _client_ip(request: Request) -> str | None:
    # Chưa có Caddy: tin request.client.host. Phase 7: sau proxy thì chỉ tin X-Forwarded-For khi
    # request đến từ Caddy (PROGRESS).
    return ip_prefix(request.client.host if request.client else None)


def _set_cookies(response: Response, tokens: IssuedTokens) -> None:
    # Mốc đọc từ Postgres mang tzinfo ZoneInfo("Etc/UTC"), không phải timezone.utc — Starlette
    # (email.utils.format_datetime) chỉ nhận đúng timezone.utc → chuẩn hoá trước khi đặt cookie.
    expires = tokens.refresh_expires_at.astimezone(UTC)
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh_token, httponly=True, secure=True, samesite="strict",
        path=REFRESH_PATH, expires=expires,
    )  # fmt: skip
    response.set_cookie(
        CSRF_COOKIE, tokens.csrf_token, httponly=False, secure=True, samesite="strict", path="/",
        expires=expires,
    )  # fmt: skip


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, secure=True, httponly=True,
                           samesite="strict")  # fmt: skip
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="strict")


def _token_body(tokens: IssuedTokens) -> dict[str, Any]:
    return {
        "access_token": tokens.access_token,
        "token_type": "bearer",
        "expires_in": tokens.expires_in,
        "csrf_token": tokens.csrf_token,
    }


@router.post("/api/auth/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    auth = get_auth(request)
    result = await auth.login(
        body.username, body.password, body.otp, ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )  # fmt: skip
    _set_cookies(response, result.tokens)
    return _token_body(result.tokens)


@router.post("/api/auth/refresh")
async def refresh(
    request: Request,
    response: Response,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> dict[str, Any]:
    auth = get_auth(request)
    if not csrf_matches(csrf_cookie, csrf_header):
        raise HTTPException(403, "csrf")
    if not refresh_cookie:
        raise HTTPException(401, "unauthorized")
    result = await auth.refresh(refresh_cookie, ip=_client_ip(request))
    _set_cookies(response, result.tokens)
    return _token_body(result.tokens)


@router.post("/api/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, principal: Annotated[Principal, Depends(require())]
) -> None:
    await get_auth(request).logout(principal)
    _clear_cookies(response)


@router.post("/api/auth/logout-all", status_code=204)
async def logout_all(
    request: Request, response: Response, principal: Annotated[Principal, Depends(require())]
) -> None:
    await get_auth(request).logout_all(principal)
    _clear_cookies(response)


@router.get("/api/auth/me")
async def me(principal: Annotated[Principal, Depends(require())]) -> dict[str, Any]:
    return {
        "user_id": principal.user_id,
        "role": principal.role,
        "permissions": sorted(principal.permissions),
    }


@router.post("/api/admin/users/{user_id}/revoke", status_code=204)
async def revoke_user(
    user_id: str,
    request: Request,
    principal: Annotated[
        Principal, Depends(require(roles=ADMIN_REVOKE_ROLES, recent_login=True))
    ],
) -> None:
    if not await get_auth(request).revoke_user(principal, user_id):
        raise HTTPException(404, "not_found")
