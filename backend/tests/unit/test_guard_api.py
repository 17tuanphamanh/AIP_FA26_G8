"""Privacy guard ở API (phase3 mục 8.3, 8.7 e6–e8; PLAN-3e Q-3e-2, Q-3e-6): guard THẬT (`RegexPrivacyGuard`) qua HTTP
thật của app, graph trên bản giả.

- e6: guard lỗi → 503 `{"error":"privacy_guard_unavailable"}`, 0 INSERT, không `start_event`, log không có body.
- e7 (unit): có bí mật → 202 kèm `notices`; `privacy_secret_redacted {count}` — lúc tạo đi cùng `tickets.create`
  (transaction, bản PG ở `integration/test_guard_pg.py`), tin nhắn sau ghi TRƯỚC `start_event`; ghi lỗi → 503.
- e8: MỌI đường trả 422 do kiểm dữ liệu vào (grep `backend/app/api/`, PLAN-3e Q-3e-2) không trả lại giá trị người gửi.
- Q-3e-13 + rà trường tự do: ô KHÔNG qua guard mà được lưu (`reason_code`, username đăng nhập) chỉ nhận mã cố định /
  định danh; giá trị khác → 422, không lưu.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from app.api.auth import USERNAME_PATTERN
from app.api.errors import GUARD_UNAVAILABLE
from app.domain.messages import ReasonCode
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL
from app.guard.privacy import (
    NOTICE_PII,
    NOTICE_SECRET,
    RedactionResult,
    RegexPrivacyGuard,
)
from app.settings import Settings
from tests.fakes.auth import seed_ad_users
from tests.fakes.desk import DeskEnv, desk_env

pytestmark = pytest.mark.asyncio

REPO = Path(__file__).resolve().parents[3]
CANARY = "Canary#" + "7781xyz"  # ghép lúc chạy (gitleaks)
PASSWORD_TEXT = f"mật khẩu của tôi là {CANARY}, reset giúp"
PLANS: dict[str, dict[str, str | list[str]]] = {
    S_CLARIFYING: {"b11_slots": ["missing", "complete"]},
    S_CONFIRMING: {"b12_assess": "auto"},
    S_PENDING_APPROVAL: {},
}


class SwitchGuard:
    """Guard thật; bật `broken` → ném lỗi có CHỨA văn bản (log/response không được lộ nó)."""

    def __init__(self) -> None:
        self.real = RegexPrivacyGuard.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
        self.broken = False
        self.calls = 0

    async def redact(self, text: str) -> RedactionResult:
        self.calls += 1
        if self.broken:
            raise RuntimeError(f"regex nổ trên {text!r}")
        return await self.real.redact(text)


async def _ticket_at(env: DeskEnv, status: str) -> tuple[str, dict[str, str]]:
    an = await env.token("an.nv")
    await env.token("ha.lt")  # người duyệt giả phải có dòng users
    ticket = await env.create(an, "VPN không vào được")
    await env.drain()
    assert (await env.ticket(ticket, an))["status"] == status
    return ticket, an


async def _post_second(env: DeskEnv, status: str, ticket: str, an: dict[str, str], text: str) -> Any:
    if status == S_CLARIFYING:
        return await env.client.post(f"/api/tickets/{ticket}/messages", json={"text": text}, headers=an)
    if status == S_CONFIRMING:
        return await env.client.post(f"/api/tickets/{ticket}/confirm", json={"confirmed": False, "note": text},
                                     headers=an)  # fmt: skip
    l1 = await env.token("ha.lt")
    return await env.client.post(f"/api/approvals/{env.approval_of(ticket)}/decision",
                                 json={"decision": "rejected", "note": text}, headers=l1)  # fmt: skip


# ---- e6: guard lỗi → 503, không lưu, không start_event, log sạch ------------------------------------------


async def test_e6_create_guard_error_503_nothing_stored(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    guard = SwitchGuard()
    guard.broken = True
    async with desk_env(guard=guard) as env:
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets", json={"text": PASSWORD_TEXT}, headers=an)
        await env.drain()
        assert (r.status_code, r.json()) == (503, GUARD_UNAVAILABLE)
        assert env.h.tickets.rows == {} and env.h.turns.rows == {} and env.h.tickets.security_events == []
        assert guard.calls == 1
    assert CANARY not in caplog.text
    assert "privacy guard lỗi: route=/api/tickets loại=RuntimeError" in caplog.text


@pytest.mark.parametrize("status", list(PLANS))
async def test_e6_followup_guard_error_503_no_event(status: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    guard = SwitchGuard()
    async with desk_env(guard=guard, plan=PLANS[status]) as env:
        ticket, an = await _ticket_at(env, status)
        turns = len(env.h.turns.of(ticket))
        guard.broken = True
        r = await _post_second(env, status, ticket, an, PASSWORD_TEXT)
        await env.drain()
        assert (r.status_code, r.json()) == (503, GUARD_UNAVAILABLE)
        assert len(env.h.turns.of(ticket)) == turns  # không start_event: không lượt mới
        assert env.late(ticket) == [] and env.sink.of("privacy_secret_redacted") == []
        guard.broken = False
        assert (await env.ticket(ticket, an))["status"] == status
    assert CANARY not in caplog.text


# ---- e7 (unit): notices + privacy_secret_redacted ---------------------------------------------------------


async def test_e7_create_with_password_notices_and_event_with_ticket() -> None:
    async with desk_env(guard=SwitchGuard()) as env:
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets", json={"text": PASSWORD_TEXT}, headers=an)
        await env.drain()
        assert r.status_code == 202 and r.json()["notices"] == [NOTICE_SECRET]
        ticket = r.json()["ticket_id"]
        assert env.h.tickets.security_events == [{
            "event_type": "privacy_secret_redacted", "ticket_id": ticket, "user_id": "nv001", "detail": {"count": 1},
        }]  # fmt: skip
        assert env.sink.of("privacy_secret_redacted") == []  # lúc tạo: cùng transaction tickets.create, không qua sink
        stored = env.h.tickets.rows[ticket]["redacted_request"]
        assert CANARY not in stored and "[BÍ_MẬT_ĐÃ_ẨN]" in stored


async def test_e7_pii_only_notice_without_event() -> None:
    async with desk_env(guard=SwitchGuard()) as env:
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets", json={"text": "gọi em 0912345678"}, headers=an)
        await env.drain()
        assert r.json()["notices"] == [NOTICE_PII]
        assert env.h.tickets.security_events == []
        assert env.h.tickets.rows[r.json()["ticket_id"]]["redacted_request"] == "gọi em <SĐT_1>"


@pytest.mark.parametrize(("status", "route"), [
    (S_CLARIFYING, "/api/tickets/{ticket_id}/messages"),
    (S_CONFIRMING, "/api/tickets/{ticket_id}/confirm"),
    (S_PENDING_APPROVAL, "/api/approvals/{approval_id}/decision"),
])  # fmt: skip
async def test_e7_followup_with_password_event_before_start(status: str, route: str) -> None:
    async with desk_env(guard=SwitchGuard(), plan=PLANS[status]) as env:
        ticket, an = await _ticket_at(env, status)
        r = await _post_second(env, status, ticket, an, PASSWORD_TEXT)
        await env.drain()
        assert r.status_code == 202 and r.json()["notices"] == [NOTICE_SECRET]  # Q-3e-6: cả /decision
        [event] = env.sink.of("privacy_secret_redacted")
        assert (event.ticket_id, event.route, event.detail) == (ticket, route, {"count": 1})
        assert CANARY not in repr(env.h.saver.storage) + repr(env.h.saver.blobs) + repr(env.h.audit.rows)


@pytest.mark.parametrize("status", list(PLANS))
async def test_e7_event_write_error_503_no_start(status: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    async with desk_env(guard=SwitchGuard(), plan=PLANS[status]) as env:
        ticket, an = await _ticket_at(env, status)
        turns = len(env.h.turns.of(ticket))

        record = env.sink.record

        async def down(event_type: str, **kw: Any) -> None:
            if event_type == "privacy_secret_redacted":
                raise ConnectionError(f"DB chết {PASSWORD_TEXT}")
            await record(event_type, **kw)  # đăng nhập (login_success) vẫn ghi được

        env.sink.record = down  # type: ignore[method-assign]
        r = await _post_second(env, status, ticket, an, PASSWORD_TEXT)
        await env.drain()
        assert (r.status_code, r.json()) == (503, GUARD_UNAVAILABLE)
        assert len(env.h.turns.of(ticket)) == turns
    assert CANARY not in caplog.text and "loại=ConnectionError" in caplog.text


# ---- e8: 422 không trả lại giá trị người gửi — mọi route tìm được -------------------------------------


def _assert_clean_422(r: Any) -> list[str]:
    assert r.status_code == 422, r.text
    body = r.json()
    assert set(body) == {"error", "fields"} and body["error"] == "invalid_request"
    assert CANARY not in r.text and "input" not in r.text and "ctx" not in r.text
    return list(body["fields"])


LONG = CANARY + "x" * 5000
BAD_BODIES: dict[str, list[Any]] = {  # route → body sai (dict = JSON, str = byte thô)
    "create": [{"text": LONG}, {"text": "x", CANARY: 1}, {"text": 7, "extra": CANARY}, f'{{"text": "{CANARY}'],
    "messages": [{"text": LONG}, {"text": "x", CANARY: 1}, f'{{"text": "{CANARY}'],
    "confirm": [{"confirmed": CANARY}, {"confirmed": True, "note": LONG}, {"confirmed": True, CANARY: 1}],
    "decision": [{"decision": CANARY}, {"decision": "approved", "view_started_at": CANARY},
                 {"decision": "approved", "note": LONG}, {"decision": "approved", CANARY: 1}],
}  # fmt: skip


def _send(env: DeskEnv, path: str, body: Any, headers: dict[str, str]) -> Any:
    kw: dict[str, Any] = {"content": body} if isinstance(body, str) else {"json": body}
    return env.client.post(path, headers=headers, **kw)


async def test_e8_create_bodies() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        fields = [_assert_clean_422(await _send(env, "/api/tickets", b, an)) for b in BAD_BODIES["create"]]
        assert fields == [["text"], ["<extra>"], ["text", "<extra>"], []]
        assert env.h.tickets.rows == {}


@pytest.mark.parametrize(("key", "status"), [("messages", S_CLARIFYING), ("confirm", S_CONFIRMING),
                                             ("decision", S_PENDING_APPROVAL)])  # fmt: skip
async def test_e8_followup_bodies(key: str, status: str) -> None:
    async with desk_env(plan=PLANS[status]) as env:
        ticket, an = await _ticket_at(env, status)
        headers = await env.token("ha.lt") if key == "decision" else an
        path = (f"/api/approvals/{env.approval_of(ticket)}/decision" if key == "decision"
                else f"/api/tickets/{ticket}/{key}")  # fmt: skip
        for body in BAD_BODIES[key]:
            assert _assert_clean_422(await _send(env, path, body, headers)) is not None
        assert env.late(ticket) == []


@pytest.mark.parametrize("body", [
    {"username": "an.nv", "password": LONG},  # max_length 256 — `input` mặc định chính là mật khẩu
    {"username": "", "password": CANARY},
    {"username": CANARY * 20, "password": CANARY},
])  # fmt: skip
async def test_e8_login_422_without_password(body: dict[str, Any]) -> None:
    async with desk_env() as env:
        fields = _assert_clean_422(await env.client.post("/api/auth/login", json=body))
        assert all(f.startswith("body.") for f in fields)


async def test_e8_query_param_422() -> None:
    async with desk_env() as env:
        l1 = await env.token("ha.lt")
        r = await env.client.get("/api/escalations/queue", params={"limit": CANARY}, headers=l1)
        assert _assert_clean_422(r) == ["query.limit"]


async def test_e8_reject_without_note_still_plain_422() -> None:
    """422 nghiệp vụ (`rejected_requires_note`, hằng chuỗi) giữ nguyên — không phải lỗi kiểm dữ liệu."""
    async with desk_env() as env:
        ticket, _ = await _ticket_at(env, S_PENDING_APPROVAL)
        l1 = await env.token("ha.lt")
        r = await env.client.post(f"/api/approvals/{env.approval_of(ticket)}/decision",
                                  json={"decision": "rejected"}, headers=l1)  # fmt: skip
        assert (r.status_code, r.json()) == (422, {"detail": "rejected_requires_note"})


# ---- Q-3e-13 + rà trường tự do: ô KHÔNG qua guard chỉ nhận mã cố định / định danh ---------------------------


@pytest.mark.parametrize("code", get_args(ReasonCode.__value__))
async def test_q3e13_reason_code_accepts_fixed_codes(code: str) -> None:
    async with desk_env() as env:
        ticket, _ = await _ticket_at(env, S_PENDING_APPROVAL)
        l1 = await env.token("ha.lt")
        r = await env.client.post(f"/api/approvals/{env.approval_of(ticket)}/decision", headers=l1,
                                  json={"decision": "rejected", "note": "thiếu", "reason_code": code})  # fmt: skip
        assert r.status_code == 202, r.text


@pytest.mark.parametrize("value", [CANARY, "abc12345", "missing_info2", "Missing_Info", ""])
async def test_q3e13_reason_code_not_in_list_422_nothing_stored(value: str) -> None:
    """Mật khẩu dán nhầm vào `reason_code` (kể cả dạng chữ thường + số — regex không chặn được) → 422, không lưu."""
    async with desk_env() as env:
        ticket, _ = await _ticket_at(env, S_PENDING_APPROVAL)
        l1 = await env.token("ha.lt")
        turns = len(env.h.turns.of(ticket))
        r = await env.client.post(f"/api/approvals/{env.approval_of(ticket)}/decision", headers=l1,
                                  json={"decision": "rejected", "note": "thiếu", "reason_code": value})  # fmt: skip
        await env.drain()
        assert _assert_clean_422(r) == ["reason_code"] and (value == "" or value not in r.text)
        assert len(env.h.turns.of(ticket)) == turns and env.late(ticket) == []
        assert (await env.ticket(ticket, l1))["status"] == S_PENDING_APPROVAL
        stored = repr(env.h.saver.storage) + repr(env.h.saver.blobs) + repr(env.h.audit.rows) + repr(env.sink.events)
        assert CANARY not in stored and "abc12345" not in stored


@pytest.mark.parametrize("username", [CANARY, "Abc@12345", "an nv", "AN.NV", "an.nv;drop", "1an.nv"])
async def test_login_username_must_be_identifier_422_no_event(username: str) -> None:
    """Username sai DẠNG (gõ nhầm mật khẩu có chữ hoa/ký tự đặc biệt vào ô username) phải bị 422 TRƯỚC khi tới AuthService (không
    sự kiện nào). Đúng dạng mà không có dòng `users` → lưu băm (Phase 4 P2, `test_auth_username_hash.py`)."""
    async with desk_env() as env:
        r = await env.client.post("/api/auth/login", json={"username": username, "password": "sai"})
        assert _assert_clean_422(r) == ["body.username"]
        assert env.sink.events == [] and username not in r.text


async def test_login_username_pattern_accepts_every_seed_user() -> None:
    """Đối chứng: ràng dạng không khoá ai trong seed AD của mock (16 người, gồm `svc-backup`) lẫn bản giả của test."""
    seed = json.loads((REPO / "mock_services" / "seed.json").read_text(encoding="utf-8"))
    names = [u["username"] for u in seed["users"]] + [u.username for u in seed_ad_users()]
    assert len(names) >= 16 and all(re.fullmatch(USERNAME_PATTERN, n) for n in names), names
