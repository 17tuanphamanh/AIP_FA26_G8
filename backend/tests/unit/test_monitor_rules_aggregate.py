"""M9-B2 GĐ1 cụm 1: helper cửa sổ ngày (Q-M9-B2-1) + luật tổng hợp chu kỳ ngày 1 `escalation_rate_high`,
12 `b2_degraded`, 13 `b3_degraded`; cụm 2: luật tổng hợp chu kỳ giờ 14 `llm_budget` — hàm thuần, nhận GIÁ TRỊ
(loader + hàm A nối ở GĐ2); cụm 4a: luật 60 s 4 `e9_spike`, 6 `e6_spike`, 5 `breaker_open` — hàm thuần CHƯA đăng ký
`@rule` (đăng ký cùng loader ở GĐ2, Q-M9-B2-10).

Nguồn: kế hoạch chung M9 mục 6 (bảng 16 luật: luật 1, 4, 5, 6, 12, 13, 14; đoạn "Trung vị 7 ngày (luật 4, 6)"), Q-M9-4
(luật 5: hợp đồng span dự kiến, "đợt" = chuỗi cách nhau < 60 s), Q-M9-B2-1 (monitor.md mục Q-M9; chia-việc thẻ B2),
Q-M9-6 (luật 14 nhắc mỗi ngày), Q-M9-B2-2/5/7/12/16/17 (đã chốt ở #14, comment 5959974287).
Mọi mốc kỳ vọng là HẰNG tính tay (giờ VN = UTC+7; Tokyo = UTC+9; Berlin CET = UTC+1, CEST = UTC+2), không tính bằng
chính hàm đang test.
"""

import ast
import inspect
import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.audit.alerts import check_alert
from app.domain.alerts import SUBJECT_MAX, SYSTEM_SUBJECT, AlertDraft
from app.monitor import rules
from app.monitor.queries.business import WeightedRate
from app.monitor.rules import (
    REGISTRY,
    RuleContext,
    TicketExit,
    ToolSpan,
    b2_degraded,
    b3_degraded,
    breaker_open,
    days_before,
    e6_spike,
    e9_spike,
    escalation_rate_high,
    llm_budget,
    prev_day_window,
    rolling_7d_window,
    spike_hours,
    spike_since,
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


# ---- luật 4 e9_spike, 6 e6_spike (chu kỳ 60 s, Q-M9-B2-2; mốc = first_at, Q-M9-B2-5) ---------------------------------

NOW_H = datetime(2026, 10, 3, 12, 30, tzinfo=UTC)
H0 = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)  # giờ hiện tại
H1 = datetime(2026, 10, 3, 11, 0, tzinfo=UTC)
H3 = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
H24 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)  # giờ cũ nhất được đánh giá
H25 = datetime(2026, 10, 2, 11, 0, tzinfo=UTC)
SPIKE_SINCE = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # H24 − 168 giờ (7 ngày)
CTX_H = ctx_at(NOW_H)

SpikeFn = Callable[[Sequence[TicketExit], RuleContext], list[AlertDraft]]
SPIKE: list[tuple[str, SpikeFn]] = [("e9_spike", e9_spike), ("e6_spike", e6_spike)]
SPIKE_IDS = [r for r, _ in SPIKE]


def ex(tid: str, first_at: datetime, last_at: datetime | None = None) -> TicketExit:
    return TicketExit(tid, first_at, first_at if last_at is None else last_at, "B9", None)


def cases(hour: datetime, n: int) -> list[TicketExit]:
    """`n` lá ở giờ `hour`, phút 10, 11, … (giữa giờ)."""
    return [ex(f"t-{hour:%m%d%H}-{i}", hour + timedelta(minutes=10 + i)) for i in range(n)]


def one_per_hour(ks: range) -> list[TicketExit]:
    """Một lá ở phút 30 của mỗi giờ `H0 − k giờ`, k ∈ `ks` — dựng lịch sử cho trung vị."""
    return [ex(f"h-{k}", H0 - timedelta(hours=k, minutes=-30)) for k in ks]


def _starts(drafts: list[AlertDraft]) -> list[datetime]:
    return [d.window_start for d in drafts]


