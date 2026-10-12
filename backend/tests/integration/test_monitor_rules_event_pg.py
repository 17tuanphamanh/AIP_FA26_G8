"""M9-B1 GĐ2 — 7 loader (`queries/rules_data.py`) + `evaluate("minute")` trên Postgres 16 thật, đọc bằng role
`app_monitor`. File này KHÔNG chạy job ghi `alerts` (chỉ seed dòng `alerts` cho luật 3); job ghi thật ở
`test_monitor_jobs_minute_pg.py` (module riêng = DB riêng, Q-M9-B1-14).

Cô lập (Q-M9-B1-14): 1 DB/module; mỗi test `day(k)` riêng + đối tượng `new_id()`; mọi assert — kể cả "0 draft" — chỉ xét
subject của chính test (loader không có chặn trên theo `now` → test chạy trước thấy dữ liệu "tương lai" của test khác).
Nguồn: file chia việc M9 mục 6 (B1); chốt Q-M9-B1-1…19 ở #13.
"""

from collections.abc import AsyncIterator, Collection, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from app.domain.alerts import AlertDraft, bruteforce_alert, bruteforce_subject
from app.monitor.evaluator import LOADERS, EvalResult, evaluate
from app.monitor.queries import rules_data  # noqa: F401 — đăng ký loader
from app.monitor.rules import LOOKBACK, REGISTRY, RuleContext, RuleSpec
from app.monitor.window import VN_TZ
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from tests.integration import monitor_rules_seed as rs
from tests.integration import monitor_seed as seed
from tests.integration.pg import PgUrls, alembic_config, fresh_database

H = timedelta(hours=1)
S = timedelta(seconds=1)
MS = timedelta(milliseconds=1)
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


async def run(mon: AsyncEngine, now: datetime) -> EvalResult:
    async with mon.connect() as conn:  # như job: một connection, không transaction ngoài
        return await evaluate("minute", conn, RuleContext(now=now, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8))


def mine(result: EvalResult, rule_id: str, subjects: Collection[str]) -> list[AlertDraft]:
    """Draft của luật `rule_id` cho đối tượng của CHÍNH test (Q-M9-B1-14)."""
    return [d for d in result.drafts if d.rule_id == rule_id and d.subject in subjects]


def keys(drafts: list[AlertDraft]) -> list[tuple[str, str, datetime]]:
    return sorted((d.rule_id, d.subject, d.window_start) for d in drafts)


RULES = pytest.mark.parametrize("rule_id", rs.B1_RULES)


# ---- bảng chung 7 luật ---------------------------------------------------------------------------------------------


