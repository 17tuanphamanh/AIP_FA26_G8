"""M9-B3 cụm 3 — luật tuần 8 `drift`: `drift_counts`, loader `load_drift` (`queries/rules_data.py`) + `evaluate("weekly")`
trên Postgres 16 thật, đọc bằng role `app_monitor`; ghi `detail` thật qua `AlertWriter` (app_rw).

Cô lập: module riêng = DB riêng. Luật 8 đếm TOÀN HỆ THỐNG → mỗi ca một `rs.weekly_now(k)` riêng (cách nhau 8 tuần > 3 tuần
đọc lùi). `weekly_now(k)` = 02:00 thứ Hai giờ VN → `W = rs.week_mark(k) = now − 2 giờ`; mốc M1 = `W − 7 ngày`. Mốc W so
tuần đo `[W − 7, W)` với tuần mốc `[W − 14, W − 7)`; mốc M1 so `[W − 14, W − 7)` với `[W − 21, W − 14)`.

Số kỳ vọng tính tay (không gọi hàm đang test):
- e3 / escalation [0,1; 0,9] → [0,5; 0,5]: 0,4·ln 5 + 0,4·ln(9/5) = 0,6437751650 + 0,2351146660 = 0,8788898309.
- e3 [0,1; 0,9] → [0,2; 0,8]: 0,1·ln 2 + 0,1·ln(9/8) = 0,0693147181 + 0,0117783036 = 0,0810930216 (< 0,2).
- override [0; 1] → [0,5; 0,5], ε = 1e-4: (0,5 − 1e-4)·ln(0,5 / 1e-4) + 0,5·ln 2 = 0,4999·8,5171931914 + 0,3465735903
  = 4,2577448764 + 0,3465735903 = 4,6043184667.
Nguồn: kế hoạch chung M9 mục 6 (luật 8); chốt #15 comment 12/10 (Q-M9-B3-1, 2, 3, 7, 8); Q-M9-B3-12 (kẹp confidence),
Q-M9-B3-14 (intent không lọc kết thúc) [Đề xuất].
"""

import json
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.audit.alerts import AlertWriter
from app.core.clock import FakeClock
from app.domain.alerts import AlertDraft
from app.monitor.evaluator import LOADERS, EvalResult, evaluate
from app.monitor.queries import rules_data
from app.monitor.queries.rules_data import DriftCounts
from app.monitor.rules import DriftWeek, RuleContext
from app.monitor.window import VN_TZ
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
US = timedelta(microseconds=1)
TOL = 1e-6
PSI_HALF = 0.8788898309
PSI_SMALL = 0.0810930216
PSI_OVERRIDE = 4.6043184667


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


def ctx(now: datetime) -> RuleContext:
    return RuleContext(now=now, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)


async def run(mon: AsyncEngine, now: datetime) -> list[AlertDraft]:
    async with mon.connect() as conn:  # như job: một connection, không transaction ngoài
        result: EvalResult = await evaluate("weekly", conn, ctx(now))
    assert result.failed_rules == []
    assert result.skipped_rules == []  # override_count đã ready (4d)
    return result.drafts


async def counts(mon: AsyncEngine, frm: datetime, to: datetime) -> DriftCounts:
    async with mon.connect() as conn:
        return await rules_data.drift_counts(conn, frm, to)


async def weeks(mon: AsyncEngine, now: datetime) -> dict[datetime, DriftWeek]:
    async with mon.connect() as conn:
        out = await LOADERS["drift"](conn, ctx(now))
    assert isinstance(out, dict)
    return out


def summary(drafts: list[AlertDraft]) -> list[tuple[str, datetime, int | None, int | None]]:
    return [(d.subject, d.window_start, d.detail["n_expected"], d.detail["n_actual"]) for d in drafts]


