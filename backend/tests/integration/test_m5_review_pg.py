"""`app.audit.m5_review` trên Postgres 16 thật — phase6 7.3 r11 (chặng 6D). Viết TỪ ĐẶC TẢ trước thân code (7.1 P1, P2, P8).

- `load_point4(engine, since)`: 12 dòng audit cài tay (luật + llm + NULL `full_auto`, lẫn điểm 3/7/8 và `llm_layer_disabled`, một ticket
  chỉ có dòng trước `since`) → đúng các `Point4` của dòng `POINT4_KEY`, thứ tự `log_id`.
- `open_engine(dsn)` (đường DUY NHẤT hai vỏ dùng): INSERT vào `audit_logs` bị Postgres từ chối — `app_rw` phải là lỗi READ ONLY (role
  này CÓ quyền INSERT; đối chứng: cùng câu INSERT bằng engine thường ghi được). M-6D-6.
- `sample_main` đi hết đường DB thật: stdout không có `ticket_id`.

Database riêng cho MỖI test (`load(since=…)` quét mọi ticket của DB).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.audit import m5_review
from app.audit.m5_review import Point4, load_point4, open_engine
from app.db.tickets import NewTicket, SqlTicketStore
from psycopg.errors import InsufficientPrivilege, ReadOnlySqlTransaction
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import REQUESTER, SESSION, scalar, seed_users
from tests.integration.pg import PgUrls, alembic_config, fresh_database

T0 = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
SINCE = T0 + timedelta(hours=1)
LATE = T0 + timedelta(hours=2)
SHA = "c" * 64


@pytest.fixture
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


async def _ticket(engine: AsyncEngine) -> str:
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(engine).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=T0),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    return ticket


async def _audit(engine: AsyncEngine, ticket: str, step: str, event: str, *, detail: dict[str, Any] | None = None,
                 created_at: datetime = LATE, **cols: Any) -> int:  # fmt: skip
    names = ["ticket_id", "step", "event", "loop_seq", "created_at", "detail", *cols]
    values = [":ticket_id", ":step", ":event", "0", ":created_at", "CAST(:detail AS jsonb)", *(f":{c}" for c in cols)]
    sql = f"INSERT INTO audit_logs ({', '.join(names)}) VALUES ({', '.join(values)}) RETURNING log_id"
    params = {**cols, "ticket_id": ticket, "step": step, "event": event, "created_at": created_at, "detail": json.dumps(detail or {})}
    async with engine.begin() as conn:
        return int((await conn.execute(text(sql), params)).scalar_one())


RULE_REASON = "Kiểm tra trạng thái VPN của chính mình"
LLM_REASON = ("Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,90 (chưa hiệu chỉnh — không tự xử lý) → "
              "chuyển L2.")
RULE: dict[str, Any] = {"decided_by": "rule", "policy_decision": "allow", "risk_level": "low", "matched_rule_id": "R16",
        "reason": RULE_REASON}  # fmt: skip
LLM: dict[str, Any] = {"decided_by": "llm", "risk_level": "high", "raw_prob": 0.9, "p_method": "self_report",
       "reason": LLM_REASON}  # fmt: skip


async def _seed(engine: AsyncEngine) -> tuple[list[str], int]:
    """12 dòng: t1 (B8, điểm 4 luật, B20), t2 (B8, điểm 4 llm, B20), t3 (điểm 4 NULL full_auto, B18), t4 (`llm_layer_disabled`, điểm 4
    llm sampling_k5), t5 (B8 + điểm 4 luật — CHỈ trước `since`). Trả (t1…t4, số dòng)."""
    t1, t2, t3, t4, t5 = [await _ticket(engine) for _ in range(5)]
    count = 0

    async def add(*args: Any, **kw: Any) -> None:
        nonlocal count
        await _audit(engine, *args, **kw)
        count += 1

    await add(t1, "B8", "retrieved", detail={"query": "vpn", "top_score": 0.8})
    await add(t1, "B13/B14", "risk_decided", detail={"route": "AUTO", "policy_sha256": SHA}, **RULE)
    await add(t1, "B20", "closed", final_state="S_RESOLVED", close_reason="resolved_user_confirmed")
    await add(t2, "B8", "retrieved", detail={"query": "vpn", "top_score": 0.7})
    await add(t2, "B13/B14", "risk_decided", detail={"route": "ESCALATE_L2", "policy_sha256": SHA, "thresholds": [0.25, 0.75]}, **LLM)
    await add(t2, "B20", "closed", final_state="S_ESCALATED", exit_code="E5")
    await add(t3, "B13/B14", "risk_decided", detail={"strategy": "full_auto", "route": "AUTO", "policy_sha256": SHA})
    await add(t3, "B18", "executed_ok", detail={"write_calls": 1, "success": True})
    await add(t4, "B13/B14", "llm_layer_disabled", reason="lỗi estimator", detail={"route": "ESCALATE_L2"})
    await add(t4, "B13/B14", "risk_decided", detail={"route": "HITL", "policy_sha256": SHA, "thresholds": [0.25, 0.75]},
              **{**LLM, "raw_prob": 0.55, "p_method": "sampling_k5", "risk_level": "medium", "reason": "Mô hình … chờ người duyệt."})
    await add(t5, "B8", "retrieved", created_at=T0, detail={"query": "cũ", "top_score": 0.5})
    await add(t5, "B13/B14", "risk_decided", created_at=T0, detail={"route": "AUTO", "policy_sha256": SHA}, **RULE)
    return [t1, t2, t3, t4], count


def _expected(t1: str, t2: str, t3: str, t4: str) -> list[Point4]:
    return [
        Point4(t1, "rule", "AUTO", RULE_REASON, None, None),
        Point4(t2, "llm", "ESCALATE_L2", LLM_REASON, 0.9, "self_report"),
        Point4(t3, None, "AUTO", None, None, None),
        Point4(t4, "llm", "HITL", "Mô hình … chờ người duyệt.", 0.55, "sampling_k5"),
    ]


@pytest.mark.asyncio
async def test_r11_load_point4_via_open_engine(db: PgUrls, rw: AsyncEngine) -> None:
    tickets, count = await _seed(rw)
    assert count == 12
    for role in ("app_rw", "app_monitor"):
        engine = open_engine(db.role(role))
        try:
            assert await load_point4(engine, SINCE) == _expected(*tickets), role
        finally:
            await engine.dispose()
    assert await m5_review._fetch(db.role("app_rw"), SINCE) == _expected(*tickets)


@pytest.mark.asyncio
async def test_r11_open_engine_refuses_insert(db: PgUrls, rw: AsyncEngine) -> None:
    """M-6D-6: `open_engine` không READ ONLY → INSERT của app_rw lọt → đỏ. Đối chứng: cùng câu bằng engine thường ghi được."""
    ticket = await _ticket(rw)
    insert = "INSERT INTO audit_logs (ticket_id, step, event, loop_seq) VALUES (:t, 'B3', 'readonly_probe_6d', 0)"
    async with rw.begin() as conn:
        await conn.execute(text(insert), {"t": ticket})
    for role in ("app_rw", "app_monitor"):
        engine = open_engine(db.role(role))
        try:
            with pytest.raises(DBAPIError) as err:
                async with engine.begin() as conn:
                    await conn.execute(text(insert), {"t": ticket})
            allowed: tuple[type[Exception], ...] = (
                (ReadOnlySqlTransaction,) if role == "app_rw" else (ReadOnlySqlTransaction, InsufficientPrivilege)
            )
            assert isinstance(err.value.orig, allowed), (role, type(err.value.orig).__name__)
        finally:
            await engine.dispose()
    assert await scalar(rw, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t", t=ticket) == 1


def test_r11_sample_main_end_to_end(db: PgUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    async def seed() -> list[str]:
        engine = create_async_engine(db.role("app_rw"))
        try:
            await seed_users(engine)
            tickets, _ = await _seed(engine)
            return tickets
        finally:
            await engine.dispose()

    tickets = asyncio.run(seed())
    settings = SimpleNamespace(monitor_database_url=db.role("app_monitor"), database_url=db.role("app_rw"), llm_backend="real")
    monkeypatch.setattr(m5_review, "get_settings", lambda: settings)
    code = m5_review.sample_main(["--since", SINCE.isoformat(), "--n", "3", "--seed", "1", "--min-llm", "1"])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert sorted(line.split(". ", 1)[1] for line in out.splitlines()) == sorted(
        [RULE_REASON, LLM_REASON, "Mô hình … chờ người duyệt."]
    )
    assert not [t for t in tickets if t in out + err] and "app_monitor" in err
