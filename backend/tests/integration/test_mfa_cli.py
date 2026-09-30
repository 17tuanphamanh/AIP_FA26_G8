"""CLI `python -m app.auth.mfa enroll|reset` trên Postgres thật (role app_rw): ghi sự kiện
mfa_enrolled/mfa_reset với `detail` chỉ {by, reason} — không secret, không URI (canary); reset tăng
token_version và thu hồi phiên. Database riêng: dòng mfa_* không xoá được."""

import base64
import json
import secrets
import uuid
from typing import Any

import pytest
from alembic import command
from app.auth.mfa import MfaCipher, main
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from tests.integration.pg import PgUrls, alembic_config, fresh_database


def _parse(out: str) -> tuple[str, str]:
    lines = dict(line.split(": ", 1) for line in out.splitlines() if ": " in line)
    return lines["Secret"], lines["URI"]


def _events(rw: Engine) -> list[tuple[str, str | None, str]]:
    with rw.connect() as conn:
        rows = conn.execute(
            text("SELECT event_type, user_id, detail::text FROM security_events ORDER BY event_id")
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def test_enroll_and_reset_via_cli(
    pg: PgUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = base64.b64encode(secrets.token_bytes(32)).decode()
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        rw = create_engine(db.role("app_rw"))
        try:
            with rw.begin() as conn:
                conn.execute(text(
                    "INSERT INTO users (user_id, username, role) VALUES ('it_mgr01', 'quan.tm', 'manager')"
                ))  # fmt: skip
                conn.execute(
                    text(
                        "INSERT INTO sessions (session_id, user_id, token_family_id, expires_at, "
                        "refresh_token_hash) VALUES ('s1', 'it_mgr01', :f, now() + interval '8 hours', :h)"
                    ),
                    {"f": uuid.uuid4(), "h": "a" * 64},
                )
            monkeypatch.setenv("DATABASE_URL", db.role("app_rw"))
            monkeypatch.setenv("MFA_ENC_KEY", key)

            assert main(["enroll", "quan.tm", "--by", "ops.an", "--reason", "cấp mới"]) == 0
            secret, uri = _parse(capsys.readouterr().out)
            assert uri.startswith("otpauth://totp/") and secret in uri
            [(etype, uid, detail)] = _events(rw)
            assert (etype, uid, json.loads(detail)) == ("mfa_enrolled", "it_mgr01",
                                                        {"by": "ops.an", "reason": "cấp mới"})  # fmt: skip
            with rw.connect() as conn:
                blob: Any = conn.execute(
                    text("SELECT mfa_secret_enc FROM users WHERE user_id = 'it_mgr01'")
                ).scalar_one()
            assert secret.encode() not in bytes(blob)
            assert MfaCipher(SecretStr(key)).decrypt("it_mgr01", bytes(blob)) == secret

            assert main(["enroll", "quan.tm", "--by", "ops.an", "--reason", "lần 2"]) == 2
            assert "reset" in capsys.readouterr().err

            assert main(["reset", "quan.tm", "--by", "ops.binh", "--reason", "mất điện thoại"]) == 0
            new_secret, _ = _parse(capsys.readouterr().out)
            assert new_secret != secret
            with rw.connect() as conn:
                tv: Any = conn.execute(text("SELECT token_version FROM users WHERE user_id='it_mgr01'")).scalar_one()
                reason: Any = conn.execute(text("SELECT revoke_reason FROM sessions WHERE session_id='s1'")).scalar_one()
            assert (tv, reason) == (1, "admin")

            assert main(["enroll", "ai.do", "--by", "ops", "--reason", "x"]) == 2
            capsys.readouterr()

            events = _events(rw)
            assert [e[0] for e in events] == ["mfa_enrolled", "mfa_reset"]
            everything = repr(events)
            for leaked in (secret, new_secret, "otpauth"):
                assert leaked not in everything  # canary
        finally:
            rw.dispose()
