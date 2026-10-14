"""M9-B3 cụm 3 — luật tuần 8 `drift` (`rules.py`), helper tuần, loader `load_drift` + `drift_counts` + `drift_scores`
(`queries/rules_data.py`). Không DB: SQL ghi lại bằng conn giả trả số đếm theo cửa sổ, `escalation_rate_weighted` của A1
thay bằng bản giả ghi `(conn, frm, to)`.

Nguồn: kế hoạch chung M9 mục 6 (luật 8: PSI > 0,2 → Trưởng BP); thẻ B3; chốt #15 comment 12/10: Q-M9-B3-1 (a) tuần đo
`[W − 7 ngày, W)`, tuần mốc `[W − 14 ngày, W − 7 ngày)`; Q-M9-B3-2 (6 phân bố, escalation = `.raw`, số mẫu = số lá đã kết
thúc); Q-M9-B3-3 (override pending → chỉ bỏ phân bố đó); Q-M9-B3-7 (2 mốc); Q-M9-B3-8 (luật chỉ so ngưỡng).
Bản Postgres: `tests/integration/test_monitor_rules_weekly_pg.py`.

Mốc tính tay, `NOW = 2026-10-11T19:00Z` = 02:00 thứ Hai 12/10/2026 giờ VN (VN không đổi giờ; 12/10/2026 là thứ Hai — lịch):
`W` = 00:00 VN 12/10 = `2026-10-11T17:00Z`; `M1 = W − 7 ngày = 2026-10-04T17:00Z`. Ba cửa sổ (cũ → mới):
A = `[09-20T17, 09-27T17)`, B = `[09-27T17, 10-04T17)`, C = `[10-04T17, 10-11T17)` — mốc M1: B so với A; mốc W: C so với B.
Số PSI tay: e = [0,1; 0,9], a = [0,5; 0,5]: 0,4·ln 5 + (−0,4)·ln(5/9) = 0,6437751650 + 0,2351146660 = 0,8788898309.
e = [0,5; 0,5], a = [0,6; 0,4]: 0,1·ln 1,2 + 0,1·(−ln 0,8)… = 0,0405465108 (như `test_monitor_drift_psi.py`).
"""

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from zoneinfo import ZoneInfo

import pytest
from app.domain.alerts import SYSTEM_SUBJECT, AlertDraft
from app.monitor.drift import DriftScore
from app.monitor.evaluator import LOADERS
from app.monitor.queries import common, rules_data
from app.monitor.queries.business import WeightedRate
from app.monitor.queries.rules_data import DriftCounts, drift_counts, drift_scores
from app.monitor.rules import (
    DRIFT_DISTRIBUTIONS,
    DRIFT_THRESHOLD,
    REGISTRY,
    WEEKLY_MARKS,
    DriftWeek,
    RuleContext,
    baseline_window,
    week_window,
    weekly_marks,
)
from app.monitor.rules import drift as drift_rule
from app.monitor.window import VN_TZ
from sqlalchemy.sql.elements import TextClause

TOL = 1e-6
NOW = datetime(2026, 10, 11, 19, 0, tzinfo=UTC)
CTX = RuleContext(now=NOW, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)
W = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
M1 = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
A = (datetime(2026, 9, 20, 17, 0, tzinfo=UTC), datetime(2026, 9, 27, 17, 0, tzinfo=UTC))
B = (datetime(2026, 9, 27, 17, 0, tzinfo=UTC), M1)
C = (M1, W)
PSI_E3 = 0.8788898309
PSI_TWO_BINS = 0.0405465108
NAMES = ("intent", "confidence", "top_score", "e3_rate", "escalation", "override")


def week(**scores: DriftScore | None) -> DriftWeek:
    """DriftWeek đủ 6 phân bố (mặc định None = không đo được), không phân bố nào pending."""
    full: dict[str, DriftScore | None] = dict.fromkeys(NAMES)
    full.update(scores)
    return DriftWeek(scores=full, skipped=())


def draft(name: str, mark: datetime, s: DriftScore) -> AlertDraft:
    return AlertDraft(
        rule_id="drift", subject=name, window_start=mark, severity="warning", value=s.psi,
        detail={"psi": s.psi, "threshold": 0.2, "n_expected": s.n_expected, "n_actual": s.n_actual},
    )  # fmt: skip


# ---- helper tuần ----------------------------------------------------------------------------------------------------


