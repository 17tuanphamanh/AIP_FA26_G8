"""Dựng app có auth với bản giả (AD, store, sink, FakeClock) cho test HTTP. Khoá JWT, MFA_ENC_KEY
sinh ngẫu nhiên mỗi lần — không đọc `.env`. Cookie `Secure` → client dùng https://testserver."""

import asyncio
import base64
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pyotp
from app.auth.mfa import MfaCipher, enroll
from app.auth.ports import AuthStore
from app.core.clock import FakeClock
from app.main import create_app
from app.settings import Settings
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from tests.fakes.auth import (
    DEMO_PASSWORD,
    EPOCH,
    FakeIdentityProvider,
    InMemoryAuthStore,
    RecordingSink,
)
from tests.fakes.identity import MemoryAlerts
from tests.fakes.runtime import no_runtime

BASE_URL = "https://testserver"


def auth_settings(**over: Any) -> Settings:
    values: dict[str, Any] = {
        "jwt_signing_key": secrets.token_urlsafe(32),
        "mfa_enc_key": base64.b64encode(secrets.token_bytes(32)).decode(),
        **over,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@dataclass
class AuthEnv:
    app: FastAPI
    client: TestClient
    clock: FakeClock
    sink: RecordingSink
    store: AuthStore
    idp: FakeIdentityProvider
    settings: Settings
    alerts: MemoryAlerts

    def login(
        self, username: str, password: str = DEMO_PASSWORD, otp: str | None = None, **extra: Any
    ) -> httpx.Response:
        body: dict[str, Any] = {"username": username, "password": password, **extra}
        if otp is not None:
            body["otp"] = otp
        return self.client.post("/api/auth/login", json=body)

    def token(self, username: str, **kw: Any) -> str:
        r = self.login(username, **kw)
        assert r.status_code == 200, r.text
        return str(r.json()["access_token"])

    @staticmethod
    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def enroll_mfa(self, username: str) -> str:
        """Đăng ký MFA qua đúng hàm CLI dùng; user phải có dòng `users` (đã thử đăng nhập một lần)."""
        key = self.settings.mfa_enc_key
        assert key is not None
        result = asyncio.run(
            enroll(self.store, self.sink, MfaCipher(key), username=username, by="ops", reason="test")
        )
        return result.secret

    def otp(self, secret: str) -> str:
        return pyotp.TOTP(secret).at(self.clock.now())

    def manager_token(self, username: str = "quan.tm") -> str:
        """Manager bắt buộc MFA: lần đầu 401 (tạo dòng users), enroll, rồi đăng nhập kèm OTP."""
        assert self.login(username).status_code == 401
        return self.token(username, otp=self.otp(self.enroll_mfa(username)))

    def refresh(self) -> httpx.Response:
        csrf = self.client.cookies.get("csrf")
        return self.client.post("/api/auth/refresh", headers={"X-CSRF-Token": csrf or ""})


@contextmanager
def auth_env(
    *,
    store: AuthStore | None = None,
    sink: RecordingSink | None = None,
    clock: FakeClock | None = None,
    idp: FakeIdentityProvider | None = None,
    alerts: MemoryAlerts | None = None,
    escalations: Any = None,
    extra_router: APIRouter | None = None,
    client_ip: str = "203.0.113.7",
    **settings_over: Any,
) -> Iterator[AuthEnv]:
    clock = clock or FakeClock(EPOCH)
    sink = sink or RecordingSink(clock)
    store = store or InMemoryAuthStore(sink)
    idp = idp or FakeIdentityProvider()
    alerts = alerts or MemoryAlerts()
    settings = auth_settings(**settings_over)
    app = create_app(
        settings, health_checks={}, idp=idp, store=store, sink=sink, alerts=alerts,
        escalations=escalations, clock=clock, runtime=no_runtime,
    )  # fmt: skip
    if extra_router is not None:
        app.include_router(extra_router)
    with TestClient(app, base_url=BASE_URL, client=(client_ip, 50000)) as client:
        yield AuthEnv(app, client, clock, sink, store, idp, settings, alerts)
