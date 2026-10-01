"""SQL của hộp thư / xem phiếu trên Postgres 16 thật — Phase 4 chặng 4c DỪNG 2 (c8, c10 phần PG). Viết TỪ ĐẶC TẢ, trước thân code:
phase4 mục 6.1 P4, P5, P6 + 6.2 c8, c10; 5.7 #5; PLAN-4c mục 2.1 ("Bổ sung khi dựng khung S7" — PG), TQ-10, TQ-11, A20, A22.

- `SqlApprovals.inbox(user_id, status, limit)`: vai trò lọc ở SQL (`approver_id = :me OR (backup_approver_id = :me AND reminder_2_at IS NOT
  NULL)`) TRƯỚC `LIMIT` — dự phòng chưa nhắc 2 / người khác không thấy; `status` lọc; `ORDER BY created_at DESC`; `requester_id` từ
  `tickets`; `intended_action` từ dòng audit `step='B15' AND event='queued'` CÙNG `ticket_id` + `action_plan_hash` của phiếu (dòng khác hash,
  khác bước/sự kiện, khác ticket → không dùng).
- `mark_viewed(approval_id, now)`: `UPDATE … WHERE first_viewed_at IS NULL AND status='pending'` → lần 1 True, lần 2 False, giá trị giữ lần
  đầu; phiếu đã đóng → False, không ghi.
- `procedure_title(doc_id)`: `kb_documents.title` của bản KB hiện hành (`kb_versions.is_current`); không có → None.

Database riêng cho MỖI test: `inbox` đọc mọi phiếu của một người (dữ liệu test khác lẫn vào), `kb_versions` chỉ một dòng `is_current`.
`approvals.created_at` = `now()` của Postgres (A12) → test đặt lại bằng SQL.
"""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.approval.store import SqlApprovals
from app.core.hashing import hash_action
from app.db.tickets import NewTicket, SqlTicketStore
from app.domain.action import Action
from app.settings import get_action_metadata
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import APPROVER, REQUESTER, SESSION, scalar, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
SLA = timedelta(minutes=30)
BACKUP = "l1-bk"
OTHER = "l1-khac"


@pytest.fixture
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)  # REQUESTER (nv-graph) + phiên, APPROVER (l1-fake)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"INSERT INTO users (user_id, username, role) VALUES ('{BACKUP}', 'graph.l1bk', 'l1'), "
            f"('{OTHER}', 'graph.l1khac', 'l1') ON CONFLICT DO NOTHING"
        ))  # fmt: skip
    yield engine
    await engine.dispose()


def _action(action_type: str = "renew_vpn_cert", device: str = "LAP-0501") -> Action:
    m = get_action_metadata().of("vpn")[action_type]
    return Action(
        type=action_type, target=f"device:{device}", requested_for=REQUESTER, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": device}, facts={"device_owner_is_requester": True},
    )  # fmt: skip


async def _exec(rw: AsyncEngine, sql: str, **params: Any) -> None:
    async with rw.begin() as conn:
        await conn.execute(text(sql), params)


async def _approval(
    rw: AsyncEngine, *, created: datetime, approver: str = APPROVER, backup: str | None = None,
    plan_hash: str = "h" * 64, reminder_2: datetime | None = None,
) -> tuple[str, str]:  # fmt: skip
    """Ticket + phiếu `pending` (khuôn `test_approval_store_pg`): `created_at` đặt lại = `created` (server default là giờ Postgres),
    hạn `created + SLA`; `reminder_2` → đặt cả `reminder_1_at` và `reminder_2_at` (như worker nhắc 2, P3)."""
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(rw).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=created),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    aid = await SqlApprovals(rw).create(ticket, approver, created + SLA, plan_hash, backup_approver_id=backup,
                                        conflict_detected=False, conflict_type=None)  # fmt: skip
    await _exec(rw, "UPDATE approvals SET created_at = :c, reminder_1_at = :r, reminder_2_at = :r WHERE approval_id = :a",
                c=created, r=reminder_2, a=int(aid))  # fmt: skip
    return ticket, aid


