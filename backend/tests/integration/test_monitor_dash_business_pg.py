"""M9 A1 — 10 chỉ số dashboard nghiệp vụ trên Postgres 16 thật, đọc bằng role `app_monitor` (kế hoạch M9 5.1, 4.3).

Mỗi test một ngày riêng của tháng 1/2030 làm cửa sổ (audit_logs chỉ ghi thêm); số kỳ vọng tính tay trong chú thích.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from app.monitor.queries import business as b
from app.monitor.queries.business import RuleCount
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

L1_A, L1_B = seed.SEED_APPROVERS
MIN = timedelta(minutes=1)


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


async def q(mon: AsyncEngine, fn: Callable[..., Awaitable[Any]], day: int, **kw: Any) -> Any:
    async with mon.connect() as conn:
        return await fn(conn, *win(day), **kw)


async def resolved(conn: AsyncConnection, at: datetime, path: str = "auto", **kw: Any) -> str:
    return await seed.leaf_ticket(conn, created_at=at, final_state="S_RESOLVED", resolution_path=path, **kw)


async def escalated(conn: AsyncConnection, at: datetime, code: str, **kw: Any) -> str:
    return await seed.leaf_ticket(
        conn, created_at=at, exit_code=code, final_state="S_ESCALATED", resolution_path="escalated", **kw
    )


@pytest.mark.asyncio
async def test_two_intent_sentence_counts_two(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Mỗi "câu 2 ý" = 1 cha + 2 con; cha cũng mang mã, phiếu, điểm log 4, escalation (dữ liệu xấu cố ý) → đếm 2."""
    at = win(1)[0] + timedelta(hours=1)
    state: dict[str, Any] = {"final_state": "S_ESCALATED", "resolution_path": "escalated"}
    async with rw.begin() as conn:
        p6, c6 = await seed.parent_with_children(
            conn, created_at=at, parent_exit_code="E6", parent_final_state="S_ESCALATED", exit_code="E6", **state
        )
        for t in (p6, *c6):
            await seed.approval(conn, t, approver_id=L1_A, created_at=at, status="timeout")
            await seed.audit_point4(conn, t, created_at=at, policy_decision="approval_required", matched_rule_id="R01")
        p1, c1 = await seed.parent_with_children(
            conn, created_at=at, parent_exit_code="E1", parent_final_state="S_ESCALATED", exit_code="E1", **state
        )
        for t in (p1, *c1):
            await seed.escalation(conn, t, exit_code="E1", created_at=at, reason_detail="out_of_scope")
        await seed.parent_with_children(
            conn, created_at=at, parent_exit_code="E3", parent_final_state="S_ESCALATED", exit_code="E3", **state
        )
    assert await q(mon, b.approval_expired_count, 1) == 2
    assert await q(mon, b.approval_expired_count, 1, approver_id=L1_A) == 2
    assert await q(mon, b.decided_by_distribution, 1) == {"rule": 2}
    assert await q(mon, b.top_matched_rules, 1) == [RuleCount("R01", 2)]
    e1 = await q(mon, b.e1_split, 1)
    assert (e1.total, e1.counts["out_of_scope"]) == (2, 2)
    assert len((await q(mon, b.e3_cases, 1)).items) == 2
    weighted = await q(mon, b.escalation_rate_weighted, 1)  # 6 lá, đều escalate: approval 2/2, routine 4/4
    assert weighted.by_group == {"routine": 1.0, "approval": 1.0, "sensitive": None}


