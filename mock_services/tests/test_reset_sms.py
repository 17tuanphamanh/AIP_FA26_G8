"""F2: đặt lại mật khẩu qua SMS — mật khẩu tạm một lần, hạn 15 phút, hộp thư đi che mật khẩu, kênh email giữ nguyên.

Mật khẩu tạm biết được nhờ monkeypatch `app.ad.new_temp_password` (CANARY), không đọc từ nội dung tin.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from app import ad
from app.main import create_app
from app.security import ServiceTokens
from app.state import load_seed
from fastapi.testclient import TestClient
from tests.conftest import NOW
from tests.test_seed import DEMO_PASSWORD

CANARY = "Canary-Tmp-9f3Kq7"
NEW_PASSWORD = "Moi@Mat-Khau-2026"
SMS = {"channel": "sms"}


class MutableClock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(NOW)


@pytest.fixture
def sms_client(tokens: ServiceTokens, clock: MutableClock) -> Iterator[TestClient]:
    with TestClient(create_app(tokens=tokens, now=clock)) as c:
        yield c


@pytest.fixture
def temp(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(ad, "new_temp_password", lambda: CANARY)
    return CANARY


def _login(
    client: TestClient, agent: dict[str, str], username: str, password: str
) -> Any:
    return client.post(
        "/ad/authenticate",
        headers=agent,
        json={"username": username, "password": password},
    )


def _change(client: TestClient, executor: dict[str, str], temp_password: str, new_password: str = NEW_PASSWORD,
            username: str = "an.nv") -> Any:  # fmt: skip
    body = {
        "username": username,
        "temp_password": temp_password,
        "new_password": new_password,
    }
    return client.post("/ad/change-password", headers=executor, json=body)


def _reset_sms(
    client: TestClient, executor: dict[str, str], user_id: str = "nv001"
) -> Any:
    return client.post(
        f"/ad/users/{user_id}/reset-password", headers=executor, json=SMS
    )


def _outbox(client: TestClient) -> list[dict[str, Any]]:
    resp = client.get("/_admin/outbox")
    assert resp.status_code == 200
    rows: list[dict[str, Any]] = resp.json()
    return rows


def test_email_channel_unchanged(
    sms_client: TestClient, executor: dict[str, str], agent: dict[str, str]
) -> None:
    resp = sms_client.post("/ad/users/nv001/reset-password", headers=executor, json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"user_id": "nv001", "account_type": "ad", "delivered_via": "email",
                    "must_change_at_next_login": True}  # fmt: skip
    assert not any("password" in k.lower() for k in body)
    assert _login(sms_client, agent, "an.nv", DEMO_PASSWORD).status_code == 200
    assert _outbox(sms_client) == []


def test_sms_sends_one_sms_and_one_notice_old_password_dies(
    sms_client: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    phone = next(u.phone for u in load_seed().users if u.user_id == "nv001")
    assert phone is not None
    resp = _reset_sms(sms_client, executor)
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivered_via"] == "sms" and body["must_change_at_next_login"] is True
    assert (
        body["expires_in_minutes"] == 15
        and body["user_id"] == "nv001"
        and body["account_type"] == "ad"
    )
    rows = _outbox(sms_client)
    assert [(r["channel"], r["to"]) for r in rows] == [
        ("sms", phone),
        ("email", "an.nv"),
    ]
    notice = rows[1]["body"]
    assert (
        "qua SMS" in notice
        and "12:00" in notice
        and phone not in notice
        and phone[-3:] in notice
    )
    assert _login(sms_client, agent, "an.nv", DEMO_PASSWORD).status_code == 401


def test_temp_password_login_requires_change(
    sms_client: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    _reset_sms(sms_client, executor)
    resp = _login(sms_client, agent, "an.nv", temp)
    assert resp.status_code == 403 and resp.json() == {
        "detail": "password_change_required"
    }


def test_change_password_then_temp_and_old_die_new_works(
    sms_client: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    _reset_sms(sms_client, executor)
    ok = _change(sms_client, executor, temp)
    assert ok.status_code == 200 and ok.json() == {
        "user_id": "nv001",
        "username": "an.nv",
        "password_changed": True,
    }
    again = _change(sms_client, executor, temp, new_password="Khac@Mat-Khau-2027")
    assert again.status_code == 401 and again.json() == {
        "detail": "invalid_credentials"
    }
    assert _login(sms_client, agent, "an.nv", temp).status_code == 401
    assert _login(sms_client, agent, "an.nv", DEMO_PASSWORD).status_code == 401
    assert _login(sms_client, agent, "an.nv", NEW_PASSWORD).status_code == 200


def test_temp_password_expires_after_15_minutes(
    sms_client: TestClient,
    executor: dict[str, str],
    agent: dict[str, str],
    temp: str,
    clock: MutableClock,
) -> None:
    _reset_sms(sms_client, executor)
    clock.t = NOW + timedelta(minutes=14, seconds=59)
    assert _login(sms_client, agent, "an.nv", temp).status_code == 403  # vẫn còn hạn
    clock.t = NOW + ad.TEMP_PASSWORD_TTL + timedelta(seconds=1)
    expired = _login(sms_client, agent, "an.nv", temp)
    assert expired.status_code == 401 and expired.json() == {
        "detail": "invalid_credentials"
    }
    assert _change(sms_client, executor, temp).status_code == 401
    assert _login(sms_client, agent, "an.nv", NEW_PASSWORD).status_code == 401


def test_canary_never_leaves_sms(
    sms_client: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    reset = _reset_sms(sms_client, executor)
    texts = [
        reset.text,
        _login(sms_client, agent, "an.nv", temp).text,
        sms_client.get("/_admin/outbox").text,
    ]
    texts.append(_change(sms_client, executor, "sai-mat-khau-tam").text)
    assert all(temp not in t for t in texts)
    internal = sms_client.app.state.mock.outbox  # type: ignore[attr-defined]
    sms, email = internal
    assert (
        temp in sms.body
    )  # chứng minh canary thật sự đi trong SMS — phép dò ở trên không rỗng
    assert temp not in email.body and temp not in repr(
        internal
    )  # repr() không in body/secret (log an toàn)
    assert all(temp not in str(r) for r in _outbox(sms_client))


def test_business_errors_and_unknown_fields(
    sms_client: TestClient, executor: dict[str, str]
) -> None:
    no_phone = _reset_sms(sms_client, executor, "svc_backup")
    assert no_phone.status_code == 409 and no_phone.json() == {
        "detail": "no_phone_on_file"
    }
    not_ad = sms_client.post("/ad/users/nv001/reset-password", headers=executor,
                             json={"account_type": "email", "channel": "sms"})  # fmt: skip
    assert not_ad.status_code == 409 and not_ad.json() == {
        "detail": "sms_reset_ad_only"
    }
    for body in ({"phone": "0900000999"}, {"channel": "sms", "phone": "0900000999"}):
        assert (
            sms_client.post(
                "/ad/users/nv001/reset-password", headers=executor, json=body
            ).status_code
            == 422
        )
    assert sms_client.post("/ad/users/nv001/reset-password", headers=executor,
                           json={"channel": "fax"}).status_code == 422  # fmt: skip
    assert _outbox(sms_client) == []


def test_change_password_validation(
    sms_client: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    _reset_sms(sms_client, executor)
    assert (
        _change(sms_client, executor, temp, new_password="Ngan@2026").status_code == 422
    )
    assert _change(sms_client, executor, temp, new_password=temp).status_code == 422
    unknown = _change(sms_client, executor, temp, username="khong.co")
    wrong = _change(sms_client, executor, "sai-mat-khau-tam")
    assert (
        unknown.status_code == wrong.status_code == 401
        and unknown.json() == wrong.json()
    )
    no_reset = _change(
        sms_client, executor, DEMO_PASSWORD, username="binh.tt"
    )  # mật khẩu thật, không có reset SMS
    assert no_reset.status_code == 401
    assert (
        _login(sms_client, agent, "an.nv", temp).status_code == 403
    )  # lỗi trên không tiêu mật khẩu tạm


def test_admin_reset_clears_outbox_and_temp_state(
    sms_client: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    _reset_sms(sms_client, executor)
    assert len(_outbox(sms_client)) == 2
    assert sms_client.post("/_admin/reset").status_code == 200
    assert _outbox(sms_client) == []
    assert _login(sms_client, agent, "an.nv", DEMO_PASSWORD).status_code == 200
    assert _login(sms_client, agent, "an.nv", temp).status_code == 401
    assert _change(sms_client, executor, temp).status_code == 401


@pytest.mark.parametrize("who", ["agent", "worker"])
def test_read_tokens_cannot_reset_or_change(
    sms_client: TestClient,
    request: pytest.FixtureRequest,
    agent: dict[str, str],
    who: str,
    temp: str,
) -> None:
    headers: dict[str, str] = request.getfixturevalue(who)
    reset = sms_client.post("/ad/users/nv001/reset-password", headers=headers, json=SMS)
    assert reset.status_code == 403
    change = _change(sms_client, headers, temp)
    assert change.status_code == 403
    assert _outbox(sms_client) == []
    assert _login(sms_client, agent, "an.nv", DEMO_PASSWORD).status_code == 200