async def _audit(
    rw: AsyncEngine, ticket: str, plan_hash: str, intended_action: dict[str, Any] | None, *, step: str = "B15",
    event: str = "queued",
) -> None:  # fmt: skip
    """Dòng `audit_logs` như B15 thật ghi ở điểm 5 (cột `action_plan_hash` + JSONB `intended_action`) — INSERT tay (2.1)."""
    await _exec(
        rw, "INSERT INTO audit_logs (ticket_id, step, event, loop_seq, action_plan_hash, intended_action) "
            "VALUES (:t, :s, :e, 0, :h, CAST(:ia AS jsonb))",
        t=ticket, s=step, e=event, h=plan_hash, ia=None if intended_action is None else json.dumps(intended_action),
    )  # fmt: skip


async def _ids(rw: AsyncEngine, user_id: str, status: str | None = None, limit: int = 50) -> list[str]:
    return [str(r.approval_id) for r in await SqlApprovals(rw).inbox(user_id, status, limit)]


# ---- inbox: vai trò ---------------------------------------------------------------------------------------------------------


async def test_c10_pg_inbox_role_filter_assigned_or_backup_after_reminder2(rw: AsyncEngine) -> None:
    """c10 PG (P4, P5, TQ-10): a1 giao APPROVER, dự phòng BACKUP chưa nhắc 2; a2 giao APPROVER, dự phòng BACKUP đã nhắc 2; a3 giao OTHER;
    a4 giao OTHER, dự phòng APPROVER chưa nhắc 2. APPROVER: a2, a1 (mới nhất trước); BACKUP: chỉ a2; OTHER: a4, a3. Đặt nhắc 2 cho a4 →
    APPROVER thấy thêm a4."""
    _, a1 = await _approval(rw, created=T0, backup=BACKUP)
    _, a2 = await _approval(rw, created=T0 + timedelta(minutes=1), backup=BACKUP, reminder_2=T0 + timedelta(minutes=25))
    _, a3 = await _approval(rw, created=T0 + timedelta(minutes=2), approver=OTHER)
    _, a4 = await _approval(rw, created=T0 + timedelta(minutes=3), approver=OTHER, backup=APPROVER)
    assert await _ids(rw, APPROVER) == [a2, a1]
    assert await _ids(rw, BACKUP) == [a2]
    assert await _ids(rw, OTHER) == [a4, a3]
    assert await _ids(rw, REQUESTER) == []
    await _exec(rw, "UPDATE approvals SET reminder_2_at = :r WHERE approval_id = :a", r=T0 + SLA - timedelta(minutes=1), a=int(a4))
    assert await _ids(rw, APPROVER) == [a4, a2, a1]


async def test_c10_pg_inbox_row_fields(rw: AsyncEngine) -> None:
    """`InboxRow` đủ trường hợp đồng (2.1 / TQ-10): phiếu, mốc nhắc, người duyệt + dự phòng, `requester_id` (JOIN `tickets`)."""
    r2 = T0 + timedelta(minutes=24)
    ticket, aid = await _approval(rw, created=T0, backup=BACKUP, reminder_2=r2)
    [row] = await SqlApprovals(rw).inbox(BACKUP, None, 50)
    assert (str(row.approval_id), row.ticket_id, row.status) == (aid, ticket, "pending")
    assert (row.created_at, row.deadline, row.reminder_1_at, row.reminder_2_at) == (T0, T0 + SLA, r2, r2)
    assert (row.approver_id, row.backup_approver_id, row.requester_id) == (APPROVER, BACKUP, REQUESTER)
    assert row.intended_action is None  # không có dòng audit B15 `queued`


async def test_c10_pg_inbox_role_filter_before_limit(rw: AsyncEngine) -> None:
    """TQ-10 "lọc vai trò ở WHERE": 3 phiếu MỚI hơn của người khác + 2 phiếu cũ của tôi, `limit=2` → đúng 2 phiếu của tôi (lọc sau LIMIT
    sẽ ra rỗng)."""
    _, mine_old = await _approval(rw, created=T0)
    _, mine_new = await _approval(rw, created=T0 + timedelta(minutes=1))
    for i in range(3):
        await _approval(rw, created=T0 + timedelta(minutes=10 + i), approver=OTHER)
    assert await _ids(rw, APPROVER, limit=2) == [mine_new, mine_old]
    assert len(await _ids(rw, OTHER, limit=2)) == 2


