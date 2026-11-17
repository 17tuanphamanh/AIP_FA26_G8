"""`GET /api/escalations/queue` (P9 mục 7; P4 tuần 8): `escalation:handle` (l1, l2), sắp theo priority từ seed, bỏ ticket cha, thân
`{items, next_cursor}`; `status=open|closed` (mặc định open, khác → 422); `limit` 1–100; `after` là cursor mờ (sai dạng → 422
`query.after`); phân trang keyset qua ranh giới trang không trùng/không sót; > 200 dòng vẫn duyệt hết (bỏ trần 200)."""

import base64
import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from app.api.escalations import QUEUE_LIMIT_MAX
from app.core.clock import FakeClock
from app.db.escalations import CloseRequest
from tests.fakes.auth import EPOCH
from tests.fakes.graph import MemoryEscalations, MemoryTickets, MemoryTurns
from tests.unit.auth_helpers import AuthEnv, auth_env

URL = "/api/escalations/queue"
ITEM_KEYS = {
    "escalation_id", "ticket_id", "exit_code", "priority", "label", "reason_detail", "is_deny_case", "handoff_note", "assigned_to",
    "created_at", "closed_at", "close_result", "closed_by", "close_note",
    # D-99 (17/11)
    "assigned_at", "tier", "raised_at", "raised_by", "raise_target", "raise_note", "user_message", "new_ticket_id", "due_at", "overdue",
}  # fmt: skip


@pytest.fixture
def queue() -> MemoryEscalations:
    tickets = MemoryTickets(MemoryTurns())
    for t in ("a", "b", "c", "d", "parent"):
        tickets.register(t, EPOCH, is_parent=t == "parent")
    return MemoryEscalations(tickets)


@pytest.fixture
def env(queue: MemoryEscalations) -> Iterator[AuthEnv]:
    with auth_env(clock=FakeClock(EPOCH), escalations=queue) as e:
        yield e


async def _fill(queue: MemoryEscalations) -> None:
    for ticket, code in (("a", "E1"), ("b", "E7"), ("c", "E9"), ("d", "E2"), ("parent", "E7")):
        await queue.create(ticket_id=ticket, exit_code=code, reason_detail=None,
                           handoff_note={"request": "x"}, is_deny_case=False, created_at=EPOCH)  # fmt: skip


async def _many(queue: MemoryEscalations, n: int) -> None:
    """`n` ca: 3 mã xen kẽ, nhiều ca TRÙNG (priority, created_at) — thứ tự phải phá hoà bằng `escalation_id`."""
    for i in range(n):
        tid = f"t{i:03d}"
        queue._tickets.register(tid, EPOCH)
        await queue.create(ticket_id=tid, exit_code=("E1", "E7", "E9")[i % 3], reason_detail=None, handoff_note={},
                           is_deny_case=False, created_at=EPOCH + timedelta(minutes=i % 4))  # fmt: skip


def _get(env: AuthEnv, query: str = "", user: str = "ha.lt") -> Any:
    return env.client.get(f"{URL}{query}", headers=env.bearer(env.token(user)))


def _walk(env: AuthEnv, status: str, limit: int) -> list[int]:
    token = env.token("long.nh")
    ids: list[int] = []
    after: str | None = None
    for _ in range(100):
        q = f"?status={status}&limit={limit}" + (f"&after={after}" if after else "")
        r = env.client.get(URL + q, headers=env.bearer(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) <= limit
        ids += [i["escalation_id"] for i in body["items"]]
        after = body["next_cursor"]
        if after is None:
            return ids
    raise AssertionError("không hết trang")


def _order(queue: MemoryEscalations, ids: list[int]) -> list[int]:
    rows = {r["escalation_id"]: r for r in queue.rows}
    return sorted(ids, key=lambda i: (rows[i]["priority"], rows[i]["created_at"], i))


@pytest.mark.asyncio
@pytest.mark.parametrize("username", ["ha.lt", "long.nh"])  # l1, l2
async def test_l1_l2_read_queue_sorted_without_parents(env: AuthEnv, queue: MemoryEscalations, username: str) -> None:
    await _fill(queue)
    r = _get(env, user=username)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "next_cursor"} and body["next_cursor"] is None
    items = body["items"]
    assert [i["ticket_id"] for i in items] == ["b", "c", "d", "a"]  # E7(1) < E9(4)=E2(4) < E1(6)
    assert items[0]["label"] == "Rất cao" and items[0]["handoff_note"] == {"request": "x"}
    assert all(set(i) == ITEM_KEYS for i in items)
    assert all(i["closed_at"] is i["close_result"] is i["closed_by"] is i["close_note"] is None for i in items)


def test_employee_forbidden_manager_reads_as_l3(env: AuthEnv) -> None:
    assert _get(env, user="an.nv").status_code == 403
    assert len(env.sink.of("permission_denied")) == 1
    # D-99: manager (Trưởng IT, `escalation:handle:l3`) đọc được hàng đợi để giám sát; xử lý chỉ ca cấp 3 (test_d99_luong_l2.py)
    headers = env.bearer(env.manager_token())
    for tier in ("2", "3"):
        r = env.client.get(f"{URL}?tier={tier}", headers=headers)
        assert r.status_code == 200, r.text


@pytest.mark.parametrize("limit", ["0", "101", "x"])
def test_limit_validated(env: AuthEnv, limit: str) -> None:
    r = _get(env, f"?limit={limit}")
    assert r.status_code == 422 and r.json() == {"error": "invalid_request", "fields": ["query.limit"]}


