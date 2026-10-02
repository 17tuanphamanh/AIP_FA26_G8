"""M9-B2 GĐ1 cụm 1: helper cửa sổ ngày (Q-M9-B2-1) + luật tổng hợp chu kỳ ngày 1 `escalation_rate_high`,
12 `b2_degraded`, 13 `b3_degraded`; cụm 2: luật tổng hợp chu kỳ giờ 14 `llm_budget` — hàm thuần, nhận GIÁ TRỊ
(loader + hàm A nối ở GĐ2).

Nguồn: kế hoạch chung M9 mục 6 (bảng 16 luật: luật 1, 12, 13, 14), Q-M9-B2-1 (monitor.md mục Q-M9; chia-việc thẻ B2),
Q-M9-6 (luật 14 nhắc mỗi ngày), Q-M9-B2-7/16/17 (luật 14, chờ chốt ở #14).
Mọi mốc kỳ vọng là HẰNG tính tay (giờ VN = UTC+7; Tokyo = UTC+9; Berlin CET = UTC+1, CEST = UTC+2), không tính bằng
chính hàm đang test.
"""

import ast
import inspect
import math
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from app.audit.alerts import check_alert
from app.domain.alerts import SYSTEM_SUBJECT, AlertDraft
from app.monitor import rules
from app.monitor.queries.business import WeightedRate
from app.monitor.rules import (
    REGISTRY,
    RuleContext,
    b2_degraded,
    b3_degraded,
    days_before,
    escalation_rate_high,
    llm_budget,
    prev_day_window,
    rolling_7d_window,
)
from app.monitor.window import VN_TZ, day_start

TOKYO = ZoneInfo("Asia/Tokyo")
BERLIN = ZoneInfo("Europe/Berlin")

NOW = datetime(2026, 10, 2, 19, 0, tzinfo=UTC)  # job ngày: 02:00 ngày 03/10 giờ VN
D0 = datetime(2026, 10, 2, 17, 0, tzinfo=UTC)  # 00:00 ngày 03/10 giờ VN
D0_MINUS_1 = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)  # 00:00 ngày 02/10 giờ VN
D0_MINUS_7 = datetime(2026, 9, 25, 17, 0, tzinfo=UTC)  # 00:00 ngày 26/09 giờ VN


def ctx_at(now: datetime, tz: ZoneInfo = VN_TZ) -> RuleContext:
    return RuleContext(now=now, tz=tz, cap_usd=38.0, warn_ratio=0.8)


CTX = ctx_at(NOW)


def wr(weighted: float | None, raw: float | None = None) -> WeightedRate:
    return WeightedRate(raw=weighted if raw is None else raw, weighted=weighted, by_group={}, sensitivity={})


def _ok(rule_id: str, drafts: list[AlertDraft], severity: str = "warning") -> None:
    for d in drafts:
        assert d.rule_id == rule_id
        assert d.subject == SYSTEM_SUBJECT
        assert d.severity == severity
        check_alert(d)  # bộ kiểm writer thật dùng (check_detail: không khoá nhạy cảm, không giá trị kiểu JWT)
        assert "audience" not in d.detail  # Q-M9-B1-9: người nhận chỉ nằm trong RuleSpec


# ---- helper cửa sổ ngày (Q-M9-B2-1) ------------------------------------------------------------------------------


def test_d0_and_days_before_vn() -> None:
    d0 = day_start(NOW, VN_TZ)
    assert d0 == D0
    assert days_before(d0, 1, VN_TZ) == D0_MINUS_1
    assert days_before(d0, 7, VN_TZ) == D0_MINUS_7
    assert days_before(d0, 0, VN_TZ) == D0


def test_windows_end_at_d0() -> None:
    """Cửa sổ KẾT THÚC ở d0 (ngày VN trọn), không phải `[d0, now)` — chạy 02:00 VN thì `[d0, now)` chỉ có 2 giờ đêm."""
    assert prev_day_window(CTX) == (D0_MINUS_1, D0)
    assert rolling_7d_window(CTX) == (D0_MINUS_7, D0)