# ---- inbox: status ------------------------------------------------------------------------------------------------------------


async def test_c10_pg_inbox_status_filter(rw: AsyncEngine) -> None:
    """P5: `status` lọc ở SQL; None → mọi trạng thái, mới nhất trước."""
    _, p = await _approval(rw, created=T0)
    _, a = await _approval(rw, created=T0 + timedelta(minutes=1))
    _, r = await _approval(rw, created=T0 + timedelta(minutes=2))
    _, t = await _approval(rw, created=T0 + timedelta(minutes=3))
    store = SqlApprovals(rw)
    assert await store.close(a, "approved", T0 + timedelta(minutes=5), decided_by=APPROVER) == 1
    assert await store.close(r, "rejected", T0 + timedelta(minutes=5), decided_by=APPROVER, note="không") == 1
    assert await store.close(t, "timeout", T0 + SLA + timedelta(minutes=4)) == 1
    assert await _ids(rw, APPROVER) == [t, r, a, p]
    for status, expected in (("pending", p), ("approved", a), ("rejected", r), ("timeout", t)):
        assert await _ids(rw, APPROVER, status) == [expected], status
        [row] = await store.inbox(APPROVER, status, 50)
        assert row.status == status


# ---- inbox: intended_action ---------------------------------------------------------------------------------------------------


async def test_c10_pg_inbox_intended_action_from_b15_queued_same_hash(rw: AsyncEngine) -> None:
    """5.7 #5 / TQ-10: `intended_action` = JSON của dòng audit B15 `queued` CÙNG `ticket_id` + `action_plan_hash`. Các dòng mồi (ghi SAU,
    nên "mới nhất" nếu không lọc đúng): B15 `queued` khác hash; cùng hash nhưng bước khác (B17); cùng hash nhưng sự kiện khác."""
    action, old_plan = _action(), _action("check_vpn_status", "PC-0001")
    plan = hash_action(action)
    ticket, aid = await _approval(rw, created=T0, plan_hash=plan)
    await _audit(rw, ticket, plan, action.model_dump(mode="json"))
    await _audit(rw, ticket, hash_action(old_plan), old_plan.model_dump(mode="json"))
    await _audit(rw, ticket, plan, old_plan.model_dump(mode="json"), step="B17", event="executed")
    await _audit(rw, ticket, plan, old_plan.model_dump(mode="json"), event="approval_refused")
    [row] = await SqlApprovals(rw).inbox(APPROVER, None, 50)
    assert str(row.approval_id) == aid
    got = row.intended_action
    assert got == action.model_dump(mode="json")
    assert got is not None and (got["type"], got["target"]) == ("renew_vpn_cert", "device:LAP-0501")


async def test_c10_pg_inbox_no_matching_queued_row_is_none(rw: AsyncEngine) -> None:
    """Không có dòng B15 `queued` CÙNG hash của phiếu (chỉ có dòng hash khác của chính ticket, và dòng cùng hash nhưng của TICKET KHÁC)
    → `intended_action` None."""
    action, other = _action(), _action("check_vpn_status")
    plan = hash_action(action)
    ticket, aid = await _approval(rw, created=T0, plan_hash=plan)
    other_ticket, _ = await _approval(rw, created=T0 + timedelta(minutes=1), approver=OTHER, plan_hash=hash_action(other))
    await _audit(rw, ticket, hash_action(other), other.model_dump(mode="json"))
    await _audit(rw, other_ticket, plan, action.model_dump(mode="json"))
    [row] = await SqlApprovals(rw).inbox(APPROVER, None, 50)
    assert (str(row.approval_id), row.intended_action) == (aid, None)


# ---- mark_viewed (c8 PG) ------------------------------------------------------------------------------------------------------


