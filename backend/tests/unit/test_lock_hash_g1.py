"""G1 — khoá ticket dùng `hashtextextended(:t, 0)` (bigint, 64 bit) thay `hashtext(:t)` (int4, 32 bit) ở MỌI chỗ `pg_advisory_*`.

Lý do: `hashtext` chỉ cho 2^32 giá trị — hai ticket khác nhau có thể trùng khoá và chặn nhau (xác suất sinh nhật ~ n²/2^33; với vài chục nghìn
ticket đang mở là đáng kể). `hashtextextended(text, 0)` cho bigint. Lock và unlock PHẢI đổi cùng lúc, cùng một biểu thức: unlock sai khoá
là no-op (Postgres chỉ cảnh báo) và khoá cấp session ở lại trên kết nối trả về pool.

Unit ở đây không cần Postgres: bản ghi lại SQL + quét tĩnh. Chạy thật trên Postgres: `integration/test_lock_pg.py` (TA chạy bằng `make test`).
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from app.db import m5_strategy
from app.graph.lock import PgTicketLock

REPO = Path(__file__).resolve().parents[3]
SOURCES = [*sorted((REPO / "backend" / "app").rglob("*.py")), REPO / "backend" / "tests" / "stack" / "gate2.py"]
BARE_HASHTEXT = re.compile(r"\bhashtext\s*\(")  # KHÔNG khớp `hashtextextended(`
KEY = re.compile(r"pg_advisory_(?:xact_)?(?:un)?lock\((.*)\)")


class RecordingConn:
    def __init__(self, log: list[tuple[str, dict[str, Any]]]) -> None:
        self.log = log

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> None:
        self.log.append((str(stmt), dict(params or {})))

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def invalidate(self) -> None: ...


class RecordingEngine:
    def __init__(self) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[RecordingConn]:
        yield RecordingConn(self.log)


@pytest.mark.asyncio
async def test_lock_and_unlock_use_the_same_64_bit_key_expression() -> None:
    engine = RecordingEngine()
    async with PgTicketLock(engine).hold("ticket-1"):  # type: ignore[arg-type]
        pass
    (lock_sql, lock_params), (unlock_sql, unlock_params) = engine.log
    assert lock_sql == "SELECT pg_advisory_lock(hashtextextended(:t, 0))"
    assert unlock_sql == "SELECT pg_advisory_unlock(hashtextextended(:t, 0))"
    assert lock_params == unlock_params == {"t": "ticket-1"}
    lock_key, unlock_key = KEY.search(lock_sql), KEY.search(unlock_sql)
    assert lock_key and unlock_key and lock_key.group(1) == unlock_key.group(1)  # đổi cùng lúc, cùng biểu thức


@pytest.mark.asyncio
async def test_unlock_still_runs_when_the_body_raises() -> None:
    engine = RecordingEngine()
    with pytest.raises(RuntimeError):
        async with PgTicketLock(engine).hold("ticket-1"):  # type: ignore[arg-type]
            raise RuntimeError("lượt lỗi")
    assert [s for s, _ in engine.log] == [
        "SELECT pg_advisory_lock(hashtextextended(:t, 0))",
        "SELECT pg_advisory_unlock(hashtextextended(:t, 0))",
    ]  # fmt: skip


def test_m5_strategy_lock_uses_64_bit_hash() -> None:
    assert str(m5_strategy._LOCK) == "SELECT pg_advisory_xact_lock(hashtextextended('m5_strategy_changes', 0))"


def test_no_32_bit_hashtext_left_in_app_or_stack_scripts() -> None:
    """Quét tĩnh: không còn `hashtext(` trần ở `backend/app` và script quan sát `gate2` (truy vấn `pg_locks` phải tính ĐÚNG khoá mới)."""
    assert len(SOURCES) > 100
    bad = {str(p.relative_to(REPO)): BARE_HASHTEXT.findall(p.read_text(encoding="utf-8")) for p in SOURCES}
    assert {k: v for k, v in bad.items() if v} == {}


def test_detector_distinguishes_extended_from_bare() -> None:
    assert BARE_HASHTEXT.search("SELECT hashtext(:t)") and BARE_HASHTEXT.search("hashtext (x)")
    assert not BARE_HASHTEXT.search("hashtextextended(:t, 0)")


def test_gate2_pg_locks_query_computes_the_new_key() -> None:
    """`gate2.ticket_lock_count` tìm khoá của ticket trong `pg_locks` bằng cùng hàm băm — lệch hàm thì luôn thấy 0 và kịch bản kill báo
    'khoá nhả' mà không chứng minh gì."""
    src = (REPO / "backend" / "tests" / "stack" / "gate2.py").read_text(encoding="utf-8")
    assert "hashtextextended(" in src and "objsubid = 1" in src


class ExhaustedEngine:
    """Lock pool cạn: `connect()` ném `sqlalchemy.exc.TimeoutError` (QueuePool hết `pool_timeout`) TRƯỚC khi có kết nối."""

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[RecordingConn]:
        from sqlalchemy.exc import TimeoutError as PoolTimeout

        raise PoolTimeout("QueuePool limit reached")
        yield RecordingConn([])  # pragma: no cover


@pytest.mark.asyncio
async def test_e13_lock_pool_exhausted_is_ticket_busy_not_500() -> None:
    """E13 (soát 12/11, agent 04 N6): cạn lock pool → `TicketBusy` (route trả 503 + Retry-After như mọi ca bận), không 500."""
    from app.graph.ports import TicketBusy

    with pytest.raises(TicketBusy):
        async with PgTicketLock(ExhaustedEngine()).hold("ticket-1"):  # type: ignore[arg-type]
            pass