def test_d0_flips_at_vn_midnight() -> None:
    before = ctx_at(datetime(2026, 10, 2, 16, 59, 59, 999999, tzinfo=UTC))  # 23:59:59,999999 ngày 02/10 giờ VN
    at = ctx_at(datetime(2026, 10, 2, 17, 0, tzinfo=UTC))  # 00:00 ngày 03/10 giờ VN
    assert prev_day_window(before) == (datetime(2026, 9, 30, 17, 0, tzinfo=UTC), D0_MINUS_1)
    assert prev_day_window(at) == (D0_MINUS_1, D0)


@pytest.mark.parametrize(
    ("d0", "k", "tz", "expected"),
    [
        # Tokyo (UTC+9, không đổi giờ): d0 = 00:00 ngày 03/10 JST. Ghim việc dùng ĐÚNG `tz` được truyền vào — bản dùng
        # VN_TZ cứng ra 2026-09-30T17:00Z. KHÔNG bắt được bản trừ 24 h trên UTC (lệch cố định → cùng kết quả).
        pytest.param(
            datetime(2026, 10, 2, 15, 0, tzinfo=UTC), 1, TOKYO, datetime(2026, 10, 1, 15, 0, tzinfo=UTC), id="tokyo"
        ),
        # Berlin, đổi giờ mùa xuân (CN 29/03/2026, ngày dài 23 giờ): d0 = 00:00 ngày 30/03 CEST = 2026-03-29T22:00Z;
        # 00:00 ngày 29/03 còn CET = 2026-03-28T23:00Z. Bản trừ 24 h trên UTC ra 2026-03-28T22:00Z = 23:00 ngày 28/03
        # CET → day_start = 2026-03-27T23:00Z (lùi 2 ngày) → ca này BẮT đột biến W-utc.
        pytest.param(
            datetime(2026, 3, 29, 22, 0, tzinfo=UTC), 1, BERLIN, datetime(2026, 3, 28, 23, 0, tzinfo=UTC),
            id="berlin-spring",
        ),
        # Berlin, đổi giờ mùa thu (CN 25/10/2026, ngày dài 25 giờ): d0 = 00:00 ngày 26/10 CET = 2026-10-25T23:00Z;
        # 00:00 ngày 25/10 còn CEST = 2026-10-24T22:00Z. Ca này KHÔNG bắt W-utc: trừ 24 h ra 2026-10-24T23:00Z = 01:00
        # ngày 25/10 CEST, vẫn trong ngày 25/10 → day_start ra cùng kết quả. Chỉ ca mùa xuân bắt; ca này ghim biên
        # còn lại.
        pytest.param(
            datetime(2026, 10, 25, 23, 0, tzinfo=UTC), 1, BERLIN, datetime(2026, 10, 24, 22, 0, tzinfo=UTC),
            id="berlin-autumn",
        ),
        # Berlin, 7 ngày vắt qua đổi giờ mùa xuân (luật 1): d0 = 00:00 ngày 01/04 CEST = 2026-03-31T22:00Z; 00:00 ngày
        # 25/03 CET = 2026-03-24T23:00Z. Bản trừ 168 h ra 23:00 ngày 24/03 CET → 2026-03-23T23:00Z (bắt W-utc).
        pytest.param(
            datetime(2026, 3, 31, 22, 0, tzinfo=UTC), 7, BERLIN, datetime(2026, 3, 24, 23, 0, tzinfo=UTC),
            id="berlin-7d-spring",
        ),
    ],
)  # fmt: skip
def test_days_before_uses_calendar_tz(d0: datetime, k: int, tz: ZoneInfo, expected: datetime) -> None:
    """Trừ `k` ngày LỊCH theo `tz` (Q-M9-B2-1: "không tự trừ 24 giờ trên UTC")."""
    assert days_before(d0, k, tz) == expected


def test_windows_follow_ctx_tz() -> None:
    """Helper lấy `tz` từ `ctx`: 19:00Z = 04:00 ngày 03/10 JST → d0 = 00:00 ngày 03/10 JST = 2026-10-02T15:00Z."""
    ctx = ctx_at(NOW, TOKYO)
    assert prev_day_window(ctx) == (datetime(2026, 10, 1, 15, 0, tzinfo=UTC), datetime(2026, 10, 2, 15, 0, tzinfo=UTC))
    # 00:00 ngày 26/09 JST = 2026-09-25T15:00Z
    assert rolling_7d_window(ctx) == (
        datetime(2026, 9, 25, 15, 0, tzinfo=UTC), datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
    )


