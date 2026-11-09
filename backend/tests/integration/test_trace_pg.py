"""`SqlTraceSource` (api/trace.py) trên Postgres 16 thật, role `app_rw`: đọc đúng dòng, `intended_action` CHỈ còn khoá `type`
(tham số không rời DB), tiêu đề KB theo (doc_id, version) của chunk đã trích dẫn, họ tên người duyệt, con của ticket cha;
QS05b: `close_note` của dòng đóng ca lấy từ cột `escalations.close_note` theo `detail.escalation_id` (không từ audit_logs, không lẫn
ca của ticket khác; ca đóng không có ghi chú → null; ticket không có dòng đóng ca thì không đọc bảng `escalations`).
Database riêng cho module (audit_logs chỉ ghi thêm)."""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.api.matched_rules import RuleRef
from app.api.trace import SqlTraceSource, build_trace
from app.db.escalations import CloseRequest, SqlEscalationStore, close_audit_row
from app.domain.escalation_close import CloseResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.pg import PgUrls, alembic_config, fresh_database

pytestmark = pytest.mark.asyncio

T0 = datetime(2031, 3, 2, 9, tzinfo=UTC)
_CANARY_PARTS = ("CANARY", "tracepg", "77c1")
CANARY = "-".join(_CANARY_PARTS)
KB = "a" * 64


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


