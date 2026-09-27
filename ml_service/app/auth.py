"""Kiểm `X-Service-Token` (P4 mục 5, P6 mục 3) — mọi endpoint trừ `/health`.

So sánh hằng thời gian (`hmac.compare_digest`). Thiếu hoặc sai → 401, không nói token gần đúng hay không.
"""

import hmac

from fastapi import Header, HTTPException, Request


async def require_token(request: Request, x_service_token: str | None = Header(default=None)) -> None:
    expected: bytes = request.app.state.token
    if not x_service_token or not hmac.compare_digest(x_service_token.encode(), expected):
        raise HTTPException(401, "invalid_service_token")