# ---- luật 1 escalation_rate_high ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("weighted", "n"), [(0.41, 1), (0.39, 0), (0.40, 0)])
def test_escalation_threshold(weighted: float, n: int) -> None:
    """`weighted > 0,40`; đúng bằng ngưỡng → không báo."""
    drafts = escalation_rate_high(wr(weighted), CTX)
    assert len(drafts) == n
    _ok("escalation_rate_high", drafts)


def test_escalation_uses_weighted_not_raw() -> None:
    """Kế hoạch chung mục 6 (mutation "luật 1 dùng raw"): chỉ `weighted` quyết định."""
    assert escalation_rate_high(wr(0.3, raw=0.9), CTX) == []
    assert len(escalation_rate_high(wr(0.5, raw=0.1), CTX)) == 1


def test_escalation_none_no_alert() -> None:
    """0 lá trong cửa sổ → `weighted` None → không nổ, không lỗi (Q-M9-B2-1)."""
    assert escalation_rate_high(None, CTX) == []
    assert escalation_rate_high(WeightedRate(raw=None, weighted=None, by_group={}, sensitivity={}), CTX) == []


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 10, 2, 17, 0, tzinfo=UTC),  # 00:00 ngày 03/10 giờ VN
        NOW,  # 02:00 — giờ job
        datetime(2026, 10, 3, 16, 59, 59, tzinfo=UTC),  # 23:59:59 ngày 03/10 giờ VN
    ],
)
def test_escalation_window_is_d0(now: datetime) -> None:
    """`window_start` = d0 (khoá chống trùng): mọi lần chạy trong cùng ngày VN ra đúng một khoá, không phải
    `ctx.now`."""
    [draft] = escalation_rate_high(wr(0.5), ctx_at(now))
    assert draft.window_start == D0


def test_escalation_detail_and_value() -> None:
    [draft] = escalation_rate_high(wr(0.5, raw=0.2), CTX)
    assert draft.value == 0.5
    assert dict(draft.detail) == {"weighted": 0.5, "raw": 0.2, "threshold": 0.40, "days": 7}


# ---- luật 12 b2_degraded, 13 b3_degraded -------------------------------------------------------------------------

DEGRADED: list[tuple[str, Callable[[float | None, RuleContext], list[AlertDraft]]]] = [
    ("b2_degraded", b2_degraded),
    ("b3_degraded", b3_degraded),
]
DEGRADED_IDS = [r for r, _ in DEGRADED]


@pytest.mark.parametrize(("rule_id", "fn"), DEGRADED, ids=DEGRADED_IDS)
@pytest.mark.parametrize(("rate", "n"), [(0.31, 1), (0.29, 0), (0.30, 0)])
def test_degraded_threshold(
    rule_id: str, fn: Callable[[float | None, RuleContext], list[AlertDraft]], rate: float, n: int
) -> None:
    """`> 0,30`; đúng bằng ngưỡng → không báo."""
    drafts = fn(rate, CTX)
    assert len(drafts) == n
    _ok(rule_id, drafts)
    if drafts:
        assert drafts[0].value == rate
        assert dict(drafts[0].detail) == {"rate": rate, "threshold": 0.30}


@pytest.mark.parametrize(("rule_id", "fn"), DEGRADED, ids=DEGRADED_IDS)
def test_degraded_none_no_alert_no_failure(
    rule_id: str, fn: Callable[[float | None, RuleContext], list[AlertDraft]]
) -> None:
    """Không có lá trong ngày → chỉ số None → 0 draft, KHÔNG ném lỗi (lỗi = luật vào failed_rules mỗi ngày)."""
    assert fn(None, CTX) == []