def _j(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    try:
        yield engine
    finally:
        await engine.dispose()


async def _tickets(rw: AsyncEngine, tickets: list[tuple[str, str | None, bool, str | None]]) -> None:
    async with rw.begin() as conn:
        await conn.execute(text(
            "INSERT INTO users (user_id, username, role, full_name) VALUES ('tr-nv', 'tr.nv', 'employee', NULL), "
            "('tr-l1', 'tr.l1', 'l1', 'Lê Thu Hà') ON CONFLICT DO NOTHING"
        ))  # fmt: skip
        for tid, parent, is_parent, intent in tickets:
            await conn.execute(text(
                "INSERT INTO tickets (ticket_id, parent_ticket_id, requester_id, requester_role, redacted_request, intent, "
                "created_at, is_parent) VALUES (:t, :p, 'tr-nv', 'employee', :req, :i, :c, :ip)"
            ), {"t": tid, "p": parent, "req": CANARY, "i": intent, "c": T0, "ip": is_parent})  # fmt: skip


async def _seed(rw: AsyncEngine) -> None:
    await _tickets(rw, [("TR-1", None, False, "vpn")])
    audit = (
        "INSERT INTO audit_logs (ticket_id, created_at, step, event, intended_action, approver_id, approval_result, "
        "decided_by, policy_decision, risk_level, matched_rule_id, note, detail) VALUES (:t, :c, :s, :e, "
        "CAST(:ia AS jsonb), :ap, :ar, :db, :pd, :rl, :rule, :note, CAST(:d AS jsonb))"
    )
    base = {"ia": None, "ap": None, "ar": None, "db": None, "pd": None, "rl": None, "rule": None, "note": None, "d": "{}"}
    async with rw.begin() as conn:
        await conn.execute(text("INSERT INTO kb_versions (kb_version, doc_count) VALUES (:k, 1)"), {"k": KB})
        await conn.execute(text(
            "INSERT INTO kb_documents (doc_id, version, title, request_type, doc_type, updated_at, sensitivity, kb_version) "
            "VALUES ('KB-VPN-001', 3, 'Gia hạn chứng chỉ VPN', 'vpn', 'howto', '2031-01-01', 'internal', :k), "
            "('KB-VPN-001', 2, 'Bản cũ', 'vpn', 'howto', '2030-01-01', 'internal', :k)"
        ), {"k": KB})  # fmt: skip
        rows = [
            {"s": "B10", "e": "deflected_info_only", "d": _j({"cited": ["KB-VPN-001#v3#0"], "prompt": CANARY})},
            {"s": "B11", "e": "action_built", "ia": _j({"type": "renew_vpn_cert", "params": {"password": CANARY}})},
            {"s": "B13/B14", "e": "risk_decided", "db": "rule", "pd": "approval_required", "rl": "medium", "rule": "R18"},
            {"s": "B15", "e": "queued", "ap": "tr-l1"},
            {"s": "B16", "e": "approved", "ar": "approved", "note": CANARY},
        ]
        for i, r in enumerate(rows):
            await conn.execute(text(audit), {**base, **r, "t": "TR-1", "c": T0 + timedelta(minutes=i)})
        await conn.execute(text(
            "INSERT INTO approvals (ticket_id, approver_id, deadline, action_plan_hash, status, note, decided_by, decided_at, "
            "created_at) VALUES ('TR-1', 'tr-l1', :dl, :h, 'approved', :note, 'tr-l1', :at, :c)"
        ), {"dl": T0 + timedelta(hours=4), "h": "0" * 64, "note": CANARY, "at": T0 + timedelta(minutes=4),
            "c": T0 + timedelta(minutes=3)})  # fmt: skip


async def test_sql_source_reads_whitelisted_shape(rw: AsyncEngine) -> None:
    await _seed(rw)
    src = SqlTraceSource(rw)
    assert await src.head("TR-404") is None
    head = await src.head("TR-1")
    assert head is not None and (head.requester_id, head.is_parent, head.parent_ticket_id) == ("tr-nv", False, None)
    data = await src.load(head)
    assert [r["step"] for r in data.audit] == ["B10", "B11", "B13/B14", "B15", "B16"]
    assert data.audit[1]["intended_action"] == {"type": "renew_vpn_cert"}  # tham số không được SELECT
    assert all("note" not in r and "reason" not in r for r in data.audit)
    assert all("note" not in a for a in data.approvals)
    assert data.kb_titles == {("KB-VPN-001", 3): "Gia hạn chứng chỉ VPN"}
    assert data.names == {"tr-l1": "Lê Thu Hà"}
    assert dict(data.close_notes) == {}  # không có dòng đóng ca → không đọc `escalations`
    out = build_trace(data, {"R18": RuleRef("approval_required", "mô tả")})
    assert CANARY not in out.model_dump_json()
    steps = {s.step: s for s in out.steps}
    assert [s.model_dump() for s in steps["B10"].sources or []] == [{"doc_id": "KB-VPN-001", "title": "Gia hạn chứng chỉ VPN"}]
    b16 = steps["B16"].approval
    assert b16 is not None and (b16.approver_name, b16.result, b16.at) == ("Lê Thu Hà", "approved", T0 + timedelta(minutes=4))


async def test_sql_source_children_of_parent(rw: AsyncEngine) -> None:
    await _tickets(rw, [("TR-P", None, True, None), ("TR-P-1", "TR-P", False, "vpn"), ("TR-P-2", "TR-P", False, "account")])
    src = SqlTraceSource(rw)
    head = await src.head("TR-P")
    assert head is not None and head.is_parent
    data = await src.load(head)
    assert [(c["ticket_id"], c["intent"]) for c in data.children] == [("TR-P-1", "vpn"), ("TR-P-2", "account")]
    child = await src.head("TR-P-1")
    assert child is not None and child.parent_ticket_id == "TR-P" and (await src.load(child)).children == []


async def _escalation(store: SqlEscalationStore, ticket_id: str) -> int:
    return int(await store.create(
        ticket_id=ticket_id, exit_code="E1", reason_detail=None, handoff_note={"request": "x"}, is_deny_case=False, created_at=T0,
    ))  # fmt: skip


async def test_sql_source_close_notes_come_from_escalations_by_escalation_id(rw: AsyncEngine) -> None:
    """Hai ca của cùng ticket đóng bằng `SqlEscalationStore.close` thật (dòng audit đúng khuôn `close_audit_row`): mỗi dòng đóng ca nhận
    đúng ghi chú của ca nó; ghi chú của ticket khác không lọt vào `close_notes` lẫn thân trả về."""
    await _tickets(rw, [("TR-C1", None, False, "account"), ("TR-C2", None, False, "account")])
    store = SqlEscalationStore(rw)
    ids = {key: await _escalation(store, ticket) for key, ticket in (("a", "TR-C1"), ("b", "TR-C1"), ("c", "TR-C2"))}
    notes = {"a": "Đã gọi lại, tài khoản đã mở khoá. [SĐT_ĐÃ_ẨN]", "b": "Giữ quyết định từ chối theo chính sách.",
             "c": f"ghi chú của ticket khác {CANARY}"}  # fmt: skip
    results: dict[str, CloseResult] = {"a": "completed", "b": "confirmed_denial", "c": "completed"}
    for hour, key in enumerate("abc", start=1):
        req = CloseRequest(
            escalation_id=ids[key], close_result=results[key], closed_by="tr-l1", close_note=notes[key],
            close_reason="resolved_after_escalation", at=T0 + timedelta(hours=hour),
        )  # fmt: skip
        assert await store.close(req) is not None
    src = SqlTraceSource(rw)
    head = await src.head("TR-C1")
    assert head is not None
    data = await src.load(head)
    assert dict(data.close_notes) == {ids["a"]: notes["a"], ids["b"]: notes["b"]}
    assert all("note" not in r for r in data.audit)
    out = build_trace(data, {})
    assert [(s.outcome.close_result, s.outcome.close_note) for s in out.steps if s.outcome is not None] == [
        ("completed", notes["a"]), ("confirmed_denial", notes["b"]),
    ]  # fmt: skip
    blob = out.model_dump_json()
    assert CANARY not in blob and "tr-l1" not in blob  # không ghi chú ticket khác, không closed_by


async def test_sql_source_closed_without_note_gives_null(rw: AsyncEngine) -> None:
    """Ca đã đóng mà cột `close_note` NULL (đóng trước migration 0013): dòng đóng ca có `close_note: null`, không lỗi."""
    await _tickets(rw, [("TR-C3", None, False, "account")])
    store = SqlEscalationStore(rw)
    eid = await _escalation(store, "TR-C3")
    at = T0 + timedelta(hours=1)
    audit = close_audit_row(
        CloseRequest(escalation_id=eid, close_result="completed", closed_by="tr-l1", close_note="x",
                     close_reason="resolved_after_escalation", at=at),
        "TR-C3",
    )  # fmt: skip
    async with rw.begin() as conn:
        await conn.execute(text(
            "UPDATE escalations SET closed_at = :at, close_result = 'completed', closed_by = 'tr-l1' WHERE escalation_id = :e"
        ), {"at": at, "e": eid})  # fmt: skip
        await conn.execute(text(
            "INSERT INTO audit_logs (ticket_id, created_at, step, event, idempotency_key, detail) "
            "VALUES (:t, :c, :s, :ev, :k, CAST(:d AS jsonb))"
        ), {"t": "TR-C3", "c": at, "s": audit["step"], "ev": audit["event"], "k": audit["idempotency_key"],
            "d": _j(audit["detail"])})  # fmt: skip
    src = SqlTraceSource(rw)
    head = await src.head("TR-C3")
    assert head is not None
    data = await src.load(head)
    assert dict(data.close_notes) == {}
    outcome = build_trace(data, {}).steps[0].outcome
    assert outcome is not None and outcome.model_dump(exclude_unset=True) == {
        "route": None, "exit_code": None, "close_result": "completed", "close_note": None,
    }  # fmt: skip
