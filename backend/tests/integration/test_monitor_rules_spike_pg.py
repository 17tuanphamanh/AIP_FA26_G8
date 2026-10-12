"""M9-B2 GĐ2 cụm 1 — loader luật 60 s 4 `e9_spike`, 6 `e6_spike`, 5 `breaker_open` (`queries/rules_data.py`) +
`evaluate("minute")` trên Postgres 16 thật, đọc bằng role `app_monitor`.

Cô lập: module riêng = DB riêng. Luật 4/6 là luật TỔNG HỢP (subject `SYSTEM_SUBJECT`, đếm toàn hệ thống) → không lọc được
theo subject như B1: mỗi ca một mốc `rs.spike_now(k)` riêng, cách nhau 10 ngày (> đọc lùi `spike_since` + 25 giờ đánh
giá — `test_spike_slots_isolated`). Dữ liệu tương lai của ca khác không ảnh hưởng: luật chỉ đánh giá giờ ≤ giờ hiện tại
và trung vị lấy 168 giờ TRƯỚC. Dữ liệu E9 và E6 độc lập (loader lọc theo mã) → hai tham số của một ca dùng chung mốc.
Nguồn: kế hoạch chung M9 mục 6 (luật 4, 5, 6; "Trung vị 7 ngày"); thẻ B2 ("luật 4/6 với trung vị 0 và 2 ca → không
báo"); chốt Q-M9-B2-2, 5, 10, 12 ở #14 (comment 5959974287); Q-M9-4 (hợp đồng span dự kiến của luật 5).
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.domain.alerts import SYSTEM_SUBJECT
from app.monitor.evaluator import EvalResult, evaluate
from app.monitor.queries import rules_data
from app.monitor.rules import RuleContext, spike_since
from app.monitor.window import VN_TZ, hour_start
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
MIN = timedelta(minutes=1)
S = timedelta(seconds=1)

SPIKE = pytest.mark.parametrize(("rule_id", "code"), [("e9_spike", "E9"), ("e6_spike", "E6")], ids=["E9", "E6"])
OTHER = {"e9_spike": "e6_spike", "e6_spike": "e9_spike"}


@pytest.fixture(scope="module")
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def mon(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_monitor"))
    yield engine
    await engine.dispose()


async def run(mon: AsyncEngine, now: datetime) -> EvalResult:
    async with mon.connect() as conn:  # như job: một connection, không transaction ngoài
        return await evaluate("minute", conn, RuleContext(now=now, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8))


def hours(result: EvalResult, rule_id: str) -> list[datetime]:
    """`window_start` các draft của luật tổng hợp `rule_id`; luật không lỗi, không bị bỏ qua, subject hằng hệ thống."""
    assert rule_id not in result.failed_rules and rule_id not in result.skipped_rules
    drafts = [d for d in result.drafts if d.rule_id == rule_id]
    assert all(d.subject == SYSTEM_SUBJECT for d in drafts)
    return [d.window_start for d in drafts]


def test_spike_slots_isolated() -> None:
    """Mỗi mốc cách nhau hơn phần loader đọc lùi (`spike_since`, ~192,5 giờ) + 25 giờ được đánh giá."""
    now = rs.spike_now(0)
    assert rs.SPIKE_SLOT > (now - spike_since(RuleContext(now, VN_TZ, 38.0, 0.8))) + 25 * H
    assert now.minute == 30 and now.tzinfo is UTC


# ---- ngưỡng: vượt / không / bằng --------------------------------------------------------------------------------------


@SPIKE
@pytest.mark.parametrize(("k", "n", "expected_h0"), [(1, 2, False), (2, 3, True)], ids=["2-ca", "3-ca"])
@pytest.mark.asyncio
async def test_spike_median0(
    rule_id: str, code: str, k: int, n: int, expected_h0: bool, rw: AsyncEngine, mon: AsyncEngine
) -> None:
    """Trung vị 0 (không có lịch sử): 2 ca → KHÔNG báo (thẻ B2); đúng tối thiểu 3 ca → báo, `window_start` = đầu giờ."""
    now = rs.spike_now(k)
    h0 = hour_start(now)
    async with rw.begin() as conn:
        await rs.spike_leaves(conn, code, hour=h0, n=n)
    assert hours(await run(mon, now), rule_id) == ([h0] if expected_h0 else [])


@SPIKE
@pytest.mark.parametrize(("k", "n", "expected_h0"), [(3, 3, False), (4, 4, True)], ids=["bang-3x1", "vuot"])
@pytest.mark.asyncio
async def test_spike_median1(
    rule_id: str, code: str, k: int, n: int, expected_h0: bool, rw: AsyncEngine, mon: AsyncEngine
) -> None:
    """85 giờ có 1 ca ở `H0 − k giờ`, k = 84…168 (gồm giờ cũ nhất `H0 − 168`) + 83 giờ trống → trung vị 1,0. Đúng bằng
    3 × 1 → không báo; 4 ca → báo. Đọc đủ 168 giờ trước H0 nhờ mốc dưới `spike_since` (đọc từ `now − 24 giờ` → trung vị
    0 → 3 ca đã báo)."""
    now = rs.spike_now(k)
    h0 = hour_start(now)
    async with rw.begin() as conn:
        for back in range(84, 169):
            await rs.spike_leaf(conn, code, at=h0 - back * H + 30 * MIN)
        await rs.spike_leaves(conn, code, hour=h0, n=n)
    assert hours(await run(mon, now), rule_id) == ([h0] if expected_h0 else [])


@SPIKE
@pytest.mark.parametrize(
    ("k", "shift", "back_hours"),
    [(5, timedelta(0), 24), (6, -(29 * MIN + 30 * S), None)],
    ids=["12h30-trong-H24", "12h00m30-ra-H25"],
)
@pytest.mark.asyncio
async def test_spike_lookback_edge(
    rule_id: str, code: str, k: int, shift: timedelta, back_hours: int | None, rw: AsyncEngine, mon: AsyncEngine
) -> None:
    """3 lá ra mã ĐÚNG `now − 24 giờ − 60 s`. now = 12:30 → 12:29 hôm trước, thuộc giờ cũ nhất còn được đánh giá
    (H24) → báo, khoá H24. now = 12:00:30 → 11:59:30 hôm trước, thuộc H25 (chỉ còn trong trung vị) → không báo."""
    now = rs.spike_now(k) + shift
    at = now - 24 * H - 60 * S
    async with rw.begin() as conn:
        for _ in range(3):
            await rs.spike_leaf(conn, code, at=at)
    expected = [] if back_hours is None else [hour_start(now) - back_hours * H]
    assert hours(await run(mon, now), rule_id) == expected


# ---- nguồn: v_leaf, mốc ra mã, đúng mã -------------------------------------------------------------------------------


@SPIKE
@pytest.mark.asyncio
async def test_spike_parent_not_counted(rule_id: str, code: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """D-30: 2 lá + 1 ticket CHA cùng giờ ra mã → chỉ 2 ca qua `v_leaf` → không báo (đếm cả cha thì 3 → báo)."""
    now = rs.spike_now(7)
    h0 = hour_start(now)
    async with rw.begin() as conn:
        await rs.spike_leaves(conn, code, hour=h0, n=2)
        await rs.spike_parent(conn, code, at=h0 + 20 * MIN)
    assert hours(await run(mon, now), rule_id) == []


@SPIKE
@pytest.mark.asyncio
async def test_spike_leaf_counted_once_at_first_row(
    rule_id: str, code: str, rw: AsyncEngine, mon: AsyncEngine
) -> None:
    """Một lá đếm MỘT lần, ở giờ dòng mang mã ĐẦU TIÊN (`first_at`, Q-M9-B2-5): 3 lá ở giờ h, một lá có thêm dòng ở
    h+1, cộng 2 lá khác ở h+1 → chỉ h báo (đếm mỗi dòng thì h+1 có 3 ca → báo sai)."""
    now = rs.spike_now(8)
    h = hour_start(now) - 2 * H
    async with rw.begin() as conn:
        first, *_ = await rs.spike_leaves(conn, code, hour=h, n=3)
        await rs.spike_row(conn, first, code, at=h + H + 15 * MIN)
        await rs.spike_leaves(conn, code, hour=h + H, n=2)
    assert hours(await run(mon, now), rule_id) == [h]


@pytest.mark.asyncio
async def test_e6_counted_at_exit_hour_not_ticket_created(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B2-5: E6 ghi lúc HẾT HẠN, sau `tickets.created_at` cả giờ SLA → đếm theo giờ ra mã (h), không theo giờ tạo
    ticket (h − 5 giờ)."""
    now = rs.spike_now(9)
    h = hour_start(now) - H
    async with rw.begin() as conn:
        for i in range(3):
            await rs.spike_leaf(conn, "E6", at=h + (10 + i) * MIN, created_at=h - 5 * H + (10 + i) * MIN)
    assert hours(await run(mon, now), "e6_spike") == [h]


