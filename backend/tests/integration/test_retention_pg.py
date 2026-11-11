"""M2 (bn-a, 08/11) — job hạn giữ trên Postgres 16 thật + `AsyncPostgresSaver` thật (test viết trước, DỪNG 1; TA chạy `make test`).

Hợp đồng (PLAN bn-a mục M2; P7 mục 4 [Chốt 17.2]):
- `db.retention.SqlRetentionStore(engine app_rw)`:
  - `expired_threads(cutoff, limit)`: ticket có checkpoint VÀ `final_state IS NOT NULL` VÀ `closed_at < cutoff` (chặt — đúng 90 ngày CÒN)
    VÀ không có escalation đang mở (`escalations.closed_at IS NULL` — L2 còn xử lý, cần hội thoại) VÀ không có lượt mở (`turns.ended_at IS
    NULL`) VÀ (không có cha HOẶC cha cũng đã kết thúc trước mốc) VÀ (là cha thì mọi con đã kết thúc); thứ tự `closed_at`, tối đa `limit`.
  - `purge_ticket_rows(ticket_id)`: xoá `side_effects` của ticket, `child_notices` có `parent_ticket_id` = ticket (P7 mục 4).
  - `count_expired_sessions(cutoff)` / `delete_expired_sessions(cutoff)`: `sessions.expires_at < cutoff` VÀ không dòng `tickets`/`turns` nào
    trỏ tới (ĐP chốt Q2). `count_fired_waits` / `delete_fired_waits`: `wait_deadlines.fired_at < cutoff` (ĐP chốt Q3).
  - `record_run(detail, at)`: đúng 1 dòng `security_events` loại `retention_run` (ĐP chốt Q5 — loại mới ở migration 0016 — dời từ 0015; tới lúc đó 1
    dòng log — ca kiểm dòng sự kiện gắn cờ chờ 0016).
- KHÔNG đụng `audit_logs` (append-only: REVOKE + trigger) — số dòng không đổi; `tickets` còn nguyên (FK của audit).
Database riêng cho module (`audit_logs`/`security_events` append-only không dọn được giữa các test).
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.core.clock import FakeClock
from app.graph.checkpoint import open_postgres_saver
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import REQUESTER, scalar, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=90)


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


@pytest_asyncio.fixture
async def saver(db: PgUrls) -> AsyncIterator[AsyncPostgresSaver]:
    async with open_postgres_saver(db.role("app_rw"), max_size=2) as s:
        yield s


def _id(tag: str) -> str:
    return f"rt-{tag}-{uuid4().hex[:6]}"


async def _ticket(rw: AsyncEngine, tag: str, *, closed_days: float | None, final: str | None = "S_RESOLVED",
                  parent: str | None = None, is_parent: bool = False, session: str | None = None) -> str:  # fmt: skip
    tid = _id(tag)
    closed = NOW - timedelta(days=closed_days) if closed_days is not None else None
    async with rw.begin() as conn:
        await conn.execute(text(
            "INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, created_at, final_state, closed_at, "
            "parent_ticket_id, is_parent, session_id) VALUES (:t, :u, 'employee', 'yêu cầu đã che', :c, :f, :cl, :p, :ip, :s)"
        ), {"t": tid, "u": REQUESTER, "c": NOW - timedelta(days=400), "f": final if closed is not None else None, "cl": closed,
            "p": parent, "ip": is_parent, "s": session})  # fmt: skip
    return tid


async def _checkpoint(saver: AsyncPostgresSaver, thread_id: str) -> None:
    cfg: Any = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    await saver.aput(cfg, empty_checkpoint(), {}, {})


async def _cp_rows(rw: AsyncEngine, thread_id: str) -> int:
    return int(await scalar(rw, "SELECT count(*) FROM checkpoints WHERE thread_id = :t", t=thread_id))


def _store(rw: AsyncEngine) -> Any:
    from app.db.retention import SqlRetentionStore

    return SqlRetentionStore(rw)


def _job(rw: AsyncEngine, saver: AsyncPostgresSaver, *, dry_run: bool, batch: int = 500) -> Any:
    from app.graph.retention import RetentionJob
    from app.settings import RetentionConfig

    cfg = RetentionConfig(retention_days=90, session_grace_days=30, wait_grace_days=7, dry_run=dry_run, batch=batch)
    return RetentionJob(_store(rw), saver, FakeClock(NOW), cfg)


# ---- chọn ticket hết hạn --------------------------------------------------------------------------------------------------------


async def test_m2_selection_closed_91_purged_89_and_exact_90_kept_pending_kept(
    rw: AsyncEngine, saver: AsyncPostgresSaver
) -> None:  # fmt: skip
    old91 = await _ticket(rw, "d91", closed_days=91)
    d89 = await _ticket(rw, "d89", closed_days=89)
    exact90 = await _ticket(rw, "d90", closed_days=90)  # đột biến `<` → `<=` chọn nhầm ticket này
    pending = await _ticket(rw, "pend", closed_days=None)  # đang chờ, tạo từ 400 ngày trước — đột biến bỏ "đã đóng" chọn nhầm
    no_cp = await _ticket(rw, "nocp", closed_days=120)  # không còn checkpoint → không có gì để dọn
    for t in (old91, d89, exact90, pending):
        await _checkpoint(saver, t)
    got = set(await _store(rw).expired_threads(CUTOFF, 500))
    assert old91 in got
    assert not got & {d89, exact90, pending, no_cp}


async def test_m2_selection_skips_open_escalation_open_turn_and_unfinished_family(
    rw: AsyncEngine, saver: AsyncPostgresSaver
) -> None:  # fmt: skip
    esc_open = await _ticket(rw, "esco", closed_days=95, final="S_ESCALATED")
    esc_done = await _ticket(rw, "escd", closed_days=95, final="S_ESCALATED")
    turn_open = await _ticket(rw, "turn", closed_days=95)
    parent_open = await _ticket(rw, "par", closed_days=None, is_parent=True)
    child = await _ticket(rw, "child", closed_days=95, parent=parent_open)
    parent_done = await _ticket(rw, "pard", closed_days=95, is_parent=True)
    child_open = await _ticket(rw, "chopen", closed_days=None, parent=parent_done)
    for t in (esc_open, esc_done, turn_open, child, parent_done, child_open):
        await _checkpoint(saver, t)
    async with rw.begin() as conn:
        await conn.execute(text("INSERT INTO escalations (ticket_id, exit_code, priority, handoff_note) "
                                "VALUES (:a, 'E5', 5, '{}'::jsonb), (:b, 'E5', 5, '{}'::jsonb)"), {"a": esc_open, "b": esc_done})
        await conn.execute(text("UPDATE escalations SET closed_at = :n WHERE ticket_id = :b"), {"n": NOW - timedelta(days=94),
                                                                                              "b": esc_done})  # fmt: skip
        await conn.execute(text("INSERT INTO turns (turn_id, ticket_id, event_type, started_at) VALUES (:id, :t, 'submit', :s)"),
                           {"id": _id("turn"), "t": turn_open, "s": NOW - timedelta(days=95)})  # fmt: skip
    got = set(await _store(rw).expired_threads(CUTOFF, 500))
    assert esc_done in got
    assert not got & {esc_open, turn_open, child, parent_done, child_open}


async def test_m2_batch_limit_oldest_first(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    a = await _ticket(rw, "b200", closed_days=200)
    b = await _ticket(rw, "b150", closed_days=150)
    for t in (a, b):
        await _checkpoint(saver, t)
    got = await _store(rw).expired_threads(CUTOFF, 1)
    assert len(got) == 1 and got[0] != b  # cũ nhất trước (DB dùng chung trong module — có thể có ticket cũ hơn của test khác)


# ---- dry-run / xoá thật -----------------------------------------------------------------------------------------------------------


async def test_m2_dry_run_deletes_nothing(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    old = await _ticket(rw, "dry", closed_days=100)
    await _checkpoint(saver, old)
    async with rw.begin() as conn:
        await conn.execute(text("INSERT INTO side_effects (effect_key, ticket_id, kind, step, turn_id) "
                                "VALUES (:k, :t, 'notify_user', 'B19', 'T1')"), {"k": uuid4().hex + uuid4().hex, "t": old})
    report = await _job(rw, saver, dry_run=True).run()
    assert await _cp_rows(rw, old) == 1
    assert int(await scalar(rw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t", t=old)) == 1
    assert report.dry_run is True and report.threads >= 1


async def test_m2_each_run_writes_exactly_one_retention_event(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    before_events = int(await scalar(rw, "SELECT count(*) FROM security_events WHERE event_type = 'retention_run'"))
    await _job(rw, saver, dry_run=True).run()
    rows = await scalar(rw, "SELECT count(*) FROM security_events WHERE event_type = 'retention_run'")
    assert int(rows) == before_events + 1
    detail = await scalar(rw, "SELECT detail FROM security_events WHERE event_type = 'retention_run' ORDER BY event_id DESC LIMIT 1")
    assert detail["dry_run"] is True and set(detail) == {"dry_run", "threads", "sessions", "waits", "errors", "retention_days"}
    assert all(type(v) in (int, bool) for v in detail.values())


async def test_m2_real_run_purges_checkpoint_and_side_rows_audit_untouched(
    rw: AsyncEngine, saver: AsyncPostgresSaver
) -> None:  # fmt: skip
    old = await _ticket(rw, "real", closed_days=91)
    young = await _ticket(rw, "young", closed_days=89)
    for t in (old, young):
        await _checkpoint(saver, t)
    async with rw.begin() as conn:
        await conn.execute(text("INSERT INTO audit_logs (ticket_id, step, event) VALUES (:t, 'B20', 'closed')"), {"t": old})
        await conn.execute(text("INSERT INTO side_effects (effect_key, ticket_id, kind, step, turn_id) "
                                "VALUES (:k, :t, 'notify_user', 'B19', 'T1')"), {"k": uuid4().hex + uuid4().hex, "t": old})
    audit_before = int(await scalar(rw, "SELECT count(*) FROM audit_logs"))
    await _job(rw, saver, dry_run=False).run()
    assert await _cp_rows(rw, old) == 0
    assert int(await scalar(rw, "SELECT count(*) FROM checkpoint_writes WHERE thread_id = :t", t=old)) == 0
    assert int(await scalar(rw, "SELECT count(*) FROM checkpoint_blobs WHERE thread_id = :t", t=old)) == 0
    assert await _cp_rows(rw, young) == 1
    assert int(await scalar(rw, "SELECT count(*) FROM side_effects WHERE ticket_id = :t", t=old)) == 0
    assert int(await scalar(rw, "SELECT count(*) FROM audit_logs")) == audit_before  # audit KHÔNG đổi
    assert int(await scalar(rw, "SELECT count(*) FROM tickets WHERE ticket_id = :t", t=old)) == 1  # dòng ticket còn (FK của audit)


async def test_m2_app_rw_cannot_delete_audit_even_if_job_tried(rw: AsyncEngine) -> None:
    """Rào DB của (c): job chạy role `app_rw` — DELETE/UPDATE/TRUNCATE `audit_logs` bị từ chối (REVOKE + trigger, D-05)."""
    for sql in ("DELETE FROM audit_logs", "UPDATE audit_logs SET note = 'x'", "TRUNCATE audit_logs"):
        with pytest.raises(DBAPIError):
            async with rw.begin() as conn:
                await conn.execute(text(sql))


# ---- sessions (P7 mục 4: 30 ngày sau khi hết hạn) -------------------------------------------------------------------------------


async def test_m2_sessions_expired_over_30_days_unreferenced_deleted(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    ids = {k: _id(k) for k in ("old", "old_ref", "d29", "live")}
    exp = {"old": NOW - timedelta(days=31), "old_ref": NOW - timedelta(days=31), "d29": NOW - timedelta(days=29),
           "live": NOW + timedelta(hours=1)}  # fmt: skip
    async with rw.begin() as conn:
        for k, sid in ids.items():
            await conn.execute(text("INSERT INTO sessions (session_id, user_id, token_family_id, expires_at, created_at) "
                                    "VALUES (:s, :u, gen_random_uuid(), :e, :c)"),
                               {"s": sid, "u": REQUESTER, "e": exp[k], "c": exp[k] - timedelta(hours=8)})  # fmt: skip
    await _ticket(rw, "sref", closed_days=10, session=ids["old_ref"])  # ticket giữ FK tới phiên cũ
    await _job(rw, saver, dry_run=False).run()
    left = {k for k, sid in ids.items()
            if int(await scalar(rw, "SELECT count(*) FROM sessions WHERE session_id = :s", s=sid)) == 1}  # fmt: skip
    assert left == {"old_ref", "d29", "live"}


# ---- wait_deadlines (ĐP chốt Q3: fired_at quá 7 ngày) ----------------------------------------------------------------------------


async def test_m2_fired_waits_older_than_7_days_deleted_unfired_kept(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    tid = await _ticket(rw, "wait", closed_days=None)
    rows = {"fired8": NOW - timedelta(days=8), "fired6": NOW - timedelta(days=6), "unfired": None}
    async with rw.begin() as conn:
        for turn, fired in rows.items():
            await conn.execute(text("INSERT INTO wait_deadlines (ticket_id, kind, deadline, created_turn, fired_at) "
                                    "VALUES (:t, 'clarify', :d, :c, :f)"),
                               {"t": tid, "d": NOW - timedelta(days=30), "c": turn, "f": fired})  # fmt: skip
    await _job(rw, saver, dry_run=False).run()
    left = set(await _all(rw, "SELECT created_turn FROM wait_deadlines WHERE ticket_id = :t", t=tid))
    assert left == {"fired6", "unfired"}


async def test_m2_child_notices_of_purged_parent_deleted(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    parent = await _ticket(rw, "npar", closed_days=95, is_parent=True)
    child = await _ticket(rw, "nchild", closed_days=96, parent=parent)
    for t in (parent, child):
        await _checkpoint(saver, t)
    async with rw.begin() as conn:
        await conn.execute(text("INSERT INTO child_notices (parent_ticket_id, child_ticket_id, source_step, kind, needs, body, effect_key) "
                                "VALUES (:p, :c, 'B19', 'result', 'none', 'nội dung đã che', :k)"),
                           {"p": parent, "c": child, "k": uuid4().hex + uuid4().hex})  # fmt: skip
    await _job(rw, saver, dry_run=False).run()
    assert int(await scalar(rw, "SELECT count(*) FROM child_notices WHERE parent_ticket_id = :p", p=parent)) == 0
    assert await _cp_rows(rw, parent) == 0 and await _cp_rows(rw, child) == 0


async def _all(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as conn:
        return [r[0] for r in await conn.execute(text(sql), params)]


async def test_m2_family_with_open_escalation_kept(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    """Soát M2 1b: escalation còn mở ở CON → giữ cả cha; escalation còn mở ở CHA → giữ con (L2 còn cần ngữ cảnh của họ)."""
    parent_a = await _ticket(rw, "fpa", closed_days=95, is_parent=True)
    child_a = await _ticket(rw, "fca", closed_days=96, parent=parent_a, final="S_ESCALATED")
    parent_b = await _ticket(rw, "fpb", closed_days=95, is_parent=True, final="S_ESCALATED")
    child_b = await _ticket(rw, "fcb", closed_days=96, parent=parent_b)
    for t in (parent_a, child_a, parent_b, child_b):
        await _checkpoint(saver, t)
    async with rw.begin() as conn:
        await conn.execute(text("INSERT INTO escalations (ticket_id, exit_code, priority, handoff_note) "
                                "VALUES (:a, 'E5', 5, '{}'::jsonb), (:b, 'E2', 4, '{}'::jsonb)"), {"a": child_a, "b": parent_b})
    got = set(await _store(rw).expired_threads(CUTOFF, 500))
    assert not got & {parent_a, child_a, parent_b, child_b}


async def test_m2_leftover_blobs_without_checkpoint_row_still_selected(rw: AsyncEngine, saver: AsyncPostgresSaver) -> None:
    """Soát M2 2b: `checkpoints` đã xoá mà còn `checkpoint_writes` (xoá dở) → lượt sau vẫn chọn ticket để dọn nốt."""
    tid = await _ticket(rw, "left", closed_days=120)
    await _checkpoint(saver, tid)
    cfg: Any = {"configurable": {"thread_id": tid, "checkpoint_ns": "", "checkpoint_id": empty_checkpoint()["id"]}}
    await saver.aput_writes(cfg, [("ch", "x")], "task-1")
    async with rw.begin() as conn:
        await conn.execute(text("DELETE FROM checkpoints WHERE thread_id = :t"), {"t": tid})  # giả lập xoá dở
    assert tid in set(await _store(rw).expired_threads(CUTOFF, 500))
    await _job(rw, saver, dry_run=False).run()
    assert int(await scalar(rw, "SELECT count(*) FROM checkpoint_writes WHERE thread_id = :t", t=tid)) == 0
