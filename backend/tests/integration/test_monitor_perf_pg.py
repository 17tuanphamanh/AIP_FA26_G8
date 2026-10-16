"""M9 A4 — hiệu năng trên 10.000 ticket lá (P9 §8 "mỗi truy vấn dashboard < 2 giây", [Chốt T5]) + chỉ mục 0009.

Dữ liệu: `monitor_perf_seed.seed_perf` (tất định) trên DB riêng của module (`fresh_database`, xoá khi xong), `ANALYZE`
bằng `app_migrate`. Mọi truy vấn đọc qua engine THẬT của app (`create_engines` → engine monitor `app_monitor`,
`default_transaction_read_only=on`), trong `read_snapshot` như route.

Ba nhóm test:
1. **< 2 giây** — mỗi truy vấn dashboard (business all + own, ai, response trọn 30/7 ngày, `/api/alerts`), 4 lượt
   `TICKET_EXIT_SQL` (luật 2/16 nhìn lại 24 h, luật 4/6 nhìn lại 192 h) và 4 lượt job luật (`evaluate` phút/giờ/ngày/tuần —
   code Duy Anh, chỉ gọi; Q-M9-A4-10: A4 vào trước, B3 bổ sung `weekly`). Mỗi lượt còn phải ĐO TRÊN DỮ LIỆU THẬT:
   giá trị rỗng (None / 0 / tập rỗng) → đỏ, vì đo trên tập rỗng không chứng minh gì.
2. **Chỉ mục 0009, hai lớp EXPLAIN** (Q-M9-A4-7):
   - lớp 1 — DÙNG ĐƯỢC: `SET LOCAL enable_seqscan = off` → plan phải có đúng tên chỉ mục, cho MỌI chỉ mục và mọi lượt
     nó phục vụ (gồm 3 lượt own của `ix_approvals_ticket`). `TICKET_EXIT_SQL` thêm `EXPLAIN (GENERIC_PLAN)` với `$1/$2`:
     chứng minh chỉ mục MỘT PHẦN dùng được với tham số bind bất kỳ (`exit_code = $1` suy ra `exit_code IS NOT NULL`).
   - lớp 2 — THẬT SỰ ĐƯỢC CHỌN: plan tự nhiên sau `ANALYZE`, CHỈ ở chỗ S3b đã thấy ổn định (4 lượt `TICKET_EXIT_SQL`,
     `automation_rate`). Lượt own chỉ lớp 1 (S3b: plan tự nhiên chưa chọn).
3. **Định nghĩa + migration** — `pg_indexes` đúng cột/vị từ; `0009` downgrade → upgrade (DB riêng) chỉ đổi đúng 2 chỉ mục.

In bảng thời gian + cấu hình Postgres khi module kết thúc — chạy với `-s` để thấy (số đưa vào PR, Q-5).
"""

import asyncio
import json
import os
import platform
import re
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from datetime import timedelta
from typing import Any

import pytest
from alembic import command
from app.db.session import create_engines
from app.monitor.db import read_snapshot
from app.monitor.evaluator import evaluate
from app.monitor.queries import ai, alerts, business
from app.monitor.queries import (
    rules_data as _rules_data,  # noqa: F401 — đăng ký loader cho `evaluate` (như worker.py)
)
from app.monitor.queries.rules_data import TICKET_EXIT_SQL
from app.monitor.rules import RuleContext
from app.monitor.window import VN_TZ
from app.settings import Settings
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.dialects.postgresql import psycopg as pg_psycopg
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration.monitor_perf_seed import (
    BASE,
    DAYS,
    PERF_LEAVES,
    analyze,
    seed_perf,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database

LIMIT_S = 2.0  # P9 §8
FRM, TO = BASE, BASE + timedelta(days=DAYS)  # 30 ngày phủ trọn dữ liệu = ca xấu nhất (trần route 90 ngày)
FRM_7D = TO - timedelta(days=7)  # cửa sổ mặc định của route
APPROVER = "perf-l1-a"
AUDIT_IX = "ix_audit_logs_exit_created_at"
APPROVALS_IX = "ix_approvals_ticket"
# Như test PG của bộ luật (test_monitor_evaluator_savepoint_pg.py): trần N1 ≈ 38 USD — luật 14 chỉ cần số dương.
CTX = RuleContext(now=TO, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)

REPORT: list[tuple[str, float, str]] = []  # (lượt, ms, giá trị) — in khi module kết thúc
META: dict[str, Any] = {}


# ---- dữ liệu --------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def perf(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as db:
        command.upgrade(alembic_config(db), "head")
        t0 = time.perf_counter()
        META["seed"] = asyncio.run(_seed(db.role("app_rw")))
        owner = create_engine(db.role("app_migrate"))
        try:
            with owner.begin() as conn:
                analyze(conn)  # ANALYZE cần chủ bảng — app_rw chỉ nhận WARNING "skipping"
            with owner.connect() as conn:
                META["pg"] = conn.execute(text("SHOW server_version")).scalar()
                META["settings"] = {
                    k: conn.execute(text(f"SHOW {k}")).scalar()
                    for k in ("shared_buffers", "work_mem", "max_parallel_workers_per_gather")
                }
        finally:
            owner.dispose()
        META["seed_s"] = time.perf_counter() - t0
        yield db
    _print_report()


async def _seed(rw_dsn: str) -> Any:
    engine = create_async_engine(rw_dsn)
    try:
        async with engine.begin() as conn:
            return await seed_perf(conn)
    finally:
        await engine.dispose()


def _settings(db: PgUrls) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=db.role("app_rw"),
        monitor_database_url=db.role("app_monitor"),
    )