@RULES
@pytest.mark.asyncio
async def test_rule_has_event_one_draft(rule_id: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Một nguồn → đúng 1 draft; `window_start` = mốc lấy từ DB (không phải `now`); không luật nào lỗi."""
    now = rs.day(1)
    async with rw.begin() as conn:
        subject, window = await rs.seed_rule(conn, rule_id, at=now - H)
    result = await run(mon, now)
    drafts = mine(result, rule_id, [subject])
    assert [(d.subject, d.window_start) for d in drafts] == [(subject, window)]
    assert drafts[0].window_start != now
    # B2: luật 5 `breaker_open` luôn skipped tới khi `tool_spans` ready (Q-M9-4). Không ghim `== ["breaker_open"]`: lật
    # nguồn sang ready (ngoài M9) không được làm đỏ test B1.
    assert result.failed_rules == [] and set(result.skipped_rules) <= {"breaker_open"}


@RULES
@pytest.mark.asyncio
async def test_rule_no_event_no_draft(rule_id: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Dữ liệu gần giống nhưng không phải nguồn (E5, `still_locked`, `token_refreshed`, 10 lần bị từ chối, event B20
    khác, `role_changed`) → 0 draft cho đối tượng đó. Luật 11 (chưa có nơi ghi) không lỗi, không skipped (chốt 02/10)."""
    now = rs.day(2)
    async with rw.begin() as conn:
        subject = await rs.seed_noise(conn, rule_id, at=now - H)
    result = await run(mon, now)
    assert mine(result, rule_id, [subject]) == []
    assert rule_id not in result.failed_rules and rule_id not in result.skipped_rules


@RULES
@pytest.mark.asyncio
async def test_rule_lookback_boundary(rule_id: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Lookback 24 giờ tính cả mốc biên: nguồn ở `now − 24h` → có; ở `now − 24h − 1 s` → không."""
    now = rs.day(3)
    async with rw.begin() as conn:
        inside, window = await rs.seed_rule(conn, rule_id, at=now - LOOKBACK)
        outside, _ = await rs.seed_rule(conn, rule_id, at=now - LOOKBACK - S)
    result = await run(mon, now)
    assert [(d.subject, d.window_start) for d in mine(result, rule_id, [inside])] == [(inside, window)]
    assert mine(result, rule_id, [outside]) == []


@RULES
@pytest.mark.asyncio
async def test_two_subjects_same_window_two_drafts(rule_id: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Hai đối tượng cùng thời điểm → 2 draft (khoá cũ từng gộp thành 1 = bỏ sót)."""
    now = rs.day(4)
    async with rw.begin() as conn:
        a, wa = await rs.seed_rule(conn, rule_id, at=now - H)
        b, wb = await rs.seed_rule(conn, rule_id, at=now - H)
    assert wa == wb and a != b
    drafts = mine(await run(mon, now), rule_id, [a, b])
    assert sorted(d.subject for d in drafts) == sorted([a, b])


@RULES
@pytest.mark.asyncio
async def test_future_event_drafts_same_key_twice(rule_id: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B1-12: không chặn trên theo `now` — nguồn có thời điểm SAU `now` (lệch đồng hồ) vẫn ra draft, cùng khoá
    qua 2 lần chạy. Luật 3: bị HOÃN (chỉ đối soát sự kiện cũ hơn 60 s) chứ không mất."""
    now = rs.day(5)
    at = now + 10 * MIN
    async with rw.begin() as conn:
        subject, window = await rs.seed_rule(conn, rule_id, at=at)
    expected = [(rule_id, subject, window)]
    if rule_id == "password_bruteforce":
        assert mine(await run(mon, now), rule_id, [subject]) == []  # hoãn
        first, second = at + 60 * S, at + 120 * S
    else:
        first, second = now, now + 60 * S
    assert keys(mine(await run(mon, first), rule_id, [subject])) == expected
    assert keys(mine(await run(mon, second), rule_id, [subject])) == expected


# ---- luật 2/16: ticket lá, MIN trên mọi dòng ---------------------------------------------------------------------------


@pytest.mark.parametrize(("rule_id", "code", "first_step", "first_reason"), [
    ("injection_detected", "E0", "B11", "injection_in_reply"),
    ("execution_failed", "E7", "B17", "exec_interrupted"),
])  # fmt: skip
@pytest.mark.asyncio
async def test_ticket_exit_first_row_older_than_24h(
    rule_id: str, code: str, first_step: str, first_reason: str, rw: AsyncEngine, mon: AsyncEngine
) -> None:
    """Review #13: `first_at` = MIN trên MỌI dòng mang mã của ticket, KHÔNG cắt 24 giờ — dòng đầu ở `now − 30h`, dòng
    mới ở `now − 1h` → `window_start = now − 30h` (cắt 24 giờ thì khoá đổi → cảnh báo trùng). step/reason của dòng đầu.
    Review #24 mục 4: thêm dòng audit KHÔNG mang mã, sớm hơn (bỏ `a.exit_code = :code` ở truy vấn ngoài → lấy nhầm dòng
    này), và chèn dòng mới TRƯỚC dòng cũ (`ORDER BY log_id` thay `created_at` → lấy nhầm dòng mới)."""
    now = rs.day(6)
    async with rw.begin() as conn:
        ticket = await seed.leaf_ticket(conn, created_at=now - 31 * H, exit_code=code)
        await seed.audit_row(conn, ticket, step="B1", event="transition", created_at=now - 30 * H - 30 * MIN)
        new_log = await rs.exit_row(conn, ticket, code=code, at=now - H, step="runner", reason="execution_interrupted")
        old_log = await rs.exit_row(conn, ticket, code=code, at=now - 30 * H, step=first_step, reason=first_reason)
    assert new_log < old_log  # log_id BIGSERIAL tăng theo thứ tự chèn — tiền đề của ca ORDER BY log_id
    drafts = mine(await run(mon, now), rule_id, [ticket])
    assert [d.window_start for d in drafts] == [now - 30 * H]
    assert (drafts[0].detail["step"], drafts[0].detail["reason_detail"]) == (first_step, first_reason)


@pytest.mark.parametrize(("rule_id", "code"), [("injection_detected", "E0"), ("execution_failed", "E7")])
@pytest.mark.asyncio
async def test_ticket_exit_parent_not_alerted(rule_id: str, code: str, rw: AsyncEngine, mon: AsyncEngine) -> None:
    """D-30: "câu 2 ý" — cha mang mã tổng hợp và cũng có dòng audit (dữ liệu xấu cố ý) → đúng 2 draft (2 con)."""
    now = rs.day(7)
    async with rw.begin() as conn:
        parent, children = await seed.parent_with_children(conn, created_at=now - H, parent_exit_code=code,
                                                           exit_code=code)  # fmt: skip
        for t in (parent, *children):
            await rs.exit_row(conn, t, code=code, at=now - H)
    drafts = mine(await run(mon, now), rule_id, [parent, *children])
    assert sorted(d.subject for d in drafts) == sorted(children)


@pytest.mark.asyncio
async def test_finalize_failed_parent_alerted(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B1-4: luật 15 KHÔNG lọc `v_leaf` — ticket CHA kẹt ở B20 vẫn báo."""
    now = rs.day(8)
    async with rw.begin() as conn:
        parent, _ = await seed.parent_with_children(conn, created_at=now - H)
        await rs.finalize_row(conn, parent, at=now - H)
    drafts = mine(await run(mon, now), "finalize_failed", [parent])
    assert [(d.subject, d.window_start, d.detail["node"]) for d in drafts] == [(parent, now - H, "b20_audit")]


@pytest.mark.asyncio
async def test_ticket_exit_reason_detail_sources(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """`reason_detail` = `detail.escalation_reason_detail`, không có thì cột `block_reason` (khớp `goto.py`). Luật 2
    gồm mọi E0 (Q-M9-B1-1): B2 và B11/B19 `injection_in_reply`; luật 16 mọi E7."""
    now = rs.day(9)
    cases = [  # (luật, mã, step, reason)
        ("injection_detected", "E0", "B2", "injection_detected"),
        ("injection_detected", "E0", "B11", "injection_in_reply"),
        ("injection_detected", "E0", "B19", "injection_in_reply"),
        ("execution_failed", "E7", "B17", "exec_interrupted"),
        ("execution_failed", "E7", "runner", "execution_interrupted"),
    ]
    tickets = []
    async with rw.begin() as conn:
        for _, code, step, reason in cases:
            t = await seed.leaf_ticket(conn, created_at=now - H, exit_code=code)
            await rs.exit_row(conn, t, code=code, at=now - H, step=step, reason=reason)
            tickets.append(t)
    result = await run(mon, now)
    got = [
        [(d.detail["step"], d.detail["reason_detail"]) for d in mine(result, rule_id, [t])]
        for (rule_id, _, _, _), t in zip(cases, tickets, strict=True)
    ]
    assert got == [[(step, reason)] for _, _, step, reason in cases]


@pytest.mark.asyncio
async def test_4b_fixture_no_alert(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Fixture 4b: R17–R19 → E5 `llm_layer_disabled`; tra người duyệt lỗi → E2 → không phải luật 2/16."""
    now = rs.day(10)
    async with rw.begin() as conn:
        e5 = await seed.llm_disabled_case(conn, created_at=now - H)
        e2 = await seed.leaf_ticket(conn, created_at=now - H, exit_code="E2", final_state="S_ESCALATED")
        await rs.exit_row(conn, e2, code="E2", at=now - H, step="B15", reason="approver_lookup_error")
    result = await run(mon, now)
    assert mine(result, "injection_detected", [e5, e2]) == []
    assert mine(result, "execution_failed", [e5, e2]) == []


# ---- luật 3: đối soát ----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bruteforce_alert_read_back_60s(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Loader đọc `alerts` lùi thêm 60 s (review #13): khoá ở `now − 24h + 30 s`, cảnh báo auth có `window_start` sớm hơn
    40 s (AD chậm) — tức TRƯỚC mốc 24 giờ — vẫn phải thấy → không tạo bản trùng."""
    now = rs.day(11)
    lock_at = now - LOOKBACK + 30 * S
    async with rw.begin() as conn:
        user, _ = await rs.seed_rule(conn, "password_bruteforce", at=lock_at)
        await rs.alert(conn, rule_id="password_bruteforce", subject=user, window_start=lock_at - 40 * S)
    assert mine(await run(mon, now), "password_bruteforce", [user]) == []


@pytest.mark.asyncio
async def test_bruteforce_other_rule_same_subject_still_drafts(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Cảnh báo luật khác (`refresh_reuse`) cùng user, lệch 3 ms không che đợt khoá (lọc rule_id ở SQL — Q-M9-B1-13; luật
    vẫn tự kiểm, ghim bằng unit)."""
    now = rs.day(12)
    async with rw.begin() as conn:
        user, _ = await rs.seed_rule(conn, "password_bruteforce", at=now - H)
        await rs.alert(conn, rule_id="refresh_reuse", subject=user, window_start=now - H + 3 * MS)
    assert len(mine(await run(mon, now), "password_bruteforce", [user])) == 1


@pytest.mark.asyncio
async def test_bruteforce_ghost_username(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Username không có trong `users` lưu dạng "h:" + HMAC (4a, Q-3e-14): subject tính bằng CHÍNH `bruteforce_subject`
    như auth → khớp cảnh báo auth; xoá cảnh báo đó → M9 tạo đúng 1."""
    now = rs.day(13)
    ghost = "h:" + seed.new_id("x").replace("-", "") * 3
    subject = bruteforce_subject(None, ghost)
    occurred = await rs.auth_lock(rw, user_id=None, username=ghost, at=now - H)
    assert mine(await run(mon, now), "password_bruteforce", [subject]) == []
    async with rw.begin() as conn:
        await conn.execute(text("DELETE FROM alerts WHERE rule_id = 'password_bruteforce' AND subject = :s"),
                           {"s": subject})  # fmt: skip
    drafts = mine(await run(mon, now), "password_bruteforce", [subject])
    assert drafts == [bruteforce_alert(user_id=None, username=ghost, lock_start=occurred, source="m9_reconcile")]


# ---- luật 10, 11 ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_denied_reads_5min_back(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Loader đọc lùi thêm 5 phút: 3 sự kiện đầu trước mốc `now − 24h`, 8 sự kiện sau, cả 11 trong 220 s → 1 draft,
    `value == 11` (đọc từ đúng mốc 24 giờ thì chỉ thấy 8 → bỏ sót)."""
    now = rs.day(14)
    since = now - LOOKBACK
    user = seed.new_id("u")
    times = [since - 150 * S, since - 120 * S, since - 90 * S, *(since + 10 * i * S for i in range(8))]
    async with rw.begin() as conn:
        for at in times:
            await rs.security_event(conn, "permission_denied", occurred_at=at, user_id=user)
    drafts = mine(await run(mon, now), "permission_denied_burst", [user])
    assert [(d.value, d.detail["count"]) for d in drafts] == [(11, 11)]


@pytest.mark.asyncio
async def test_policy_saved_version_subject(rw: AsyncEngine, mon: AsyncEngine) -> None:
    """Q-M9-B1-5: subject = `detail.version`; thiếu → `event:<event_id>`."""
    now = rs.day(15)
    version = seed.new_id("v")
    async with rw.begin() as conn:
        await rs.security_event(conn, "policy_saved", occurred_at=now - H, detail={"version": version})
        event_id = await rs.security_event(conn, "policy_saved", occurred_at=now - H, detail={})
    result = await run(mon, now)
    assert [d.subject for d in mine(result, "policy_saved", [version, f"event:{event_id}"])] == [
        version, f"event:{event_id}"
    ]


# ---- chỉ đọc, lỗi một luật ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loader_connection_is_app_monitor(
    rw: AsyncEngine, mon: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader chạy bằng role `app_monitor`; loader thử INSERT → permission denied → chỉ luật đó vào `failed_rules`,
    luật khác vẫn ra draft (savepoint)."""
    now = rs.day(16)
    seen: list[str] = []

    async def whoami(conn: AsyncConnection, ctx: RuleContext) -> list[object]:
        seen.append((await conn.execute(text("SELECT current_user"))).scalar_one())
        return []

    async def writes(conn: AsyncConnection, ctx: RuleContext) -> list[object]:
        await conn.execute(text("INSERT INTO alerts (rule_id, subject, severity, window_start) "
                                "VALUES ('x', 'x', 'info', now())"))  # fmt: skip
        return []

    for rid, fn in (("probe_whoami", whoami), ("probe_writes", writes)):
        monkeypatch.setitem(REGISTRY, rid, RuleSpec(rid, "minute", lambda data, ctx: [], ("dev",)))
        monkeypatch.setitem(LOADERS, rid, fn)
    async with rw.begin() as conn:
        user, _ = await rs.seed_rule(conn, "refresh_reuse", at=now - H)
    result = await run(mon, now)
    assert seen == ["app_monitor"]
    assert result.failed_rules == ["probe_writes"]
    assert len(mine(result, "refresh_reuse", [user])) == 1


@pytest.mark.asyncio
async def test_one_rule_sql_error_others_still_draft(
    rw: AsyncEngine, mon: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader `refresh_reuse` lỗi SQL thật → chỉ nó vào `failed_rules`; 6 luật kia vẫn ra draft cho đối tượng của test."""
    now = rs.day(17)

    async def broken(conn: AsyncConnection, ctx: RuleContext) -> list[object]:
        await conn.execute(text("SELECT * FROM bang_khong_ton_tai"))
        return []

    monkeypatch.setitem(LOADERS, "refresh_reuse", broken)
    async with rw.begin() as conn:
        seeded = {r: await rs.seed_rule(conn, r, at=now - H) for r in rs.B1_RULES}
    result = await run(mon, now)
    assert result.failed_rules == ["refresh_reuse"]
    for rule_id, (subject, window) in seeded.items():
        expected = [] if rule_id == "refresh_reuse" else [(subject, window)]
        assert [(d.subject, d.window_start) for d in mine(result, rule_id, [subject])] == expected, rule_id


def test_day_windows_do_not_overlap() -> None:
    """Mỗi `day(k)` cách nhau hơn lookback + 5 phút đọc lùi (Q-M9-B1-14 c)."""
    assert rs.day(1) - rs.day(0) > LOOKBACK + 5 * MIN
    assert rs.day(0).tzinfo is UTC
