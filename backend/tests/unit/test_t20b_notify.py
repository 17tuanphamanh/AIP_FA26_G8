"""T20b — con không nhắn, không đặt hạn (phase5 P5, D-31; 5.2.8 n1–n4; Q-T20b-3 = A). Viết TỪ ĐẶC TẢ trước code.

- Unit `ChildAwareNotifier` (chữ ký khai ở S1 — không mở `notify/*`) trên `MemoryNoticeStore` + `bind_effect`: kind theo bước, `notice:<id>`,
  ticket thường/cha → notifier bên trong như cũ; bước lạ / ngoài `effects.once` → `ValueError`.
- n3: chạy lại `effects.once` cùng khoá → không nhân đôi notice.
- n4 SQL: `SqlDeadlineStore.set` với kết nối GIẢ gắn qua `_TX` (contextvar của `effects.once`) — con → `child:skip`, 0 câu ghi
  `wait_deadlines`; thường/cha → có INSERT. Không phụ thuộc thứ tự/số câu SELECT.
- n1/n4 trên graph (harness `_t20b`): notice của con có `effect_key` = khoá dòng `side_effects`; `h.notifier` không có dòng của con;
  con không có dòng `wait_deadlines`.
Mọi ca thuộc DỪNG 1 — không xfail.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.db.runtime import _TX, CHILD_SKIP, SqlDeadlineStore, bind_effect
from app.graph import effects
from app.graph.context import RunContext, bind_run
from app.notify.child import NOTICE_KIND_BY_STEP, ChildAwareNotifier, notice_kind
from sqlalchemy.exc import SQLAlchemyError
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import (
    MemoryAudit,
    MemoryEffects,
    MemoryNoticeStore,
    MemorySpans,
    MemoryTickets,
    MemoryTurns,
    RecordingNotifier,
)
from tests.unit._t20b import TC34, adobe_item, classify, make_flow, reset_item

T0 = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
CHO_DUNG2: frozenset[str] = frozenset()  # mọi ca thuộc DỪNG 1 — không xfail


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.originalname in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError), reason="T20b DỪNG 2"))


# bước → (kind, needs mà node gửi) — P5 (a) + 5.2.0 "Notifier"
STEPS = [
    pytest.param("B10", "answer", "confirm", id="B10-answer-confirm"),
    pytest.param("B11", "question", "answer", id="B11-question-answer"),
    pytest.param("B16", "rejection", "none", id="B16-rejection-none"),
    pytest.param("B18", "result", "confirm", id="B18-result-confirm"),
    pytest.param("B20", "escalation", "none", id="B20-escalation-none"),
]


def _env() -> tuple[ChildAwareNotifier, MemoryTickets, RecordingNotifier]:
    tickets = MemoryTickets(MemoryTurns())
    tickets.register("P", T0, is_parent=True)
    tickets.register("P-1", T0, parent_ticket_id="P")
    tickets.register("N", T0)
    inner = RecordingNotifier()
    return ChildAwareNotifier(MemoryNoticeStore(tickets, FakeClock(T0)), inner), tickets, inner


# ---- n1/n2: unit ChildAwareNotifier --------------------------------------------------------------------------------------------


def test_n2_notice_kind_by_step_table() -> None:
    """P5 (a): B10 → answer, B11 → question, B16 → rejection, B18 → result, B20 → escalation; bước khác → `ValueError` (E9)."""
    assert NOTICE_KIND_BY_STEP == {"B10": "answer", "B11": "question", "B16": "rejection", "B18": "result",
                                   "B20": "escalation"}  # fmt: skip
    assert [notice_kind(s) for s in ("B10", "B11", "B16", "B18", "B20")] == ["answer", "question", "rejection", "result",
                                                                             "escalation"]  # fmt: skip
    for bad in ("B15", "B17", "B19", "B5", ""):
        with pytest.raises(ValueError):
            notice_kind(bad)


@pytest.mark.asyncio
@pytest.mark.parametrize(("step", "kind", "needs"), STEPS)
async def test_n1_n2_child_notify_writes_notice_not_inner(step: str, kind: str, needs: str) -> None:
    """n1/n2: con → 1 dòng `child_notices` (`kind` theo bước, `needs`, `source_step`, `effect_key` = khoá `effects.once`, `body` = text)
    → trả `notice:<id>`; notifier bên trong KHÔNG nhận gì (M-T20b-5)."""
    n, tickets, inner = _env()
    with bind_effect(step, "khoa-1"):
        ref = await n.notify_user("P-1", "Thân tin của con", needs)
    [row] = tickets.notices
    assert ref == f"notice:{row['notice_id']}"
    cols = ("parent_ticket_id", "child_ticket_id", "source_step", "kind", "needs", "body", "effect_key")
    assert {k: row[k] for k in cols} == {
        "parent_ticket_id": "P", "child_ticket_id": "P-1", "source_step": step, "kind": kind, "needs": needs,
        "body": "Thân tin của con", "effect_key": "khoa-1",
    }  # fmt: skip
    assert row["delivered_round"] is None and row["delivered_at"] is None
    assert inner.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ticket", ["N", "P"], ids=["thuong", "cha"])
async def test_n1_normal_and_parent_ticket_use_inner_notifier(ticket: str) -> None:
    """n1: ticket thường / cha → notifier bên trong như cũ (`m<n>` của `RecordingNotifier`), không dòng notice."""
    n, tickets, inner = _env()
    with bind_effect("B18", "khoa-2"):
        ref = await n.notify_user(ticket, "Đã xong", "confirm")
    assert ref == "m1" and inner.sent == [(ticket, "Đã xong", "confirm")]
    assert tickets.notices == []


@pytest.mark.asyncio
async def test_n1_child_unknown_step_or_outside_once_value_error() -> None:
    """P5 (a): bước khác → `ValueError` (E9, thấy được); con gửi ngoài `effects.once` (không `current_effect()`) → `ValueError`."""
    n, tickets, inner = _env()
    with bind_effect("B15", "khoa-3"), pytest.raises(ValueError):
        await n.notify_user("P-1", "x", "none")
    with pytest.raises(ValueError):
        await n.notify_user("P-1", "x", "none")
    assert tickets.notices == [] and inner.sent == []


# ---- n3: chạy lại cùng khoá ----------------------------------------------------------------------------------------------------


@contextmanager
def _run(eff: MemoryEffects) -> Iterator[RunContext]:
    with bind_run(RunContext(turn_id="T1", trace_id="0" * 32, audit=MemoryAudit(), effects=eff, spans=MemorySpans(),
                             clock=FakeClock(T0), txlog=MemoryTxLog())) as run:  # fmt: skip
        yield run


@pytest.mark.asyncio
async def test_n3_rerun_same_effect_no_duplicate_notice() -> None:
    """n3: chạy lại node con cùng lượt → `effects.once` trả ref cũ; kể cả khi dòng `side_effects` mất (store mới) mà notice đã ghi,
    `effect_key` UNIQUE → không nhân đôi (lần 2 trả CÙNG id)."""
    n, tickets, _ = _env()
    state = {"ticket_id": "P-1", "reasoning_loops": 1}
    eff = MemoryEffects()
    with _run(eff):
        r1 = await effects.once(state, "notify_user", n.notify_user, "P-1", "Đã xong", "confirm", step="B18")
        r2 = await effects.once(state, "notify_user", n.notify_user, "P-1", "Đã xong", "confirm", step="B18")
    with _run(MemoryEffects()):
        r3 = await effects.once(state, "notify_user", n.notify_user, "P-1", "Đã xong", "confirm", step="B18")
    [row] = tickets.notices
    assert r1 == r2 == r3 == f"notice:{row['notice_id']}"
    [key] = eff.rows
    assert row["effect_key"] == key  # = khoá dòng `side_effects` (T20b TQ-2)


# ---- n4: SqlDeadlineStore.set với kết nối giả ----------------------------------------------------------------------------------


class _Result:
    def __init__(self, row: Any = None) -> None:
        self._row = row
        self.rowcount = 0

    def first(self) -> Any:
        return self._row

    def one_or_none(self) -> Any:
        return self._row

    def fetchone(self) -> Any:
        return self._row

    def scalar(self) -> Any:
        return None

    def scalar_one_or_none(self) -> Any:
        return None


def _sql(stmt: Any) -> str:
    try:
        return str(stmt)
    except SQLAlchemyError:  # câu đặc thù dialect không in được — vẫn nhận diện theo bảng
        table = getattr(stmt, "table", None)
        return f"{type(stmt).__name__} {getattr(table, 'name', '')}"


class FakeConn:
    """Ghi lại mọi câu lệnh; SELECT đọc bảng `tickets` → dòng có `parent_ticket_id`, `is_parent` (hoặc None)."""

    def __init__(self, row: Any) -> None:
        self.row = row
        self.stmts: list[str] = []

    async def execute(self, stmt: Any, params: Any = None) -> _Result:
        sql = _sql(stmt)
        self.stmts.append(sql)
        if sql.lstrip().upper().startswith("SELECT") and "tickets" in sql and "wait_deadlines" not in sql:
            return _Result(self.row)
        return _Result()

    def writes_to_waits(self) -> list[str]:
        return [s for s in self.stmts if "wait_deadlines" in s and not s.lstrip().upper().startswith("SELECT")]


async def _set_with(row: Any) -> tuple[str, FakeConn]:
    conn = FakeConn(row)
    store = SqlDeadlineStore(engine=None)  # type: ignore[arg-type]  # engine không được dùng khi có `_TX`
    token = _TX.set(conn)  # type: ignore[arg-type]
    try:
        ref = await store.set("X-1", "confirm", T0 + timedelta(hours=48), "turn-9")
    finally:
        _TX.reset(token)
    return ref, conn


@pytest.mark.asyncio
async def test_n4_sql_child_skip_no_wait_deadlines_write() -> None:
    """n4 (P5 (b), M-T20b-6): ticket CON → trả `child:skip`, KHÔNG câu INSERT/UPDATE nào vào `wait_deadlines`."""
    ref, conn = await _set_with(SimpleNamespace(parent_ticket_id="X", is_parent=False))
    assert ref == CHILD_SKIP == "child:skip"
    assert conn.writes_to_waits() == [], conn.stmts


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [SimpleNamespace(parent_ticket_id=None, is_parent=False),
                                 SimpleNamespace(parent_ticket_id=None, is_parent=True)], ids=["thuong", "cha"])  # fmt: skip
async def test_n4_sql_normal_and_parent_still_insert(row: Any) -> None:
    """n4: ticket thường / cha → như cũ: có INSERT `wait_deadlines`, trả `created_turn`."""
    ref, conn = await _set_with(row)
    assert ref == "turn-9"
    assert any(s.lstrip().upper().startswith("INSERT") for s in conn.writes_to_waits()), conn.stmts


# ---- n1/n4 trên graph ----------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n1_n4_graph_child_b18_notice_no_message_no_deadline() -> None:
    """n1 + n4 trên graph (TC34): con 1 qua B18 → 1 notice `result/confirm/B18`, `effect_key` = khoá dòng `side_effects`
    `notify_user` của con; `h.notifier` không có dòng của con; con không có dòng `wait_deadlines` (`deadline_set` → `child:skip`)."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    [nt] = f.h.tickets.notices_of("T1-1")
    assert (nt["kind"], nt["needs"], nt["source_step"], nt["parent_ticket_id"]) == ("result", "confirm", "B18", "T1")
    [(key, eff)] = [(k, r) for k, r in f.h.effects.rows.items() if r["ticket_id"] == "T1-1" and r["kind"] == "notify_user"]
    assert nt["effect_key"] == key and eff["result_ref"] == f"notice:{nt['notice_id']}"
    assert f.h.notifier.count("T1-1") == 0 and f.h.notifier.count("T1-2") == 0
    assert [w for w in f.h.deadlines.waits if w["ticket_id"] in ("T1-1", "T1-2")] == []
    [dl] = [r for r in f.h.effects.rows.values() if r["ticket_id"] == "T1-1" and r["kind"] == "deadline_set"]
    assert dl["result_ref"] == CHILD_SKIP
    # tin của con VẪN vào `conversation` của checkpoint con (nội bộ — P5 (c))
    assert [m["kind"] for m in (await f.values("T1-1"))["conversation"]] == ["result"]
