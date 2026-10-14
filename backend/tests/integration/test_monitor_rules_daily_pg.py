"""M9-B2 GĐ2 cụm 2 — loader luật ngày 1 `escalation_rate_high`, 7 `reflex_approval`, 12 `b2_degraded`, 13 `b3_degraded`
(`queries/rules_data.py`) + `evaluate("daily")` trên Postgres 16 thật, đọc bằng role `app_monitor`.

Cô lập: module riêng = DB riêng. Luật 1/12/13 là luật TỔNG HỢP → mỗi ca một mốc `rs.daily_now(k)` riêng, cách nhau 30 ngày.
`daily_now(k)` là 19:00 UTC = 02:00 giờ VN (giờ job ngày) → `d0 = now − 2 giờ` (VN không đổi giờ). Luật 7 theo người
quyết (`new_id`) và lọc theo 7 mốc ngày → dữ liệu của ca khác không lọt vào. Mỗi lượt `evaluate("daily")` đều kiểm
`failed_rules == []` và luật 12/13 nằm trong `skipped_rules` (nguồn pending tới Phase 5).

Số kỳ vọng tính tay (comment từng ca), không gọi hàm đang test. Nguồn: kế hoạch chung M9 mục 6 (luật 1, 7, 12, 13);
thẻ B2; chốt Q-M9-B2-1, 3, 6, 15 ở #14 (5955137864, 5955436721, 5959974287); Q-M9-B2-23, 24 chốt ở PR #31.
Cấp job (cụm 3): chạy hai lượt, ranh giới luật 1 với `policy_versions`, worker nghỉ 2 mốc → `test_monitor_jobs_daily_pg.py`;
job đúng 19:00 UTC → `tests/unit/test_monitor_jobs_periodic.py`.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.domain.alerts import SYSTEM_SUBJECT, AlertDraft
from app.monitor.evaluator import LOADERS, EvalResult, evaluate
from app.monitor.queries import rules_data
from app.monitor.rules import ApprovalDecision, RuleContext
from app.monitor.window import VN_TZ
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
DAY = timedelta(days=1)
US = timedelta(microseconds=1)
PENDING_DAILY = ["b2_degraded", "b3_degraded"]  # thứ tự đăng ký trong rules.py
FAST, NORMAL = rs.FAST_B16, rs.NORMAL_B16


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


async def run(mon: AsyncEngine, now: datetime, *, skipped: list[str] = PENDING_DAILY) -> list[AlertDraft]:
    async with mon.connect() as conn:  # như job: một connection, không transaction ngoài
        result: EvalResult = await evaluate("daily", conn, ctx(now))
    assert result.failed_rules == []
    assert result.skipped_rules == skipped
    return result.drafts


async def decisions(mon: AsyncEngine, now: datetime, approver: str) -> list[ApprovalDecision]:
    """Đầu ra loader 7 (gọi thẳng) của MỘT người quyết, theo thứ tự SQL (`decided_at`)."""
    async with mon.connect() as conn:
        out = await LOADERS["reflex_approval"](conn, ctx(now))
    assert isinstance(out, list)
    return [d for d in out if d.decided_by == approver]


def escalation(d0: datetime, weighted: float, raw: float) -> AlertDraft:
    return AlertDraft(
        rule_id="escalation_rate_high", subject=SYSTEM_SUBJECT, window_start=d0, severity="warning", value=weighted,
        detail={"weighted": weighted, "raw": raw, "threshold": 0.4, "days": 7},
    )  # fmt: skip


def reflex(subject: str, r: datetime, count: int, ambiguous: int = 0) -> AlertDraft:
    return AlertDraft(
        rule_id="reflex_approval", subject=subject, window_start=r, severity="warning", value=count,
        detail={"count": count, "ambiguous_views": ambiguous, "threshold": 3},
    )  # fmt: skip


def test_daily_slots_isolated() -> None:
    """Mốc là 02:00 giờ VN; hai mốc cách nhau hơn 7 ngày đọc lùi + 7 mốc (luật 1 và luật 7 đều lùi 7 ngày)."""
    now = rs.daily_now(0)
    assert now.astimezone(VN_TZ).hour == 2 and (now - 2 * H).astimezone(VN_TZ).hour == 0
    assert rs.DAILY_SLOT > 14 * DAY


# ---- luật 1: escalation_rate_weighted 7 ngày VN trọn > 0,40 --------------------------------------------------------------
# Nhóm N3 (R routine / A approval / S sensitive) = (số lá, số lá escalate), trọng số 0,7 / 0,2 / 0,1 chuẩn hoá trên nhóm có
# lá. Giá trị số thực tính trước bằng đúng phép cộng/nhân/chia theo thứ tự nhóm của `weigh`.

ESCALATION = pytest.mark.parametrize(
    ("k", "groups", "expected"),
    [
        # (0,7·0,5 + 0,2·1 + 0,1·0,5) / 1 → 0.6000000000000002; raw 3/5 = 0,6
        (0, {"routine": (2, 1), "approval": (1, 1), "sensitive": (2, 1)}, (0.6000000000000002, 0.6)),
        # (0,35 + 0 + 0) / 1 → 0.35000000000000003 → không báo
        (1, {"routine": (2, 1), "approval": (1, 0), "sensitive": (2, 0)}, None),
        # (0,35 + 0 + 0,05) / 1 → đúng 0.4 → bằng ngưỡng, không báo
        (2, {"routine": (2, 1), "approval": (1, 0), "sensitive": (2, 1)}, None),
    ],
    ids=["vuot", "khong", "bang"],
)  # fmt: skip


@ESCALATION
@pytest.mark.asyncio
async def test_escalation_threshold(
    k: int, groups: dict[str, tuple[int, int]], expected: tuple[float, float] | None, rw: AsyncEngine, mon: AsyncEngine
) -> None:
    now = rs.daily_now(k)
    d0 = now - 2 * H
    async with rw.begin() as conn:
        for group, (n, escalated) in groups.items():
            for i in range(n):
                await rs.n3_leaf(conn, group=group, escalated=i < escalated, created_at=d0 - 3 * DAY)
    assert await run(mon, now) == ([] if expected is None else [escalation(d0, *expected)])


@pytest.mark.asyncio
async def test_escalation_window_bounds(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Cửa sổ `[d0 − 7 ngày, d0)` (Q-M9-B2-1): X escalate tạo ĐÚNG `d0 − 7 ngày` (tính), Y không escalate trong cửa sổ;
    Z escalate đúng `d0` và W escalate `d0 − 7 ngày − 1 µs` (không tính) → 1/2 = 0,5 (thêm Z hoặc W thì số đổi)."""
    now = rs.daily_now(3)
    d0 = now - 2 * H
    async with rw.begin() as conn:
        await rs.n3_leaf(conn, group="routine", escalated=True, created_at=d0 - 7 * DAY)
        await rs.n3_leaf(conn, group="routine", escalated=False, created_at=d0 - 7 * DAY + H)
        await rs.n3_leaf(conn, group="routine", escalated=True, created_at=d0)
        await rs.n3_leaf(conn, group="routine", escalated=True, created_at=d0 - 7 * DAY - US)
    assert await run(mon, now) == [escalation(d0, 0.5, 0.5)]