async def shifted_e3(
    conn: AsyncConnection, *, baseline: datetime, measured: datetime, override: bool = False
) -> None:  # fmt: skip
    """Tuần mốc: 10 lá xong (1 E3 + 4 E5 + 5 không mã); tuần đo: 10 lá xong (5 E3 + 5 không mã); mọi lá intent vpn.
    e3 0,1 → 0,5 (PSI_HALF); escalation 5/10 → 5/10 (PSI 0 — E5 bù cho E3); intent giống nhau; không audit.
    `override` → 5 lá không mã của tuần đo có ghi đè: override 0/10 → 5/10 (PSI_OVERRIDE)."""
    await rs.drift_leaves(conn, 1, created_at=baseline + H, intent="vpn", exit_code="E3")
    await rs.drift_leaves(conn, 4, created_at=baseline + 2 * H, intent="vpn", exit_code="E5")
    await rs.drift_leaves(conn, 5, created_at=baseline + 3 * H, intent="vpn")
    await rs.drift_leaves(conn, 5, created_at=measured + H, intent="vpn", exit_code="E3")
    await rs.drift_leaves(conn, 5, created_at=measured + 2 * H, intent="vpn", override=override)


def test_weekly_slots_isolated() -> None:
    """Mốc là 02:00 thứ Hai giờ VN; hai slot cách nhau hơn 3 tuần đọc lùi."""
    now = rs.weekly_now(0)
    local = rs.week_mark(0).astimezone(VN_TZ)
    assert now.astimezone(VN_TZ).hour == 2 and (local.weekday(), local.hour) == (0, 0)
    assert rs.WEEKLY_SLOT > 3 * WEEK


