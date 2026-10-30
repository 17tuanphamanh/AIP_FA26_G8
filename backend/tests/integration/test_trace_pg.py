"""`SqlTraceSource` (api/trace.py) trên Postgres 16 thật, role `app_rw`: đọc đúng dòng, `intended_action` CHỈ còn khoá `type`
(tham số không rời DB), tiêu đề KB theo (doc_id, version) của chunk đã trích dẫn, họ tên người duyệt, con của ticket cha.
Database riêng cho module (audit_logs chỉ ghi thêm)."""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.api.matched_rules import RuleRef
from app.api.trace import SqlTraceSource, build_trace
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
