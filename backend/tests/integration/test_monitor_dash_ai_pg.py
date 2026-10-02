"""M9 A2 — 12 chỉ số dashboard AI/LLMOps trên Postgres 16 thật, đọc bằng role `app_monitor` (kế hoạch M9 5.2, 4.3; chốt
[C-A2] ở #9).

Mỗi test một ngày riêng của tháng 1/2030 làm cửa sổ (`cost_per_day` dùng tháng 2); số kỳ vọng tính tay trong chú thích.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.monitor.queries import ai
from app.monitor.queries.ai import DayCost
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
PENDING = ("multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn")


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


def win(day: int) -> tuple[datetime, datetime]:
    frm = datetime(2030, 1, day, tzinfo=UTC)
    return frm, frm + timedelta(days=1)


def at(day: int, hours: int = 1) -> datetime:
    return win(day)[0] + hours * H


async def q(mon: AsyncEngine, fn: Callable[..., Awaitable[Any]], day: int) -> Any:
    async with mon.connect() as conn:
        return await fn(conn, *win(day))


async def done(conn: AsyncConnection, created_at: datetime, **kw: Any) -> str:
    """Lá đã kết thúc (vào mẫu số `tokens_per_ticket`)."""
    kw.setdefault("final_state", "S_RESOLVED")
    kw.setdefault("resolution_path", "auto")
    return await seed.leaf_ticket(conn, created_at=created_at, **kw)


async def e_leaf(conn: AsyncConnection, created_at: datetime, code: str, reason: str | None = None) -> str:
    ticket = await seed.leaf_ticket(
        conn, created_at=created_at, exit_code=code, final_state="S_ESCALATED", resolution_path="escalated"
    )
    if reason is not None:
        await seed.escalation(conn, ticket, exit_code=code, created_at=created_at, reason_detail=reason)
    return ticket


async def node_span(
    conn: AsyncConnection, ticket: str, started_at: datetime, name: str, ms: int | None, status: str = "ok"
) -> None:
    turn = await seed.turn(conn, ticket, started_at=started_at)
    await seed.span(conn, turn, name=name, started_at=started_at, duration_ms=ms, status=status)


async def audit(conn: AsyncConnection, ticket: str, step: str, event: str, created_at: datetime, **detail: Any) -> None:
    await seed.audit_row(conn, ticket, step=step, event=event, created_at=created_at, detail=detail)


def b2(layer: str) -> dict[str, Any]:
    return {"screening": {"layer_decided": layer}}


@pytest.mark.asyncio
async def test_tokens_per_ticket_hand(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """A: 100+50; B: (30+20) + (NULL+NULL = 0); C: không lời gọi; D: đang chạy 2000 token → không vào. 200 / 2 = 100."""
    async with rw.begin() as conn:
        a, b = await done(conn, at(1)), await done(conn, at(1))
        await done(conn, at(1))
        running = await seed.leaf_ticket(conn, created_at=at(1))
        await seed.llm_call_for(conn, a, created_at=at(1), tokens_in=100, tokens_out=50)
        await seed.llm_call_for(conn, b, created_at=at(1), tokens_in=30, tokens_out=20)
        await seed.llm_call_for(conn, b, created_at=at(1), tokens_in=None, tokens_out=None)
        await seed.llm_call_for(conn, running, created_at=at(1), tokens_in=1000, tokens_out=1000)
    assert await q(mon, ai.tokens_per_ticket, 1) == 100.0


@pytest.mark.asyncio
async def test_cost_per_day_vn_days(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Cửa sổ 3 ngày VN từ 2030-02-02 00:00 VN (= 02-01 17:00 UTC). 23:30 UTC = 06:30 VN hôm sau và 16:59 UTC = 23:59 VN
    → ngày 1: 0,5 + 0,25; 17:00 UTC = 00:00 VN → ngày 2: 1,0; ngày 3 trống → 0,0; lời gọi trước `frm` không tính.
    Cắt theo UTC thì 23:30 và 16:59 rơi vào hai ngày khác nhau → đỏ."""
    day1 = datetime(2030, 2, 1, 17, tzinfo=UTC)
    async with rw.begin() as conn:
        leaf = await done(conn, day1)
        for ts, cost in [
            (datetime(2030, 2, 1, 23, 30, tzinfo=UTC), 0.5),
            (datetime(2030, 2, 2, 16, 59, tzinfo=UTC), 0.25),
            (datetime(2030, 2, 2, 17, 0, tzinfo=UTC), 1.0),
            (datetime(2030, 2, 1, 16, 59, tzinfo=UTC), 9.0),  # trước frm
        ]:
            await seed.llm_call_for(conn, leaf, created_at=ts, cost_usd=cost)
    async with mon.connect() as conn:
        got = await ai.cost_per_day(conn, day1, day1 + timedelta(days=3))
    assert got == (
        DayCost(day1, 0.75), DayCost(day1 + timedelta(days=1), 1.0), DayCost(day1 + timedelta(days=2), 0.0),
    )  # fmt: skip