# ---- drift_counts: số đếm từng bin ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drift_counts_exact_bins(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Một tuần: 2 lá vpn xong không mã; 1 account xong E3 có ghi đè; 1 access xong có ghi đè; 1 lá intent NULL xong E5;
    1 software ĐANG CHẠY. intent đếm mọi lá tạo trong tuần (Q-M9-B3-14) → (account 1, vpn 2, software 1, access 1,
    none 1, other 0); e3/override/escalation chỉ lá đã kết thúc (5): e3 (1, 4), override (2, 3), raw = 2/5 = 0,4."""
    w = rs.week_mark(1)
    at = w - 3 * DAY
    async with rw.begin() as conn:
        await rs.drift_leaves(conn, 2, created_at=at, intent="vpn")
        await rs.drift_leaf(conn, created_at=at, intent="account", exit_code="E3", override=True)
        await rs.drift_leaf(conn, created_at=at, intent="access", override=True)
        await rs.drift_leaf(conn, created_at=at, exit_code="E5")
        await rs.drift_leaf(conn, created_at=at, intent="software", done=False)
    assert await counts(mon, w - WEEK, w) == DriftCounts(
        bins={
            "intent": (1, 2, 1, 1, 1, 0), "confidence": (0,) * 10, "top_score": (0,) * 12, "e3_rate": (1, 4),
            "override": (2, 3),
        },
        escalation_raw=0.4, leaves_done=5, pending=(),
    )  # fmt: skip


@pytest.mark.asyncio
async def test_drift_counts_leaf_not_parent(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """"Câu 2 ý": cha (dữ liệu xấu cố ý: E3, đã kết thúc, intent NULL, dòng B3 confidence 0,95, có ghi đè) + 2 con vpn đã
    xong. Chỉ 2 con được đếm (v_leaf, D-30): cha lọt vào thì intent có `none`, e3 có 1, confidence có 1, override có 1."""
    w = rs.week_mark(2)
    at = w - 3 * DAY
    async with rw.begin() as conn:
        parent, _ = await seed.parent_with_children(
            conn, 2, created_at=at, parent_exit_code="E3", parent_final_state="S_ESCALATED", intent="vpn",
            final_state="S_RESOLVED",
        )  # fmt: skip
        await seed.audit_row(conn, parent, step="B3", event="intent_classified", created_at=at, detail={"confidence": 0.95})
        await seed.override(conn, parent, created_at=at + H)
    assert await counts(mon, w - WEEK, w) == DriftCounts(
        bins={
            "intent": (0, 2, 0, 0, 0, 0), "confidence": (0,) * 10, "top_score": (0,) * 12, "e3_rate": (0, 2),
            "override": (0, 2),
        },
        escalation_raw=0.0, leaves_done=2, pending=(),
    )  # fmt: skip


@pytest.mark.asyncio
async def test_drift_confidence_non_number_filtered(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """`detail.confidence` không phải số (chuỗi, bool, null, object, thiếu khoá) và `detail` không phải object (mảng, chuỗi,
    số) bị LOẠI, không lỗi SQL; dòng step khác (B5) và top_score dạng chuỗi cũng loại. Chỉ 0,95 (B3) và 0,05 (B4) được
    đếm → confidence (1, 0, …, 0, 1)."""
    w = rs.week_mark(3)
    at = w - 3 * DAY
    async with rw.begin() as conn:
        leaf = await rs.drift_leaf(conn, created_at=at, intent="vpn")
        for detail in ({"confidence": 0.95}, {"confidence": "0.9"}, {"confidence": True}, {"confidence": None},
                       {"confidence": {"x": 1}}, {}):  # fmt: skip
            await seed.audit_row(conn, leaf, step="B3", event="intent_classified", created_at=at, detail=detail)
        await seed.audit_row(conn, leaf, step="B4", event="intent_low_confidence", created_at=at,
                             detail={"confidence": 0.05})  # fmt: skip
        await seed.audit_row(conn, leaf, step="B5", event="other", created_at=at, detail={"confidence": 0.5})
        await seed.audit_row(conn, leaf, step="B8", event="retrieved", created_at=at, detail={"top_score": "0.5"})
        for raw in ("[1, 2]", '"chuỗi"', "7"):
            await rs.audit_raw(conn, leaf, step="B3", event="intent_classified", created_at=at, detail_json=raw)
    got = await counts(mon, w - WEEK, w)
    assert got.bins["confidence"] == (1, 0, 0, 0, 0, 0, 0, 0, 0, 1)
    assert got.bins["top_score"] == (0,) * 12


@pytest.mark.asyncio
async def test_drift_top_score_non_number_filtered(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Như ca confidence, cho top_score (step B8). `{"top_score": null}` là jsonb `null` (KHÔNG phải SQL NULL) — ép
    `::numeric` mà không qua guard `jsonb_typeof` thì lỗi "cannot cast jsonb null to type numeric" (đã gặp ở câu tự kiểm
    của script EXPLAIN). Bị LOẠI, không lỗi SQL: null, chuỗi "0.9", true, object, thiếu khoá; `detail` là mảng, chuỗi, số
    trần. Dòng B3 có top_score (sai step) cũng loại. Chỉ một dòng B8 `0.5` được đếm: width_bucket(0,5; 0; 1; 10) =
    ⌊0,5·10⌋ + 1 = 6 → chỉ số 6 (bin [0,5; 0,6)) → (0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)."""
    w = rs.week_mark(13)
    at = w - 3 * DAY
    async with rw.begin() as conn:
        leaf = await rs.drift_leaf(conn, created_at=at, intent="vpn")
        for detail in ({"top_score": None}, {"top_score": "0.9"}, {"top_score": True}, {"top_score": {"x": 1}}, {},
                       {"top_score": 0.5}):  # fmt: skip
            await seed.audit_row(conn, leaf, step="B8", event="retrieved", created_at=at, detail=detail)
        for raw in ("[0.5]", '"0.5"', "0.5"):
            await rs.audit_raw(conn, leaf, step="B8", event="retrieved", created_at=at, detail_json=raw)
        await seed.audit_row(conn, leaf, step="B3", event="intent_classified", created_at=at, detail={"top_score": 0.5})
    got = await counts(mon, w - WEEK, w)
    assert got.bins["top_score"] == (0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
    assert got.bins["confidence"] == (0,) * 10


@pytest.mark.asyncio
async def test_drift_bin_edges(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Mốc bin (hằng trong code): bin đều [k/10; (k+1)/10), bin cuối ĐÓNG (1,0 vào bin 10). confidence ngoài [0; 1] kẹp
    vào bin biên (Q-M9-B3-12): 0, 0,0999, −0,2 → bin 1; 0,1 → bin 2; 0,95, 1,0, 1,5 → bin 10. top_score có bin riêng:
    −0,01 → `<0`; 0 → bin 1; 0,1 → bin 2; 0,35 → bin 4; 1,0 → bin 10; 1,01 → `>1`."""
    w = rs.week_mark(4)
    at = w - 3 * DAY
    async with rw.begin() as conn:
        leaf = await rs.drift_leaf(conn, created_at=at, intent="vpn")
        for value in (0, 0.0999, -0.2, 0.1, 0.95, 1.0, 1.5):
            await seed.audit_row(conn, leaf, step="B3", event="intent_classified", created_at=at,
                                 detail={"confidence": value})  # fmt: skip
        for value in (-0.01, 0, 0.1, 0.35, 1.0, 1.01):
            await seed.audit_row(conn, leaf, step="B8", event="retrieved", created_at=at, detail={"top_score": value})
    got = await counts(mon, w - WEEK, w)
    assert got.bins["confidence"] == (3, 1, 0, 0, 0, 0, 0, 0, 0, 3)
    assert got.bins["top_score"] == (1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 1)


@pytest.mark.asyncio
async def test_drift_window_bounds(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Tuần đo `[W − 7 ngày, W)` theo `created_at` của lá: đúng `W − 7 ngày` và `W − 1 µs` thuộc; `W` và
    `W − 7 ngày − 1 µs` không."""
    w = rs.week_mark(5)
    async with rw.begin() as conn:
        for at in (w - WEEK, w - US, w, w - WEEK - US):
            await rs.drift_leaf(conn, created_at=at, intent="vpn")
    got = await counts(mon, w - WEEK, w)
    assert (got.bins["intent"], got.leaves_done) == ((0, 2, 0, 0, 0, 0), 2)


# ---- evaluate("weekly"): ngưỡng, mốc, số mẫu --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drift_two_distributions_two_drafts(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Hai phân bố vượt → 2 draft (subject = tên phân bố, KHÔNG phải SYSTEM_SUBJECT; window_start = W, không phải now):
    e3 0,1 → 0,5 (PSI_HALF) và override 0/10 → 5/10 (PSI_OVERRIDE). escalation 5/10 → 5/10 → không báo. Mốc M1: tuần mốc
    `[W − 21, W − 14)` trống → mọi phân bố None → không báo."""
    now, w = rs.weekly_now(6), rs.week_mark(6)
    async with rw.begin() as conn:
        await shifted_e3(conn, baseline=w - 2 * WEEK, measured=w - WEEK, override=True)
    drafts = await run(mon, now)
    assert summary(drafts) == [("e3_rate", w, 10, 10), ("override", w, 10, 10)]
    e3, override = (d.detail["psi"] for d in drafts)
    assert abs(e3 - PSI_HALF) <= TOL and abs(override - PSI_OVERRIDE) <= TOL
    assert all(d.severity == "warning" and d.value == d.detail["psi"] and d.detail["threshold"] == 0.2 for d in drafts)


@pytest.mark.asyncio
async def test_drift_below_threshold(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """e3 1/10 → 2/10 (escalation cũng 1/10 → 2/10): PSI_SMALL < 0,2 → 0 draft (loader vẫn đo được)."""
    now, w = rs.weekly_now(8), rs.week_mark(8)
    async with rw.begin() as conn:
        await rs.drift_leaves(conn, 1, created_at=w - 2 * WEEK + H, intent="vpn", exit_code="E3")
        await rs.drift_leaves(conn, 9, created_at=w - 2 * WEEK + 2 * H, intent="vpn")
        await rs.drift_leaves(conn, 2, created_at=w - WEEK + H, intent="vpn", exit_code="E3")
        await rs.drift_leaves(conn, 8, created_at=w - WEEK + 2 * H, intent="vpn")
    assert await run(mon, now) == []
    scores = (await weeks(mon, now))[w].scores
    for name in ("e3_rate", "escalation"):
        s = scores[name]
        assert s is not None and abs(s.psi - PSI_SMALL) <= TOL and (s.n_expected, s.n_actual) == (10, 10), name


@pytest.mark.asyncio
async def test_drift_one_side_empty_skipped(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """confidence chỉ có ở tuần đo (5 dòng 0,95) → tuần mốc 0 mẫu → None, KHÔNG báo dù lệch hết cỡ (Q-M9-B3-6 (A)).
    Mọi phân bố khác giống nhau hai tuần → 0 draft."""
    now, w = rs.weekly_now(9), rs.week_mark(9)
    async with rw.begin() as conn:
        await rs.drift_leaves(conn, 10, created_at=w - 2 * WEEK + H, intent="vpn")
        measured = await rs.drift_leaves(conn, 10, created_at=w - WEEK + H, intent="vpn")
        for ticket in measured[:5]:
            await seed.audit_row(conn, ticket, step="B3", event="intent_classified", created_at=w - WEEK + 2 * H,
                                 detail={"confidence": 0.95})  # fmt: skip
    assert await run(mon, now) == []
    assert (await weeks(mon, now))[w].scores["confidence"] is None


@pytest.mark.asyncio
async def test_drift_escalation_detail_n(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """escalation 1/10 → 10/20 (E5) → draft `escalation` PSI_HALF, số mẫu = số lá ĐÃ KẾT THÚC (10, 20) — 3 lá đang chạy
    ở tuần đo vào intent (vpn, không đổi tỉ lệ) nhưng không vào số mẫu escalation (cùng mẫu số với `.raw` của A1)."""
    now, w = rs.weekly_now(10), rs.week_mark(10)
    async with rw.begin() as conn:
        await rs.drift_leaves(conn, 1, created_at=w - 2 * WEEK + H, intent="vpn", exit_code="E5")
        await rs.drift_leaves(conn, 9, created_at=w - 2 * WEEK + 2 * H, intent="vpn")
        await rs.drift_leaves(conn, 10, created_at=w - WEEK + H, intent="vpn", exit_code="E5")
        await rs.drift_leaves(conn, 10, created_at=w - WEEK + 2 * H, intent="vpn")
        await rs.drift_leaves(conn, 3, created_at=w - WEEK + 3 * H, intent="vpn", done=False)
    drafts = await run(mon, now)
    assert summary(drafts) == [("escalation", w, 10, 20)]
    assert abs(drafts[0].detail["psi"] - PSI_HALF) <= TOL


@pytest.mark.asyncio
async def test_drift_previous_mark(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B3-7: dữ liệu chỉ ở cặp tuần của mốc M1 (`[W − 21, W − 14)` → `[W − 14, W − 7)`) → draft `window_start = M1`
    (tuần bị lỡ vẫn được đánh giá); mốc W: tuần đo trống → None → không báo."""
    now, w = rs.weekly_now(11), rs.week_mark(11)
    m1 = w - WEEK
    async with rw.begin() as conn:
        await shifted_e3(conn, baseline=w - 3 * WEEK, measured=w - 2 * WEEK)
    drafts = await run(mon, now)
    assert summary(drafts) == [("e3_rate", m1, 10, 10)]
    assert abs(drafts[0].detail["psi"] - PSI_HALF) <= TOL


@pytest.mark.asyncio
async def test_drift_detail_written_via_alert_writer(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """`detail` ghi được vào JSONB thật (int/float Python, không kiểu numpy) qua `AlertWriter.raise_once` (đường ghi duy
    nhất, worker gọi); đọc lại bằng nhau, khoá `(drift, e3_rate, W)`; chạy lại → trùng (False)."""
    now, w = rs.weekly_now(12), rs.week_mark(12)
    async with rw.begin() as conn:
        await shifted_e3(conn, baseline=w - 2 * WEEK, measured=w - WEEK)
    [draft] = await run(mon, now)
    writer = AlertWriter(rw, FakeClock(now))
    assert await writer.raise_once(draft) is True
    assert await writer.raise_once(draft) is False
    async with rw.connect() as conn:
        row = (await conn.execute(text(
            "SELECT subject, window_start, severity, value, detail FROM alerts WHERE rule_id = 'drift' AND window_start = :w"
        ), {"w": w})).one()  # fmt: skip
    assert (row.subject, row.window_start, row.severity) == ("e3_rate", w, "warning")
    assert row.detail == dict(draft.detail) == json.loads(json.dumps(dict(draft.detail)))
    assert set(row.detail) == {"psi", "threshold", "n_expected", "n_actual"}
    assert (row.detail["n_expected"], row.detail["n_actual"], row.detail["threshold"]) == (10, 10, 0.2)
    assert abs(row.value - PSI_HALF) <= TOL