# ---- luật 7: reflex_approval ---------------------------------------------------------------------------------------------
# Phiếu quyết lúc `d0 − 12 giờ` (mốc r = d0), dòng B16 sau 1 s. Nhanh = không xem; bình thường = xem 30 s, người chính, chưa
# nhắc 2. Người duyệt mới mỗi ca.


async def fast(conn: Any, approver: str, d0: datetime, n: int = 1) -> None:
    for _ in range(n):
        await rs.reflex_decision(conn, approver=approver, decided_at=d0 - 12 * H)


@pytest.mark.asyncio
async def test_reflex_three_fast(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """A: 3 phiếu nhanh → 1 draft (count 3). A2: 2 nhanh + 1 xem đúng 5,0 giây (không tính) → count 2 → không báo."""
    now = rs.daily_now(4)
    d0 = now - 2 * H
    a, a2 = seed.new_id("l1"), seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, a, d0, 3)
        await fast(conn, a2, d0, 2)
        await rs.reflex_decision(conn, approver=a2, decided_at=d0 - 12 * H, b16={**NORMAL, "view_duration": 5.0})
    assert await run(mon, now) == [reflex(a, d0, 3)]


@pytest.mark.asyncio
async def test_reflex_two_approvers_two_drafts(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Luật theo đối tượng: hai người, mỗi người 3 phiếu nhanh, cùng mốc → 2 draft (không gộp)."""
    now = rs.daily_now(5)
    d0 = now - 2 * H
    b, c = seed.new_id("l1"), seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, b, d0, 3)
        await fast(conn, c, d0, 3)
    drafts = await run(mon, now)
    assert sorted(drafts, key=lambda d: d.subject) == sorted([reflex(b, d0, 3), reflex(c, d0, 3)], key=lambda d: d.subject)


@pytest.mark.asyncio
async def test_reflex_timeout_not_counted(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """D: 2 nhanh + 1 phiếu `timeout` (dòng B16 `approval_timeout`, `approval_result='timeout'`, không xem) → count 2 →
    không báo. Loader lọc ở SQL (`status = ANY(:decisions)`): phiếu timeout không có trong đầu ra (luật cũng tự lọc —
    nên assert ở tầng loader).

    Assert trên TOÀN BỘ đầu ra loader, không qua `decisions(…)`: phiếu timeout không có người quyết (`decided_by` NULL,
    như worker/B16 đóng hết hạn) nên lọc theo người quyết thì không bao giờ thấy nó — bỏ lọc status ở SQL vẫn xanh. Phiếu
    timeout quyết lúc d0 − 12h ≥ `daily_since` = d0 − 7 ngày nên chắc chắn được đọc nếu SQL không lọc; chỉ test này seed
    phiếu timeout (module = DB riêng) nên dữ liệu mốc khác không làm nhiễu."""
    now = rs.daily_now(6)
    d0 = now - 2 * H
    d = seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, d, d0, 2)
        await rs.reflex_decision(conn, approver=d, decided_at=d0 - 12 * H, status="timeout")
    assert await run(mon, now) == []
    assert [x.status for x in await decisions(mon, now, d)] == ["approved", "approved"]
    async with mon.connect() as conn:
        everything = await LOADERS["reflex_approval"](conn, ctx(now))
    assert isinstance(everything, list) and everything  # quét không rỗng (ít nhất 2 phiếu của D)
    assert [x for x in everything if x.status == "timeout"] == []


@pytest.mark.asyncio
async def test_reflex_plan_changed_counted(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """#14 5955436721: ca duyệt mà kế hoạch đã đổi — dòng B16 event `action_plan_changed_since_approval`, cột
    `approval_result='approved'` — nối theo CỘT nên khớp: 2 nhanh + 1 ca này (không xem) → count 3, ambiguous 0 (lọc theo
    `event` thì phiếu này mất dòng B16 → thành mơ hồ → ambiguous 1)."""
    now = rs.daily_now(7)
    d0 = now - 2 * H
    e = seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, e, d0, 2)
        await rs.reflex_decision(conn, approver=e, decided_at=d0 - 12 * H, event="action_plan_changed_since_approval")
    assert await run(mon, now) == [reflex(e, d0, 3)]
    assert [x.b16 for x in await decisions(mon, now, e)] == [FAST, FAST, FAST]


@pytest.mark.asyncio
async def test_reflex_two_approvals_same_ticket(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Chốt Q-M9-B2-6: một ticket hai phiếu nối tiếp, mỗi phiếu nối ĐÚNG dòng B16 của mình. T.p1 (tạo d0−20h, quyết
    d0−19h, B16 nhanh), T.p2 (tạo d0−18h, quyết d0−17h, B16 bình thường) + X1, X2 nhanh → count 3 (p2 không tính). Bỏ
    `created_at ≥ phiếu.created_at` thì p2 lấy dòng sớm nhất (của p1) → count 4."""
    now = rs.daily_now(8)
    d0 = now - 2 * H
    f = seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, f, d0, 2)
        t = await rs.reflex_decision(conn, approver=f, decided_at=d0 - 19 * H, created_at=d0 - 20 * H)
        await rs.reflex_decision(conn, approver=f, decided_at=d0 - 17 * H, created_at=d0 - 18 * H, ticket_id=t,
                                 b16=NORMAL)  # fmt: skip
    assert await run(mon, now) == [reflex(f, d0, 3)]
    assert [x.b16 for x in await decisions(mon, now, f)] == [FAST, NORMAL, FAST, FAST]  # theo decided_at


