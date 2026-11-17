"""SQL của `GET /api/me/notifications` trên Postgres 16 thật (db/notifications.py `SqlNotificationSource`) + cả route.

- Lọc requester TRONG SQL: nhân viên A không bao giờ thấy dòng của B — kể cả qua con trỏ của B và qua `LIMIT` nhỏ.
- Nhánh phiếu duyệt: chỉ `approved`/`rejected` (không `pending`/`timeout`/`late_ignored`), `created_at` = `decided_at`.
- Nhánh ca L2: chỉ ca đã đóng (`closed_at` + `close_result`), `created_at` = `closed_at`; ticket CON trả `ticket_id` của CHA.
- Keyset `(created_at, id COLLATE "C")`: nhiều dòng TRÙNG `created_at` (appr:9 đứng SAU appr:10 theo byte), > 2 trang, không trùng/sót.
- Cả route với nguồn SQL thật: JSON đúng hợp đồng, 422, text trung tính cho E0 / E1 injection_suspected.

Một database riêng cho cả module (seed bằng engine đồng bộ, đọc bằng engine async của `app_rw`).
"""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.api import notifications as api
from app.db.notifications import Cursor, SqlNotificationSource, decode_cursor
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit.auth_helpers import AuthEnv, auth_env

T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
A, B, L1, L2 = "nv001", "nv002", "l1_01", "l2_01"  # nv001 = an.nv, nv002 = binh.tt của auth_env
URL = "/api/me/notifications"


def _at(m: int) -> datetime:
    return T0 + timedelta(minutes=m)


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest.fixture(scope="module")
def seeded(db: PgUrls) -> PgUrls:
    sync: Engine = create_engine(db.role("app_rw"))
    with sync.begin() as c:
        c.execute(text(
            "INSERT INTO users (user_id, username, role) VALUES (:a,'an.nv','employee'), (:b,'binh.tt','employee'), "
            "(:l1,'ha.lt','l1'), (:l2,'long.nh','l2')"), {"a": A, "b": B, "l1": L1, "l2": L2})  # fmt: skip
        for tid, who, parent, is_parent in (
            ("T-A1", A, None, False), ("T-A2", A, None, False), ("P-A", A, None, True), ("C-A1", A, "P-A", False),
            ("T-B1", B, None, False),
        ):  # fmt: skip
            c.execute(text(
                "INSERT INTO tickets (ticket_id, parent_ticket_id, requester_id, requester_role, redacted_request, is_parent, created_at) "
                "VALUES (:t, :p, :u, 'employee', 'yêu cầu thử', :ip, :c)"),
                {"t": tid, "p": parent, "u": who, "ip": is_parent, "c": T0})  # fmt: skip
        # phiếu duyệt
        def approval(ticket: str, status: str, decided: datetime | None, note: str | None = None, n: int = 0) -> None:
            c.execute(text(
                "INSERT INTO approvals (ticket_id, approver_id, deadline, action_plan_hash, status, note, decided_by, decided_at) "
                "VALUES (:t, :ap, :d, :h, :s, :n, :db, :da)"),
                {"t": ticket, "ap": L1, "d": T0 + timedelta(hours=1), "h": "h" * 64, "s": status, "n": note,
                 "db": L1 if decided else None, "da": decided})  # fmt: skip

        approval("T-A1", "approved", _at(10))
        approval("C-A1", "rejected", _at(20), note="Thiếu thông tin máy")
        approval("T-A2", "timeout", _at(30))  # không phải quyết định của người duyệt → không thông báo
        approval("T-A2", "late_ignored", _at(31))
        approval("T-A2", "pending", None)  # chưa quyết
        approval("T-B1", "approved", _at(40))
        approval("T-B1", "rejected", _at(41), note="của B")
        # ca L2 (exit_code_priority được migration seed)
        def escalation(ticket: str, code: str, detail: str | None, result: str | None, closed: datetime | None) -> None:
            c.execute(text(
                "INSERT INTO escalations (ticket_id, exit_code, priority, reason_detail, handoff_note, close_result, closed_by, closed_at) "
                "VALUES (:t, :c, 1, :d, CAST(:hn AS jsonb), :r, :cb, :ca)"),
                {"t": ticket, "c": code, "d": detail, "hn": json.dumps({}), "r": result, "cb": L2 if closed else None, "ca": closed})  # fmt: skip

        escalation("T-A1", "E3", "no_grounding", "completed", _at(15))
        escalation("T-A2", "E0", None, "confirmed_denial", _at(25))
        escalation("T-A2", "E1", "injection_suspected", "reopened_as_new", _at(26))
        escalation("T-A2", "E1", "out_of_scope", "reopened_as_new", _at(27))
        escalation("T-A2", "E5", "llm_high_risk", None, None)  # còn mở
        escalation("T-A2", "E3", "no_grounding", None, _at(28))  # dữ liệu lạ: có closed_at mà close_result NULL → không trả ra
        escalation("T-B1", "E3", "no_grounding", "completed", _at(45))
        # nhiều dòng TRÙNG created_at → id 'appr:<n>' có cả số 1 chữ số lẫn 2 chữ số
        for _ in range(12):
            approval("T-A1", "approved", _at(100))
    sync.dispose()
    return db