async def test_c8_pg_mark_viewed_first_wins(rw: AsyncEngine) -> None:
    """c8 PG (P6 `WHERE first_viewed_at IS NULL AND status='pending'`): lần 1 True, lần 2 False, giá trị giữ lần đầu."""
    _, aid = await _approval(rw, created=T0)
    store, first = SqlApprovals(rw), T0 + timedelta(minutes=3)
    assert await store.mark_viewed(aid, first) is True
    assert await store.mark_viewed(aid, first + timedelta(minutes=2)) is False
    row = await store.get(aid)
    assert row is not None and row.first_viewed_at == first
    assert await scalar(rw, "SELECT first_viewed_at = :f FROM approvals WHERE approval_id = :a", f=first, a=int(aid))


@pytest.mark.parametrize("status", ["approved", "rejected", "timeout"])
async def test_c8_pg_mark_viewed_closed_approval_false(rw: AsyncEngine, status: str) -> None:
    """P6: phiếu không còn `pending` → False, `first_viewed_at` vẫn NULL."""
    _, aid = await _approval(rw, created=T0)
    store = SqlApprovals(rw)
    note = "không" if status == "rejected" else None
    decided_by = None if status == "timeout" else APPROVER
    assert await store.close(aid, status, T0 + timedelta(minutes=5), decided_by=decided_by, note=note) == 1
    assert await store.mark_viewed(aid, T0 + timedelta(minutes=6)) is False
    row = await store.get(aid)
    assert row is not None and row.first_viewed_at is None


# ---- procedure_title (P6, A22) ----------------------------------------------------------------------------------------------------


async def _kb(rw: AsyncEngine, version: str, *, current: bool, docs: list[tuple[str, int, str]]) -> None:
    """Một bản KB (`kb_versions`) + tài liệu thuộc bản đó (`kb_documents`, cột NOT NULL theo `db/models.py`)."""
    await _exec(rw, "INSERT INTO kb_versions (kb_version, doc_count, is_current) VALUES (:v, :n, :c)",
                v=version, n=len(docs), c=current)  # fmt: skip
    for doc_id, doc_version, title in docs:
        await _exec(
            rw, "INSERT INTO kb_documents (doc_id, version, title, request_type, doc_type, updated_at, sensitivity, kb_version) "
                "VALUES (:d, :dv, :t, 'vpn', 'howto', '2026-09-01', 'internal', :v)",
            d=doc_id, dv=doc_version, t=title, v=version,
        )  # fmt: skip


async def test_pg_procedure_title_from_current_kb_version(rw: AsyncEngine) -> None:
    """P6 + A22: tiêu đề của tài liệu ở bản KB HIỆN HÀNH (`is_current`) — bản cũ có tiêu đề khác không được dùng; doc không có → None."""
    await _kb(rw, "a" * 64, current=False, docs=[("KB-VPN-004", 1, "Gia hạn chứng chỉ (bản cũ)")])
    await _kb(rw, "b" * 64, current=True, docs=[("KB-VPN-004", 2, "Quy trình gia hạn chứng chỉ VPN"),
                                                 ("KB-VPN-001", 1, "Kiểm tra trạng thái VPN")])  # fmt: skip
    store = SqlApprovals(rw)
    assert await store.procedure_title("KB-VPN-004") == "Quy trình gia hạn chứng chỉ VPN"
    assert await store.procedure_title("KB-VPN-001") == "Kiểm tra trạng thái VPN"
    assert await store.procedure_title("KB-VPN-999") is None


async def test_pg_procedure_title_doc_only_in_old_kb_version_is_none(rw: AsyncEngine) -> None:
    """P6 + A22 (diễn giải "bản hiện hành"): tài liệu chỉ còn ở bản KB cũ (không có trong bản `is_current`) → None."""
    await _kb(rw, "c" * 64, current=False, docs=[("KB-VPN-002", 1, "Tài liệu đã bỏ")])
    await _kb(rw, "d" * 64, current=True, docs=[("KB-VPN-004", 1, "Quy trình gia hạn chứng chỉ VPN")])
    assert await SqlApprovals(rw).procedure_title("KB-VPN-002") is None
