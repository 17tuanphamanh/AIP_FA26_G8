"""SqlAuthStore chuẩn hoá datetime đọc từ DB thành tzinfo=timezone.utc — kiểm phần ánh xạ dòng không cần
Postgres (psycopg trả tzinfo theo TimeZone của phiên, ví dụ ZoneInfo("Etc/UTC")). Hợp đồng đầy đủ trên DB
thật: integration/test_auth_store_sql.py."""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.auth import store
from tests.unit.auth_store_contract import assert_utc

PG_UTC = ZoneInfo("Etc/UTC")  # đúng thứ psycopg trả với TimeZone mặc định của image postgres
AT = datetime(2026, 9, 26, 16, 0, tzinfo=PG_UTC)


def _row(**mapping: Any) -> Any:
    return SimpleNamespace(_mapping=mapping)


def test_user_row_locked_until_normalized() -> None:
    user = store._user(_row(
        user_id="nv001", username="an.nv", full_name="An", role="employee", department="finance",
        manager_id=None, employment_status="active", hired_at=date(2024, 1, 1),
        is_privileged_account=False, token_version=0, locked_until=AT, mfa_secret_enc=None,
    ))  # fmt: skip
    assert user.locked_until == AT
    assert_utc(user)


def test_session_row_all_datetimes_normalized() -> None:
    hcm = AT.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
    session = store._session(_row(
        session_id="s1", user_id="nv001", token_family_id=uuid.uuid4(), refresh_token_hash="h" * 64,
        created_at=AT, expires_at=hcm, revoked_at=AT, revoke_reason="logout", ip_prefix=None,
        user_agent_hash=None,
    ))  # fmt: skip
    assert (session.created_at, session.expires_at, session.revoked_at) == (AT, AT, AT)
    assert_utc(session)


def test_utc_helper() -> None:
    assert store._utc(None) is None
    assert store._utc(AT).tzinfo is UTC  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="TIMESTAMPTZ"):
        store._utc(datetime(2026, 9, 26, 16, 0))  # noqa: DTZ001 — cố ý naive