@pytest.mark.parametrize("status", ["OPEN", "all", "", "closed "])
def test_status_validated(env: AuthEnv, status: str) -> None:
    r = _get(env, f"?status={status}")
    assert r.status_code == 422 and r.json() == {"error": "invalid_request", "fields": ["query.status"]}


@pytest.mark.asyncio
async def test_limit_applies_and_gives_cursor(env: AuthEnv, queue: MemoryEscalations) -> None:
    await _fill(queue)
    body = _get(env, "?limit=2").json()
    assert [i["ticket_id"] for i in body["items"]] == ["b", "c"] and isinstance(body["next_cursor"], str)
    rest = _get(env, f"?limit=2&after={body['next_cursor']}").json()
    assert [i["ticket_id"] for i in rest["items"]] == ["d", "a"] and rest["next_cursor"] is None


@pytest.mark.asyncio
async def test_more_than_200_rows_paginate_without_dup_or_gap(env: AuthEnv, queue: MemoryEscalations) -> None:
    await _many(queue, 250)
    ids = _walk(env, "open", QUEUE_LIMIT_MAX)
    assert len(ids) == len(set(ids)) == 250
    assert ids == _order(queue, ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 7, 33])
async def test_page_boundaries_with_ties(env: AuthEnv, queue: MemoryEscalations, limit: int) -> None:
    await _many(queue, 40)
    assert _walk(env, "open", limit) == _order(queue, [r["escalation_id"] for r in queue.rows])


@pytest.mark.asyncio
async def test_closing_between_pages_does_not_skip_others(env: AuthEnv, queue: MemoryEscalations) -> None:
    await _many(queue, 10)
    first = _get(env, "?limit=4").json()
    seen = [i["escalation_id"] for i in first["items"]]
    for eid in (seen[0], _order(queue, [r["escalation_id"] for r in queue.rows])[6]):  # đóng một dòng đã thấy + một dòng chưa thấy
        await queue.close(CloseRequest(escalation_id=eid, close_result="confirmed_denial", closed_by="l2_01", close_note="x",
                                       close_reason="resolved_after_escalation", at=EPOCH))  # fmt: skip
    after = first["next_cursor"]
    while after:
        body = _get(env, f"?limit=4&after={after}").json()
        seen += [i["escalation_id"] for i in body["items"]]
        after = body["next_cursor"]
    still_open = [r["escalation_id"] for r in queue.rows if r["closed_at"] is None]
    assert len(seen) == len(set(seen)) and set(still_open) <= set(seen)


@pytest.mark.asyncio
async def test_closed_status_lists_closed_with_fields(env: AuthEnv, queue: MemoryEscalations) -> None:
    await _fill(queue)
    await queue.close(CloseRequest(escalation_id=1, close_result="completed", closed_by="l2_01", close_note="đã xử lý",
                                   close_reason="resolved_after_escalation", at=EPOCH + timedelta(hours=1)))  # fmt: skip
    closed = _get(env, "?status=closed").json()
    assert [i["ticket_id"] for i in closed["items"]] == ["a"]
    item = closed["items"][0]
    assert (item["close_result"], item["closed_by"], item["close_note"]) == ("completed", "l2_01", "đã xử lý")
    assert item["closed_at"] is not None
    assert "a" not in [i["ticket_id"] for i in _get(env).json()["items"]]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _cur(**over: Any) -> str:
    data: dict[str, Any] = {"v": 1, "s": "open", "p": 1, "t": EPOCH.isoformat(), "i": 1, **over}
    return _b64(json.dumps({k: v for k, v in data.items() if v is not ...}).encode())


BAD_CURSORS = {
    "rong": "", "ky-tu-la": "a+b/c", "padding": "eyJ2IjoxfQ==", "khong-base64": "@@@", "khong-json": _b64(b"khong-phai-json"),
    "mang": _b64(b"[1,2]"), "thieu-khoa": _cur(i=...), "thua-khoa": _cur(x=1), "v-2": _cur(v=2), "v-bool": _cur(v=True),
    "status-khac": _cur(s="closed"), "p-bool": _cur(p=True), "p-chuoi": _cur(p="1"), "p-am": _cur(p=-1), "i-0": _cur(i=0),
    "i-float": _cur(i=1.5), "t-ngay-tho": _cur(t="2026-10-01T03:00:00"), "t-sai": _cur(t="hom-qua"), "t-so": _cur(t=5),
    "qua-dai": "A" * 513,
}  # fmt: skip


@pytest.mark.parametrize("after", BAD_CURSORS.values(), ids=BAD_CURSORS.keys())
def test_bad_cursor_is_422_query_after(env: AuthEnv, after: str) -> None:
    r = _get(env, f"?after={after}")
    assert r.status_code == 422 and r.json() == {"error": "invalid_request", "fields": ["query.after"]}
    assert after == "" or after[:20] not in r.text  # không trả lại giá trị người gửi


@pytest.mark.asyncio
async def test_valid_handmade_cursor_accepted(env: AuthEnv, queue: MemoryEscalations) -> None:
    await _fill(queue)
    r = _get(env, f"?after={_cur(p=1, t=EPOCH.isoformat(), i=2)}")  # sau "b" (E7, id 2)
    assert r.status_code == 200 and [i["ticket_id"] for i in r.json()["items"]] == ["c", "d", "a"]