@pytest_asyncio.fixture
async def source(seeded: PgUrls) -> AsyncIterator[SqlNotificationSource]:
    engine: AsyncEngine = create_async_engine(seeded.role("app_rw"))
    yield SqlNotificationSource(engine)
    await engine.dispose()


async def _all(source: SqlNotificationSource, user: str, per_page: int) -> tuple[list[str], int]:
    """Đi hết các trang như route (limit+1): trả (id theo thứ tự, số trang)."""
    ids, after, pages = [], None, 0
    while True:
        rows = await source.page(user, per_page + 1, after)
        page = rows[:per_page]
        ids += [r.id for r in page]
        pages += 1
        if len(rows) <= per_page:
            return ids, pages
        after = Cursor(page[-1].created_at, page[-1].id)
        assert pages < 50


@pytest.mark.asyncio
async def test_requester_isolation_in_sql_even_with_tiny_limit_and_foreign_cursor(source: SqlNotificationSource) -> None:
    a_ids, _ = await _all(source, A, 1)
    b_ids, _ = await _all(source, B, 1)
    assert not set(a_ids) & set(b_ids) and len(a_ids) == len(set(a_ids))
    assert len(b_ids) == 3 and all(r.ticket_id == "T-B1" for r in await source.page(B, 50, None))
    # con trỏ ĐẶT TRƯỚC mọi dòng của B nhưng sau dòng của A: A vẫn chỉ thấy của A
    rows = await source.page(A, 50, Cursor(_at(50), "esc:99"))
    assert rows and all(r.ticket_id in {"T-A1", "T-A2", "P-A"} for r in rows)
    assert await source.page("nguoi-la", 50, None) == []


@pytest.mark.asyncio
async def test_sources_filters_and_created_at(source: SqlNotificationSource) -> None:
    rows = {r.id: r for r in await source.page(A, 100, None)}
    kinds = {r.kind for r in rows.values()}
    assert kinds == {"approval_decided", "escalation_closed"}
    by_note = {r.note: r for r in rows.values() if r.note}
    rejected = by_note["Thiếu thông tin máy"]
    assert (rejected.result, rejected.ticket_id, rejected.created_at) == ("rejected", "P-A", _at(20))  # con → id của CHA
    assert {r.result for r in rows.values() if r.kind == "approval_decided"} == {"approved", "rejected"}
    escs = [r for r in rows.values() if r.kind == "escalation_closed"]
    assert sorted(r.created_at for r in escs) == [_at(15), _at(25), _at(26), _at(27)]  # ca còn mở / close_result NULL không có
    assert {(r.exit_code, r.reason_detail, r.result) for r in escs} == {
        ("E3", "no_grounding", "completed"), ("E0", None, "confirmed_denial"),
        ("E1", "injection_suspected", "reopened_as_new"), ("E1", "out_of_scope", "reopened_as_new"),
    }  # fmt: skip
    assert len(rows) == 2 + 12 + 4  # 2 phiếu (T-A1 _at(10), C-A1) + 12 trùng giờ + 4 ca đóng
    assert all(r.created_at.tzinfo is not None for r in rows.values())