def _print_report() -> None:
    seed = META.get("seed")
    print(f"\n\n=== A4 hiệu năng — {PERF_LEAVES} ticket lá ===")
    print(f"Postgres {META.get('pg')} · {META.get('settings')} · máy chủ {platform.platform()} · {os.cpu_count()} CPU")
    print(f"seed + ANALYZE: {META.get('seed_s', 0):.1f} s · {seed.line() if seed else ''}")
    print(f"{'lượt':58s} {'ms':>9s}  giá trị")
    for label, ms, value in sorted(REPORT, key=lambda r: -r[1]):
        print(f"{label:58s} {ms:9.1f}  {value}")
    print(f"chậm nhất: {max((ms for _, ms, _ in REPORT), default=0):.1f} ms / trần {LIMIT_S * 1000:.0f} ms\n")


# ---- giá trị rỗng = đo vô nghĩa ------------------------------------------------------------------------------


def _emptiness(value: Any) -> tuple[str, bool]:
    """(mô tả, rỗng?) — rỗng = None, số 0, tập rỗng (như cờ KHÔNG HỢP LỆ của lượt đo S3b)."""
    if value is None:
        return "None", True
    if isinstance(value, bool):
        return str(value), False
    if isinstance(value, int | float):
        return f"{value:g}", value == 0
    if isinstance(value, str):
        return value or "''", value == ""
    if isinstance(value, Mapping):
        return f"{len(value)} khóa", len(value) == 0
    if isinstance(value, list | tuple):
        if value and all(hasattr(v, "cost_usd") for v in value):
            total = sum((v.cost_usd or 0) for v in value)
            return f"{len(value)} ngày, Σ={total:.4f} USD", total == 0
        return f"{len(value)} phần tử", len(value) == 0
    if isinstance(value, business.WeightedRate):
        return f"weighted={value.weighted}", value.weighted is None
    if isinstance(value, business.E1Split):
        return f"total={value.total}", value.total == 0
    if isinstance(value, business.E3Cases):
        return f"{len(value.items)} ca", len(value.items) == 0
    if isinstance(value, alerts.AlertPage):
        return f"{len(value.rows)} cảnh báo", len(value.rows) == 0
    if isinstance(value, business.BusinessMetrics | ai.AiMetrics):
        empty = [k for k, v in value.values.items() if k not in value.unavailable and _emptiness(v)[1]]
        return f"{len(value.values)} khóa, rỗng: {', '.join(empty) or 'không'}", bool(empty)
    return type(value).__name__, False


# ---- 1. mỗi truy vấn < 2 giây, trên dữ liệu thật -------------------------------------------------------------

Query = Callable[..., Awaitable[Any]]