def test_spike_hours_and_since() -> None:
    """Q-M9-B2-2: giờ hiện tại + 24 giờ trước (25 giờ, cũ → mới); loader GĐ2 đọc từ 168 giờ trước giờ cũ nhất."""
    hours = spike_hours(CTX_H)
    assert len(hours) == 25
    assert (hours[0], hours[1], hours[-1]) == (H24, datetime(2026, 10, 2, 13, 0, tzinfo=UTC), H0)
    assert spike_since(CTX_H) == SPIKE_SINCE
    at_mark = spike_hours(ctx_at(datetime(2026, 10, 3, 12, 0, tzinfo=UTC)))  # đúng mốc giờ → giờ đó là giờ hiện tại
    assert (at_mark[0], at_mark[-1]) == (H24, H0)


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
@pytest.mark.parametrize(("n", "expected"), [(2, []), (3, [H0])], ids=["2-ca", "3-ca"])
def test_spike_median0_threshold(rule_id: str, fn: SpikeFn, n: int, expected: list[datetime]) -> None:
    """Trung vị 0: 2 ca → không báo (thẻ B2: "trung vị 0 và 2 ca → không báo"); đúng tối thiểu 3 → báo."""
    drafts = fn(cases(H0, n), CTX_H)
    assert _starts(drafts) == expected
    _ok(rule_id, drafts)


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
@pytest.mark.parametrize(("n", "expected"), [(2, []), (3, []), (4, [H0])], ids=["duoi", "bang-3x1", "vuot"])
def test_spike_median1_threshold(rule_id: str, fn: SpikeFn, n: int, expected: list[datetime]) -> None:
    """85 giờ có 1 ca ở `H0 − k giờ`, k = 84…168 (gồm giờ cũ nhất `h − 168`) + 83 giờ trống → trung vị 1,0 (phần tử
    84 và 85 đều là 1). Đúng bằng 3 × 1 → không báo; hơn 1 → báo."""
    drafts = fn(one_per_hour(range(84, 169)) + cases(H0, n), CTX_H)
    assert _starts(drafts) == expected
    _ok(rule_id, drafts)
    if drafts:
        assert drafts[0].value == 4
        assert dict(drafts[0].detail) == {"count": 4, "median": 1.0, "factor": 3, "minimum": 3}


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_median_excludes_current_hour(rule_id: str, fn: SpikeFn) -> None:
    """84 giờ 1 ca ở k = 84…167 (k = 168 trống) → trung vị của `[H0 − 168 giờ, H0)` = 0,5; 3 ca ở H0 > 1,5 → báo.
    Gộp cả H0 vào cửa sổ (85 giờ khác 0) thì trung vị 1,0 → 3 không vượt → mất cảnh báo."""
    drafts = fn(one_per_hour(range(84, 168)) + cases(H0, 3), CTX_H)
    assert _starts(drafts) == [H0]
    assert drafts[0].detail["median"] == 0.5


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_window_is_hour_start_not_now(rule_id: str, fn: SpikeFn) -> None:
    """`window_start` = đầu giờ (12:00), không phải `ctx.now` (12:30). Mốc có micro giây vẫn về đúng giờ."""
    data = [
        ex("a", datetime(2026, 10, 3, 12, 5, 0, 250000, tzinfo=UTC)),
        ex("b", datetime(2026, 10, 3, 12, 10, 0, 500000, tzinfo=UTC)),
        ex("c", datetime(2026, 10, 3, 12, 20, 0, 750000, tzinfo=UTC)),
    ]
    drafts = fn(data, CTX_H)
    assert _starts(drafts) == [H0]
    _ok(rule_id, drafts)


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
@pytest.mark.parametrize(
    ("third", "expected"),
    [
        (datetime(2026, 10, 3, 12, 0, tzinfo=UTC), [H0]),  # đúng mốc 12:00:00 → thuộc giờ 12
        (datetime(2026, 10, 3, 11, 59, 59, 999999, tzinfo=UTC), []),  # trước mốc 1 µs → thuộc giờ 11
    ],
    ids=["dung-moc", "truoc-moc-1us"],
)
def test_spike_hour_boundary(rule_id: str, fn: SpikeFn, third: datetime, expected: list[datetime]) -> None:
    drafts = fn([*cases(H0, 2), ex("bien", third)], CTX_H)
    assert _starts(drafts) == expected


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_previous_hour_caught(rule_id: str, fn: SpikeFn) -> None:
    """Worker chết qua mốc giờ: đợt tăng ở 09:xx, lượt chạy lúc 12:30 vẫn báo, khoá = 09:00."""
    assert _starts(fn(cases(H3, 3), CTX_H)) == [H3]


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
@pytest.mark.parametrize(("hour", "expected"), [(H24, [H24]), (H25, [])], ids=["H24", "H25"])
def test_spike_24h_plus_current_edge(rule_id: str, fn: SpikeFn, hour: datetime, expected: list[datetime]) -> None:
    """Giờ cũ nhất được đánh giá là 2026-10-02T12:00Z (24 giờ trước giờ hiện tại); 11:00Z đã ra ngoài."""
    assert _starts(fn(cases(hour, 3), CTX_H)) == expected


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_two_hours_two_drafts(rule_id: str, fn: SpikeFn) -> None:
    """Luật tổng hợp: các giờ phân biệt bằng `window_start` → 2 giờ vượt ngưỡng = 2 draft (theo thứ tự thời gian)."""
    drafts = fn(cases(H1, 3) + cases(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), 3), CTX_H)
    assert _starts(drafts) == [datetime(2026, 10, 3, 7, 0, tzinfo=UTC), H1]
    _ok(rule_id, drafts)


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_uses_first_at(rule_id: str, fn: SpikeFn) -> None:
    """Q-M9-B2-5: mốc = dòng mang mã ĐẦU TIÊN của lá (`first_at`), không phải `last_at`."""
    data = [
        ex(f"t-{i}", datetime(2026, 10, 3, 10, 10 + i, tzinfo=UTC), datetime(2026, 10, 3, 12, 10 + i, tzinfo=UTC))
        for i in range(3)
    ]
    assert _starts(fn(data, CTX_H)) == [datetime(2026, 10, 3, 10, 0, tzinfo=UTC)]


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_future_hour_later_caught(rule_id: str, fn: SpikeFn) -> None:
    """Ca ở 13:xx (lệch đồng hồ) khi now = 12:30 → chưa đánh giá; tới 13:30 thì báo, khoá 13:00 — không mất."""
    data = cases(datetime(2026, 10, 3, 13, 0, tzinfo=UTC), 3)
    assert fn(data, CTX_H) == []
    assert _starts(fn(data, ctx_at(datetime(2026, 10, 3, 13, 30, tzinfo=UTC)))) == [
        datetime(2026, 10, 3, 13, 0, tzinfo=UTC)
    ]


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
@pytest.mark.parametrize(
    "now",
    [
        NOW_H,
        datetime(2026, 10, 3, 12, 59, 59, 999999, tzinfo=UTC),
        datetime(2026, 10, 3, 13, 10, tzinfo=UTC),  # đã qua giờ mới — 11:00 vẫn trong 24 giờ
    ],
)
def test_spike_rerun_same_key(rule_id: str, fn: SpikeFn, now: datetime) -> None:
    assert _starts(fn(cases(H1, 3), ctx_at(now))) == [H1]


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_empty(rule_id: str, fn: SpikeFn) -> None:
    assert fn([], CTX_H) == []