@pytest.mark.asyncio
async def test_keyset_over_ties_c_collation_no_dup_no_gap(source: SqlNotificationSource) -> None:
    full = await source.page(A, 100, None)
    ids = [r.id for r in full]
    assert [(r.created_at, r.id) for r in full] == sorted(((r.created_at, r.id) for r in full), reverse=True)
    ties = [r.id for r in full if r.created_at == _at(100)]
    assert len(ties) == 12 and ties == sorted(ties, reverse=True)  # theo byte: 'appr:9' > 'appr:10'
    for per_page in (1, 2, 5, 7):
        got, pages = await _all(source, A, per_page)
        assert got == ids and len(set(got)) == len(got)
        assert pages == -(-len(ids) // per_page)
    assert (await _all(source, A, 5))[1] > 2


@pytest.mark.asyncio
async def test_cursor_boundary_is_exclusive(source: SqlNotificationSource) -> None:
    full = await source.page(A, 100, None)
    after = Cursor(full[3].created_at, full[3].id)
    assert [r.id for r in await source.page(A, 100, after)] == [r.id for r in full[4:]]
    assert await source.page(A, 100, Cursor(full[-1].created_at, full[-1].id)) == []


# ---- cả route với nguồn SQL thật ---------------------------------------------------------------------------------------


class PerCallSql:
    """Engine async dựng TRONG vòng lặp của app (TestClient chạy app ở luồng riêng)."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def page(self, user_id: str, limit: int, after: Cursor | None) -> Any:
        engine = create_async_engine(self._url)
        try:
            return await SqlNotificationSource(engine).page(user_id, limit, after)
        finally:
            await engine.dispose()


@pytest.fixture
def env(seeded: PgUrls) -> Iterator[AuthEnv]:
    with auth_env() as e:
        e.app.state.notifications = PerCallSql(seeded.role("app_rw"))
        yield e


KIND_CONTRACT = {
    "approval_decided": ("appr:", {"approved", "rejected"}),
    "escalation_closed": ("esc:", {"completed", "confirmed_denial", "reopened_as_new"}),
}


@pytest.mark.asyncio
async def test_every_row_kind_result_and_id_prefix_agree_and_odd_data_excluded(source: SqlNotificationSource) -> None:
    """Quét MỌI dòng của mọi người dùng: kind ↔ tiền tố id ↔ result hợp lệ. Phiếu `timeout`/`late_ignored`/`pending` và ca L2 còn mở hoặc
    có `closed_at` mà `close_result` NULL không bao giờ ra (dòng lạ ở mốc `_at(28)` không có trong kết quả)."""
    for user in (A, B):
        rows = await source.page(user, 200, None)
        assert rows
        for r in rows:
            prefix, results = KIND_CONTRACT[r.kind]
            assert r.id.startswith(prefix) and r.result in results, r
        assert _at(28) not in {r.created_at for r in rows}
    assert {r.result for r in await source.page(A, 200, None)} == {"approved", "rejected", "completed", "confirmed_denial", "reopened_as_new"}


def _get(env: AuthEnv, user: str, query: str = "") -> Any:
    return env.client.get(URL + query, headers=env.bearer(env.token(user)))


def test_route_real_sql_json_contract_and_isolation(env: AuthEnv) -> None:
    r = _get(env, "an.nv", "?limit=50")
    assert r.status_code == 200
    body = r.json()
    assert body["next_cursor"] is None and len(body["items"]) == 18
    for i in body["items"]:
        assert set(i) == {"id", "kind", "ticket_id", "text", "result", "new_ticket_id", "created_at"}
        assert i["new_ticket_id"] is None and i["ticket_id"] in {"T-A1", "T-A2", "P-A"}
        assert datetime.fromisoformat(i["created_at"]).utcoffset() == timedelta(0)
    texts = {i["id"]: i for i in body["items"]}
    rejected = next(i for i in body["items"] if i["result"] == "rejected")
    assert rejected["text"] == "Yêu cầu của bạn chưa được duyệt. Ghi chú của người duyệt: Thiếu thông tin máy"
    assert rejected["ticket_id"] == "P-A"
    closed = [i for i in body["items"] if i["kind"] == "escalation_closed"]
    assert all(i["text"] == api.CLOSED_TEXT[i["result"]] for i in closed)  # D-98: mọi mã (cả E0 / E1 nghi) câu theo kết quả
    # E0 (confirmed_denial) + E1 injection_suspected (reopened_as_new) + E1 out_of_scope (reopened_as_new)
    assert sum(1 for i in texts.values() if i["text"] == api.CLOSED_TEXT["reopened_as_new"]) == 2
    assert "của B" not in r.text
    other = _get(env, "binh.tt", "?limit=50").json()
    assert {i["ticket_id"] for i in other["items"]} == {"T-B1"} and len(other["items"]) == 3


def test_route_real_sql_paginates_over_three_pages(env: AuthEnv) -> None:
    seen, after, pages = [], None, 0
    while True:
        body = _get(env, "an.nv", "?limit=7" + (f"&after={after}" if after else "")).json()
        seen += [i["id"] for i in body["items"]]
        pages += 1
        after = body["next_cursor"]
        if after is None:
            break
        decode_cursor(after)
    assert pages == 3 and len(seen) == len(set(seen)) == 18


def test_route_real_sql_422_and_401(env: AuthEnv) -> None:
    assert _get(env, "an.nv", "?limit=0").json() == {"error": "invalid_request", "fields": ["query.limit"]}
    assert _get(env, "an.nv", "?after=zzz").json() == {"error": "invalid_request", "fields": ["query.after"]}
    assert env.client.get(URL).status_code == 401