def _dashboard_cases() -> list[Any]:
    cases: list[Any] = []
    for name, fn in business.QUERIES.items():
        if fn is None:
            continue
        cases.append(pytest.param(fn, {"frm": FRM, "to": TO}, id=f"business.{name}[30d]"))
        if name in business.OWN_KEYS:
            cases.append(pytest.param(fn, {"frm": FRM, "to": TO, "approver_id": APPROVER}, id=f"business.{name}[own]"))
    cases += [
        pytest.param(fn, {"frm": FRM, "to": TO}, id=f"ai.{name}[30d]") for name, fn in ai.QUERIES.items() if fn
    ]
    cases += [
        pytest.param(business.business_metrics, {"frm": FRM, "to": TO}, id="business.business_metrics[30d]"),
        pytest.param(business.business_metrics, {"frm": FRM_7D, "to": TO}, id="business.business_metrics[7d]"),
        pytest.param(ai.ai_metrics, {"frm": FRM, "to": TO}, id="ai.ai_metrics[30d]"),
        pytest.param(alerts.list_alerts, {"status": None, "audience": None, "limit": 200}, id="alerts.list[all]"),
        pytest.param(alerts.list_alerts, {"status": "open", "audience": None, "limit": 200}, id="alerts.list[open]"),
    ]
    return cases


TICKET_EXIT_CASES = [
    pytest.param(code, hours, id=f"TICKET_EXIT_SQL[{code},{hours}h]")
    for code, hours in (("E0", 24), ("E7", 24), ("E9", 192), ("E6", 192))
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("fn", "kwargs"), _dashboard_cases())
async def test_dashboard_query_under_2s(
    perf: PgUrls, fn: Query, kwargs: dict[str, Any], request: pytest.FixtureRequest
) -> None:
    engines = create_engines(_settings(perf))
    try:
        async with read_snapshot(engines) as conn:
            t0 = time.perf_counter()
            value = await fn(conn, **kwargs)
            elapsed = time.perf_counter() - t0
    finally:
        await engines.dispose()
    desc, empty = _emptiness(value)
    REPORT.append((request.node.callspec.id, elapsed * 1000, desc))
    assert not empty, f"đo trên tập rỗng — seed không phủ lượt này: {desc}"
    assert elapsed < LIMIT_S, f"{elapsed:.3f} s ≥ {LIMIT_S} s"


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "hours"), TICKET_EXIT_CASES)
async def test_ticket_exit_sql_under_2s(
    perf: PgUrls, code: str, hours: int, request: pytest.FixtureRequest
) -> None:
    """Đúng câu và tham số loader gửi (`rules_data._ticket_exits`), `now` = mép phải dữ liệu."""
    engines = create_engines(_settings(perf))
    try:
        async with read_snapshot(engines) as conn:
            t0 = time.perf_counter()
            rows = (await conn.execute(TICKET_EXIT_SQL, {"code": code, "since": TO - timedelta(hours=hours)})).all()
            elapsed = time.perf_counter() - t0
    finally:
        await engines.dispose()
    REPORT.append((request.node.callspec.id, elapsed * 1000, f"{len(rows)} ticket"))
    assert rows, "đo trên tập rỗng"
    assert elapsed < LIMIT_S, f"{elapsed:.3f} s ≥ {LIMIT_S} s"


@pytest.mark.asyncio
@pytest.mark.parametrize("every", ["minute", "hourly", "daily", "weekly"])
async def test_rule_jobs_under_2s(perf: PgUrls, every: Any) -> None:
    """Một lượt job luật trên engine monitor (như `worker.MonitorRulesJob.run`, không ghi): < 2 giây, không luật lỗi."""
    engines = create_engines(_settings(perf))
    try:
        assert engines.monitor is not None
        async with engines.monitor.connect() as conn:
            t0 = time.perf_counter()
            result = await evaluate(every, conn, CTX)
            elapsed = time.perf_counter() - t0
    finally:
        await engines.dispose()
    REPORT.append((f"evaluate[{every}]", elapsed * 1000, f"{len(result.drafts)} nháp, bỏ qua {result.skipped_rules}"))
    assert result.failed_rules == [], result.failed_rules
    assert elapsed < LIMIT_S, f"{elapsed:.3f} s ≥ {LIMIT_S} s"


# ---- 2. chỉ mục 0009: hai lớp EXPLAIN ------------------------------------------------------------------------


