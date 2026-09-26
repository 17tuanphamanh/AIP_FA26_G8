"""Auth end-to-end trên Postgres thật: `create_app` tự nối SqlAuthStore + SecurityEventWriter (role
app_rw) trong lifespan; AD giả, FakeClock. Kiểm dữ liệu ghi xuống bảng, không chỉ mã HTTP.
Database riêng (có bước enroll MFA → dòng mfa_enrolled không xoá được)."""

import asyncio
import contextlib
import hashlib
import io
import json
from collections.abc import Iterator
from datetime import timedelta

import pyotp
import pytest
from alembic import command
from app.auth.mfa import main as mfa_cli
from app.auth.service import AuthError, AuthService
from app.core.clock import FakeClock
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from tests.fakes.auth import EPOCH, FakeIdentityProvider
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit.auth_helpers import BASE_URL, auth_settings


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest.fixture
def rw(db: PgUrls) -> Iterator[Engine]:
    engine = create_engine(db.role("app_rw"))
    yield engine
    engine.dispose()


def _rows(rw: Engine, sql: str, **params: object) -> list[tuple[object, ...]]:
    with rw.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params).all()]


def _refresh(client: TestClient) -> int:
    csrf = client.cookies.get("csrf") or ""
    return client.post("/api/auth/refresh", headers={"X-CSRF-Token": csrf}).status_code


def test_full_flow_on_postgres(db: PgUrls, rw: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock(EPOCH)
    settings = auth_settings(database_url=db.role("app_rw"))
    app = create_app(settings, health_checks={}, idp=FakeIdentityProvider(), clock=clock)
    with TestClient(app, base_url=BASE_URL, client=("203.0.113.50", 50000)) as client:
        # đăng nhập → users (kèm người quản lý), sessions (chỉ hash), login_success
        r = client.post("/api/auth/login", json={"username": "an.nv", "password": "Demo@2026!"})
        assert r.status_code == 200, r.text
        access = r.json()["access_token"]
        first_refresh = client.cookies.get("refresh") or ""
        assert _rows(rw, "SELECT user_id, role, manager_id FROM users ORDER BY user_id") == [
            ("fin_head", "employee", None), ("nv001", "employee", "fin_head")]  # fmt: skip
        [(rhash, ip)] = _rows(rw, "SELECT refresh_token_hash, ip_prefix FROM sessions")
        assert rhash == hashlib.sha256(first_refresh.encode()).hexdigest() and ip == "203.0.113.0/24"
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 200

        # refresh xoay vòng: dòng cũ 'rotated', dòng mới cùng họ, cùng hạn tuyệt đối
        assert _refresh(client) == 200
        rows = _rows(rw, "SELECT revoke_reason, token_family_id, expires_at FROM sessions ORDER BY created_at, revoke_reason NULLS LAST")
        assert [r[0] for r in rows] == ["rotated", None]
        assert rows[0][1] == rows[1][1] and rows[0][2] == rows[1][2]

        # trình lại token cũ → cả họ bị thu hồi + refresh_reuse_detected
        client.cookies.clear()
        stolen = client.post("/api/auth/refresh", headers={
            "Cookie": f"refresh={first_refresh}; csrf=x", "X-CSRF-Token": "x"})  # fmt: skip
        assert stolen.status_code == 401
        assert {r[0] for r in _rows(rw, "SELECT revoke_reason FROM sessions")} == {"rotated", "reuse_detected"}

        # TC25 trên SQL: 5 lần sai → locked_until = now + 15 phút; đúng mật khẩu vẫn 401
        for _ in range(5):
            client.post("/api/auth/login", json={"username": "an.nv", "password": "sai"})
        [(locked,)] = _rows(rw, "SELECT locked_until FROM users WHERE user_id = 'nv001'")
        assert locked == clock.now() + timedelta(minutes=15)
        assert client.post("/api/auth/login", json={"username": "an.nv", "password": "Demo@2026!"}).status_code == 401
        clock.advance(timedelta(minutes=15))

        # 2 refresh đồng thời trên Postgres thật → cái thứ hai là reuse
        assert client.post("/api/auth/login", json={"username": "an.nv", "password": "Demo@2026!"}).status_code == 200
        token = client.cookies.get("refresh") or ""
        auth = app.state.auth
        assert isinstance(auth, AuthService)

        async def both() -> list[object]:
            return await asyncio.gather(
                auth.refresh(token, ip=None), auth.refresh(token, ip=None), return_exceptions=True
            )

        results = client.portal.call(both)  # chạy trên event loop của app (engine gắn với loop đó)
        assert sum(isinstance(x, AuthError) for x in results) == 1

        # manager: chưa enroll → 401 + mfa_failed(not_enrolled); enroll bằng CLI; OTP đúng → 200
        r = client.post("/api/auth/login", json={"username": "quan.tm", "password": "Demo@2026!"})
        assert r.json() == {"detail": "mfa_not_enrolled"}
        monkeypatch.setenv("DATABASE_URL", db.role("app_rw"))
        assert settings.mfa_enc_key is not None
        monkeypatch.setenv("MFA_ENC_KEY", settings.mfa_enc_key.get_secret_value())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert mfa_cli(["enroll", "quan.tm", "--by", "ops", "--reason", "test"]) == 0
        secret = next(line.split(": ", 1)[1] for line in out.getvalue().splitlines() if line.startswith("Secret: "))
        otp = pyotp.TOTP(secret).at(clock.now())
        r = client.post("/api/auth/login", json={"username": "quan.tm", "password": "Demo@2026!", "otp": otp})
        assert r.status_code == 200, r.text

    # canary trên bảng thật: không mật khẩu, token, secret trong security_events
    details = json.dumps(_rows(rw, "SELECT event_type, detail::text, username_attempted FROM security_events"),
                         default=str)  # fmt: skip
    for leaked in ("Demo@2026!", access, first_refresh, token, secret, "otpauth"):
        assert leaked not in details
    types = [r[0] for r in _rows(rw, "SELECT event_type FROM security_events ORDER BY event_id")]
    for expected in ("login_success", "token_refreshed", "refresh_reuse_detected", "login_failed",
                     "account_locked", "mfa_failed", "mfa_enrolled"):  # fmt: skip
        assert expected in types