@pytest.mark.parametrize(("rule_id", "fn"), SPIKE, ids=SPIKE_IDS)
def test_spike_shuffled_same_result(rule_id: str, fn: SpikeFn) -> None:
    data = cases(H1, 3) + cases(datetime(2026, 10, 3, 7, 0, tzinfo=UTC), 3)
    assert fn(list(reversed(data)), CTX_H) == fn(data, CTX_H)


# ---- luật 5 breaker_open (Q-M9-4: hợp đồng span dự kiến; Q-M9-B2-12: subject = spans.name) ---------------------------

T = datetime(2026, 10, 3, 12, 20, tzinfo=UTC)
AD = "tool:ad.reset_password"
MAIL = "tool:mail.send"


def sp(name: str, at: datetime) -> ToolSpan:
    return ToolSpan(name=name, started_at=at)


def _ok_tool(drafts: list[AlertDraft]) -> None:
    for d in drafts:
        assert d.rule_id == "breaker_open"
        assert d.severity == "warning"
        assert d.subject != SYSTEM_SUBJECT  # luật theo đối tượng: subject tường minh
        check_alert(d)
        assert "audience" not in d.detail


def test_breaker_one_span_one_draft() -> None:
    """Một span `circuit_open` là đủ: breaker đã mở."""
    [draft] = breaker_open([sp(AD, T)], CTX_H)
    assert (draft.subject, draft.window_start, draft.value) == (AD, T, 1)
    assert dict(draft.detail) == {"count": 1}
    _ok_tool([draft])


def test_breaker_no_span() -> None:
    assert breaker_open([], CTX_H) == []


@pytest.mark.parametrize(
    ("second", "expected"),
    [
        (datetime(2026, 10, 3, 12, 20, 59, 999999, tzinfo=UTC), [T]),  # khe < 60 s → cùng đợt
        (datetime(2026, 10, 3, 12, 21, 0, tzinfo=UTC), [T, datetime(2026, 10, 3, 12, 21, 0, tzinfo=UTC)]),  # = 60 s
    ],
    ids=["59.999999s", "60s"],
)
def test_breaker_gap_boundary(second: datetime, expected: list[datetime]) -> None:
    """Q-M9-4: "đợt" = chuỗi cách nhau < 60 s — đúng 60 s là đợt mới."""
    drafts = breaker_open([sp(AD, T), sp(AD, second)], CTX_H)
    assert _starts(drafts) == expected
    _ok_tool(drafts)