def test_hand_computed_weeks() -> None:
    """Hằng của file tính tay (không gọi helper): ba cửa sổ liền nhau, mỗi cửa sổ 7 ngày; W là 00:00 thứ Hai VN."""
    assert A[1] == B[0] and B[1] == C[0] and C[1] == W
    assert all(hi - lo == W - M1 for lo, hi in (A, B, C))
    local = W.astimezone(VN_TZ)
    assert (local.weekday(), local.hour, local.minute) == (0, 0, 0)
    assert NOW.astimezone(VN_TZ).hour == 2


def test_weekly_marks_vn() -> None:
    assert WEEKLY_MARKS == 2
    assert weekly_marks(CTX) == [M1, W]
    assert (week_window(W, VN_TZ), baseline_window(W, VN_TZ)) == (C, B)
    assert (week_window(M1, VN_TZ), baseline_window(M1, VN_TZ)) == (B, A)


@pytest.mark.parametrize(
    ("now", "marks"),
    [
        (W, [M1, W]),  # đúng 00:00 thứ Hai VN → W = now
        (datetime(2026, 10, 11, 16, 59, tzinfo=UTC), [B[0], M1]),  # 23:59 CN VN → còn tuần trước
    ],
    ids=["dung_0h_thu_hai", "23h59_chu_nhat"],
)
def test_weekly_marks_week_start_boundary(now: datetime, marks: list[datetime]) -> None:
    assert weekly_marks(RuleContext(now=now, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)) == marks


def test_week_windows_dst_berlin() -> None:
    """Trừ ngày LỊCH theo `tz`. Lịch (kiểm độc lập): EU đổi giờ CN 29/03/2026 (CET +1 → CEST +2); 06/04/2026 là thứ Hai.
    now = 2026-04-05T22:30Z = 00:30 thứ Hai 06/04 CEST → W = 00:00 06/04 CEST = 04-05T22:00Z; W − 7 = 00:00 30/03 CEST =
    03-29T22:00Z; W − 14 = 00:00 23/03 CET = 03-22T23:00Z (bản trừ 168 giờ UTC ra 03-22T22:00Z = 23:00 CN — sai);
    W − 21 = 00:00 16/03 CET = 03-15T23:00Z."""
    berlin = ZoneInfo("Europe/Berlin")
    ctx = RuleContext(now=datetime(2026, 4, 5, 22, 30, tzinfo=UTC), tz=berlin, cap_usd=38.0, warn_ratio=0.8)
    w, m1 = datetime(2026, 4, 5, 22, 0, tzinfo=UTC), datetime(2026, 3, 29, 22, 0, tzinfo=UTC)
    w14, w21 = datetime(2026, 3, 22, 23, 0, tzinfo=UTC), datetime(2026, 3, 15, 23, 0, tzinfo=UTC)
    assert weekly_marks(ctx) == [m1, w]
    assert week_window(w, berlin) == (m1, w)
    assert baseline_window(w, berlin) == (w14, m1)
    assert baseline_window(m1, berlin) == (w21, w14)


# ---- luật 8 ---------------------------------------------------------------------------------------------------------


def test_drift_constants_and_spec() -> None:
    assert DRIFT_THRESHOLD == 0.2
    assert DRIFT_DISTRIBUTIONS == NAMES
    spec = REGISTRY["drift"]
    assert (spec.every, spec.audience, spec.fn) == ("weekly", ("manager",), drift_rule)


@pytest.mark.parametrize(("value", "n_drafts"), [(0.21, 1), (0.2, 0), (0.19, 0)], ids=["vuot", "bang", "duoi"])
def test_drift_threshold(value: float, n_drafts: int) -> None:
    """PSI > 0,2; đúng bằng 0,2 → không báo."""
    s = DriftScore(value, 10, 10)
    out = drift_rule({M1: week(), W: week(intent=s)}, CTX)
    assert out == [draft("intent", W, s)] * n_drafts


