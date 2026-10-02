"""`app.audit.check` trên Postgres 16 thật — Phase 4 chặng 4d DỪNG 1. Viết TỪ ĐẶC TẢ trước thân code: phase4 mục 7.1 P5, 7.2;
PLAN-4d mục 2.1 (`load`, `run`, `readonly_engine`, `main`), mục 3 (dòng "PG", a5 phần có DB), mục 4 (bảng điểm đã chốt), mục 9
điều kiện 1 (TQ-6), TQ-8.

- `load(engine, tickets=…)`: dòng `audit_logs` (dict cột → giá trị, `detail` là dict, có `log_id`) của ĐÚNG các ticket xin + `final_state`.
- `load(engine, since=…)`: ticket có ÍT NHẤT một dòng audit `created_at >= since` → lấy MỌI dòng của ticket đó (TQ-8).
- `readonly_engine(dsn)` — ĐIỀU KIỆN 1 PLAN mục 9: CẢ HAI đường `app_monitor` và `app_rw` qua `readonly_engine` đều TỪ CHỐI INSERT vào
  `audit_logs` (đối chứng: cùng câu INSERT bằng engine `app_rw` thường thì ghi được → lỗi là do READ ONLY, không do dữ liệu).
- `run`: canary cài bằng SQL vào `audit_logs.detail` → `SecretHit(rule="canary", column="audit_logs.detail", ref=<log_id>)` (M-4d-8);
  dòng B15 `queued` thiếu `approver_id` → `Missing(point=5)` (M-4d-9); điểm 8; `log_lines`.
- `main` (a5 phần có DB): 0 sạch / 1 có lỗi; đầu ra không có canary, không có DSN (mật khẩu role).

Database riêng cho MỖI test (`load(since=…)` quét mọi ticket của DB). Test điều kiện 1 dùng `migrated` (DB chung của phiên) như lời giao.
"""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from app.audit.check import (
    Missing,
    SecretHit,
    SecretScanner,
    load,
    main,
    readonly_engine,
    run,
)
from app.db.tickets import NewTicket, SqlTicketStore
from app.settings import Settings, get_settings
from psycopg.errors import InsufficientPrivilege, ReadOnlySqlTransaction
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration.graph_pg import APPROVER, REQUESTER, SESSION, scalar, seed_users
from tests.integration.pg import PASSWORDS, PgUrls, alembic_config, fresh_database

T0 = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
CONFIG_DIR = Settings(_env_file=None).config_dir  # type: ignore[call-arg]
_CANARY_PARTS = ("Canary#4d", "pg", "k2")
CANARY = "-".join(_CANARY_PARTS)  # ghép lúc chạy (gitleaks)
PASSWORD_TEXT = "mật khẩu là " + "Tr0ub" + "4dor99"
HEX64 = "a" * 64
B3_FULL = {"layer": "model", "dropped_slot_keys": [], "intent": "vpn", "confidence": 0.92}


def _scanner() -> SecretScanner:
    return SecretScanner.from_config(CONFIG_DIR, canaries=(CANARY,))


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


async def _exec(engine: AsyncEngine, sql: str, **params: Any) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


async def _ticket(engine: AsyncEngine, *, final_state: str | None = None, exit_code: str | None = None) -> str:
    ticket = f"tk-{uuid4().hex[:8]}"
    await SqlTicketStore(engine).create(
        NewTicket(ticket_id=ticket, requester_id=REQUESTER, requester_role="employee", requester_dept="it",
                  session_id=SESSION, redacted_request="VPN lỗi", created_at=T0),
        turn_id=f"turn-{uuid4().hex[:8]}",
    )  # fmt: skip
    if final_state is not None:
        await _exec(engine, "UPDATE tickets SET final_state = :f, exit_code = :e, closed_at = :c WHERE ticket_id = :t",
                    f=final_state, e=exit_code, c=T0 + timedelta(minutes=5), t=ticket)  # fmt: skip
    return ticket