def _index_names(plan: Any) -> set[str]:
    """Mọi `Index Name` trong cây plan JSON (Index Scan, Index Only Scan, Bitmap Index Scan)."""
    found: set[str] = set()
    if isinstance(plan, dict):
        if "Index Name" in plan:
            found.add(plan["Index Name"])
        for v in plan.values():
            found |= _index_names(v)
    elif isinstance(plan, list):
        for v in plan:
            found |= _index_names(v)
    return found


def _scans(plan: Any) -> list[str]:
    """Nút quét của plan (`Seq Scan on approvals`, `Index Scan using … on …`) — cho thông báo khi đỏ."""
    out: list[str] = []
    if isinstance(plan, dict):
        node = plan.get("Node Type", "")
        if "Scan" in node and "Relation Name" in plan:
            out.append(f"{node} {plan.get('Index Name', '')} on {plan['Relation Name']}".replace("  ", " "))
        for v in plan.values():
            out += _scans(v)
    elif isinstance(plan, list):
        for v in plan:
            out += _scans(v)
    return out


class _Recording:
    """Proxy AsyncConnection: ghi (sql, params) của mọi `execute` — EXPLAIN đúng câu code gửi, không chép SQL tay."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.sql: list[tuple[str, Any]] = []

    async def execute(self, clause: Any, params: Any = None) -> Any:
        self.sql.append((str(clause), params))
        return await (self.conn.execute(clause, params) if params is not None else self.conn.execute(clause))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.conn, name)


async def _plan(perf: PgUrls, target: str, *, seqscan_off: bool) -> tuple[set[str], list[str]]:
    """(tên chỉ mục, nút quét) trong plan của lượt `target`, role app_monitor, giao dịch READ ONLY."""
    engines = create_engines(_settings(perf))
    try:
        async with read_snapshot(engines) as conn:
            if seqscan_off:
                await conn.execute(text("SET LOCAL enable_seqscan = off"))
            sql, params = await _target_sql(conn, target)
            rows: Any = (await conn.execute(text("EXPLAIN (FORMAT JSON) " + sql), params or {})).scalar_one()
    finally:
        await engines.dispose()
    plan = rows if not isinstance(rows, str) else json.loads(rows)
    return _index_names(plan), _scans(plan)


async def _target_sql(conn: Any, target: str) -> tuple[str, Any]:
    """Câu SQL (và tham số) mà code thật gửi cho lượt `target` — chạy hàm qua proxy rồi lấy câu chứa `approvals`."""
    if target.startswith("TICKET_EXIT_SQL"):
        code, hours = re.fullmatch(r"TICKET_EXIT_SQL\[(E\d),(\d+)h\]", target).groups()  # type: ignore[union-attr]
        return str(TICKET_EXIT_SQL), {"code": code, "since": TO - timedelta(hours=int(hours))}
    name, scope = re.fullmatch(r"business\.(\w+)\[(30d|own)\]", target).groups()  # type: ignore[union-attr]
    proxy = _Recording(conn)
    kwargs: dict[str, Any] = {"approver_id": APPROVER} if scope == "own" else {}
    await business.QUERIES[name](proxy, FRM, TO, **kwargs)  # type: ignore[misc]
    hits = [(s, p) for s, p in proxy.sql if "approvals" in s]
    assert len(hits) == 1, f"{target}: cần đúng 1 câu đọc approvals, thấy {len(hits)}"
    return hits[0]


# Lớp 1: MỌI chỉ mục × MỌI lượt nó phục vụ.
USABLE = [
    *[pytest.param(f"TICKET_EXIT_SQL[{c},{h}h]", AUDIT_IX, id=f"{AUDIT_IX}:TICKET_EXIT_SQL[{c},{h}h]")
      for c, h in (("E0", 24), ("E7", 24), ("E9", 192), ("E6", 192))],
    pytest.param("business.automation_rate[30d]", APPROVALS_IX, id=f"{APPROVALS_IX}:automation_rate[30d]"),
    *[pytest.param(f"business.{k}[own]", APPROVALS_IX, id=f"{APPROVALS_IX}:{k}[own]") for k in business.OWN_KEYS],
]  # fmt: skip
# Lớp 2: chỉ chỗ S3b đã thấy plan tự nhiên chọn chỉ mục (lượt own KHÔNG có ở đây).
CHOSEN = [
    *[pytest.param(f"TICKET_EXIT_SQL[{c},{h}h]", AUDIT_IX, id=f"{AUDIT_IX}:TICKET_EXIT_SQL[{c},{h}h]")
      for c, h in (("E0", 24), ("E7", 24), ("E9", 192), ("E6", 192))],
    pytest.param("business.automation_rate[30d]", APPROVALS_IX, id=f"{APPROVALS_IX}:automation_rate[30d]"),
]  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.parametrize(("target", "index"), USABLE)
async def test_index_usable_with_seqscan_off(perf: PgUrls, target: str, index: str) -> None:
    """Lớp 1: tắt seqscan → planner PHẢI dùng được chỉ mục. Không dùng được (vị từ chỉ mục một phần không suy ra
    được, cột sai…) thì planner vẫn buộc phải quét cả bảng, tên chỉ mục không xuất hiện."""
    names, scans = await _plan(perf, target, seqscan_off=True)
    assert index in names, f"{target}: không thấy {index} — nút quét: {scans}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("target", "index"), CHOSEN)
async def test_index_chosen_naturally(perf: PgUrls, target: str, index: str) -> None:
    """Lớp 2: plan tự nhiên trên 10.000 lá sau ANALYZE chọn chỉ mục (như S3b)."""
    names, scans = await _plan(perf, target, seqscan_off=False)
    assert index in names, f"{target}: plan tự nhiên không chọn {index} — nút quét: {scans}"


@pytest.mark.asyncio
async def test_ticket_exit_partial_index_generic_plan(perf: PgUrls) -> None:
    """Chỉ mục MỘT PHẦN dùng được với tham số bind BẤT KỲ: `EXPLAIN (GENERIC_PLAN)` (PG16) đúng câu loader, `:code`/
    `:since` thành `$1`/`$2` (không có giá trị cụ thể) — planner phải tự suy `exit_code = $1` ⇒ `exit_code IS NOT NULL`."""
    compiled = str(TICKET_EXIT_SQL.compile(dialect=pg_psycopg.dialect()))
    generic = compiled.replace("%(code)s", "$1").replace("%(since)s", "$2").replace("%%", "%")
    assert "%(" not in generic and "$1" in generic and "$2" in generic
    engines = create_engines(_settings(perf))
    try:
        async with read_snapshot(engines) as conn:
            await conn.execute(text("SET LOCAL enable_seqscan = off"))
            raw = await conn.exec_driver_sql("EXPLAIN (GENERIC_PLAN, FORMAT JSON) " + generic)
            plan = raw.scalar_one()
    finally:
        await engines.dispose()
    plan = plan if not isinstance(plan, str) else json.loads(plan)
    assert AUDIT_IX in _index_names(plan), _scans(plan)


# ---- 3. định nghĩa chỉ mục + migration 0009 -------------------------------------------------------------------

INDEX_DEFS = {
    AUDIT_IX: "CREATE INDEX ix_audit_logs_exit_created_at ON public.audit_logs USING btree (created_at) "
              "WHERE (exit_code IS NOT NULL)",
    APPROVALS_IX: "CREATE INDEX ix_approvals_ticket ON public.approvals USING btree (ticket_id)",
}  # fmt: skip


def _indexes(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")).all()
    return {name: definition for name, definition in rows}


def test_index_definitions(perf: PgUrls) -> None:
    """Đúng bảng, đúng cột, đúng vị từ (`WHERE exit_code IS NOT NULL` — thiếu vị từ là phương án B lớn ~12 lần)."""
    engine = create_engine(perf.role("app_migrate"))
    try:
        found = _indexes(engine)
    finally:
        engine.dispose()
    assert {k: found.get(k) for k in INDEX_DEFS} == INDEX_DEFS


def test_migration_0009_down_up(pg: PgUrls) -> None:
    """`downgrade 0008` xoá ĐÚNG 2 chỉ mục của 0009 (không đụng chỉ mục khác); `upgrade head` dựng lại y hệt."""
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "head")
        engine = create_engine(db.role("app_migrate"))
        try:
            before = _indexes(engine)
            assert set(INDEX_DEFS) <= set(before)
            command.downgrade(cfg, "0008")
            assert _indexes(engine) == {k: v for k, v in before.items() if k not in INDEX_DEFS}
            command.upgrade(cfg, "head")
            assert _indexes(engine) == before
        finally:
            engine.dispose()