def test_drift_two_distributions_two_drafts() -> None:
    """Hai phân bố vượt cùng mốc → 2 draft: subject = TÊN phân bố (không phải SYSTEM_SUBJECT), window_start = mốc W (không
    phải ctx.now); thứ tự theo DRIFT_DISTRIBUTIONS. `detail` đúng 4 khoá, kiểu ghi được vào JSONB."""
    e3, override = DriftScore(0.5, 20, 40), DriftScore(0.3, 7, 9)
    out = drift_rule({M1: week(), W: week(override=override, e3_rate=e3, confidence=DriftScore(0.1, 5, 5))}, CTX)
    assert out == [draft("e3_rate", W, e3), draft("override", W, override)]
    for d in out:
        assert d.subject != SYSTEM_SUBJECT and d.window_start == W != NOW
        assert set(d.detail) == {"psi", "threshold", "n_expected", "n_actual"}
        assert type(d.detail["psi"]) is float and type(d.detail["n_expected"]) is int
        assert type(d.detail["n_actual"]) is int


def test_drift_two_marks() -> None:
    """Cả hai mốc vượt → 2 draft cùng subject, khoá theo mốc (cũ → mới)."""
    old, new = DriftScore(0.4, 3, 4), DriftScore(0.25, 4, 5)
    out = drift_rule({M1: week(top_score=old), W: week(top_score=new)}, CTX)
    assert out == [draft("top_score", M1, old), draft("top_score", W, new)]


def test_drift_none_and_skipped() -> None:
    """None (một phía 0 mẫu) → không báo; phân bố pending (skipped) → không báo; phân bố khác vẫn báo."""
    hit = DriftScore(0.9, 10, 10)
    scores: dict[str, DriftScore | None] = {name: None for name in NAMES if name != "override"}
    scores["escalation"] = hit
    out = drift_rule({M1: week(), W: DriftWeek(scores=scores, skipped=("override",))}, CTX)
    assert out == [draft("escalation", W, hit)]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({W: week()}, "luật drift: mốc dữ liệu lệch weekly_marks"),
        ({M1: week(), W: week(), NOW: week()}, "luật drift: mốc dữ liệu lệch weekly_marks"),
        ({M1: week(), W: DriftWeek(scores=dict.fromkeys(NAMES[:5]), skipped=())},
         "luật drift: phân bố lệch DRIFT_DISTRIBUTIONS"),
        ({M1: week(), W: DriftWeek(scores={**dict.fromkeys(NAMES), "la": None}, skipped=())},
         "luật drift: phân bố lệch DRIFT_DISTRIBUTIONS"),
        ({M1: week(), W: DriftWeek(scores=dict.fromkeys(NAMES), skipped=("override",))},
         "luật drift: phân bố lệch DRIFT_DISTRIBUTIONS"),
    ],
    ids=["thieu_moc", "thua_moc", "thieu_ten", "ten_la", "vua_scores_vua_skipped"],
)  # fmt: skip
def test_drift_rejects_bad_data(data: dict[datetime, DriftWeek], message: str) -> None:
    """Loader dựng dict từ chính `weekly_marks` và đủ 6 phân bố → lệch là bug, không im lặng (thiếu = bỏ sót)."""
    with pytest.raises(ValueError) as info:
        drift_rule(data, CTX)
    assert str(info.value) == message


# ---- loader + drift_counts (conn giả) -------------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def one(self) -> Any:
        [row] = self.rows
        return row


def _row(n: int, hit: int) -> SimpleNamespace:
    return SimpleNamespace(n=n, hit=hit)


# Số đếm theo câu SQL và theo `frm` của cửa sổ (A, B, C khác nhau để lộ cặp cửa sổ sai).
SQL_NAMES = {
    id(rules_data.DRIFT_INTENT_SQL): "intent", id(rules_data.DRIFT_CONFIDENCE_SQL): "confidence",
    id(rules_data.DRIFT_TOP_SCORE_SQL): "top_score", id(rules_data.DRIFT_DONE_SQL): "done",
    id(rules_data.DRIFT_OVERRIDE_SQL): "override",
}  # fmt: skip
ROWS: dict[str, dict[datetime, list[Any]]] = {
    "intent": {A[0]: [("vpn", 5), ("account", 5)], B[0]: [("vpn", 10), ("account", 10)], C[0]: [("account", 20),
                                                                                               ("vpn", 20)]},
    "confidence": {A[0]: [], B[0]: [], C[0]: []},  # 0 mẫu cả ba tuần → None
    "top_score": {A[0]: [], B[0]: [(3, 2)], C[0]: [(3, 2)]},  # mốc M1: tuần mốc 0 mẫu → None; mốc W: giống nhau → 0
    "done": {A[0]: [_row(10, 1)], B[0]: [_row(20, 10)], C[0]: [_row(40, 4)]},
    "override": {A[0]: [_row(10, 5)], B[0]: [_row(20, 10)], C[0]: [_row(40, 20)]},
}  # fmt: skip


