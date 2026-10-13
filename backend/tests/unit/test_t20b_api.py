"""T20b — API `/reply` + `children_progress` (phase5 P11, 5.2.6; 5.2.8 a1–a7). Viết TỪ ĐẶC TẢ trước code (không mở phần `/reply`
của `api/tickets.py`, không đọc thân `children_progress`).

Trạng thái cha dựng bằng graph THẬT (`_t20b.make_flow`, cha `T1` của nv001 = an.nv), rồi gắn app HTTP thật (auth thật, khuôn
`tests/fakes/desk.desk_env`) lên CHÍNH runner/store của harness đó (`harness_runtime`). Người: an.nv = nv001 (chủ), binh.tt = nv002,
ha.lt = l1_01 (l1, không phải chủ).

DỪNG 2: ca a* gom `CHO_DUNG2` (`xfail(strict)`). Ghim (xanh sẵn, không xfail): `/messages`, `/confirm` lên ticket con → 409 (a4 phần cũ).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from app.domain.children import ChildProgressRow, children_progress
from app.domain.messages import ACTION_LABELS
from app.domain.states import (
    S_CONFIRMING,
    S_ESCALATED,
    S_PENDING_APPROVAL,
    S_REJECTED,
    S_RESOLVED,
)
from app.guard.privacy import NOTICE_SECRET
from app.main import create_app
from fastapi import FastAPI
from tests.fakes.auth import (
    DEMO_PASSWORD,
    FakeIdentityProvider,
    InMemoryAuthStore,
    RecordingSink,
)
from tests.fakes.desk import MASK, SECRET, MaskingGuard, harness_runtime
from tests.unit._t20b import (
    RESET,
    TC34,
    TC35,
    Flow,
    adobe_item,
    classify,
    extend_item,
    make_flow,
    reset_item,
)
from tests.unit.auth_helpers import BASE_URL, auth_settings
from tests.unit.test_guard_api import CANARY, PASSWORD_TEXT, SwitchGuard

CHO_DUNG2 = frozenset({
    "test_a1_reply_valid_202_parent_resumes",
    "test_a2_items_must_equal_awaiting_422",
    "test_a3_reply_when_not_waiting_reply_409_one_late_event",
    "test_a3_reply_on_normal_ticket_409_one_late_event",
    "test_a4_reply_on_child_ticket_409_child_message",
    "test_a5_reply_not_owner_403_stranger_404_missing_404",
    "test_a6_secret_in_answer_redacted_everywhere",
    "test_a6_masking_guard_answer_reaches_child_masked",
    "test_a7_children_progress_pure_five_states",
    "test_a7_get_parent_children_progress_milestones",
    "test_a7_get_normal_ticket_children_progress_null",
})  # fmt: skip

NOT_FOUND = {"detail": "not_found"}


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.originalname in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError), reason="T20b DỪNG 2"))


pytestmark = pytest.mark.asyncio


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


@dataclass
class Api:
    app: FastAPI
    client: httpx.AsyncClient
    f: Flow
    sink: RecordingSink
    guard: Any

    async def token(self, username: str) -> dict[str, str]:
        r = await self.client.post("/api/auth/login", json={"username": username, "password": DEMO_PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def drain(self) -> None:
        await self.app.state.background.drain()

    async def reply(self, headers: dict[str, str], items: dict[str, Any], ticket: str = "T1") -> httpx.Response:
        return await self.client.post(f"/api/tickets/{ticket}/reply", json={"items": items}, headers=headers)

    async def get(self, headers: dict[str, str], ticket: str = "T1") -> dict[str, Any]:
        r = await self.client.get(f"/api/tickets/{ticket}", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]

    def late(self, ticket: str) -> list[dict[str, Any]]:
        return self.f.h.audit.of(ticket, "late_event")


@asynccontextmanager
async def api(f: Flow, guard: Any = None) -> AsyncIterator[Api]:
    clock = f.env.clock
    sink = RecordingSink(clock)
    store = InMemoryAuthStore(sink)
    guard = guard or MaskingGuard()
    app = create_app(
        auth_settings(), health_checks={}, idp=FakeIdentityProvider(), store=store, sink=sink, alerts=f.h.alerts,
        runtime=harness_runtime(f.h), guard=guard, clock=clock,
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 50000))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        yield Api(app, client, f, sink, guard)
        await app.state.background.drain()


async def tc35() -> Flow:
    f = make_flow([classify(reset_item(), extend_item())] * 2, extract={"duration": "30"})
    r = await f.submit(TC35)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "parent_reply_wait")
    return f


async def control_reset() -> Flow:
    f = make_flow(classify(reset_item()))
    r = await f.submit(RESET)
    assert (r.status, r.waiting_at) == (S_CONFIRMING, "confirm_wait")
    return f


VALID = {"T1-1": {"confirmed": True}, "T1-2": {"answer": "30"}}


# ---- a1 ------------------------------------------------------------------------------------------------------------------------


async def test_a1_reply_valid_202_parent_resumes() -> None:
    """a1: 202 `{ticket_id, status, notices}`; cha resume sự kiện `reply` (→ `reply_dispatched`, 2 `child_event`)."""
    f = await tc35()
    async with api(f) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, VALID)
        assert r.status_code == 202, r.text
        assert set(r.json()) == {"ticket_id", "status", "notices"} and r.json()["ticket_id"] == "T1"
        await a.drain()
        assert len(f.h.audit.of("T1", "reply_dispatched")) == 1
        assert f.h.effects.count("T1", "child_event") == 2


# ---- a2 ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("items", "field"),
    [
        pytest.param({"T1-1": {"confirmed": True}}, "T1-2", id="thieu-y"),
        pytest.param({**VALID, "T1-3": {"confirmed": True}}, "T1-3", id="y-ngoai-awaiting"),
        pytest.param({"T1-1": {"answer": "ok"}, "T1-2": {"answer": "30"}}, "T1-1", id="answer-cho-y-confirm"),
        pytest.param({"T1-1": {"confirmed": True}, "T1-2": {"confirmed": True}}, "T1-2", id="confirm-cho-y-answer"),
    ],
)  # fmt: skip
async def test_a2_items_must_equal_awaiting_422(items: dict[str, Any], field: str) -> None:
    """a2 (M-T20b-11, chốt (c) — chặt): thiếu ý / ý ngoài `awaiting` / sai loại so với `needs` → 422
    `{"error": "invalid_request", "fields": ["body.items.<child_id>"]}`; 0 `child_event`, không con nào nhận, không `late_event`."""
    f = await tc35()
    turns = {c: len(f.h.turns.of(c)) for c in ("T1", "T1-1", "T1-2")}
    async with api(f) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, items)
        await a.drain()
        assert r.status_code == 422, r.text
        assert (r.json()["error"], r.json()["fields"]) == ("invalid_request", [f"body.items.{field}"])
        assert f.h.effects.count("T1", "child_event") == 0
        assert {c: len(f.h.turns.of(c)) for c in turns} == turns
        assert a.late("T1") == []
        assert (await f.waiting("T1")) == "parent_reply_wait"


# ---- a3 ------------------------------------------------------------------------------------------------------------------------


async def test_a3_reply_when_not_waiting_reply_409_one_late_event() -> None:
    """a3: cha KHÔNG ở `parent_reply_wait` (đang `parent_wait` — con 2 chờ duyệt) → 409 + đúng 1 dòng `late_event`."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    assert (await f.waiting("T1")) == "parent_wait"
    async with api(f) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, {"T1-1": {"confirmed": True}})
        await a.drain()
        assert r.status_code == 409, r.text
        [late] = a.late("T1")
        assert late["detail"]["source"] == "user"