def _insert_sql(cols: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    names = ["ticket_id", "step", "event", "loop_seq", "created_at", "detail", *cols]
    values = [":ticket_id", ":step", ":event", "0", ":created_at", "CAST(:detail AS jsonb)", *(f":{c}" for c in cols)]
    sql = f"INSERT INTO audit_logs ({', '.join(names)}) VALUES ({', '.join(values)}) RETURNING log_id"
    return sql, dict(cols)


async def _audit(
    engine: AsyncEngine, ticket: str, step: str, event: str, *, detail: dict[str, Any] | None = None,
    created_at: datetime = T0, **cols: Any,
) -> int:  # fmt: skip
    """Một dòng `audit_logs` INSERT tay (cột trần + `detail` JSONB) → `log_id`."""
    sql, params = _insert_sql(cols)
    async with engine.begin() as conn:
        log_id: Any = (await conn.execute(text(sql), {**params, "ticket_id": ticket, "step": step, "event": event,
                                                 "created_at": created_at, "detail": json.dumps(detail or {})})).scalar_one()  # fmt: skip
    return int(log_id)


# ---- load ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pg_load_by_ticket_list(rw: AsyncEngine) -> None:
    t1 = await _ticket(rw, final_state="S_RESOLVED")
    l11 = await _audit(rw, t1, "B3", "intent_classified", detail=B3_FULL, intent="vpn")
    l12 = await _audit(rw, t1, "B20", "closed", final_state="S_RESOLVED", close_reason="resolved_user_confirmed")
    t2 = await _ticket(rw)
    l21 = await _audit(rw, t2, "B15", "queued", detail={"choice_reason": "primary"}, approver_id=APPROVER,
                       deadline=T0 + timedelta(minutes=30), conflict_detected=False, action_plan_hash=HEX64)  # fmt: skip
    t3 = await _ticket(rw)
    await _audit(rw, t3, "B3", "intent_classified", detail=B3_FULL, intent="vpn")

    rows, finals = await load(rw, tickets=[t1, t2])
    assert set(rows) == {t1, t2}
    assert sorted(r["log_id"] for r in rows[t1]) == [l11, l12]
    [r21] = rows[t2]
    assert r21["log_id"] == l21 and r21["ticket_id"] == t2 and (r21["step"], r21["event"]) == ("B15", "queued")
    assert (r21["approver_id"], r21["conflict_detected"], r21["action_plan_hash"]) == (APPROVER, False, HEX64)
    assert r21["detail"] == {"choice_reason": "primary"}
    r11 = next(r for r in rows[t1] if r["log_id"] == l11)
    assert r11["detail"] == B3_FULL and r11["intent"] == "vpn" and r11.get("approver_id") is None
    assert finals[t1] == "S_RESOLVED" and finals.get(t2) is None and t3 not in finals


@pytest.mark.asyncio
async def test_pg_load_since_takes_all_rows_of_touched_tickets(rw: AsyncEngine) -> None:
    """TQ-8: `ticket_id IN (ticket có dòng audit created_at >= since)` → MỌI dòng của các ticket đó (cả dòng cũ hơn `since`)."""
    old, new, mixed = await _ticket(rw), await _ticket(rw), await _ticket(rw)
    await _audit(rw, old, "B3", "intent_classified", detail=B3_FULL, intent="vpn")
    l_new = await _audit(rw, new, "B3", "intent_classified", detail=B3_FULL, intent="vpn", created_at=T0 + timedelta(hours=2))
    l_mixed_old = await _audit(rw, mixed, "B3", "intent_classified", detail=B3_FULL, intent="vpn")
    l_mixed_new = await _audit(rw, mixed, "B10", "deflected_info_only", created_at=T0 + timedelta(hours=3))
    rows, _ = await load(rw, since=T0 + timedelta(hours=1))
    assert set(rows) == {new, mixed}
    assert [r["log_id"] for r in rows[new]] == [l_new]
    assert {r["log_id"] for r in rows[mixed]} == {l_mixed_old, l_mixed_new}


# ---- readonly_engine — điều kiện 1 PLAN mục 9 ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pg_readonly_engine_app_monitor_and_app_rw_both_refuse_insert(migrated: PgUrls) -> None:
    """Điều kiện 1 (TQ-6, S6): `readonly_engine(DSN app_monitor)` và `readonly_engine(DSN app_rw)` — đọc được, INSERT vào
    `audit_logs` bị Postgres từ chối (app_rw: phải là lỗi READ ONLY — role này CÓ quyền INSERT; app_monitor: READ ONLY hoặc thiếu
    quyền). Đối chứng: cùng câu INSERT bằng engine `app_rw` thường → ghi được."""
    writer = create_async_engine(migrated.role("app_rw"))
    insert = "INSERT INTO audit_logs (ticket_id, step, event, loop_seq) VALUES (:t, 'B3', 'readonly_probe', 0)"
    try:
        await seed_users(writer)
        ticket = await _ticket(writer)
        await _exec(writer, insert, t=ticket)
        for role in ("app_monitor", "app_rw"):
            engine = readonly_engine(migrated.role(role))
            try:
                assert await scalar(engine, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t", t=ticket) == 1, role
                with pytest.raises(DBAPIError) as err:
                    async with engine.begin() as conn:
                        await conn.execute(text(insert), {"t": ticket})
                allowed: tuple[type[Exception], ...] = (
                    (ReadOnlySqlTransaction,) if role == "app_rw" else (ReadOnlySqlTransaction, InsufficientPrivilege)
                )
                assert isinstance(err.value.orig, allowed), (role, type(err.value.orig).__name__)
            finally:
                await engine.dispose()
        assert await scalar(writer, "SELECT count(*) FROM audit_logs WHERE ticket_id = :t", t=ticket) == 1
    finally:
        await writer.dispose()


# ---- run ----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pg_run_canary_planted_in_detail_hits_with_log_id(rw: AsyncEngine) -> None:
    """M-4d-8: canary cài bằng SQL vào `audit_logs.detail` (lá lồng) → đúng một `SecretHit(t, "audit_logs.detail", log_id,
    "canary")`; mật khẩu trong cột `note` → luật `password`. Ticket sạch cùng lần chạy → không trúng."""
    dirty, clean = await _ticket(rw), await _ticket(rw)
    log_canary = await _audit(rw, dirty, "B3", "intent_classified", detail={**B3_FULL, "x": {"y": [1, f"z {CANARY}"]}},
                              intent="vpn")  # fmt: skip
    log_pw = await _audit(rw, dirty, "B3", "intent_classified", detail=B3_FULL, intent="vpn", note=PASSWORD_TEXT)
    await _audit(rw, clean, "B3", "intent_classified", detail=B3_FULL, intent="vpn", note="mật khẩu là [BÍ_MẬT_ĐÃ_ẨN]")
    report = await run(rw, tickets=[dirty, clean], scanner=_scanner())
    assert list(report.missing) == []
    assert set(report.secrets) == {SecretHit(dirty, "audit_logs.detail", log_canary, "canary"),
                                   SecretHit(dirty, "audit_logs.note", log_pw, "password")}  # fmt: skip
    assert len(report.secrets) == 2 and report.ok is False
    assert set(report.tickets) == {dirty, clean}
    clean_report = await run(rw, tickets=[clean], scanner=_scanner())
    assert clean_report.ok is True and list(clean_report.secrets) == [] and list(clean_report.missing) == []


@pytest.mark.asyncio
async def test_pg_run_b15_queued_without_approver_id_is_point5(rw: AsyncEngine) -> None:
    """M-4d-9 (i17 đối chứng, ở PG): dòng B15 `queued` đủ mọi trường trừ cột `approver_id` → `Missing(t, 5, log_id,
    ("approver_id",))`."""
    ticket = await _ticket(rw)
    log_id = await _audit(rw, ticket, "B15", "queued", detail={"choice_reason": "primary"}, deadline=T0 + timedelta(minutes=30),
                          conflict_detected=False, action_plan_hash=HEX64)  # fmt: skip
    report = await run(rw, tickets=[ticket], scanner=_scanner())
    assert list(report.missing) == [Missing(ticket, 5, log_id, ("approver_id",))]
    assert list(report.secrets) == [] and report.ok is False


@pytest.mark.asyncio
async def test_pg_run_point8_reads_tickets_final_state(rw: AsyncEngine) -> None:
    """Điểm 8 đọc `tickets.final_state`: kết thúc mà không có dòng B20 `closed` → `Missing(point=8, log_id=None)`; thêm dòng B20 đủ
    → sạch. Ticket mở không có B20 → không đòi."""
    final = await _ticket(rw, final_state="S_ESCALATED", exit_code="E5")
    await _audit(rw, final, "B3", "intent_classified", detail=B3_FULL, intent="vpn")
    opened = await _ticket(rw)
    await _audit(rw, opened, "B3", "intent_classified", detail=B3_FULL, intent="vpn")
    report = await run(rw, tickets=[final, opened], scanner=_scanner())
    [m] = report.missing
    assert (m.ticket_id, m.point, m.log_id) == (final, 8, None)
    await _audit(rw, final, "B20", "closed", final_state="S_ESCALATED", exit_code="E5")
    assert (await run(rw, tickets=[final, opened], scanner=_scanner())).ok is True


@pytest.mark.asyncio
async def test_pg_run_log_lines_scanned(rw: AsyncEngine) -> None:
    ticket = await _ticket(rw)
    await _audit(rw, ticket, "B3", "intent_classified", detail=B3_FULL, intent="vpn")
    report = await run(rw, tickets=[ticket], scanner=_scanner(), log_lines=["INFO ok", f"WARN x {CANARY}", "INFO hết"])
    assert list(report.secrets) == [SecretHit(None, "log", 2, "canary")]


# ---- main (a5 phần có DB) -------------------------------------------------------------------------------------------------------------


def _sync_ticket(engine: Engine, *, canary: bool) -> str:
    ticket = f"tk-{uuid4().hex[:8]}"
    detail = {**B3_FULL, **({"x": f"y {CANARY}"} if canary else {})}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, created_at) "
                          "VALUES (:t, :u, 'employee', 'VPN lỗi', :c)"), {"t": ticket, "u": REQUESTER, "c": T0})  # fmt: skip
        sql, params = _insert_sql({"intent": "vpn"})
        conn.execute(text(sql), {**params, "ticket_id": ticket, "step": "B3", "event": "intent_classified",
                                 "created_at": T0 + timedelta(days=3650), "detail": json.dumps(detail)})  # fmt: skip
    return ticket


