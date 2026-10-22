"""M9 A2 — 12 chỉ số dashboard AI/LLMOps trên Postgres 16 thật, đọc bằng role `app_monitor` (kế hoạch M9 5.2, 4.3; chốt
[C-A2] ở #9).

Mỗi test một ngày (hoặc cửa sổ) riêng của năm 2030; số kỳ vọng tính tay trong chú thích. Tháng 1: các test chỉ số theo ngày
(+ R26-3, R26-5, R26-6); tháng 2: `cost_per_day`; tháng 3: cửa sổ theo lá hai chiều (R26-4: 2, 4, 6, 8; R26b-1: 10, 12, 14;
R26b-2: 16, 18); tháng 4: cost theo thời điểm lời gọi (R26-1, R26-2) và `DayCost` UTC. Bảng ngày chi tiết ở khối R26 dưới.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.monitor.queries import ai
from app.monitor.queries.ai import DayCost
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
PENDING = ("multi_intent_messages_per_turn",)  # F12: first_stop đã ready (v_child_notices); messages_per_turn chờ D-30


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


def win(day: int, month: int = 1) -> tuple[datetime, datetime]:
    """Cửa sổ 1 ngày theo UTC: `[2030-<month>-<day> 00:00 UTC, +1 ngày)` (= 07:00 VN → 07:00 VN hôm sau)."""
    frm = datetime(2030, month, day, tzinfo=UTC)
    return frm, frm + timedelta(days=1)


def at(day: int, hours: int = 1, month: int = 1) -> datetime:
    return win(day, month)[0] + hours * H


async def q(mon: AsyncEngine, fn: Callable[..., Awaitable[Any]], day: int, month: int = 1) -> Any:
    async with mon.connect() as conn:
        return await fn(conn, *win(day, month))


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


type Notice = tuple[int, float, int | None, float | None]  # (con thứ mấy, giây tạo, vòng gửi, giây gửi) tính từ mốc


async def multi(conn: AsyncConnection, created_at: datetime, notices: list[Notice], *, children: int = 2) -> str:
    """F12: 1 ticket cha + `children` con tạo lúc `created_at`, kèm các notice; giây tính từ `created_at`. Trả id cha."""
    parent, kids = await seed.parent_with_children(conn, children, created_at=created_at)
    for i, made, round_no, sent in notices:
        await seed.child_notice(
            conn, parent, kids[i], created_at=created_at + timedelta(seconds=made), delivered_round=round_no,
            delivered_at=None if sent is None else created_at + timedelta(seconds=sent),
        )  # fmt: skip
    return parent


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
        "intent_filter_fallback_rate", "b3_llm_rate", "intent_model_version", "multi_intent_first_stop_to_reply_s",
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
    """Đủ 14 khóa; chỉ `multi_intent_messages_per_turn` vào `unavailable` (None) — F12: `first_stop` ready, ngày không có
    cha → None nhưng KHÔNG vào `unavailable`. `intent_model_version` None (Phase 3–4, model_missing) nhưng KHÔNG vào
    `unavailable` (Q-M9-A2-1)."""
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
    assert got.values["multi_intent_first_stop_to_reply_s"] is None
    assert got.values["b3_llm_rate"] == 1.0


@pytest.mark.asyncio
async def test_window_bounds(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Lá tạo đúng `frm` vào cửa sổ, đúng `to` không vào (E9 và lời gọi của nó). Ngày 30/01 UTC [00:00, 31/01 00:00) = 07:00 VN;
    lá `to` rơi vào 31/01 00:00, ngày không test nào dùng (R26 sửa kèm a: lá `to` ở ngày có test khác thì phụ thuộc thứ tự)."""
    frm, to = win(30)
    async with rw.begin() as conn:
        inside, outside = await e_leaf(conn, frm, "E9"), await e_leaf(conn, to, "E9")
        await seed.llm_call_for(conn, inside, created_at=frm, cache_hit=True)
        await seed.llm_call_for(conn, outside, created_at=to, cache_hit=False)
    assert await q(mon, ai.e9_count, 30) == 1
    assert await q(mon, ai.cache_hit_rate, 30) == 1.0