async def test_a3_reply_on_normal_ticket_409_one_late_event() -> None:
    """a3 + 5.2.6: `/reply` lên ticket thường → 409 `LateEvent` (không ở `parent_reply_wait`) + 1 dòng `late_event`."""
    f = await control_reset()
    async with api(f) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, {"T1-1": {"confirmed": True}})
        await a.drain()
        assert r.status_code == 409, r.text
        assert len(a.late("T1")) == 1
        assert (await f.waiting("T1")) == "confirm_wait"


# ---- a4 ------------------------------------------------------------------------------------------------------------------------


async def test_a4_reply_on_child_ticket_409_child_message() -> None:
    """a4: `/reply` lên ticket CON → 409 `CHILD_MESSAGE` ("trả lời trong hội thoại chung"), trước body/guard, không ghi gì."""
    f = await control_reset()
    f.h.tickets.rows["T1"]["parent_ticket_id"] = "cha-1"  # ticket con (khuôn `test_tickets_api`)
    async with api(f) as a:
        an = await a.token("an.nv")
        calls = a.guard.calls
        r = await a.reply(an, {"T1-1": {"answer": SECRET}})
        assert r.status_code == 409 and "hội thoại chung" in r.json()["detail"], r.text
        assert a.guard.calls == calls and a.late("T1") == []