def _clear_settings_cache() -> None:
    clear = getattr(get_settings, "cache_clear", None)
    if clear is not None:
        clear()


def test_pg_main_exit_codes_and_output_without_values(
    db: PgUrls, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """a5 (P5, TQ-5, TQ-6): `main` đọc DSN từ Settings (`MONITOR_DATABASE_URL` nếu đặt) — 0 khi sạch, 1 khi có bí mật/canary (DB hoặc
    `--log`); `--since` chạy được; đầu ra KHÔNG chứa canary, mật khẩu của role (không in DSN)."""
    sync = create_engine(db.role("app_rw"))
    try:
        with sync.begin() as conn:
            conn.execute(text(f"INSERT INTO users (user_id, username, role) VALUES ('{REQUESTER}', 'graph.nv', 'employee') "
                              "ON CONFLICT DO NOTHING"))  # fmt: skip
        clean, dirty = _sync_ticket(sync, canary=False), _sync_ticket(sync, canary=True)
    finally:
        sync.dispose()
    monkeypatch.setenv("DATABASE_URL", db.role("app_rw"))
    monkeypatch.setenv("MONITOR_DATABASE_URL", db.role("app_monitor"))
    _clear_settings_cache()
    log = tmp_path / "app.log"
    log.write_text(f"INFO ok\nWARN {CANARY}\n", encoding="utf-8")
    try:
        assert main([clean, "--canary", CANARY]) == 0
        assert main([dirty, "--canary", CANARY]) == 1
        since = (T0 + timedelta(days=3650) - timedelta(minutes=1)).isoformat()
        assert main(["--since", since, "--canary", CANARY]) == 1
        assert main([clean, "--canary", CANARY, "--log", str(log)]) == 1
    finally:
        _clear_settings_cache()
    out = capsys.readouterr()
    text_out = out.out + out.err
    assert "bí mật: audit_logs.detail dòng" in text_out and "(luật canary)" in text_out
    assert "bí mật: log dòng 2 (luật canary)" in text_out
    assert "KẾT LUẬN:" in text_out
    assert CANARY not in text_out
    for password in PASSWORDS.values():
        assert password not in text_out
    assert "postgresql" not in text_out