def test_breaker_gap_from_previous_span() -> None:
    """Khe đo giữa hai span LIỀN NHAU (50 s, 50 s), không đo từ span đầu đợt (100 s)."""
    data = [
        sp(AD, T),
        sp(AD, datetime(2026, 10, 3, 12, 20, 50, tzinfo=UTC)),
        sp(AD, datetime(2026, 10, 3, 12, 21, 40, tzinfo=UTC)),
    ]
    [draft] = breaker_open(data, CTX_H)
    assert (draft.window_start, draft.value) == (T, 3)


def test_breaker_two_tools_same_window() -> None:
    """Luật theo đối tượng: 2 tool cùng thời điểm → 2 draft (gộp = bỏ sót tool thứ hai)."""
    drafts = breaker_open([sp(AD, T), sp(MAIL, T)], CTX_H)
    assert sorted(d.subject for d in drafts) == [AD, MAIL]
    assert _starts(drafts) == [T, T]


def test_breaker_same_tool_two_bursts() -> None:
    drafts = breaker_open([sp(AD, T), sp(AD, datetime(2026, 10, 3, 12, 10, tzinfo=UTC))], CTX_H)
    assert _starts(drafts) == [datetime(2026, 10, 3, 12, 10, tzinfo=UTC), T]


def test_breaker_subject_length() -> None:
    """subject = tên khi 1…64 ký tự; dài hơn → `_bounded("tool", …)` (sha256 hex, 40 ký tự đầu — tính sẵn ngoài code
    bằng `sha256sum` của chuỗi 65 chữ `a`); rỗng → `tool:` (không trùng SYSTEM_SUBJECT)."""
    n64, n65, n128 = "a" * 64, "a" * 65, "b" * 128
    drafts = breaker_open([sp(n64, T), sp(n65, T), sp(n128, T), sp("", T)], CTX_H)
    subjects = [d.subject for d in drafts]
    assert subjects[0] == n64
    assert subjects[1] == "tool#635361c48bb9eab14198e76ea8ab7f1a41685d6a"
    assert subjects[2].startswith("tool#") and len(subjects[2]) <= SUBJECT_MAX
    assert subjects[2] != subjects[1]
    assert subjects[3] == "tool:"
    _ok_tool(drafts)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        # span cuối đúng now − 24 giờ → còn trong lookback (tính cả mốc biên)
        ([datetime(2026, 10, 2, 12, 30, tzinfo=UTC)], [datetime(2026, 10, 2, 12, 30, tzinfo=UTC)]),
        # sớm hơn 1 µs → ra ngoài
        ([datetime(2026, 10, 2, 12, 29, 59, 999999, tzinfo=UTC)], []),
        # đợt bắt đầu trước mốc, span cuối trong mốc → báo, khoá = span đầu đợt (ổn định giữa các lượt)
        (
            [datetime(2026, 10, 2, 12, 29, 30, tzinfo=UTC), datetime(2026, 10, 2, 12, 30, 20, tzinfo=UTC)],
            [datetime(2026, 10, 2, 12, 29, 30, tzinfo=UTC)],
        ),
    ],
    ids=["cuoi-dung-moc", "truoc-moc-1us", "vat-qua-moc"],
)
def test_breaker_lookback(data: list[datetime], expected: list[datetime]) -> None:
    assert _starts(breaker_open([sp(AD, t) for t in data], CTX_H)) == expected


def test_breaker_shuffled_and_duplicate_times() -> None:
    data = [
        sp(AD, datetime(2026, 10, 3, 12, 21, 40, tzinfo=UTC)),
        sp(AD, T),
        sp(AD, datetime(2026, 10, 3, 12, 20, 50, tzinfo=UTC)),
        sp(AD, T),  # trùng thời điểm → cùng đợt
    ]
    [draft] = breaker_open(data, CTX_H)
    assert (draft.window_start, draft.value) == (T, 4)


def test_breaker_future_span_kept() -> None:
    """Không chặn trên theo `now` (Q-M9-B1-12): span sau `now` (lệch đồng hồ) vẫn báo."""
    future = datetime(2026, 10, 3, 12, 35, tzinfo=UTC)
    assert _starts(breaker_open([sp(AD, future)], CTX_H)) == [future]


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
    assert len(named) >= 4  # luật 1 + helper luật 12/13 + luật 14 + helper luật 4/6 — quét không rỗng


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