class WindowConn:
    """Ghi (câu SQL, tham số bind); trả số đếm của `ROWS` theo câu và `frm`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, clause: TextClause, params: dict[str, Any]) -> _Result:
        self.calls.append((clause.text, params))
        return _Result(ROWS[SQL_NAMES[id(clause)]][params["frm"]])


class FakeWeighted:
    """Bản giả `escalation_rate_weighted(conn, frm, to)` (A1): ghi lời gọi; `raw` và `weighted` khác nhau theo cửa sổ."""

    RAW: ClassVar[dict[datetime, float]] = {A[0]: 0.5, B[0]: 0.6, C[0]: 0.5}
    WEIGHTED: ClassVar[dict[datetime, float]] = {A[0]: 0.9, B[0]: 0.1, C[0]: 0.9}

    def __init__(self) -> None:
        self.calls: list[tuple[object, datetime, datetime]] = []

    async def __call__(self, conn: object, frm: datetime, to: datetime) -> WeightedRate:
        self.calls.append((conn, frm, to))
        return WeightedRate(raw=self.RAW[frm], weighted=self.WEIGHTED[frm], by_group={}, sensitivity={})


@pytest.fixture
def weighted(monkeypatch: pytest.MonkeyPatch) -> FakeWeighted:
    fake = FakeWeighted()
    monkeypatch.setattr(rules_data, "escalation_rate_weighted", fake)
    return fake


def pending_override(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    real = rules_data.is_pending
    monkeypatch.setattr(rules_data, "is_pending", lambda k: value if k == "override_count" else real(k))


def load(conn: WindowConn) -> Any:
    return asyncio.run(LOADERS["drift"](cast(Any, conn), CTX))


def test_drift_loader_windows_and_pairing(weighted: FakeWeighted) -> None:
    """Đọc đúng 3 cửa sổ tay (A, B, C — B dùng chung cho hai mốc, đếm một lần); escalation gọi ĐÚNG hàm A1 với chữ ký
    `(conn, frm, to)`; PSI từng mốc = số tay; số mẫu escalation = số lá đã kết thúc của câu e3 (cùng mẫu số)."""
    conn = WindowConn()
    out = load(conn)
    assert weighted.calls == [(conn, *A), (conn, *B), (conn, *C)]
    assert sorted({(p["frm"], p["to"]) for _, p in conn.calls}) == [A, B, C]
    assert len(conn.calls) == 3 * 5  # 5 câu mỗi cửa sổ, mỗi cửa sổ một lần
    assert list(out) == [M1, W]
    for mark, (n_e, n_a) in ((M1, (10, 20)), (W, (20, 40))):
        s = out[mark].scores
        assert out[mark].skipped == ()
        e3, esc = s["e3_rate"], s["escalation"]
        assert e3 is not None and esc is not None
        assert abs(e3.psi - PSI_E3) <= TOL and (e3.n_expected, e3.n_actual) == (n_e, n_a)
        # mốc M1: raw 0,5 → 0,6; mốc W: 0,6 → 0,5 (weighted 0,9/0,1 thì PSI khác hẳn)
        assert abs(esc.psi - PSI_TWO_BINS) <= TOL and (esc.n_expected, esc.n_actual) == (n_e, n_a)
        assert s["intent"] == DriftScore(0.0, n_e, n_a)  # cùng tỉ lệ vpn/account
        assert s["override"] == DriftScore(0.0, n_e, n_a)
        assert s["confidence"] is None
        assert type(e3.psi) is float and type(e3.n_expected) is int
    assert out[M1].scores["top_score"] is None
    assert out[W].scores["top_score"] == DriftScore(0.0, 2, 2)


def test_drift_loader_override_pending(
    weighted: FakeWeighted, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Q-M9-B3-3: nguồn ghi đè pending → CHỈ bỏ phân bố override (không trả Pending cả luật), không chạy câu ghi đè; 5
    phân bố còn lại vẫn được tính. Log INFO một dòng, không mang số liệu (Q-M9-B3-13)."""
    pending_override(monkeypatch, True)
    conn = WindowConn()
    with caplog.at_level(logging.INFO, logger=rules_data.__name__):
        out = load(conn)
    assert isinstance(out, dict) and list(out) == [M1, W]
    assert rules_data.DRIFT_OVERRIDE_SQL.text not in [sql for sql, _ in conn.calls]
    for mark in (M1, W):
        assert out[mark].skipped == ("override",)
        assert set(out[mark].scores) == set(NAMES) - {"override"}
        assert out[mark].scores["e3_rate"] is not None
    records = [r for r in caplog.records if r.name == rules_data.__name__]
    assert [(r.levelno, r.getMessage()) for r in records] == [
        (logging.INFO, "luật drift bỏ phân bố override: nguồn chưa có (override_count)")
    ]