@pytest.mark.asyncio
async def test_ratios_ignore_parent_with_different_outcome(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """D-30 cho 4 chỉ số tỉ lệ: cha kết cục KHÁC con. Cha `S_RESOLVED` deflected, không phiếu, không escalation;
    2 con E1 đã kết thúc. Chỉ lá: raw 2/2, automation 0/2, deflection 0/2. Đếm cả cha (đọc `tickets`) sẽ ra
    2/3, 1/3, 1/3 → đỏ. (Khi cha cùng kết cục với con, tỉ lệ không đổi nên các test khác không bắt được.)
    Có `UPDATE tickets` vì `parent_with_children` không nhận `resolution_path` cho cha; thiếu cha deflected thì
    `deflection_rate` đọc nhầm `tickets` vẫn ra 0/3 = 0,0 → không bắt được."""
    at = win(16)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        parent, _ = await seed.parent_with_children(
            conn, 2, created_at=at, parent_final_state="S_RESOLVED", exit_code="E1", final_state="S_ESCALATED",
            resolution_path="escalated",
        )  # fmt: skip
        # parent_with_children không nhận resolution_path cho cha → đặt tại chỗ (app_rw được UPDATE tickets)
        await conn.execute(
            text("UPDATE tickets SET resolution_path = 'deflected' WHERE ticket_id = :p AND is_parent"), {"p": parent}
        )
    assert await q(mon, b.escalation_rate_raw, 16) == 1.0
    assert await q(mon, b.automation_rate, 16) == 0.0
    assert await q(mon, b.deflection_rate, 16) == 0.0
    weighted = await q(mon, b.escalation_rate_weighted, 16)
    assert weighted.raw == 1.0
    assert weighted.by_group == {"routine": 1.0, "approval": None, "sensitive": None}  # con không tới M5 → routine
    assert weighted.weighted == pytest.approx(1.0)  # weigh() nhân/chia float: 3 lá routine ra 0,9999999999999999


@pytest.mark.asyncio
async def test_automation_rate_hand(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = win(2)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        await resolved(conn, at)  # tự động
        await resolved(conn, at, path="deflected")  # tự động — P8 §6.2 gồm ca deflected
        with_approval = await resolved(conn, at, path="approved")
        await seed.approval(conn, with_approval, approver_id=L1_A, created_at=at, status="approved", decided_by=L1_A)
        with_escalation = await resolved(conn, at)
        await seed.escalation(conn, with_escalation, exit_code="E8", created_at=at, closed_at=at + MIN)
        await escalated(conn, at, "E3")
        await seed.leaf_ticket(conn, created_at=at)  # đang chạy → ngoài mẫu số
    assert await q(mon, b.automation_rate, 2) == pytest.approx(2 / 5)


@pytest.mark.asyncio
async def test_escalation_raw_and_deflection_hand(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = win(3)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        await resolved(conn, at, path="deflected")
        await resolved(conn, at)
        await escalated(conn, at, "E1")
        await escalated(conn, at, "E3")
        await seed.leaf_ticket(conn, created_at=at)  # đang chạy → ngoài mẫu số
    assert await q(mon, b.escalation_rate_raw, 3) == pytest.approx(2 / 4)
    assert await q(mon, b.deflection_rate, 3) == pytest.approx(1 / 4)


@pytest.mark.asyncio
async def test_weighted_hand_4b_reality(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """routine 4 lá (2 không tới M5, 2 allow; 1 escalate), approval 2 (1 E6), sensitive 2 (deny E5 + LLM-tắt E5
    R17–R19) → by_group 0,25 / 0,5 / 1,0; weighted 0,7·0,25 + 0,2·0,5 + 0,1·1 = 0,375; raw 4/8."""
    at = win(4)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        await escalated(conn, at, "E1")
        await resolved(conn, at)
        for _ in range(2):
            await seed.audit_point4(conn, await resolved(conn, at), created_at=at, policy_decision="allow")
        approved = await resolved(conn, at, path="approved")
        await seed.audit_point4(conn, approved, created_at=at, policy_decision="approval_required")
        expired = await escalated(conn, at, "E6")
        await seed.audit_point4(conn, expired, created_at=at, policy_decision="approval_required")
        denied = await escalated(conn, at, "E5")
        await seed.audit_point4(conn, denied, created_at=at, policy_decision="deny", exit_code="E5")
        await seed.llm_disabled_case(conn, created_at=at)
        running = await seed.leaf_ticket(conn, created_at=at)  # đang chạy → ngoài mẫu số
        await seed.audit_point4(conn, running, created_at=at, policy_decision="deny")
    r = await q(mon, b.escalation_rate_weighted, 4)
    assert r.by_group == {"routine": 0.25, "approval": 0.5, "sensitive": 1.0}
    assert r.weighted == pytest.approx(0.375)
    assert r.raw == pytest.approx(0.5)
    assert r.sensitivity == {"60/30/10": pytest.approx(0.40), "80/15/5": pytest.approx(0.325)}


@pytest.mark.asyncio
async def test_weighted_only_routine_renormalized(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = win(5)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        for _ in range(2):
            await seed.audit_point4(conn, await resolved(conn, at), created_at=at, policy_decision="allow")
        await resolved(conn, at)
        await escalated(conn, at, "E1")
    r = await q(mon, b.escalation_rate_weighted, 5)
    assert r.by_group == {"routine": 0.25, "approval": None, "sensitive": None}
    assert r.weighted == pytest.approx(0.25)  # không phải 0,7 × 0,25
    assert r.sensitivity == {"60/30/10": pytest.approx(0.25), "80/15/5": pytest.approx(0.25)}


@pytest.mark.asyncio
async def test_group_most_sensitive_row(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """A: deny rồi allow; B: allow rồi deny → cả hai sensitive (không theo dòng đầu/cuối). C: allow + risk high cùng
    dòng → sensitive. D, E: allow/low → routine (allow KHÔNG vào sensitive). sensitive 2/3, routine 1/2."""
    at = win(6)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        a = await escalated(conn, at, "E5")
        await seed.audit_point4(conn, a, created_at=at, policy_decision="deny")
        await seed.audit_point4(conn, a, created_at=at + MIN, policy_decision="allow")
        b_ = await escalated(conn, at, "E5")
        await seed.audit_point4(conn, b_, created_at=at, policy_decision="allow")
        await seed.audit_point4(conn, b_, created_at=at + MIN, policy_decision="deny")
        c = await resolved(conn, at)
        await seed.audit_point4(conn, c, created_at=at, policy_decision="allow", risk_level="high")
        await seed.audit_point4(conn, await resolved(conn, at), created_at=at, policy_decision="allow")
        await seed.audit_point4(conn, await escalated(conn, at, "E8"), created_at=at, policy_decision="allow")
    r = await q(mon, b.escalation_rate_weighted, 6)
    assert r.by_group == {"routine": 0.5, "approval": None, "sensitive": pytest.approx(2 / 3)}


@pytest.mark.asyncio
async def test_point4_one_row_per_leaf(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Mỗi lá một dòng điểm log 4: nhạy nhất; hòa → mới nhất (`created_at`, rồi `log_id`)."""
    at = win(7)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        a = await resolved(conn, at)
        await seed.audit_point4(conn, a, created_at=at, policy_decision="deny", matched_rule_id="R02")
        await seed.audit_point4(conn, a, created_at=at + MIN, policy_decision="allow", matched_rule_id="R01")
        b_ = await resolved(conn, at)
        await seed.audit_point4(conn, b_, created_at=at, policy_decision="allow", matched_rule_id="R01")
        await seed.audit_point4(conn, b_, created_at=at + MIN, policy_decision="deny", matched_rule_id="R02")
        g = await resolved(conn, at)
        await seed.audit_point4(conn, g, created_at=at, policy_decision="allow", matched_rule_id="R01")
        await seed.audit_point4(
            conn, g, created_at=at + MIN, decided_by="llm", policy_decision=None, risk_level="high"
        )
        e = await resolved(conn, at)
        await seed.audit_point4(conn, e, created_at=at, policy_decision="approval_required", matched_rule_id="R03")
        await seed.audit_point4(
            conn, e, created_at=at + MIN, policy_decision="approval_required", matched_rule_id="R04"
        )
        f = await resolved(conn, at)  # cùng created_at → log_id lớn hơn thắng
        await seed.audit_point4(conn, f, created_at=at, policy_decision="approval_required", matched_rule_id="R05")
        await seed.audit_point4(conn, f, created_at=at, policy_decision="approval_required", matched_rule_id="R06")
    assert await q(mon, b.decided_by_distribution, 7) == {"llm": 1, "rule": 4}
    assert await q(mon, b.top_matched_rules, 7) == [RuleCount("R02", 2), RuleCount("R04", 1), RuleCount("R06", 1)]


@pytest.mark.asyncio
async def test_top_rules_limit_and_tie(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = win(8)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        for rule in ["R00", "R00", *(f"R{i:02d}" for i in range(12, 0, -1))]:
            await seed.audit_point4(conn, await resolved(conn, at), created_at=at, matched_rule_id=rule)
    top = await q(mon, b.top_matched_rules, 8)
    assert top == [RuleCount("R00", 2), *(RuleCount(f"R{i:02d}", 1) for i in range(1, 10))]


@pytest.mark.asyncio
async def test_approval_expired_and_own(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """L1 A: 1 E6 + 1 đã duyệt; L1 B: 1 E6. Hai L1 không thấy số của nhau; own trả đúng 3 khóa."""
    at = win(9)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        t1 = await escalated(conn, at, "E6")
        await seed.approval(conn, t1, approver_id=L1_A, created_at=at, status="timeout")
        await seed.audit_point4(conn, t1, created_at=at, policy_decision="approval_required", matched_rule_id="R10")
        t2 = await resolved(conn, at, path="approved")
        await seed.approval(conn, t2, approver_id=L1_A, created_at=at, status="approved", decided_by=L1_A)
        await seed.audit_point4(conn, t2, created_at=at, policy_decision="approval_required", matched_rule_id="R11")
        t3 = await escalated(conn, at, "E6")
        await seed.approval(conn, t3, approver_id=L1_B, created_at=at, status="timeout")
        await seed.audit_point4(conn, t3, created_at=at, policy_decision="approval_required", matched_rule_id="R12")
    assert await q(mon, b.approval_expired_count, 9) == 2
    own_a = await q(mon, b.business_metrics, 9, approver_id=L1_A)
    own_b = await q(mon, b.business_metrics, 9, approver_id=L1_B)
    for own in (own_a, own_b):
        assert tuple(own.values) == b.OWN_KEYS
        assert own.unavailable == ()
    assert own_a.values == {
        "approval_expired_count": 1,
        "decided_by_distribution": {"rule": 2},  # cột audit_logs, không phải approvals.decided_by (user id)
        "top_matched_rules": [RuleCount("R10", 1), RuleCount("R11", 1)],
    }
    assert own_b.values == {
        "approval_expired_count": 1,
        "decided_by_distribution": {"rule": 1},
        "top_matched_rules": [RuleCount("R12", 1)],
    }


@pytest.mark.asyncio
async def test_e1_split_verbatim_and_other(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = win(10)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        for reason in ("out_of_scope", "multi_intent_not_enabled", "intent_low_confidence", "intent_not_enabled"):
            leaf = await escalated(conn, at, "E1")
            await seed.escalation(conn, leaf, exit_code="E1", created_at=at, reason_detail=reason)
        odd = await escalated(conn, at, "E1")
        await seed.escalation(conn, odd, exit_code="E1", created_at=at, reason_detail="role_unmappable")  # → other
        await escalated(conn, at, "E1")  # không có dòng escalations → other (không rơi ca)
        twice = await escalated(conn, at, "E1")  # dòng E1 mới nhất thắng
        await seed.escalation(conn, twice, exit_code="E1", created_at=at, reason_detail="role_unmappable")
        await seed.escalation(conn, twice, exit_code="E1", created_at=at + MIN, reason_detail="out_of_scope")
        e3 = await escalated(conn, at, "E3")  # không phải E1
        await seed.escalation(conn, e3, exit_code="E3", created_at=at, reason_detail="out_of_scope")
    e1 = await q(mon, b.e1_split, 10)
    assert dict(e1.counts) == {
        "out_of_scope": 2, "multi_intent_not_enabled": 1, "intent_low_confidence": 1, "intent_not_enabled": 1,
        "other": 2,
    }  # fmt: skip
    assert e1.total == 7 == sum(e1.counts.values())
    assert e1.shares["out_of_scope"] == pytest.approx(2 / 7)
    assert e1.shares["other"] == pytest.approx(2 / 7)


@pytest.mark.asyncio
async def test_e3_cases_fields(rw: AsyncEngine, mon: AsyncEngine) -> None:
    t0 = win(11)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        a = await escalated(conn, t0, "E3", intent="vpn", redacted_request="x" * 300)
        await seed.audit_row(conn, a, step="B8", event="retrieved", created_at=t0, kb_version="a" * 64)
        await seed.audit_row(conn, a, step="B10", event="no_grounding", created_at=t0 + MIN, kb_version="b" * 64)
        await seed.audit_row(conn, a, step="B20", event="finalized", created_at=t0 + 2 * MIN)  # kb_version NULL
        no_kb = await escalated(conn, t0 + timedelta(hours=1), "E3")
        _, (child,) = await seed.parent_with_children(
            conn, 1, created_at=t0 + timedelta(hours=2), parent_exit_code="E3", parent_final_state="S_ESCALATED",
            exit_code="E3", final_state="S_ESCALATED",
        )  # fmt: skip
    got = await q(mon, b.e3_cases, 11)
    assert got.truncated is False
    cases = got.items
    assert [c.ticket_id for c in cases] == [child, no_kb, a]  # mới nhất trước, không có cha
    last = cases[2]
    assert (last.intent, last.kb_version, last.request_excerpt) == ("vpn", "b" * 64, "x" * 200)
    assert last.created_at == t0
    assert cases[1].kb_version is None  # không có kb_version → null, vẫn giữ ca


@pytest.mark.asyncio
async def test_e3_cases_truncated_101(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """A3 (review PR #22, Q-M9-A3-4): ngày 18 có 101 lá E3 → 100 mục, `truncated=true`, mất đúng ca CŨ nhất; ngày 19 có
    đúng 100 → 100 mục, `false` (biên)."""
    t18, t19 = win(18)[0], win(19)[0]
    async with rw.begin() as conn:
        day18 = [await escalated(conn, t18 + i * MIN, "E3") for i in range(101)]
        for i in range(100):
            await escalated(conn, t19 + i * MIN, "E3")
    got = await q(mon, b.e3_cases, 18)
    assert (len(got.items), got.truncated) == (100, True)
    assert [c.ticket_id for c in got.items] == day18[:0:-1]  # mới nhất trước, ca đầu tiên (cũ nhất) bị cắt
    got = await q(mon, b.e3_cases, 19)
    assert (len(got.items), got.truncated) == (100, False)


@pytest.mark.asyncio
async def test_zero_denominator_none(rw: AsyncEngine, mon: AsyncEngine) -> None:
    for day in (12, 13):  # 12: cửa sổ trống; 13: chỉ có lá đang chạy (ngoài mẫu số)
        if day == 13:
            async with rw.begin() as conn:
                running = await seed.leaf_ticket(conn, created_at=win(13)[0] + timedelta(hours=1))
                await seed.audit_point4(conn, running, created_at=win(13)[0], policy_decision="deny")
        for fn in (b.automation_rate, b.escalation_rate_raw, b.deflection_rate):
            assert await q(mon, fn, day) is None, (day, fn.__name__)
        r = await q(mon, b.escalation_rate_weighted, day)
        assert (r.raw, r.weighted) == (None, None)
        assert r.by_group == dict.fromkeys(("routine", "approval", "sensitive"))
        assert r.sensitivity == dict.fromkeys(("60/30/10", "80/15/5"))
        e1 = await q(mon, b.e1_split, day)
        assert e1.total == 0 and set(e1.shares.values()) == {None}
        assert await q(mon, b.approval_expired_count, day) == 0
        assert await q(mon, b.override_count, day) == 0  # đếm → 0, không None
        assert await q(mon, b.e3_cases, day) == b.E3Cases(items=(), truncated=False)
    assert await q(mon, b.decided_by_distribution, 12) == {}
    assert await q(mon, b.top_matched_rules, 12) == []
    empty = await q(mon, b.business_metrics, 12)
    assert empty.values["override_count"] == 0  # cửa sổ trống: 0, không None
    assert empty.unavailable == ()  # không vào `unavailable`


@pytest.mark.asyncio
async def test_business_metrics_all_keys_and_unavailable(rw: AsyncEngine, mon: AsyncEngine) -> None:
    at = win(14)[0] + timedelta(hours=1)
    async with rw.begin() as conn:
        await resolved(conn, at)
    m = await q(mon, b.business_metrics, 14)
    assert tuple(m.values) == b.BUSINESS_METRICS
    assert m.values["override_count"] == 0  # 4d đã nối: không dòng ghi đè → 0
    assert m.unavailable == ()
    assert m.values["automation_rate"] == 1.0


@pytest.mark.asyncio
async def test_window_bounds(rw: AsyncEngine, mon: AsyncEngine) -> None:
    frm, to = win(25)  # lá `to` rơi vào 26/01 00:00 UTC (07:00 VN), ngày không test nào dùng (R26 sửa kèm a)
    async with rw.begin() as conn:
        await resolved(conn, frm)  # đúng frm → tính
        await escalated(conn, to, "E1")  # đúng to → không tính
    assert await q(mon, b.escalation_rate_raw, 25) == 0.0  # đã đo, không có ca escalate (khác None)


@pytest.mark.asyncio
async def test_override_count_rows_on_leaves(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Đếm DÒNG ghi đè của lá, kỳ vọng 3: lá A (đã xong) 2 dòng (L1_A, L1_B) + lá B (ĐANG CHẠY, không lọc final_state) 1
    dòng; ticket cha có 1 dòng → không tính (v_leaf). Dòng nhiễu không tính: step OVERRIDE nhưng event khác; event
    `override_recorded` nhưng step khác. Hai dòng nhiễu ghi thẳng, không `idempotency_key`/`overrider_id` (key NULL nằm
    ngoài `ux_audit_idem`)."""
    t = win(20)[0] + timedelta(hours=1)  # 20/01 01:00 UTC = 08:00 VN, trong cửa sổ UTC [20/01, 21/01)
    async with rw.begin() as conn:
        a, running = await resolved(conn, t), await seed.leaf_ticket(conn, created_at=t)
        parent, _ = await seed.parent_with_children(conn, 1, created_at=t)
        await seed.override(conn, a, created_at=t, overrider_id=L1_A)
        await seed.override(conn, a, created_at=t, overrider_id=L1_B)
        await seed.override(conn, running, created_at=t, overrider_id=L1_A)
        await seed.override(conn, parent, created_at=t, overrider_id=L1_A)
        noise = {"reason_code": "policy_gap"}
        await seed.audit_row(conn, a, step="OVERRIDE", event="override_denied", created_at=t, detail=noise)
        await seed.audit_row(conn, running, step="B13/B14", event="override_recorded", created_at=t, detail=noise)
    assert await q(mon, b.override_count, 20) == 3


@pytest.mark.asyncio
async def test_override_count_window_by_leaf_created_at(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Cửa sổ theo `created_at` của LÁ (không theo dòng audit), `win()` cắt theo UTC: [22/01 00:00, 23/01 00:00) UTC.
    Lá C tạo 22/01 01:00 UTC (08:00 VN) trong cửa sổ, 2 dòng ghi 23/01 02:00 UTC (09:00 VN, SAU `to`) → tính 2. Lá D tạo
    21/01 23:00 UTC (22/01 06:00 VN, trước `frm` 1 giờ; theo giờ VN đã sang ngày 22 nhưng cửa sổ cắt theo UTC), 1 dòng ghi
    22/01 01:00 UTC (trong cửa sổ) → không tính. Kỳ vọng 2; lọc theo `audit_logs.created_at` thì ra 1 (đỏ)."""
    frm, to = win(22)
    async with rw.begin() as conn:
        c = await resolved(conn, frm + timedelta(hours=1))
        d = await resolved(conn, datetime(2030, 1, 21, 23, tzinfo=UTC))
        for who in (L1_A, L1_B):
            await seed.override(conn, c, created_at=to + timedelta(hours=2), overrider_id=who)
        await seed.override(conn, d, created_at=frm + timedelta(hours=1), overrider_id=L1_A)
    assert await q(mon, b.override_count, 22) == 2