# ---- R26 (review PR #26, Tuấn Anh): cửa sổ theo lá, cost theo thời điểm lời gọi, nối khóa → hàm ----
# Ngày dùng riêng: tháng 1: 2 (R26-3), 19 (R26-5), 22, 23 (R26-6); tháng 3: 2, 4, 6, 8 (R26-4), 10, 12, 14 (R26b-1), 16,
# 18 (R26b-2); tháng 4: 10–11 (R26-2), 20–21 (R26-1), 25–26 (thêm). Mọi mốc `tzinfo=UTC`; giờ VN = UTC + 7.


@pytest.mark.asyncio
async def test_cost_per_day_by_call_time(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-1: cost lọc theo thời điểm LỜI GỌI (Q-M9-A2-3), không theo `created_at` của lá. Cửa sổ [20/04 17:00 UTC (21/04
    00:00 VN), 21/04 05:00 UTC (21/04 12:00 VN)). Lá A tạo 18/04 17:00 UTC (2 ngày trước `frm`), lời gọi 20/04 18:00 UTC
    (21/04 01:00 VN) 0,5 → tính. Lá B tạo trong cửa sổ (20/04 18:00 UTC), lời gọi 21/04 06:00 UTC (21/04 13:00 VN, SAU
    `to`, vẫn trong ngày VN) 2,0 → không tính. Lọc theo lá ra 2,0; bỏ WHERE ra 2,5."""
    frm, to = datetime(2030, 4, 20, 17, tzinfo=UTC), datetime(2030, 4, 21, 5, tzinfo=UTC)
    async with rw.begin() as conn:
        a, b = await done(conn, frm - timedelta(days=2)), await done(conn, frm + H)
        await seed.llm_call_for(conn, a, created_at=frm + H, cost_usd=0.5)
        await seed.llm_call_for(conn, b, created_at=to + H, cost_usd=2.0)
    async with mon.connect() as conn:
        got = await ai.cost_per_day(conn, frm, to)
    assert got == (DayCost(frm, 0.5),)


@pytest.mark.asyncio
async def test_cost_per_day_cut_mid_vn_day(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-2: cửa sổ bắt đầu GIỮA ngày VN: [10/04 05:00 UTC (12:00 VN), 11/04 05:00 UTC (12:00 VN)); 2 ngày VN: [09/04
    17:00, 10/04 17:00) và [10/04 17:00, 11/04 17:00) UTC. Lá tạo đúng `frm`. Lời gọi: 10/04 04:59 UTC (trước `frm`) 9,0
    → không; đúng `frm` 0,5 → tính (ngày 1); 11/04 04:59 UTC 0,25 → tính (ngày 2); đúng `to` 7,0 → không. Xóa
    `WHERE c.created_at` hoặc lọc theo lá ra (9,5; 7,25)."""
    frm, to = datetime(2030, 4, 10, 5, tzinfo=UTC), datetime(2030, 4, 11, 5, tzinfo=UTC)
    minute = timedelta(minutes=1)
    async with rw.begin() as conn:
        leaf = await done(conn, frm)
        for ts, cost in [(frm - minute, 9.0), (frm, 0.5), (to - minute, 0.25), (to, 7.0)]:
            await seed.llm_call_for(conn, leaf, created_at=ts, cost_usd=cost)
    async with mon.connect() as conn:
        got = await ai.cost_per_day(conn, frm, to)
    day1 = datetime(2030, 4, 9, 17, tzinfo=UTC)
    assert got == (DayCost(day1, 0.5), DayCost(day1 + timedelta(days=1), 0.25))


@pytest.mark.asyncio
async def test_ai_metrics_key_to_function(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-3: `ai_metrics` nối khóa → hàm đúng; mỗi giá trị khác nhau theo cặp dễ nhầm (cache 0,75 / fallback 0,25; E2 2 /
    E9 1). Ngày 02/01, mọi dòng 01:00 UTC (08:00 VN). Lá A (đã xong) 4 lời gọi (10 token, 0,1 USD): (cache, fallback, json) =
    (T,T,F), (T,F,T), (T,F,T), (F,F,NULL). B2: llm ×1 + classifier ×4 → 0,2. B8: true ×3, false ×2 → 0,6. B3: llm ×2 + model
    ×3 → 0,4 (dòng mới nhất `v-r26`). Span node 123 ms. 2 lá E2 `llm_unavailable`, 1 lá E9."""
    async with rw.begin() as conn:
        leaf = await done(conn, at(2))
        for cache, fallback, valid in [(True, True, False), (True, False, True), (True, False, True), (False, False, None)]:
            await seed.llm_call_for(
                conn, leaf, created_at=at(2), tokens_in=10, tokens_out=0, cost_usd=0.1, cache_hit=cache,
                used_fallback=fallback, json_valid_first_try=valid,
            )  # fmt: skip
        for layer in ["llm", *["classifier"] * 4]:
            await audit(conn, leaf, "B2", "screened", at(2), **b2(layer))
        for flag in (True, True, True, False, False):
            await audit(conn, leaf, "B8", "retrieved", at(2), intent_filter_fallback=flag)
        for layer in ("llm", "llm", "model", "model"):
            await audit(conn, leaf, "B3", "intent_classified", at(2), layer=layer)
        await audit(conn, leaf, "B3", "intent_classified", at(2, 3), layer="model", model_version="v-r26")
        await node_span(conn, leaf, at(2), "node:b02_screen", 123)
        await e_leaf(conn, at(2), "E2", "llm_unavailable")
        await e_leaf(conn, at(2), "E2", "llm_unavailable")
        await e_leaf(conn, at(2), "E9")
        await multi(conn, at(2), [(0, 0, 1, 42)])  # F12: 1 cha, vòng đầu gửi sau 42 s
    async with mon.connect() as conn:
        got = await ai.ai_metrics(conn, *win(2))
    values = got.values
    assert list(values) == list(ai.AI_METRICS)
    assert values["tokens_per_ticket"] == pytest.approx(40.0)
    assert values["cache_hit_rate"] == pytest.approx(0.75)
    assert values["fallback_rate"] == pytest.approx(0.25)
    assert values["json_invalid_first_try_rate"] == pytest.approx(1 / 3)
    assert values["b2_llm_rate"] == pytest.approx(0.2)
    assert values["intent_filter_fallback_rate"] == pytest.approx(0.6)
    assert values["b3_llm_rate"] == pytest.approx(0.4)
    assert (values["e2_llm_count"], values["e9_count"]) == (2, 1)
    assert values["intent_model_version"] == "v-r26"
    assert values["latency_p95_by_step"] == {"node:b02_screen": pytest.approx(123.0)}
    assert values["multi_intent_first_stop_to_reply_s"] == pytest.approx(42.0)
    day = datetime(2030, 1, 1, 17, tzinfo=UTC)  # 02/01 00:00 VN
    assert [(d.day_start, round(d.cost_usd, 6)) for d in values["cost_per_day"]] == [
        (day, 0.4), (day + timedelta(days=1), 0.0),
    ]  # fmt: skip
    assert got.unavailable == PENDING


def _leaf_times(frm: datetime, to: datetime) -> tuple[datetime, datetime, datetime, datetime, datetime]:
    """(lá đúng `frm`, lá đúng `to`, lá trước `frm` 1 giờ, thời điểm trong cửa sổ, thời điểm sau `to`)."""
    return frm, to, frm - H, frm + H, to + H


@pytest.mark.asyncio
async def test_b2_llm_rate_leaf_window(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-4 (b2): cửa sổ theo LÁ, hai chiều. Cửa sổ ngày 02/03 UTC [00:00, +1 ngày) = 07:00 VN. Lá đúng `frm` (tính): B2 llm +
    classifier ghi SAU `to` → 1/2. Lá đúng `to` (không): 2 dòng llm ghi trong cửa sổ. Lá trước `frm` 1 giờ (không): 1 dòng
    llm trong cửa sổ. Kỳ vọng 0,5; lọc theo thời điểm dòng ra 3/3 = 1,0."""
    frm, to = win(2, 3)
    t_frm, t_to, t_before, inside, after = _leaf_times(frm, to)
    async with rw.begin() as conn:
        in_leaf, to_leaf, before_leaf = await done(conn, t_frm), await done(conn, t_to), await done(conn, t_before)
        await audit(conn, in_leaf, "B2", "screened", after, **b2("llm"))
        await audit(conn, in_leaf, "B2", "screened", after, **b2("classifier"))
        await audit(conn, to_leaf, "B2", "screened", inside, **b2("llm"))
        await audit(conn, to_leaf, "B2", "screened", inside, **b2("llm"))
        await audit(conn, before_leaf, "B2", "screened", inside, **b2("llm"))
    assert await q(mon, ai.b2_llm_rate, 2, 3) == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_b3_llm_rate_leaf_window(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-4 (b3): cửa sổ ngày 04/03 UTC. Lá đúng `frm`: B3 llm + B4 model ghi SAU `to` → 1/2. Lá đúng `to`: 2 dòng B3 model
    trong cửa sổ; lá trước `frm` 1 giờ: 1 dòng B3 model trong cửa sổ (đều không tính). Kỳ vọng 0,5; lọc theo thời điểm dòng
    ra 0/3 = 0,0."""
    frm, to = win(4, 3)
    t_frm, t_to, t_before, inside, after = _leaf_times(frm, to)
    async with rw.begin() as conn:
        in_leaf, to_leaf, before_leaf = await done(conn, t_frm), await done(conn, t_to), await done(conn, t_before)
        await audit(conn, in_leaf, "B3", "intent_classified", after, layer="llm")
        await audit(conn, in_leaf, "B4", "intent_out_of_scope", after, layer="model")
        await audit(conn, to_leaf, "B3", "intent_classified", inside, layer="model")
        await audit(conn, to_leaf, "B3", "intent_classified", inside, layer="model")
        await audit(conn, before_leaf, "B3", "intent_classified", inside, layer="model")
    assert await q(mon, ai.b3_llm_rate, 4, 3) == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_latency_p95_leaf_window(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-4 (latency): cửa sổ ngày 06/03 UTC. Lá đúng `frm`: span node 100 ms bắt đầu SAU `to` → tính. Lá đúng `to`: span 900
    ms và lá trước `frm` 1 giờ: span 700 ms, cả hai bắt đầu trong cửa sổ → không tính. Kỳ vọng 100; lọc theo thời điểm span
    ra p95(700, 900) = 890."""
    frm, to = win(6, 3)
    t_frm, t_to, t_before, inside, after = _leaf_times(frm, to)
    async with rw.begin() as conn:
        in_leaf, to_leaf, before_leaf = await done(conn, t_frm), await done(conn, t_to), await done(conn, t_before)
        await node_span(conn, in_leaf, after, "node:b03_classify", 100)
        await node_span(conn, to_leaf, inside, "node:b03_classify", 900)
        await node_span(conn, before_leaf, inside, "node:b03_classify", 700)
    assert await q(mon, ai.latency_p95_by_step, 6, 3) == {"node:b03_classify": pytest.approx(100.0)}


@pytest.mark.asyncio
async def test_tokens_per_ticket_leaf_window(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-4 (tokens): cửa sổ ngày 08/03 UTC, mọi lá đã xong. Lá đúng `frm`: lời gọi 100 token ghi SAU `to` → tính. Lá đúng
    `to`: 1000 token và lá trước `frm` 1 giờ: 500 token, cả hai ghi trong cửa sổ → không tính. Kỳ vọng 100,0; lọc theo thời
    điểm lời gọi ra 1500/2 = 750,0."""
    frm, to = win(8, 3)
    t_frm, t_to, t_before, inside, after = _leaf_times(frm, to)
    async with rw.begin() as conn:
        in_leaf, to_leaf, before_leaf = await done(conn, t_frm), await done(conn, t_to), await done(conn, t_before)
        await seed.llm_call_for(conn, in_leaf, created_at=after, tokens_in=100, tokens_out=0)
        await seed.llm_call_for(conn, to_leaf, created_at=inside, tokens_in=1000, tokens_out=0)
        await seed.llm_call_for(conn, before_leaf, created_at=inside, tokens_in=500, tokens_out=0)
    assert await q(mon, ai.tokens_per_ticket, 8, 3) == pytest.approx(100.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fn", "day", "hit", "miss"),
    [
        (ai.cache_hit_rate, 10, {"cache_hit": True}, {"cache_hit": False}),
        (ai.json_invalid_first_try_rate, 12, {"json_valid_first_try": False}, {"json_valid_first_try": True}),
        (ai.fallback_rate, 14, {"used_fallback": True}, {"used_fallback": False}),
    ],
    ids=["cache_hit", "json_invalid", "fallback"],
)  # fmt: skip
async def test_call_rates_leaf_window(
    rw: AsyncEngine, mon: AsyncEngine, fn: Callable[..., Awaitable[Any]], day: int, hit: dict[str, Any],
    miss: dict[str, Any],
) -> None:  # fmt: skip
    """R26b-1 (`_call_rate`): cửa sổ theo LÁ, hai chiều. Cửa sổ ngày `day`/03 UTC. Lá đúng `frm` (tính): 1 lời gọi "trúng" ghi
    SAU `to`. Lá đúng `to` và lá trước `frm` 1 giờ (không tính): mỗi lá 1 lời gọi "trượt" ghi trong cửa sổ. Kỳ vọng 1/1 = 1,0;
    lọc theo `c.created_at` ra 0/2 = 0,0."""
    frm, to = win(day, 3)
    t_frm, t_to, t_before, inside, after = _leaf_times(frm, to)
    async with rw.begin() as conn:
        in_leaf, to_leaf, before_leaf = await done(conn, t_frm), await done(conn, t_to), await done(conn, t_before)
        await seed.llm_call_for(conn, in_leaf, created_at=after, **hit)
        await seed.llm_call_for(conn, to_leaf, created_at=inside, **miss)
        await seed.llm_call_for(conn, before_leaf, created_at=inside, **miss)
    assert await q(mon, fn, day, 3) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_intent_model_version_leaf_window(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26b-2: cửa sổ theo LÁ, hai chiều. Cửa sổ ngày 16/03 UTC. Lá đúng `frm`: dòng B3 `model_version="v-in"` ghi SAU `to` →
    tính. Lá đúng `to` và lá trước `frm` 1 giờ: dòng B3 `"v-out"` ghi trong cửa sổ → không tính. Kỳ vọng "v-in"; lọc theo
    `a.created_at` ra "v-out"."""
    frm, to = win(16, 3)
    t_frm, t_to, t_before, inside, after = _leaf_times(frm, to)
    async with rw.begin() as conn:
        in_leaf, to_leaf, before_leaf = await done(conn, t_frm), await done(conn, t_to), await done(conn, t_before)
        await audit(conn, in_leaf, "B3", "intent_classified", after, layer="llm", model_version="v-in")
        await audit(conn, to_leaf, "B3", "intent_classified", inside, layer="llm", model_version="v-out")
        await audit(conn, before_leaf, "B3", "intent_classified", inside, layer="llm", model_version="v-out")
    assert await q(mon, ai.intent_model_version, 16, 3) == "v-in"


@pytest.mark.asyncio
async def test_intent_model_version_leaf_window_newest_out(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26b-2, chiều còn lại (review PR #30, 8): dòng của lá NGOÀI cửa sổ MỚI HƠN dòng của lá trong cửa sổ. Cửa sổ ngày 18/03
    UTC. Lá đúng `frm`: B3 `"v-in-18"` lúc `frm + 1h`. Lá đúng `to` và lá trước `frm` 1 giờ: B3 `"v-out-18"` lúc `frm + 2h`
    (mới hơn) → vẫn "v-in-18". Bỏ cận dưới hoặc cận trên của cửa sổ lá thì `ORDER BY … LIMIT 1` ra "v-out-18" (hoặc dòng của
    test khác). Tên riêng ngày 18 — không trùng "v-in" của ngày 16."""
    frm, to = win(18, 3)
    t_frm, t_to, t_before, inside, _ = _leaf_times(frm, to)
    async with rw.begin() as conn:
        in_leaf, to_leaf, before_leaf = await done(conn, t_frm), await done(conn, t_to), await done(conn, t_before)
        await audit(conn, in_leaf, "B3", "intent_classified", inside, layer="llm", model_version="v-in-18")
        for leaf in (to_leaf, before_leaf):
            await audit(conn, leaf, "B3", "intent_classified", inside + H, layer="llm", model_version="v-out-18")
    assert await q(mon, ai.intent_model_version, 18, 3) == "v-in-18"


@pytest.mark.asyncio
async def test_tokens_per_ticket_null_column(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-5: token NULL một cột không làm mất cả dòng: (30 + NULL) và (NULL + 12) → 42 (cộng NULL ra NULL, `sum` bỏ qua →
    0,0). Ngày 19/01 UTC, lá đã xong."""
    async with rw.begin() as conn:
        leaf = await done(conn, at(19))
        await seed.llm_call_for(conn, leaf, created_at=at(19), tokens_in=30, tokens_out=None)
        await seed.llm_call_for(conn, leaf, created_at=at(19), tokens_in=None, tokens_out=12)
    assert await q(mon, ai.tokens_per_ticket, 19) == pytest.approx(42.0)


@pytest.mark.asyncio
async def test_e2_llm_count_latest_row_both_ways(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-6a: lấy dòng E2 MỚI NHẤT, hai chiều. Ngày 22/01 UTC. 2 lá X: E2 cũ `rag_system_error` (01:00 UTC = 08:00 VN), mới nhất
    `llm_unavailable` (02:00 UTC) → đếm. 1 lá Y: `llm_unavailable` cũ, mới nhất `rag_system_error` → không. Kỳ vọng 2; lấy dòng
    cũ nhất ra 1."""
    async with rw.begin() as conn:
        for _ in range(2):
            x = await e_leaf(conn, at(22, 1), "E2", "rag_system_error")
            await seed.escalation(conn, x, exit_code="E2", created_at=at(22, 2), reason_detail="llm_unavailable")
        y = await e_leaf(conn, at(22, 1), "E2", "llm_unavailable")
        await seed.escalation(conn, y, exit_code="E2", created_at=at(22, 2), reason_detail="rag_system_error")
    assert await q(mon, ai.e2_llm_count, 22) == 2


@pytest.mark.asyncio
async def test_json_invalid_counts_running_leaf(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """R26-6b: lá ĐANG CHẠY có lời gọi JSON lỗi vẫn tính (Q-M9-A2-7, không lọc `final_state`). Ngày 23/01 UTC: lá đã xong 1 lời gọi
    JSON đúng, lá đang chạy 1 lời gọi JSON lỗi → 1/2 = 0,5 (lọc `final_state` ra 0,0)."""
    async with rw.begin() as conn:
        fin, run = await done(conn, at(23)), await seed.leaf_ticket(conn, created_at=at(23))
        await seed.llm_call_for(conn, fin, created_at=at(23), json_valid_first_try=True)
        await seed.llm_call_for(conn, run, created_at=at(23), json_valid_first_try=False)
    assert await q(mon, ai.json_invalid_first_try_rate, 23) == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_cost_per_day_day_start_utc(mon: AsyncEngine) -> None:
    """(thêm) `DayCost.day_start` luôn tzinfo UTC, kể cả khi session DB đặt múi giờ khác. Cửa sổ 1 ngày VN [25/04 17:00 UTC,
    +1 ngày), không dữ liệu. `datetime ==` chỉ so mốc tuyệt đối nên phải kiểm `tzinfo`; `SET LOCAL` chỉ sống tới hết transaction
    (không rò sang test khác; engine `mon` còn là fixture riêng từng test); cuối test kiểm múi giờ session về như cũ."""
    frm = datetime(2030, 4, 25, 17, tzinfo=UTC)
    async with mon.connect() as conn:
        before: str = (await conn.execute(text("SHOW TIME ZONE"))).scalar_one()
    async with mon.begin() as conn:
        await conn.execute(text("SET LOCAL TIME ZONE 'Asia/Ho_Chi_Minh'"))
        got = await ai.cost_per_day(conn, frm, frm + timedelta(days=1))
    async with mon.connect() as conn:
        assert (await conn.execute(text("SHOW TIME ZONE"))).scalar_one() == before
    assert got == (DayCost(frm, 0.0),)
    assert got[0].day_start.tzinfo is UTC


# ---- F12 (#45): `multi_intent_first_stop_to_reply_s` — trung vị theo cha, CHỈ vòng đầu (`min(delivered_round)`), từ notice
# tạo sớm nhất của vòng đó tới lúc vòng đó được gửi; cha vào cửa sổ theo `min(created_at)` của con. Tháng 5: ngày 1–4.

P1: list[Notice] = [(0, 10, 1, 70), (1, 40, 1, 70), (1, 100, 2, 500)]  # vòng 1: 70 − 10 = 60; vòng 2 bỏ qua
P2: list[Notice] = [(1, 5, None, None), (0, 50, 1, 80)]  # notice chưa gửi (tạo sớm hơn) bỏ qua: 80 − 50 = 30
P3: list[Notice] = [(0, 10, None, None)]  # chưa gửi vòng nào → không tính


@pytest.mark.asyncio
async def test_first_stop_odd_median(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """60, 30, 120 (+ cha chưa gửi) → trung vị 60. avg = 70; bỏ lọc vòng đầu → P2 = 75 → 75; vòng cuối → P1 = 400 → 120."""
    async with rw.begin() as conn:
        await multi(conn, at(1, month=5), P1)
        await multi(conn, at(1, month=5), P2)
        await multi(conn, at(1, month=5), P3)
        await multi(conn, at(1, month=5), [(0, 0, 1, 120)], children=1)
    assert await q(mon, ai.multi_intent_first_stop_to_reply_s, 1, 5) == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_first_stop_even_median(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """60, 30 → trung vị (nội suy) 45."""
    async with rw.begin() as conn:
        await multi(conn, at(2, month=5), P1)
        await multi(conn, at(2, month=5), P2)
    assert await q(mon, ai.multi_intent_first_stop_to_reply_s, 2, 5) == pytest.approx(45.0)


@pytest.mark.asyncio
async def test_first_stop_none(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Chỉ có cha chưa gửi vòng nào + lá đơn → None (không 0)."""
    async with rw.begin() as conn:
        await multi(conn, at(3, month=5), P3)
        await done(conn, at(3, month=5))
    assert await q(mon, ai.multi_intent_first_stop_to_reply_s, 3, 5) is None


@pytest.mark.asyncio
async def test_first_stop_window_by_children(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Cửa sổ [04/05, 05/05) UTC theo `created_at` của CON. PA: con tạo 23:00, notice 23:00:10, gửi sang hôm sau 01:00
    → tính 7190. PB: con tạo đúng `to` → không. PC: con tạo hôm trước 23:00, notice và lần gửi trong cửa sổ (20 s) → không.
    Lọc theo `created_at` của notice → {7190, 20} → 3605 (đỏ)."""
    frm, to = win(4, 5)
    async with rw.begin() as conn:
        await multi(conn, frm + 23 * H, [(0, 10, 1, 7200)], children=1)
        await multi(conn, to, [(0, 0, 1, 5)], children=1)
        await multi(conn, frm - H, [(0, 2 * 3600, 1, 2 * 3600 + 20)], children=1)
    assert await q(mon, ai.multi_intent_first_stop_to_reply_s, 4, 5) == pytest.approx(7190.0)