@pytest.mark.parametrize(("rule_id", "fn"), DEGRADED, ids=DEGRADED_IDS)
@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 10, 2, 17, 0, tzinfo=UTC),  # 00:00 ngày 03/10 giờ VN
        NOW,  # 02:00 — giờ job
        datetime(2026, 10, 3, 16, 59, 59, tzinfo=UTC),  # 23:59:59 ngày 03/10 giờ VN
    ],
)
def test_degraded_window_is_d0(
    rule_id: str, fn: Callable[[float | None, RuleContext], list[AlertDraft]], now: datetime
) -> None:
    """`window_start` = d0 (đầu ngày đánh giá), không phải đầu ngày dữ liệu `d0 − 1 ngày`, không phải `ctx.now`."""
    [draft] = fn(0.5, ctx_at(now))
    assert draft.window_start == D0


# ---- luật 14 llm_budget (ctx mặc định: cap 38, warn 0,8 → ngưỡng 30,4) ---------------------------------------------


@pytest.mark.parametrize(
    ("spent", "n"),
    [
        pytest.param(30.41, 1, id="over"),
        pytest.param(30.39, 0, id="under"),
        pytest.param(30.4, 1, id="equal-80pct"),  # `30.4 >= 38*0.8` là False → cần BUDGET_EPS (Q-M9-B2-7)
        pytest.param(30.02, 0, id="79pct"),  # thẻ B2: 79% không báo
        pytest.param(30.399999, 0, id="just-under"),  # epsilon không được rộng tới 1e-6
    ],
)
def test_budget_threshold(spent: float, n: int) -> None:
    """`tổng ≥ warn_ratio × cap_usd`; đúng bằng ngưỡng (80%) → báo."""
    drafts = llm_budget(spent, CTX)
    assert len(drafts) == n
    _ok("llm_budget", drafts, severity="critical")


@pytest.mark.parametrize(("spent", "n"), [(5.01, 1), (4.99, 0), (5.0, 1)])
def test_budget_threshold_from_ctx(spent: float, n: int) -> None:
    """Ngưỡng đọc từ `ctx` (cap 10, warn 0,5 → 5,0), không phải số viết cứng 38 × 0,8."""
    ctx = RuleContext(now=NOW, tz=VN_TZ, cap_usd=10.0, warn_ratio=0.5)
    assert len(llm_budget(spent, ctx)) == n


@pytest.mark.parametrize("spent", [38.0, 1000.0])
def test_budget_over_cap_single_draft(spent: float) -> None:
    """Một mức (Q-M9-B2-17): vượt trần vẫn đúng 1 draft, không thêm draft "vượt cap"."""
    drafts = llm_budget(spent, CTX)
    assert len(drafts) == 1
    _ok("llm_budget", drafts, severity="critical")


def test_budget_zero_no_alert() -> None:
    """0 = đã đo, chưa chi (loader `COALESCE`) → không báo, không lỗi."""
    assert llm_budget(0.0, CTX) == []


@pytest.mark.parametrize(
    ("spent", "shown"),
    [(None, "None"), (math.nan, "nan"), (math.inf, "inf"), (-0.01, "-0.01")],
    ids=["none", "nan", "inf", "negative"],
)
def test_budget_invalid_raises(spent: float | None, shown: str) -> None:
    """Q-M9-B2-16: tổng không hợp lệ → `ValueError` (luật vào `failed_rules`), không trả `[]` (tắt im lặng = FN).
    Thông điệp không in giá trị: evaluator ghi nó vào log."""
    with pytest.raises(ValueError) as exc:
        llm_budget(spent, CTX)
    assert shown not in str(exc.value)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 10, 2, 17, 0, tzinfo=UTC),  # 00:00 ngày 03/10 giờ VN
        datetime(2026, 10, 3, 3, 30, tzinfo=UTC),  # 10:30 ngày 03/10 giờ VN
        datetime(2026, 10, 3, 16, 59, 59, 999999, tzinfo=UTC),  # 23:59:59,999999 ngày 03/10 giờ VN
    ],
)
def test_budget_window_is_d0(now: datetime) -> None:
    """Q-M9-6: chạy mỗi giờ, `window_start` = đầu ngày VN → mọi lượt trong ngày ra đúng một khoá (không phải
    `hour_start`, không phải `ctx.now`)."""
    [draft] = llm_budget(30.4, ctx_at(now))
    assert draft.window_start == D0