@pytest.mark.asyncio
async def test_reflex_previous_approval_without_b16(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B2-23 (chốt PR #31): U.p1 (tạo d0−20h, quyết d0−19h) KHÔNG có dòng B16; U.p2 (tạo d0−18h, quyết d0−17h)
    có dòng B16 bình thường ghi ĐÚNG lúc `decided_at` của p2 (cùng `clock.now()`, có thể bằng nhau). Chặn trên của p1 =
    `decided_at` p2 = d0−17h; `d0−17h > d0−17h` sai → dòng đó KHÔNG thuộc p1 → p1 mơ hồ; p2 nối dòng của mình (bình
    thường). G: Y1, Y2 nhanh + U.p1 mơ hồ → count 3, ambiguous 1. Bỏ chặn trên, hoặc so `>=`, thì p1 mượn dòng bình
    thường của p2 → count 2 → không báo (sót)."""
    now = rs.daily_now(9)
    d0 = now - 2 * H
    g = seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, g, d0, 2)
        u = await rs.reflex_decision(conn, approver=g, decided_at=d0 - 19 * H, created_at=d0 - 20 * H, with_b16=False)
        await rs.reflex_decision(conn, approver=g, decided_at=d0 - 17 * H, created_at=d0 - 18 * H, ticket_id=u,
                                 b16=NORMAL, b16_at=d0 - 17 * H)  # fmt: skip
    assert await run(mon, now) == [reflex(g, d0, 3, 1)]
    assert [x.b16 for x in await decisions(mon, now, g)] == [None, NORMAL, FAST, FAST]


@pytest.mark.asyncio
async def test_reflex_missing_b16_ambiguous(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B2-6: phiếu đã quyết mà không có dòng B16 → mơ hồ (báo thừa): 2 nhanh + 1 thiếu B16 → count 3, ambiguous 1.
    LEFT JOIN: JOIN thường thì phiếu thiếu B16 mất hẳn → count 2."""
    now = rs.daily_now(10)
    d0 = now - 2 * H
    h = seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, h, d0, 2)
        await rs.reflex_decision(conn, approver=h, decided_at=d0 - 12 * H, with_b16=False)
    assert await run(mon, now) == [reflex(h, d0, 3, 1)]
    assert [x.b16 for x in await decisions(mon, now, h)] == [FAST, FAST, None]


@pytest.mark.asyncio
async def test_reflex_detail_not_object(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """`detail` dòng B16 là mảng JSON → loader trả `{}` (không ném) → luật xếp mơ hồ: 2 nhanh + 1 → count 3, ambiguous 1."""
    now = rs.daily_now(11)
    d0 = now - 2 * H
    i = seed.new_id("l1")
    async with rw.begin() as conn:
        await fast(conn, i, d0, 2)
        await rs.reflex_decision(conn, approver=i, decided_at=d0 - 12 * H, b16=[1])
    assert await run(mon, now) == [reflex(i, d0, 3, 1)]
    assert [x.b16 for x in await decisions(mon, now, i)] == [FAST, FAST, {}]


@pytest.mark.asyncio
async def test_reflex_daily_since_bound(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Mốc dưới loader = `daily_since` = d0 − 7 ngày (đầu cửa sổ của mốc cũ nhất r = d0 − 6 ngày). J: 3 nhanh quyết ĐÚNG
    d0 − 7 ngày → 1 draft `window_start = d0 − 6 ngày`. K: 3 nhanh quyết d0 − 7 ngày − 1 µs → không báo và loader không
    đọc (đọc từ `now − 24 giờ` thì mất draft của J)."""
    now = rs.daily_now(12)
    d0 = now - 2 * H
    j, k = seed.new_id("l1"), seed.new_id("l1")
    async with rw.begin() as conn:
        for _ in range(3):
            await rs.reflex_decision(conn, approver=j, decided_at=d0 - 7 * DAY)
            await rs.reflex_decision(conn, approver=k, decided_at=d0 - 7 * DAY - US)
    assert await run(mon, now) == [reflex(j, d0 - 6 * DAY, 3)]
    assert len(await decisions(mon, now, j)) == 3
    assert await decisions(mon, now, k) == []


# ---- luật 12, 13: nguồn pending tới Phase 5 ----------------------------------------------------------------------------

DEGRADED = pytest.mark.parametrize(
    ("k", "rule_id", "key", "point"),
    [(13, "b2_degraded", "b2_classifier", rs.b2_point), (14, "b3_degraded", "b3_cascade", rs.b3_point)],
    ids=["12", "13"],
)  # fmt: skip


@pytest.mark.asyncio
async def test_degraded_pending_skipped(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B2-1, Q-M9-9: có dữ liệu vượt ngưỡng thật (mọi dòng xuống LLM) mà luật 12/13 vẫn `skipped`, 0 draft — pending
    đến từ `is_pending`, không phải từ việc thiếu dữ liệu."""
    now = rs.daily_now(15)
    d0 = now - 2 * H
    async with rw.begin() as conn:
        await rs.b2_point(conn, created_at=d0 - 12 * H, layer="llm")
        await rs.b3_point(conn, created_at=d0 - 12 * H, layer="llm")
    assert await run(mon, now) == []


@DEGRADED
@pytest.mark.asyncio
async def test_degraded_ready_seven_marks(
    k: int, rule_id: str, key: str, point: Any, rw: AsyncEngine, mon: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vá RIÊNG khoá nguồn sang ready: loader gọi hàm A thật trên 7 ngày VN. Hàm A đếm DÒNG audit (`count(*)`), mỗi lá
    ở đây có đúng 1 dòng nên số dòng = số lá (theo dòng audit — chốt Q-M9-B2-27). Lá tạo d0 − 12h
    (mốc d0) có 1 dòng `llm` → 1/1 dòng; lá tạo d0 − 2 ngày − 12h (mốc d0 − 2 ngày) có 1 dòng `rule` → 0/1, không báo;
    lá tạo d0 − 5 ngày − 12h (mốc d0 − 5 ngày) có 1 dòng `llm` → 1/1. Mốc khác 0 dòng → None. → 2 draft, cũ → mới."""
    real = rules_data.is_pending
    monkeypatch.setattr(rules_data, "is_pending", lambda name: False if name == key else real(name))
    now = rs.daily_now(k)
    d0 = now - 2 * H
    async with rw.begin() as conn:
        await point(conn, created_at=d0 - 12 * H, layer="llm")
        await point(conn, created_at=d0 - 2 * DAY - 12 * H, layer="rule")
        await point(conn, created_at=d0 - 5 * DAY - 12 * H, layer="llm")
    drafts = await run(mon, now, skipped=[r for r in PENDING_DAILY if r != rule_id])
    assert drafts == [
        AlertDraft(rule_id=rule_id, subject=SYSTEM_SUBJECT, window_start=r, severity="warning", value=1.0,
                   detail={"rate": 1.0, "threshold": 0.3})
        for r in (d0 - 5 * DAY, d0)
    ]  # fmt: skip