@pytest.mark.parametrize(("route", "body"), [("messages", {"text": "x"}), ("confirm", {"confirmed": True})])
async def test_a4_messages_confirm_on_child_ticket_409_pinned(route: str, body: dict[str, Any]) -> None:
    """a4 (đã có, ghim — không xfail): `/messages`, `/confirm` lên ticket con → 409 "hội thoại chung"."""
    f = await control_reset()
    f.h.tickets.rows["T1"]["parent_ticket_id"] = "cha-1"
    async with api(f) as a:
        an = await a.token("an.nv")
        r = await a.client.post(f"/api/tickets/T1/{route}", json=body, headers=an)
        assert r.status_code == 409 and "hội thoại chung" in r.json()["detail"]


# ---- a5 ------------------------------------------------------------------------------------------------------------------------


async def test_a5_reply_not_owner_403_stranger_404_missing_404() -> None:
    """a5 (khuôn TC30 / `/messages`): l1 không phải chủ → 403; nhân viên khác → 404 y hệt id giả; id giả → 404; không ai giao gì."""
    f = await tc35()
    async with api(f) as a:
        binh, l1 = await a.token("binh.tt"), await a.token("ha.lt")
        r_l1 = await a.reply(l1, VALID)
        r_binh = await a.reply(binh, VALID)
        r_missing = await a.reply(binh, VALID, ticket="khong-co")
        await a.drain()
        assert r_l1.status_code == 403
        assert (r_binh.status_code, r_binh.json()) == (r_missing.status_code, r_missing.json()) == (404, NOT_FOUND)
        assert f.h.effects.count("T1", "child_event") == 0 and (await f.waiting("T1")) == "parent_reply_wait"


# ---- a6 ------------------------------------------------------------------------------------------------------------------------


async def test_a6_secret_in_answer_redacted_everywhere() -> None:
    """a6: `answer` có bí mật → privacy guard (TRƯỚC mọi ghi/giao) → bản che vào con (B11 thấy bản che) + `conversation` cha; 202
    `notices=[privacy_secret_redacted]` + 1 sự kiện `privacy_secret_redacted {count}`; bí mật không nằm trong checkpoint/audit."""
    f = await tc35()
    async with api(f, guard=SwitchGuard()) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, {"T1-1": {"confirmed": True}, "T1-2": {"answer": f"30, {PASSWORD_TEXT}"}})
        await a.drain()
        assert r.status_code == 202 and r.json()["notices"] == [NOTICE_SECRET], r.text
        [event] = a.sink.of("privacy_secret_redacted")
        assert (event.ticket_id, event.detail) == ("T1", {"count": 1})
        [extract] = f.gw.llm.calls_for("b11_extract_slots")
        assert CANARY not in str(extract.variables["text"])
        [user] = await f.user_msgs("T1")
        assert CANARY not in user["text"]
        assert CANARY not in repr(f.h.saver.storage) + repr(f.h.saver.blobs) + repr(f.h.audit.rows)