def test_drift_loader_no_log_when_ready(weighted: FakeWeighted, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger=rules_data.__name__):
        load(WindowConn())
    assert [r for r in caplog.records if r.name == rules_data.__name__] == []


@pytest.mark.parametrize(
    ("frm", "to", "message"),
    [
        (datetime(2026, 10, 4, 17), W, "drift_counts: cần datetime có múi giờ"),  # noqa: DTZ001 — cố ý naive
        (M1, datetime(2026, 10, 11, 17), "drift_counts: cần datetime có múi giờ"),  # noqa: DTZ001
        (W, W, "drift_counts: cửa sổ rỗng"),
        (W, M1, "drift_counts: cửa sổ rỗng"),
    ],
    ids=["frm_naive", "to_naive", "rong", "nguoc"],
)
def test_drift_counts_rejects_window(frm: datetime, to: datetime, message: str, weighted: FakeWeighted) -> None:
    conn = WindowConn()
    with pytest.raises(ValueError) as info:
        asyncio.run(drift_counts(cast(Any, conn), frm, to))
    assert str(info.value) == message
    assert conn.calls == [] and weighted.calls == []


def test_drift_counts_bins_and_order(weighted: FakeWeighted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dòng SQL → tuple đủ bin theo thứ tự cố định; bin không có dòng = 0. confidence: chỉ số SQL 1…10 → vị trí 0…9;
    top_score: 0…11 → 0…11; intent NULL → none, lạ → other (SQL đã gộp, Python chỉ xếp)."""
    monkeypatch.setitem(ROWS["intent"], A[0], [("other", 2), ("none", 3), ("access", 1)])
    monkeypatch.setitem(ROWS["confidence"], A[0], [(1, 4), (10, 6)])
    monkeypatch.setitem(ROWS["top_score"], A[0], [(0, 1), (11, 2), (5, 3)])
    counts = asyncio.run(drift_counts(cast(Any, WindowConn()), *A))
    assert counts == DriftCounts(
        bins={
            "intent": (0, 0, 0, 1, 3, 2), "confidence": (4, 0, 0, 0, 0, 0, 0, 0, 0, 6),
            "top_score": (1, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 2), "e3_rate": (1, 9), "override": (5, 5),
        },
        escalation_raw=0.5, leaves_done=10, pending=(),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("sql", "rows", "message"),
    [
        ("confidence", [(11, 1)], "drift_counts: chỉ số bin ngoài dải"),
        ("confidence", [(0, 1)], "drift_counts: chỉ số bin ngoài dải"),
        ("top_score", [(12, 1)], "drift_counts: chỉ số bin ngoài dải"),
        ("top_score", [(-1, 1)], "drift_counts: chỉ số bin ngoài dải"),
        ("confidence", [(None, 1)], "drift_counts: chỉ số bin ngoài dải"),
        ("intent", [("printer", 1)], "drift_counts: bin intent lạ"),
    ],
    ids=["conf_11", "conf_0", "top_12", "top_am", "conf_null", "intent_la"],
)
def test_drift_counts_bin_out_of_range(
    sql: str, rows: list[Any], message: str, weighted: FakeWeighted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQL lệch mốc bin (vd bỏ LEAST) → lỗi to tiếng (luật vào failed_rules), không gộp im lặng vào bin khác."""
    monkeypatch.setitem(ROWS[sql], A[0], rows)
    with pytest.raises(ValueError) as info:
        asyncio.run(drift_counts(cast(Any, WindowConn()), *A))
    assert str(info.value) == message


def _counts(**kw: Any) -> DriftCounts:
    base: dict[str, Any] = {
        "bins": {"intent": (1, 1, 0, 0, 0, 0), "confidence": (0,) * 10, "top_score": (0,) * 12, "e3_rate": (1, 1),
                 "override": (0, 2)},
        "escalation_raw": 0.5, "leaves_done": 2, "pending": (),
    }  # fmt: skip
    return DriftCounts(**(base | kw))


def test_drift_scores_escalation() -> None:
    """escalation qua `score_rate`: số tay [0,5; 0,5] vs [0,6; 0,4]; `raw` None một phía (A: 0 lá) → None; 0 lá xong → None."""
    out = drift_scores(_counts(leaves_done=100), _counts(escalation_raw=0.6, leaves_done=50))
    esc = out.scores["escalation"]
    assert esc is not None and abs(esc.psi - PSI_TWO_BINS) <= TOL and (esc.n_expected, esc.n_actual) == (100, 50)
    assert drift_scores(_counts(escalation_raw=None), _counts()).scores["escalation"] is None
    assert drift_scores(_counts(), _counts(escalation_raw=None, leaves_done=0)).scores["escalation"] is None


def test_drift_scores_pending_one_side() -> None:
    """Một phía pending override → skipped (không so số đếm với phía kia)."""
    bins = dict(_counts().bins)
    del bins["override"]
    out = drift_scores(_counts(), _counts(bins=bins, pending=("override",)))
    assert out.skipped == ("override",) and "override" not in out.scores
    assert set(out.scores) == set(NAMES) - {"override"}


# ---- hình dạng SQL + hằng bin ---------------------------------------------------------------------------------------

DRIFT_SQL_NAMES = ("DRIFT_INTENT_SQL", "DRIFT_CONFIDENCE_SQL", "DRIFT_TOP_SCORE_SQL", "DRIFT_DONE_SQL",
                   "DRIFT_OVERRIDE_SQL")  # fmt: skip


def test_drift_sql_shape() -> None:
    """Mọi câu qua `v_leaf t` (D-30), không chạm `tickets`; cửa sổ và "đã kết thúc" CÙNG CHỮ với mẫu số của A
    (`common.LEAF_WINDOW`, `common.DONE`) — e3_rate và số mẫu escalation cùng mẫu số với `escalation_rate_weighted.raw`.
    Ép `::numeric` chỉ sau guard `jsonb_typeof(...) = 'number' THEN`."""
    assert rules_data.DRIFT_LEAF_WINDOW == common.LEAF_WINDOW
    assert rules_data.DRIFT_DONE == common.DONE
    for name in DRIFT_SQL_NAMES:
        body = getattr(rules_data, name).text
        assert "v_leaf t" in body and rules_data.DRIFT_LEAF_WINDOW in body, name
        assert " tickets" not in body.lower(), name
    for name in ("DRIFT_DONE_SQL", "DRIFT_OVERRIDE_SQL"):
        assert rules_data.DRIFT_DONE in getattr(rules_data, name).text, name
    for name in ("DRIFT_INTENT_SQL", "DRIFT_CONFIDENCE_SQL", "DRIFT_TOP_SCORE_SQL"):
        assert rules_data.DRIFT_DONE not in getattr(rules_data, name).text, name
    for name, key in (("DRIFT_CONFIDENCE_SQL", "confidence"), ("DRIFT_TOP_SCORE_SQL", "top_score")):
        body = getattr(rules_data, name).text
        guard = f"jsonb_typeof(a.detail->'{key}') = 'number' THEN"
        assert body.count("jsonb_typeof") == 1 and guard in body, name
        assert body.count("::numeric") >= 1 and body.index(guard) < body.index("::numeric"), name
        assert "a.confidence" not in body, name  # khoá JSON, không phải cột chưa ghi


def test_drift_bin_constants() -> None:
    """Mốc bin cố định trong code (Q-M9-B3-2), viết tay."""
    assert rules_data.DRIFT_INTENT_BINS == ("account", "vpn", "software", "access", "none", "other")
    assert (rules_data.UNIT_LO, rules_data.UNIT_HI, rules_data.UNIT_BINS) == (0, 1, 10)
    assert rules_data.TOP_SCORE_BINS == 12
    assert rules_data.CONFIDENCE_STEPS == ("B3", "B4") and rules_data.TOP_SCORE_STEP == "B8"
    assert "width_bucket((a.detail->'confidence')::numeric, 0, 1, 10)" in rules_data.DRIFT_CONFIDENCE_SQL.text
    assert "LEAST(GREATEST(" in rules_data.DRIFT_CONFIDENCE_SQL.text
