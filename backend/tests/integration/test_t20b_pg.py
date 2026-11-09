"""T20b trên Postgres 16 thật (phase5 5.2.0, P3, P5, P7, P11–P13; 5.2.8 n1, n3, n4, p2, s*, h1 mức SQL; Q-T20b-3 = A). Viết TỪ ĐẶC TẢ
trước code (không mở `db/notices.py`, `notify/*`, thân `children_view`/`deliver_round`/`parents_to_wake`/`orphan_children`).

- `SqlTicketStore.create_child` / `mark_parent_once` / `children_view` / `deliver_round` / `children_progress_rows`.
- `ChildAwareNotifier.on_engine` trong transaction THẬT của `effects.once` (`SqlEffectStore` đặt `_TX`): con → `child_notices`
  (`effect_key` = khoá `side_effects`, UNIQUE — chạy lại không nhân đôi); ticket thường → notifier bên trong.
- `SqlDeadlineStore.set`: con → `child:skip`, 0 dòng; cha → thay hạn chưa bắn của CẢ HAI loại; thường → chỉ cùng loại; không đụng
  `approvals`.
- `parents_to_wake` / `orphan_children` (P12, chỉ đọc DB); `SqlPresetResolver` cho ticket con (P13).
Chỉ chạy ở verify/CI (testcontainers).
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.db.runtime import (
    CHILD_SKIP,
    OrphanChild,
    SqlDeadlineStore,
    SqlEffectStore,
    SqlTurnStore,
)
from app.db.tickets import SqlTicketStore
from app.domain.final import FinalSummary
from app.graph import effects
from app.graph.context import RunContext, bind_run
from app.llm.ports import TraceParent
from app.llm.providers.scripted import SqlPresetResolver
from app.notify.child import ChildAwareNotifier
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import MemoryAudit, MemorySpans, RecordingNotifier
from tests.integration.graph_pg import (
    APPROVER,
    REQUESTER,
    RecordingApprovals,
    create_ticket,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


async def _rows(rw: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with rw.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def _parent(rw: AsyncEngine, *, request: str | None = None) -> str:
    ticket = f"t20b-{uuid4().hex[:10]}"
    await create_ticket(rw, ticket, created_at=NOW)
    if request is not None:
        async with rw.begin() as conn:
            await conn.execute(text("UPDATE tickets SET redacted_request=:r WHERE ticket_id=:t"), {"r": request, "t": ticket})
    return ticket


async def _children(rw: AsyncEngine, parent: str, n: int, *, started: bool = True) -> list[str]:
    store = SqlTicketStore(rw)
    out = []
    for i in range(1, n + 1):
        cid = f"{parent}-{i}"
        await store.create_child(cid, parent_id=parent, redacted_request=f"ý {i}", created_at=NOW, intents=n, intent_type="vpn")
        if started:  # như `ChildOps.start_missing`: lượt `submit` của con + dòng `child_submit` của cha (Q-T20b-7 = A, P12 (a) vế 1)
            await _turn(rw, cid)
            async with rw.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO side_effects (effect_key, ticket_id, kind, step, turn_id, result_ref) "
                    "VALUES (:k, :p, 'child_submit', 'B5', 'turn-cha', :r)"
                ), {"k": uuid4().hex + uuid4().hex, "p": parent, "r": f"started:{cid}"})  # fmt: skip
        out.append(cid)
    await store.mark_parent_once(parent)
    return out


async def _turn(rw: AsyncEngine, ticket: str) -> str:
    turn = f"{ticket}-{uuid4().hex[:6]}"
    await SqlTurnStore(rw).start(turn_id=turn, ticket_id=ticket, session_id=None, event_type="submit", at=NOW)
    return turn


@contextmanager
def _run(rw: AsyncEngine, turn_id: str) -> Iterator[RunContext]:
    with bind_run(RunContext(turn_id=turn_id, trace_id="0" * 32, audit=MemoryAudit(), effects=SqlEffectStore(rw),
                             spans=MemorySpans(), clock=FakeClock(NOW), txlog=MemoryTxLog())) as run:  # fmt: skip
        yield run


async def _notice(
    rw: AsyncEngine, child: str, step: str, needs: str, body: str = "thân", *, inner: RecordingNotifier | None = None
) -> str | None:
    notifier = ChildAwareNotifier.on_engine(rw, inner or RecordingNotifier())
    turn = await _turn(rw, child)
    with _run(rw, turn):
        return await effects.once({"ticket_id": child, "reasoning_loops": 1}, "notify_user", notifier.notify_user, child, body,
                                  needs, step=step)  # fmt: skip


def _final(state: str = "S_RESOLVED", *, parent: bool = False) -> FinalSummary:
    """Dòng kết quả hợp CHECK (khuôn `test_b20_pg`): con RESOLVED `auto`, con ESCALATED E1 `escalated`; cha không `exit_code`/
    `close_reason`/`resolution_path`, có `aggregate_status` (D-30)."""
    if parent:
        return FinalSummary(state, None, None, None, None, "ALL_ESCALATED", False, None, None, 1, 10, NOW)
    if state == "S_RESOLVED":
        return FinalSummary(state, None, None, "resolved_user_confirmed", "auto", None, False, "account", None, 1, 10, NOW)
    return FinalSummary(state, "E1", None, None, "escalated", None, False, None, None, 1, 10, NOW)


# ---- P3: create_child / mark_parent_once ----------------------------------------------------------------------------------------


async def test_create_child_copies_parent_no_turn_pk(rw: AsyncEngine) -> None:
    """P3 (TQ-6): dòng `tickets` con chép người gửi/vai trò/phiên từ cha, `parent_ticket_id`, `redacted_request` = span; KHÔNG dòng
    `turns`; trùng khoá → lỗi (một con một dòng — D-18 dựa vào `effects.once`)."""
    store = SqlTicketStore(rw)
    parent = await _parent(rw)
    cid = f"{parent}-1"
    ref = await store.create_child(
        cid, parent_id=parent, redacted_request="đặt lại mật khẩu", created_at=NOW, intents=2, intent_type="account"
    )
    assert ref == f"{cid}|2|account"  # Q-T20b-12: `result_ref` của `child_create`
    row, prow = await store.get(cid), await store.get(parent)
    assert row is not None and prow is not None
    assert (row.parent_ticket_id, row.requester_id, row.session_id, row.redacted_request, row.is_parent) == (
        parent, REQUESTER, prow.session_id, "đặt lại mật khẩu", False)  # fmt: skip
    assert await scalar(rw, "SELECT requester_role FROM tickets WHERE ticket_id=:t", t=cid) == "employee"
    assert await scalar(rw, "SELECT count(*) FROM turns WHERE ticket_id=:t", t=cid) == 0
    with pytest.raises((IntegrityError, ValueError)):
        await store.create_child(cid, parent_id=parent, redacted_request="x", created_at=NOW, intents=2, intent_type="account")


async def test_mark_parent_once_idempotent(rw: AsyncEngine) -> None:
    """P3: `is_parent=true` chỉ khi đang false — True lần đầu, False lần sau."""
    store = SqlTicketStore(rw)
    parent = await _parent(rw)
    assert await store.mark_parent_once(parent) is True
    assert await store.mark_parent_once(parent) is False
    assert await scalar(rw, "SELECT is_parent FROM tickets WHERE ticket_id=:t", t=parent) is True


# ---- P5 (a): notifier trong transaction effects.once — n1, n3 mức SQL --------------------------------------------------------------


async def test_n1_n3_child_notice_same_tx_effect_key_unique(rw: AsyncEngine) -> None:
    """n1: con → 1 dòng `child_notices` (`kind`/`needs`/`source_step`/`body`, `effect_key` = khoá dòng `side_effects`), `notice:<id>`;
    notifier bên trong không nhận. n3: chạy lại cùng khoá → cùng ref, không dòng thứ hai."""
    parent = await _parent(rw)
    [c1] = await _children(rw, parent, 1)
    inner = RecordingNotifier()
    notifier = ChildAwareNotifier.on_engine(rw, inner)
    turn = await _turn(rw, c1)
    state = {"ticket_id": c1, "reasoning_loops": 1}
    with _run(rw, turn):
        r1 = await effects.once(state, "notify_user", notifier.notify_user, c1, "Đã đặt lại", "confirm", step="B18")
        r2 = await effects.once(state, "notify_user", notifier.notify_user, c1, "Đã đặt lại", "confirm", step="B18")
    rows = await _rows(rw, "SELECT notice_id, parent_ticket_id, source_step, kind, needs, body, effect_key, delivered_round "
                           "FROM child_notices WHERE child_ticket_id=:c", c=c1)  # fmt: skip
    assert len(rows) == 1
    nid, p, step, kind, needs, body, key, rnd = rows[0]
    assert r1 == r2 == f"notice:{nid}"
    assert (p, step, kind, needs, body, rnd) == (parent, "B18", "result", "confirm", "Đã đặt lại", None)
    assert key == await scalar(rw, "SELECT effect_key FROM side_effects WHERE ticket_id=:t AND kind='notify_user'", t=c1)
    assert inner.sent == []


async def test_n1_normal_ticket_goes_to_inner_notifier(rw: AsyncEngine) -> None:
    """n1: ticket thường → notifier bên trong như cũ; 0 dòng `child_notices`."""
    ticket = await _parent(rw)
    inner = RecordingNotifier()
    ref = await _notice(rw, ticket, "B18", "confirm", "Đã xong", inner=inner)
    assert ref == "m1" and inner.sent == [(ticket, "Đã xong", "confirm")]
    assert await scalar(rw, "SELECT count(*) FROM child_notices WHERE child_ticket_id=:t", t=ticket) == 0


# ---- P7: children_view / deliver_round / children_progress_rows -------------------------------------------------------------------


async def test_children_view_deliver_round_only_given_ids_once(rw: AsyncEngine) -> None:
    """P7 (D-17): `children_view` theo thứ tự `children` — `final_state` + notice CHƯA gửi; `deliver_round` đánh dấu đúng các id
    (của cha, còn chưa gửi) — lần sau với vòng khác không đánh dấu lại (M-T20b-7)."""
    store = SqlTicketStore(rw)
    parent = await _parent(rw)
    c1, c2, c3 = await _children(rw, parent, 3)
    await _notice(rw, c1, "B18", "confirm", "Đã đặt lại")
    await _notice(rw, c2, "B11", "answer", "Máy nào?")
    await store.finalize_once(c3, _final("S_ESCALATED"))
    async with rw.begin() as conn:  # B20 của con xong → lượt đóng (`children_view`: kết thúc = `final_state` VÀ không lượt mở — NGHI lượt 2)
        await conn.execute(text("UPDATE turns SET ended_at = now() WHERE ticket_id = :t"), {"t": c3})
    view = await store.children_view(parent, [c1, c2, c3])
    assert [(v.child_id, v.index, v.final_state, [(n.kind, n.needs, n.body) for n in v.pending]) for v in view] == [
        (c1, 1, None, [("result", "confirm", "Đã đặt lại")]), (c2, 2, None, [("question", "answer", "Máy nào?")]),
        (c3, 3, "S_ESCALATED", []),
    ]  # fmt: skip
    first = view[0].pending[0].notice_id
    await store.deliver_round(parent, 1, [first], NOW + timedelta(minutes=1))
    await store.deliver_round(parent, 2, [first], NOW + timedelta(minutes=2))
    [(rnd, at)] = await _rows(rw, "SELECT delivered_round, delivered_at FROM child_notices WHERE notice_id=:n", n=first)
    assert rnd == 1 and at == NOW + timedelta(minutes=1)
    after = await store.children_view(parent, [c1, c2, c3])
    assert [len(v.pending) for v in after] == [0, 1, 0]


async def test_children_progress_rows(rw: AsyncEngine) -> None:
    """P11: mỗi con theo thứ tự — `final_state`, có phiếu `pending`, có notice chưa gửi `needs≠none`."""
    store = SqlTicketStore(rw)
    parent = await _parent(rw)
    c1, c2, c3, c4 = await _children(rw, parent, 4)
    await store.finalize_once(c1, _final())
    await RecordingApprovals(rw).create(c2, APPROVER, NOW + timedelta(hours=24), "a" * 64, backup_approver_id=None,
                                        conflict_detected=False, conflict_type=None)  # fmt: skip
    await _notice(rw, c3, "B18", "confirm")
    await _notice(rw, c4, "B16", "none")
    rows = await store.children_progress_rows(parent, [c1, c2, c3, c4])
    assert [(r.child_id, r.final_state, r.pending_approval, r.ready) for r in rows] == [
        (c1, "S_RESOLVED", False, False), (c2, None, True, False), (c3, None, False, True), (c4, None, False, False),
    ]  # fmt: skip


# ---- P5 (b) + Q-T20b-3: SqlDeadlineStore.set ------------------------------------------------------------------------------------


async def _unfired(rw: AsyncEngine, ticket: str) -> list[str]:
    return sorted(r[0] for r in await _rows(rw, "SELECT kind FROM wait_deadlines WHERE ticket_id=:t AND fired_at IS NULL",
                                            t=ticket))  # fmt: skip


async def test_n4_deadline_child_skip_parent_replaces_both_kinds_normal_same_kind(rw: AsyncEngine) -> None:
    """n4 (M-T20b-6): con → `child:skip`, 0 dòng `wait_deadlines`. Q-T20b-3 = A: cha vòng 1 `clarify` → vòng 2 `confirm` → chỉ hạn
    vòng 2 chưa bắn; ticket thường → chỉ thay CÙNG loại (như cũ); không đụng phiếu duyệt."""
    dl = SqlDeadlineStore(rw)
    parent = await _parent(rw)
    [child] = await _children(rw, parent, 1)
    t_child = await _turn(rw, child)
    assert await dl.set(child, "confirm", NOW + timedelta(hours=48), t_child) == CHILD_SKIP
    assert await scalar(rw, "SELECT count(*) FROM wait_deadlines WHERE ticket_id=:t", t=child) == 0
    approval = await RecordingApprovals(rw).create(parent, APPROVER, NOW + timedelta(hours=24), "b" * 64,
                                                   backup_approver_id=None, conflict_detected=False,
                                                   conflict_type=None)  # fmt: skip
    r1, r2 = await _turn(rw, parent), await _turn(rw, parent)
    assert await dl.set(parent, "clarify", NOW + timedelta(hours=24), r1) == r1
    assert await dl.set(parent, "confirm", NOW + timedelta(hours=48), r2) == r2
    assert await _unfired(rw, parent) == ["confirm"]
    assert await scalar(rw, "SELECT status FROM approvals WHERE approval_id=:a", a=int(approval)) == "pending"
    normal = await _parent(rw)
    n1, n2, n3 = await _turn(rw, normal), await _turn(rw, normal), await _turn(rw, normal)
    await dl.set(normal, "clarify", NOW + timedelta(hours=24), n1)
    await dl.set(normal, "confirm", NOW + timedelta(hours=48), n2)
    assert await _unfired(rw, normal) == ["clarify", "confirm"]
    await dl.set(normal, "clarify", NOW + timedelta(hours=30), n3)
    assert await _unfired(rw, normal) == ["clarify", "confirm"]
    assert await scalar(rw, "SELECT count(*) FROM wait_deadlines WHERE ticket_id=:t AND kind='clarify'", t=normal) == 2


# ---- P12: parents_to_wake / orphan_children -------------------------------------------------------------------------------------


async def test_s_parents_to_wake_and_orphan_children(rw: AsyncEngine) -> None:
    """P12 (a) (Q-T20b-7 = A + NGHI-2): cha `final_state IS NULL` mà mọi con đã dừng theo DB (final VÀ không lượt mở, hoặc notice chưa gửi
    `needs≠none`) HOẶC số `child_submit` của cha < số con → chọn; con chờ duyệt (không notice) → không. (b): cha đã kết thúc, con chưa kết thúc có notice chưa gửi `needs≠none`
    → `OrphanChild(con, needs mới nhất)`."""
    store, dl = SqlTicketStore(rw), SqlDeadlineStore(rw)
    stopped = await _parent(rw)
    s1, s2 = await _children(rw, stopped, 2)
    await store.finalize_once(s1, _final())
    async with rw.begin() as conn:  # B20 của con xong → lượt đóng (P12 (a) vế 2: `final_state` VÀ không lượt mở)
        await conn.execute(text("UPDATE turns SET ended_at = now() WHERE ticket_id = :t"), {"t": s1})
    await _notice(rw, s2, "B18", "confirm")
    unstarted = await _parent(rw)
    await _children(rw, unstarted, 1, started=False)
    busy = await _parent(rw)
    b1, _b2 = await _children(rw, busy, 2)
    await _notice(rw, b1, "B18", "confirm")  # b2 đang chờ duyệt: chưa dừng
    closed = await _parent(rw)
    o1, o2, o3 = await _children(rw, closed, 3)
    await _notice(rw, o1, "B11", "answer")
    await _notice(rw, o2, "B18", "confirm")
    await store.finalize_once(o2, _final())
    await _notice(rw, o3, "B20", "none")
    await store.finalize_once(closed, _final("S_ESCALATED", parent=True))
    woken = set(await dl.parents_to_wake(1000))
    assert {stopped, unstarted} <= woken and busy not in woken and closed not in woken
    later = datetime.now(UTC) + timedelta(hours=24, minutes=1)  # Q-T20b-9 (ii): chỉ khi đã quá hạn thường (o1: notice chưa gửi → created_at)
    orphans = [o for o in await dl.orphan_children(later, 1000, clarify_hours=24, confirm_hours=48)
               if o.ticket_id in (o1, o2, o3, b1, s2)]  # fmt: skip
    assert orphans == [OrphanChild(o1, "answer")]


# ---- D-77 (Q6): con chờ duyệt là điểm dừng — children_view.awaiting_approval + parents_to_wake theo round_ready ------------------


async def _close_turns(rw: AsyncEngine, ticket: str) -> None:
    async with rw.begin() as conn:
        await conn.execute(text("UPDATE turns SET ended_at = now() WHERE ticket_id = :t AND ended_at IS NULL"), {"t": ticket})


async def _pending_approval(rw: AsyncEngine, child: str) -> None:
    await RecordingApprovals(rw).create(child, APPROVER, NOW + timedelta(minutes=30), "c" * 64, backup_approver_id=None,
                                        conflict_detected=False, conflict_type=None)  # fmt: skip


async def test_q6_children_view_awaiting_approval_and_parents_to_wake(rw: AsyncEngine) -> None:
    """D-77: `awaiting_approval` = phiếu `pending` VÀ không còn lượt mở (B15 đang chạy → chưa). `parents_to_wake` vế 2 = `round_ready`:
    con chờ duyệt + con có câu hỏi chưa gửi → chọn; hai con chờ duyệt mà notice đã gửi hết → KHÔNG chọn (không đánh thức mỗi 60 s); có
    notice mới chưa gửi → chọn lại."""
    store, dl = SqlTicketStore(rw), SqlDeadlineStore(rw)
    asked = await _parent(rw)
    a1, a2 = await _children(rw, asked, 2)
    await _pending_approval(rw, a1)
    await _notice(rw, a1, "B15", "none")
    view = await store.children_view(asked, [a1, a2])
    assert [v.awaiting_approval for v in view] == [False, False]  # a1 còn lượt mở (B15 chưa xong)
    assert asked not in set(await dl.parents_to_wake(1000))
    await _close_turns(rw, a1)
    await _notice(rw, a2, "B11", "answer")
    view = await store.children_view(asked, [a1, a2])
    assert [v.awaiting_approval for v in view] == [True, False]
    assert asked in set(await dl.parents_to_wake(1000))

    quiet = await _parent(rw)
    q1, q2 = await _children(rw, quiet, 2)
    ids = []
    for c in (q1, q2):
        await _pending_approval(rw, c)
        ref = await _notice(rw, c, "B15", "none")
        assert ref is not None
        ids.append(int(ref.removeprefix("notice:")))
        await _close_turns(rw, c)
    assert quiet in set(await dl.parents_to_wake(1000))  # vòng 1 chưa gửi
    await store.deliver_round(quiet, 1, ids, NOW + timedelta(minutes=1))
    assert quiet not in set(await dl.parents_to_wake(1000))  # đã báo, chỉ còn chờ duyệt → không đánh thức
    await store.finalize_once(q2, _final())
    await _notice(rw, q2, "B20", "none")
    await _close_turns(rw, q2)
    assert quiet in set(await dl.parents_to_wake(1000))  # notice mới của q2 → vòng 2


# ---- P13: SqlPresetResolver cho ticket con --------------------------------------------------------------------------------------


async def test_h1_sql_preset_resolver_child_uses_parent_tag_plus_index(rw: AsyncEngine) -> None:
    """h1 (P13): lượt của ticket con (không thẻ) → `<thẻ cha>-<i>`; lượt của cha → thẻ cha; cha không thẻ → None (`default`)."""
    parent = await _parent(rw, request="đặt lại mật khẩu, cài Adobe [fake:tc34]")
    _, c2 = await _children(rw, parent, 2, started=False)
    resolver = SqlPresetResolver(rw)

    def trace(turn: str) -> TraceParent:
        return TraceParent(turn_id=turn, trace_id="0" * 32, parent_span_id=None)

    assert await resolver.tag_for(trace(await _turn(rw, c2))) == "tc34-2"
    assert await resolver.tag_for(trace(await _turn(rw, parent))) == "tc34"
    plain = await _parent(rw)
    [p1] = await _children(rw, plain, 1, started=False)
    assert await resolver.tag_for(trace(await _turn(rw, p1))) is None