async def test_a6_masking_guard_answer_reaches_child_masked() -> None:
    """a6 (bản `MaskingGuard` của desk): chuỗi bí mật giả → `[BÍ_MẬT_ĐÃ_ẨN]` trong câu con nhận và trong tin user của cha."""
    f = await tc35()
    async with api(f) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, {"T1-1": {"confirmed": True}, "T1-2": {"answer": f"30 {SECRET}"}})
        await a.drain()
        assert r.status_code == 202, r.text
        [extract] = f.gw.llm.calls_for("b11_extract_slots")
        assert SECRET not in str(extract.variables["text"]) and MASK in str(extract.variables["text"])
        [user] = await f.user_msgs("T1")
        assert SECRET not in user["text"] and MASK in user["text"]


# ---- a7 ------------------------------------------------------------------------------------------------------------------------


async def test_a7_children_progress_pure_five_states() -> None:
    """a7 (5.2.6): thứ tự xét closed (+ outcome) > pending_approval > ready > needs_user (con ∈ `awaiting`) > processing; outcome
    None khi chưa closed; `index` từ `child_id`; tiêu đề từ `titles`."""
    rows = [
        ChildProgressRow("P-1", S_RESOLVED, True, True),
        ChildProgressRow("P-2", None, True, True),
        ChildProgressRow("P-3", None, False, True),
        ChildProgressRow("P-4", None, False, False),
        ChildProgressRow("P-5", None, False, False),
        ChildProgressRow("P-6", S_ESCALATED, False, False),
        ChildProgressRow("P-7", S_REJECTED, False, False),
    ]
    titles = {f"P-{i}": f"Ý số {i}" for i in range(1, 8)}
    out = children_progress(rows, titles, {"P-3": "answer", "P-4": "confirm"})
    assert out == [
        {"child_id": "P-1", "index": 1, "title": "Ý số 1", "progress": "closed", "outcome": "resolved"},
        {"child_id": "P-2", "index": 2, "title": "Ý số 2", "progress": "pending_approval", "outcome": None},
        {"child_id": "P-3", "index": 3, "title": "Ý số 3", "progress": "ready", "outcome": None},
        {"child_id": "P-4", "index": 4, "title": "Ý số 4", "progress": "needs_user", "outcome": None},
        {"child_id": "P-5", "index": 5, "title": "Ý số 5", "progress": "processing", "outcome": None},
        {"child_id": "P-6", "index": 6, "title": "Ý số 6", "progress": "closed", "outcome": "escalated"},
        {"child_id": "P-7", "index": 7, "title": "Ý số 7", "progress": "closed", "outcome": "rejected"},
    ]
    assert [x["progress"] for x in children_progress(rows[3:5], titles, None)] == ["processing", "processing"]


async def test_a7_get_parent_children_progress_milestones() -> None:
    """a7 + 5.2.7: `GET` cha có `children_progress` đúng ở từng mốc — `ready` + `pending_approval` lúc chờ duyệt, `needs_user` sau
    digest, `closed`/`resolved` cuối. Chỉ từ DB + checkpoint CHA."""
    install = cap(ACTION_LABELS["install_software"])
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    async with api(f) as a:
        an = await a.token("an.nv")

        def progress(view: dict[str, Any]) -> list[tuple[str, int, str, str, str | None]]:
            assert isinstance(view.get("children_progress"), list), view.get("children_progress")
            return [(x["child_id"], x["index"], x["title"], x["progress"], x["outcome"]) for x in view["children_progress"]]

        assert progress(await a.get(an)) == [("T1-1", 1, "Đặt lại mật khẩu", "ready", None),
                                             ("T1-2", 2, install, "pending_approval", None)]  # fmt: skip
        await f.deliver("T1-2", S_PENDING_APPROVAL, f.decision("T1-2"))
        assert [p[3] for p in progress(await a.get(an))] == ["needs_user", "needs_user"]
        r = await a.reply(an, {"T1-1": {"confirmed": True}, "T1-2": {"confirmed": True}})
        assert r.status_code == 202, r.text
        await a.drain()
        assert [(p[3], p[4]) for p in progress(await a.get(an))] == [("closed", "resolved"), ("closed", "resolved")]


async def test_a7_get_normal_ticket_children_progress_null() -> None:
    """a7: ticket thường → `children_progress: null`."""
    f = await control_reset()
    async with api(f) as a:
        an = await a.token("an.nv")
        view = await a.get(an)
        assert "children_progress" in view and view["children_progress"] is None
