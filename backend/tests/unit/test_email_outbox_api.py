"""E7 — `GET /api/admin/email-outbox` (chỉ đọc, Trưởng BP IT): 401 không token; 403 cho L1, L2, nhân viên (+ `permission_denied`, không
đọc DB); 405 method khác; marker quyền `audit:read:all`; body đúng khoá, người nhận ĐÃ CHE, KHÔNG thân/tiêu đề/địa chỉ đầy đủ. Truy vấn
SQL thật ở `tests/integration/test_email_outbox_pg.py`; ở đây `recent_outbox` là bản giả."""

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from app.api import email_outbox as api
from app.main import create_app
from app.notify.outbox import OutboxRow
from tests.unit.auth_helpers import AuthEnv, auth_env, auth_settings
from tests.unit.test_auth_route_scan import route_auth

URL = "/api/admin/email-outbox"
ADDRESS = "nguyen.van.a@congty-abc.vn"
AT = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)
ITEM_KEYS = {"id", "created_at", "sent_at", "kind", "recipient", "status", "attempts", "last_error_class"}


class Source:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str | None]] = []
        self.rows = [
            OutboxRow(2, AT, AT, "result", "sent", 0, None, ADDRESS),
            OutboxRow(1, AT, None, "approval_new", "skipped", 0, "NoRecipientEmail", None),
        ]

    async def recent(self, _engine: Any, limit: int, status: str | None = None) -> list[OutboxRow]:
        self.calls.append((limit, status))
        return self.rows


@pytest.fixture
def src(monkeypatch: pytest.MonkeyPatch) -> Source:
    s = Source()
    monkeypatch.setattr(api, "recent_outbox", s.recent)
    return s


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env(llm_backend="scripted") as e:
        e.app.state.engines = SimpleNamespace(main=None)  # `no_runtime` không dựng engine thật; bản giả `recent_outbox` không dùng tới
        yield e


def test_no_token_401(env: AuthEnv) -> None:
    r = env.client.get(URL)
    assert (r.status_code, r.json()) == (401, {"detail": "unauthorized"})


@pytest.mark.parametrize("username", ["ha.lt", "long.nh", "an.nv"])
def test_other_roles_403(env: AuthEnv, src: Source, username: str) -> None:
    before = len(env.sink.of("permission_denied"))
    r = env.client.get(URL, headers=env.bearer(env.token(username)))
    assert (r.status_code, r.json()) == (403, {"detail": "forbidden"})
    events = env.sink.of("permission_denied")[before:]
    assert [(e.route, e.detail.get("perm")) for e in events] == [(URL, "audit:read:all")]
    assert src.calls == []


def test_route_marker_get_only() -> None:
    app = create_app(auth_settings(), health_checks={})
    found = {c.path: (c.methods, c.requirements) for c in route_auth(app)}
    assert found[URL] == (frozenset({"GET"}), (("audit:read:all", None, False),))


def test_manager_reads_masked_rows_without_body(env: AuthEnv, src: Source) -> None:
    r = env.client.get(URL, headers=env.bearer(env.manager_token()))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [set(i) for i in items] == [ITEM_KEYS, ITEM_KEYS]
    assert items[0] == {
        "id": 2, "created_at": "2026-10-24T03:00:00Z", "sent_at": "2026-10-24T03:00:00Z", "kind": "result",
        "recipient": "n***@congty-abc.vn", "status": "sent", "attempts": 0, "last_error_class": None,
    }  # fmt: skip
    assert items[1]["recipient"] is None and items[1]["last_error_class"] == "NoRecipientEmail"
    assert ADDRESS not in r.text and "body" not in r.text and "subject" not in r.text
    assert src.calls == [(50, None)]


def test_filters_and_limits(env: AuthEnv, src: Source) -> None:
    headers = env.bearer(env.manager_token())
    assert env.client.get(URL, params={"status": "failed", "limit": 5}, headers=headers).status_code == 200
    assert src.calls == [(5, "failed")]
    assert env.client.get(URL, params={"status": "lạ"}, headers=headers).status_code == 422
    assert env.client.get(URL, params={"limit": 201}, headers=headers).status_code == 422


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_other_methods_405(env: AuthEnv, method: str) -> None:
    assert env.client.request(method, URL).status_code == 405