@SPIKE
@pytest.mark.asyncio
async def test_spike_code_isolated(rule_id: str, code: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """3 lá chỉ mang mã của luật này → luật này báo, luật kia (mã khác) không: loader đọc ĐÚNG mã của luật. Mỗi tham số
    một mốc riêng (luật kia phải thấy 0 ca)."""
    now = rs.spike_now(10 if code == "E9" else 11)
    h0 = hour_start(now)
    async with rw.begin() as conn:
        await rs.spike_leaves(conn, code, hour=h0, n=3)
    result = await run(mon, now)
    assert hours(result, rule_id) == [h0]
    assert hours(result, OTHER[rule_id]) == []


# ---- luật 5 breaker_open ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breaker_pending_skipped(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Nguồn `tool_spans` pending (Q-M9-4): có cả span `circuit_open` thật trong DB → luật vẫn vào `skipped_rules`, 0
    draft, không lỗi (pending đến từ `is_pending`, không phải từ việc thiếu dữ liệu)."""
    now = rs.spike_now(12)
    async with rw.begin() as conn:
        await rs.tool_span(conn, name=seed.new_id("tool:pending"), at=now - 5 * MIN)
    result = await run(mon, now)
    assert "breaker_open" in result.skipped_rules and "breaker_open" not in result.failed_rules
    assert [d for d in result.drafts if d.rule_id == "breaker_open"] == []


@pytest.mark.asyncio
async def test_breaker_loader_ready_reads_contract(
    rw: AsyncEngine, mon: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nhánh khi nguồn ready (vá RIÊNG khoá `tool_spans`): `app_monitor` đọc được `spans`; 2 tool `circuit_open` cùng lúc
    → 2 draft (luật theo đối tượng). Không đọc span `status='ok'`, `error='timeout'`, `span_type='llm'`."""
    real = rules_data.is_pending
    monkeypatch.setattr(rules_data, "is_pending", lambda key: False if key == "tool_spans" else real(key))
    now = rs.spike_now(13)
    at = now - 10 * MIN
    ad, mail = seed.new_id("tool:ad"), seed.new_id("tool:mail")
    noise = {
        seed.new_id("tool:ok"): {"status": "ok"},
        seed.new_id("tool:timeout"): {"error": "timeout"},
        seed.new_id("llm:x"): {"span_type": "llm"},
    }
    async with rw.begin() as conn:
        for name in (ad, mail):
            await rs.tool_span(conn, name=name, at=at)
        for name, fields in noise.items():
            await rs.tool_span(conn, name=name, at=at, **fields)
    result = await run(mon, now)
    assert "breaker_open" not in result.failed_rules and "breaker_open" not in result.skipped_rules
    mine = sorted((d.subject, d.window_start) for d in result.drafts if d.rule_id == "breaker_open"
                  and d.subject in {ad, mail, *noise})  # fmt: skip
    assert mine == sorted([(ad, at), (mail, at)])