def test_budget_window_flips_at_vn_midnight() -> None:
    [before] = llm_budget(30.4, ctx_at(datetime(2026, 10, 2, 16, 59, 59, 999999, tzinfo=UTC)))  # 23:59:59 02/10 VN
    [at] = llm_budget(30.4, ctx_at(datetime(2026, 10, 2, 17, 0, tzinfo=UTC)))  # 00:00 03/10 VN
    assert before.window_start == D0_MINUS_1
    assert at.window_start == D0


def test_budget_window_follows_ctx_tz() -> None:
    """19:00Z = 04:00 ngày 03/10 JST → đầu ngày 03/10 JST = 2026-10-02T15:00Z."""
    [draft] = llm_budget(30.4, ctx_at(NOW, TOKYO))
    assert draft.window_start == datetime(2026, 10, 2, 15, 0, tzinfo=UTC)


def test_budget_detail_and_value() -> None:
    [draft] = llm_budget(30.4, CTX)
    assert draft.value == 30.4
    assert dict(draft.detail) == {"spent_usd": 30.4, "cap_usd": 38.0, "warn_ratio": 0.8}
    _ok("llm_budget", [draft], severity="critical")


def test_registry_llm_budget() -> None:
    """Bảng 16 luật (monitor.md mục 6): chu kỳ giờ; "cả nhóm" = cả 3 giá trị `Audience`."""
    spec = REGISTRY["llm_budget"]
    assert (spec.every, spec.audience) == ("hourly", ("dev", "manager", "ops"))
    assert spec.fn is llm_budget


# ---- chung -------------------------------------------------------------------------------------------------------


def test_registry_every_audience_cluster1() -> None:
    """Bảng 16 luật (kế hoạch chung M9 mục 6): chu kỳ ngày; luật 1 → Trưởng BP, luật 12/13 → dev."""
    expected = {
        "escalation_rate_high": (escalation_rate_high, ("manager",)),
        "b2_degraded": (b2_degraded, ("dev",)),
        "b3_degraded": (b3_degraded, ("dev",)),
    }
    for rule_id, (fn, audience) in expected.items():
        spec = REGISTRY[rule_id]
        assert (spec.every, spec.audience) == ("daily", audience), rule_id
        assert spec.fn is fn


def _keywords(tree: ast.AST, name: str) -> list[ast.keyword]:
    return [k for k in ast.walk(tree) if isinstance(k, ast.keyword) and k.arg == name]


def test_aggregate_rules_use_system_subject() -> None:
    """Luật tổng hợp truyền HẰNG `SYSTEM_SUBJECT`, không viết chuỗi rỗng trần (luật cứng 6, kế hoạch chung 4.4.2): cùng
    giá trị nên test theo giá trị không phân biệt được → quét AST của `rules.py`."""
    subjects = _keywords(ast.parse(inspect.getsource(rules)), "subject")
    bare = [k.value.lineno for k in subjects if isinstance(k.value, ast.Constant) and k.value.value == ""]
    assert bare == []
    named = [k for k in subjects if isinstance(k.value, ast.Name) and k.value.id == "SYSTEM_SUBJECT"]
    assert len(named) >= 3  # luật 1 + helper luật 12/13 + luật 14 — quét không rỗng


def _is_type_checking(node: ast.If) -> bool:
    return isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"


def test_rules_imports_queries_only_for_typing() -> None:
    """`rules.py` là hàm thuần, KHÔNG I/O: kiểu `WeightedRate` của luồng A chỉ import trong `if TYPE_CHECKING` — lúc
    chạy không nạp `queries/*` (sqlalchemy, hàm truy vấn) vào luật."""
    tree = ast.parse(inspect.getsource(rules))
    typing_only = {
        id(n) for block in ast.walk(tree) if isinstance(block, ast.If) and _is_type_checking(block)
        for n in ast.walk(block)
    }  # fmt: skip
    queries = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom | ast.Import)
        and any(m.startswith("app.monitor.queries") for m in ([n.module or ""] if isinstance(n, ast.ImportFrom)
                                                               else [a.name for a in n.names]))
    ]  # fmt: skip
    assert queries  # quét không rỗng: WeightedRate được import (cho kiểu)
    assert [n.lineno for n in queries if id(n) not in typing_only] == []