@pytest.mark.asyncio
async def test_latency_p95_twenty_spans(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """20 span `node:b03_classify` = 10, 20, …, 200 ms (1 span `error` vẫn tính) → vị trí 0,95·19 = 18,05 → 190 + 0,05·10
    = 190,5 (`percentile_disc` ra 200). `node:b02_screen` 1 span 50. Span `llm` 9999 ms và span `duration_ms` NULL
    không tính."""
    async with rw.begin() as conn:
        leaf = await done(conn, at(3))
        for i in range(1, 21):
            await node_span(conn, leaf, at(3), "node:b03_classify", 10 * i, status="error" if i == 20 else "ok")
        await node_span(conn, leaf, at(3), "node:b02_screen", 50)
        await node_span(conn, leaf, at(3), "node:b02_screen", None)
        turn = await seed.turn(conn, leaf, started_at=at(3))
        await seed.span(conn, turn, name="node:b03_classify", started_at=at(3), duration_ms=9999, span_type="llm")
    got = await q(mon, ai.latency_p95_by_step, 3)
    assert set(got) == {"node:b02_screen", "node:b03_classify"}
    assert got["node:b03_classify"] == pytest.approx(190.5)
    assert got["node:b02_screen"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_call_rates_hand(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """5 lời gọi trên 2 lá: cache T, T, F, F, F → 2/5; fallback T, F, F, F, F → 1/5."""
    async with rw.begin() as conn:
        a, b = await done(conn, at(4)), await seed.leaf_ticket(conn, created_at=at(4))
        for leaf, cache, fb in [(a, True, True), (a, True, False), (b, False, False), (b, False, False), (b, False, False)]:
            await seed.llm_call_for(conn, leaf, created_at=at(4), cache_hit=cache, used_fallback=fb)
    assert await q(mon, ai.cache_hit_rate, 4) == pytest.approx(0.4)
    assert await q(mon, ai.fallback_rate, 4) == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_json_null_not_error(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """`json_valid_first_try` F, T, T, NULL, NULL → 1/3 (NULL đếm là lỗi ra 3/5; NULL vào mẫu ra 1/5). Toàn NULL → None."""
    async with rw.begin() as conn:
        leaf = await done(conn, at(5))
        for value in (False, True, True, None, None):
            await seed.llm_call_for(conn, leaf, created_at=at(5), json_valid_first_try=value)
        other = await done(conn, at(6))
        for _ in range(2):
            await seed.llm_call_for(conn, other, created_at=at(6), json_valid_first_try=None)
    assert await q(mon, ai.json_invalid_first_try_rate, 5) == pytest.approx(1 / 3)
    assert await q(mon, ai.json_invalid_first_try_rate, 6) is None


@pytest.mark.asyncio
async def test_e2_llm_count_excludes_4b(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """E2 do LLM: llm_unavailable, llm_schema_error, screening_unavailable → 3. Không tính: 2 lý do Phase 4b,
    rag_system_error, turn_budget_exceeded; lá có dòng E2 cũ `llm_unavailable` nhưng dòng MỚI NHẤT `approver_lookup_error`;
    lá E9 có escalation `llm_unavailable`."""
    async with rw.begin() as conn:
        for reason in (
            "llm_unavailable", "llm_schema_error", "screening_unavailable", "approver_lookup_error",
            "approver_sync_unavailable", "rag_system_error", "turn_budget_exceeded",
        ):  # fmt: skip
            await e_leaf(conn, at(7), "E2", reason)
        latest = await e_leaf(conn, at(7), "E2", "llm_unavailable")
        await seed.escalation(conn, latest, exit_code="E2", created_at=at(7, 2), reason_detail="approver_lookup_error")
        await e_leaf(conn, at(7), "E9", "llm_unavailable")
    assert await q(mon, ai.e2_llm_count, 7) == 3


@pytest.mark.asyncio
async def test_e9_count_hand(rw: AsyncEngine, mon: AsyncEngine) -> None:
    async with rw.begin() as conn:
        await e_leaf(conn, at(8), "E9")
        await e_leaf(conn, at(8), "E9")
        await e_leaf(conn, at(8), "E2", "llm_unavailable")
    assert await q(mon, ai.e9_count, 8) == 2


@pytest.mark.asyncio
async def test_b2_llm_rate_path(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-A2-5: llm, llm, classifier, regex + 1 `guard_unavailable` → 3/5 = 0,6. Không tính: `turn_budget_exceeded`
    (không có screening), dòng ghi `layer_decided` sai chỗ (`detail.layer_decided`), dòng step khác B2."""
    async with rw.begin() as conn:
        leaf = await seed.leaf_ticket(conn, created_at=at(9))
        await audit(conn, leaf, "B2", "screened", at(9), **b2("llm"))
        await audit(conn, leaf, "B2", "injection_detected", at(9), **b2("llm"))
        await audit(conn, leaf, "B2", "screened", at(9), **b2("classifier"))
        await audit(conn, leaf, "B2", "injection_detected", at(9), **b2("regex"))
        await audit(conn, leaf, "B2", "guard_unavailable", at(9), ml_error="model_missing", llm_error="LLMUnavailable")
        await audit(conn, leaf, "B2", "turn_budget_exceeded", at(9), error="TurnBudgetExceeded")
        await audit(conn, leaf, "B2", "screened", at(9), layer_decided="llm")
        await audit(conn, leaf, "B3", "intent_classified", at(9), **b2("llm"))
    assert await q(mon, ai.b2_llm_rate, 9) == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_intent_filter_fallback_hand(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """B8: true, false, false, NULL (`retrieval_error`), "abc" (giá trị lệch kiểu) → 1/3. "abc" vào mẫu thì ra 1/4; ép
    `::boolean` thì cả truy vấn lỗi (Q-A2; không dùng yes/1/t/on vì `::boolean` coi là hợp lệ)."""
    async with rw.begin() as conn:
        leaf = await seed.leaf_ticket(conn, created_at=at(10))
        for value in (True, False, False):
            await audit(conn, leaf, "B8", "retrieved", at(10), intent_filter_fallback=value)
        await audit(conn, leaf, "B8", "retrieval_error", at(10), intent_filter_fallback=None)
        await audit(conn, leaf, "B8", "retrieved", at(10), intent_filter_fallback="abc")
    assert await q(mon, ai.intent_filter_fallback_rate, 10) == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_b3_llm_rate_counts_b4(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Ngày 11: B3 llm, B4 llm (ca E1), B3 `layer` NULL (`max_loops_exceeded`) → 2/2 = 1,0 (chỉ đếm B3 ra 1/1 vẫn 1,0 nên
    ngày 12 thêm B3 `layer='model'`: 2/3; chỉ B3 ra 1/2)."""
    async with rw.begin() as conn:
        for day in (11, 12):
            leaf = await seed.leaf_ticket(conn, created_at=at(day))
            await audit(conn, leaf, "B3", "intent_classified", at(day), layer="llm")
            await audit(conn, leaf, "B4", "intent_out_of_scope", at(day), layer="llm")
            await audit(conn, leaf, "B3", "max_loops_exceeded", at(day), layer=None)
        await audit(conn, leaf, "B3", "intent_classified", at(12), layer="model")
    assert await q(mon, ai.b3_llm_rate, 11) == 1.0
    assert await q(mon, ai.b3_llm_rate, 12) == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_intent_model_version_latest_non_null(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """B3 v1 (01:00), B4 v2 (02:00), B3 NULL (03:00), B2 `x` (04:00, step khác) → "v2". Ngày không có → None."""
    async with rw.begin() as conn:
        leaf = await seed.leaf_ticket(conn, created_at=at(13))
        await audit(conn, leaf, "B3", "intent_classified", at(13, 1), layer="llm", model_version="v1")
        await audit(conn, leaf, "B4", "intent_low_confidence", at(13, 2), layer="llm", model_version="v2")
        await audit(conn, leaf, "B3", "intent_classified", at(13, 3), layer="llm", model_version=None)
        await audit(conn, leaf, "B2", "screened", at(13, 4), model_version="x")
    assert await q(mon, ai.intent_model_version, 13) == "v2"
    assert await q(mon, ai.intent_model_version, 14) is None


@pytest.mark.asyncio
async def test_zero_denominator_none(mon: AsyncEngine) -> None:
    """Ngày 15 trống: tỉ lệ + `tokens_per_ticket` → None (không 0); đếm → 0; latency → {}; cost → 2 ngày VN giao với
    ngày UTC, đều 0,0."""
    async with mon.connect() as conn:
        got = await ai.ai_metrics(conn, *win(15))
    for key in (
        "tokens_per_ticket", "cache_hit_rate", "json_invalid_first_try_rate", "fallback_rate", "b2_llm_rate",
        "intent_filter_fallback_rate", "b3_llm_rate", "intent_model_version",
    ):  # fmt: skip
        assert got.values[key] is None, key
    assert (got.values["e2_llm_count"], got.values["e9_count"]) == (0, 0)
    assert got.values["latency_p95_by_step"] == {}
    vn = datetime(2030, 1, 14, 17, tzinfo=UTC)
    assert got.values["cost_per_day"] == (DayCost(vn, 0.0), DayCost(vn + timedelta(days=1), 0.0))


@pytest.mark.asyncio
async def test_parent_with_llm_calls_excluded(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """D-30 lớp 1 — cha kết cục KHÁC con và mang mọi nguồn A2 với số "xấu": lời gọi 2000 token / cache / JSON lỗi /
    fallback / 5 USD, span 9999 ms, B2 llm, B3 llm, B8 fallback, model_version mới hơn, E2 `llm_unavailable` (cha 1)
    và E9 (cha 2). 2 con đã xong: mỗi con 1 lời gọi 10+10 token, 0,1 USD, không cache/fallback, JSON đúng; span 100 ms;
    B2 classifier; B3 `model`; B8 false. Chỉ lá: mọi tỉ lệ 0,0, token 20, p95 100, E2/E9 0, model "child-v", cost 0,2.
    Đọc cả cha thì mọi số đều lệch → đỏ."""
    async with rw.begin() as conn:
        p1, kids = await seed.parent_with_children(
            conn, created_at=at(16), parent_exit_code="E2", parent_final_state="S_ESCALATED",
            final_state="S_RESOLVED", resolution_path="auto",
        )  # fmt: skip
        await seed.escalation(conn, p1, exit_code="E2", created_at=at(16), reason_detail="llm_unavailable")
        await seed.parent_with_children(conn, 1, created_at=at(16), parent_exit_code="E9", final_state="S_RESOLVED")
        await seed.llm_call_for(
            conn, p1, created_at=at(16), tokens_in=1000, tokens_out=1000, cost_usd=5.0, cache_hit=True,
            json_valid_first_try=False, used_fallback=True,
        )  # fmt: skip
        await node_span(conn, p1, at(16), "node:b02_screen", 9999)
        await audit(conn, p1, "B2", "screened", at(16), **b2("llm"))
        await audit(conn, p1, "B3", "intent_classified", at(16, 3), layer="llm", model_version="parent-v")
        await audit(conn, p1, "B8", "retrieved", at(16), intent_filter_fallback=True)
        for kid in kids:
            await seed.llm_call_for(conn, kid, created_at=at(16), tokens_in=10, tokens_out=10, cost_usd=0.1)
            await node_span(conn, kid, at(16), "node:b02_screen", 100)
            await audit(conn, kid, "B2", "screened", at(16), **b2("classifier"))
            await audit(conn, kid, "B3", "intent_classified", at(16, 2), layer="model", model_version="child-v")
            await audit(conn, kid, "B8", "retrieved", at(16), intent_filter_fallback=False)
    async with mon.connect() as conn:
        got = (await ai.ai_metrics(conn, *win(16))).values
    assert got["tokens_per_ticket"] == 20.0
    for key in ("cache_hit_rate", "json_invalid_first_try_rate", "fallback_rate", "b2_llm_rate", "b3_llm_rate",
                "intent_filter_fallback_rate"):  # fmt: skip
        assert got[key] == 0.0, key
    assert got["latency_p95_by_step"] == {"node:b02_screen": pytest.approx(100.0)}
    assert (got["e2_llm_count"], got["e9_count"]) == (0, 0)
    assert got["intent_model_version"] == "child-v"
    assert [round(d.cost_usd, 6) for d in got["cost_per_day"]] == [0.2, 0.0]


@pytest.mark.asyncio
async def test_running_leaf_scope(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-A2-7 phương án A: 1 lá đã xong + 1 lá ĐANG CHẠY. Chỉ số theo lời gọi / dòng audit / span tính cả hai (0,5;
    p95 của 100 và 300 = 290; cost 0,1 + 0,2); chỉ `tokens_per_ticket` lọc lá đã kết thúc (10, không phải 505)."""
    async with rw.begin() as conn:
        fin, run = await done(conn, at(20)), await seed.leaf_ticket(conn, created_at=at(20))
        for leaf, flag, layer, b3, ms, cost, tokens in [
            (fin, False, "classifier", "model", 100, 0.1, 10), (run, True, "llm", "llm", 300, 0.2, 1000),
        ]:  # fmt: skip
            await seed.llm_call_for(
                conn, leaf, created_at=at(20), cache_hit=flag, used_fallback=flag, cost_usd=cost, tokens_in=tokens
            )
            await audit(conn, leaf, "B2", "screened", at(20), **b2(layer))
            await audit(conn, leaf, "B3", "intent_classified", at(20), layer=b3)
            await audit(conn, leaf, "B8", "retrieved", at(20), intent_filter_fallback=flag)
            await node_span(conn, leaf, at(20), "node:b02_screen", ms)
    async with mon.connect() as conn:
        got = (await ai.ai_metrics(conn, *win(20))).values
    for key in ("cache_hit_rate", "fallback_rate", "b2_llm_rate", "b3_llm_rate", "intent_filter_fallback_rate"):
        assert got[key] == pytest.approx(0.5), key
    assert got["latency_p95_by_step"]["node:b02_screen"] == pytest.approx(290.0)
    assert [round(d.cost_usd, 6) for d in got["cost_per_day"]] == [0.3, 0.0]
    assert got["tokens_per_ticket"] == 10.0


@pytest.mark.asyncio
async def test_ai_metrics_all_keys_and_unavailable(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Đủ 14 khóa; chỉ 2 khóa nhiều ý vào `unavailable` (None). `intent_model_version` None (Phase 3–4, model_missing)
    nhưng KHÔNG vào `unavailable` (Q-M9-A2-1)."""
    async with rw.begin() as conn:
        leaf = await seed.leaf_ticket(conn, created_at=at(17))
        await audit(conn, leaf, "B3", "intent_classified", at(17), layer="llm", model_version=None)
    async with mon.connect() as conn:
        got = await ai.ai_metrics(conn, *win(17))
    assert list(got.values) == list(ai.AI_METRICS)
    assert got.unavailable == PENDING
    for key in PENDING:
        assert got.values[key] is None
    assert got.values["intent_model_version"] is None
    assert got.values["b3_llm_rate"] == 1.0


@pytest.mark.asyncio
async def test_window_bounds(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Lá tạo đúng `frm` vào cửa sổ, đúng `to` không vào (E9 và lời gọi của nó)."""
    frm, to = win(18)
    async with rw.begin() as conn:
        inside, outside = await e_leaf(conn, frm, "E9"), await e_leaf(conn, to, "E9")
        await seed.llm_call_for(conn, inside, created_at=frm, cache_hit=True)
        await seed.llm_call_for(conn, outside, created_at=to, cache_hit=False)
    assert await q(mon, ai.e9_count, 18) == 1
    assert await q(mon, ai.cache_hit_rate, 18) == 1.0
