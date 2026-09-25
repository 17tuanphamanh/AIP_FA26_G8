"""Kiểm token dịch vụ ở header `X-Service-Token` (P6 mục 3, D-03).

- Endpoint đọc: `svc_agent` (B6, B11, đăng nhập) hoặc `svc_executor` (B17 kiểm lại AD — D-15).
- Endpoint ghi: **chỉ** `svc_executor` — danh tính duy nhất có credential ghi.
- `svc_worker` mock biết mặt để trả 403 rõ ràng: worker không có việc gì với hệ thống ngoài.

Thiếu token → 401; token lạ → 401; token đúng nhưng sai quyền → 403. Mock chưa cấu hình token
(rỗng, quá ngắn, trùng nhau) → 503 cho mọi endpoint cần token — không bao giờ so khớp chuỗi rỗng.
"""

import hmac
import os
from dataclasses import dataclass
from typing import Literal

from fastapi import Header, HTTPException, Request

MIN_TOKEN_LEN = 32  # P6 mục 3: ≥ 32 byte ngẫu nhiên (token_urlsafe(32) dài 43 ký tự)

Identity = Literal["svc_agent", "svc_executor", "svc_worker"]
READ_IDENTITIES: frozenset[Identity] = frozenset({"svc_agent", "svc_executor"})
WRITE_IDENTITIES: frozenset[Identity] = frozenset({"svc_executor"})


@dataclass(frozen=True)
class ServiceTokens:
    agent: str
    executor: str
    worker: str = ""  # tuỳ chọn: chỉ để nhận diện và trả 403

    @classmethod
    def from_env(cls) -> "ServiceTokens":
        return cls(
            agent=os.environ.get("SVC_AGENT_TOKEN", ""),
            executor=os.environ.get("SVC_EXECUTOR_TOKEN", ""),
            worker=os.environ.get("SVC_WORKER_TOKEN", ""),
        )

    @property
    def configured(self) -> bool:
        required = [self.agent, self.executor]
        present = [t for t in (self.agent, self.executor, self.worker) if t]
        return all(len(t) >= MIN_TOKEN_LEN for t in required + present) and len(set(present)) == len(
            present
        )

    def identify(self, presented: str) -> Identity | None:
        found: Identity | None = None
        candidates: tuple[tuple[Identity, str], ...] = (
            ("svc_agent", self.agent),
            ("svc_executor", self.executor),
            ("svc_worker", self.worker),
        )
        for name, token in candidates:
            # So hết cả ba (không dừng sớm) để thời gian không lộ token nào gần đúng.
            if token and hmac.compare_digest(presented.encode(), token.encode()):
                found = name
        return found


def _check(request: Request, token: str | None, allowed: frozenset[Identity]) -> Identity:
    tokens: ServiceTokens = request.app.state.tokens
    if not tokens.configured:
        raise HTTPException(503, "mock_service_tokens_not_configured")
    if not token:
        raise HTTPException(401, "missing_service_token")
    identity = tokens.identify(token)
    if identity is None:
        raise HTTPException(401, "unknown_service_token")
    if identity not in allowed:
        raise HTTPException(403, f"{identity}_not_allowed")
    return identity


async def require_read(
    request: Request, x_service_token: str | None = Header(default=None)
) -> Identity:
    return _check(request, x_service_token, READ_IDENTITIES)


async def require_write(
    request: Request, x_service_token: str | None = Header(default=None)
) -> Identity:
    return _check(request, x_service_token, WRITE_IDENTITIES)
