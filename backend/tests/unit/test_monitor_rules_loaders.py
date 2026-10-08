"""M9-B2 GĐ2 cụm 2 — loader luật giờ 14 `llm_budget` và luật ngày 1 `escalation_rate_high`, 7 `reflex_approval`,
12 `b2_degraded`, 13 `b3_degraded` (`queries/rules_data.py`). Không DB: SQL ghi lại bằng conn giả, hàm của luồng A thay
bằng bản giả ghi `(conn, frm, to)` — test chỉ kiểm loader GỌI đúng hàm, đúng cửa sổ, không tự tính lại.

Nguồn: kế hoạch chung M9 mục 6 (luật 1, 7, 12, 13, 14); file chia việc mục 3 (hợp đồng hàm A, `is_pending`), thẻ B2;
chốt Q-M9-B2-1, 3, 6, 7, 15, 16, 17 ở #14 (comment 5955137864, 5955436721, 5959974287). Đề xuất Q-M9-B2-23, 24, 25 (plan
cụm 2). Bản Postgres: `tests/integration/test_monitor_rules_daily_pg.py`, `test_monitor_rules_budget_pg.py`.

Mốc tính tay với `NOW = 2026-10-02T19:00Z` (02:00 giờ VN ngày 03/10, VN không đổi giờ): `d0` = 00:00 VN 03/10 =
`2026-10-02T17:00Z`; `d0 − 7 ngày = 2026-09-25T17:00Z`.
"""

import asyncio
import re
from datetime import UTC, datetime
from itertools import pairwise
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.graph.late_event import WAITS
from app.monitor.evaluator import LOADERS, Pending
from app.monitor.queries import rules_data
from app.monitor.queries.business import WeightedRate
from app.monitor.rules import (
    REGISTRY,
    ApprovalDecision,
    RuleContext,
    b2_degraded,
    b3_degraded,
)
from app.monitor.window import VN_TZ
from sqlalchemy.sql.elements import TextClause

NOW = datetime(2026, 10, 2, 19, 0, tzinfo=UTC)
CTX = RuleContext(now=NOW, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)
D0 = datetime(2026, 10, 2, 17, 0, tzinfo=UTC)
SINCE = datetime(2026, 9, 25, 17, 0, tzinfo=UTC)  # d0 − 7 ngày
# 7 mốc r = d0 − k ngày (k = 6…0), cửa sổ [r − 1 ngày, r) — cũ → mới
MARKS = [datetime(2026, 9, day, 17, 0, tzinfo=UTC) for day in range(26, 31)] + [
    datetime(2026, 10, 1, 17, 0, tzinfo=UTC), D0,
]  # fmt: skip
WINDOWS = [(SINCE, MARKS[0]), *pairwise(MARKS)]

HOURLY_DAILY = {"llm_budget", "escalation_rate_high", "reflex_approval", "b2_degraded", "b3_degraded"}


class RecordingConn:
    """Ghi (câu SQL, tham số bind); trả `rows` cho trước."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, clause: TextClause, params: dict[str, Any] | None = None) -> list[Any]:
        self.calls.append((clause.text, params))
        return self.rows


class _Scalar:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value


class ScalarConn:
    """Như RecordingConn nhưng kết quả có `scalar_one()` (luật 14)."""

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, clause: TextClause, params: dict[str, Any] | None = None) -> _Scalar:
        self.calls.append((clause.text, params))
        return _Scalar(self.value)


class FakeRate:
    """Bản giả một hàm chỉ số của luồng A `(conn, frm, to)`: ghi lời gọi, trả giá trị theo thứ tự `values`."""

    def __init__(self, values: list[Any]) -> None:
        self.values = list(values)
        self.calls: list[tuple[object, datetime, datetime]] = []

    async def __call__(self, conn: object, frm: datetime, to: datetime) -> Any:
        self.calls.append((conn, frm, to))
        return self.values.pop(0)


def load(rule_id: str, conn: object) -> Any:
    return asyncio.run(LOADERS[rule_id](cast(Any, conn), CTX))


def pending_only(monkeypatch: pytest.MonkeyPatch, key: str, value: bool) -> None:
    """Vá RIÊNG khoá `key` của `is_pending` (khoá khác giữ nguyên trạng thái thật)."""
    real = rules_data.is_pending
    monkeypatch.setattr(rules_data, "is_pending", lambda k: value if k == key else real(k))


def test_hand_computed_marks() -> None:
    """Hằng mốc của file này tính tay (không gọi helper đang test): 7 mốc liền nhau cách 1 ngày, mốc cuối là d0."""
    assert len(MARKS) == 7 and MARKS[-1] == D0 and len(WINDOWS) == 7
    assert all(b - a == MARKS[1] - MARKS[0] for a, b in WINDOWS)
    assert D0.astimezone(VN_TZ).hour == 0


# ---- đăng ký -----------------------------------------------------------------------------------------------------------


def test_hourly_daily_rules_have_loader() -> None:
    """Mọi luật giờ/ngày có loader ở `rules_data` (thiếu → MissingLoaderError → luật lỗi mỗi lượt của job cụm 3).
    So BẰNG: không thiếu luật, không loader mồ côi (loader không có luật = dữ liệu đọc rồi bỏ)."""
    periodic = {r for r, spec in REGISTRY.items() if spec.every in ("hourly", "daily")}
    assert periodic == HOURLY_DAILY
    assert {r for r in LOADERS if REGISTRY[r].every in ("hourly", "daily")} == HOURLY_DAILY
    assert {LOADERS[r].__module__ for r in HOURLY_DAILY} == {rules_data.__name__}
    assert set(LOADERS) == set(REGISTRY)


# ---- luật 14 llm_budget -------------------------------------------------------------------------------------------------


def test_llm_budget_loader_whole_table() -> None:
    """Q-M9-6, Q-M9-B2-16: Σ cost_usd TOÀN BẢNG, `COALESCE(…, 0)`, không cửa sổ, không nối, không bind; trả nguyên giá trị
    DB (không ép kiểu — `cost_usd` double precision → psycopg trả float)."""
    value = object()
    conn = ScalarConn(value)
    assert load("llm_budget", conn) is value
    [(sql, params)] = conn.calls
    assert re.fullmatch(r"\s*SELECT COALESCE\(SUM\(c\.cost_usd\), 0\) AS spent\s+FROM llm_calls c\s*", sql)
    assert not params


# ---- luật 1 escalation_rate_high -----------------------------------------------------------------------------------------


def test_escalation_loader_calls_weighted_rolling_7d(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gọi `escalation_rate_weighted(conn, d0 − 7 ngày, d0)` của A1 đúng MỘT lần (chỉ mốc d0 — Q-M9-B2-15), trả nguyên
    kết quả; loader không tự truy vấn."""
    rate = WeightedRate(raw=0.5, weighted=0.5, by_group={}, sensitivity={})
    fake = FakeRate([rate])
    monkeypatch.setattr(rules_data, "escalation_rate_weighted", fake)
    conn = RecordingConn()
    assert load("escalation_rate_high", conn) is rate
    assert fake.calls == [(conn, SINCE, D0)]
    assert conn.calls == []


# ---- luật 12 b2_degraded, 13 b3_degraded ----------------------------------------------------------------------------------

DEGRADED = pytest.mark.parametrize(
    ("rule_id", "key", "reason", "own", "other"),
    [
        ("b2_degraded", "b2_classifier", "injection_clf_not_enabled", "b2_llm_rate", "b3_llm_rate"),
        ("b3_degraded", "b3_cascade", "cascade_not_enabled", "b3_llm_rate", "b2_llm_rate"),
    ],
    ids=["12", "13"],
)  # fmt: skip


@DEGRADED
def test_degraded_loader_pending_no_sql(
    rule_id: str, key: str, reason: str, own: str, other: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nguồn pending (Phase 3–4, Q-M9-A2-8 / Q-M9-9) → `Pending`, KHÔNG gọi hàm A, không chạy SQL (không báo, không đoán)."""
    fakes = {name: FakeRate([]) for name in (own, other)}
    for name, fake in fakes.items():
        monkeypatch.setattr(rules_data, name, fake)
    conn = RecordingConn()
    assert load(rule_id, conn) == Pending(reason)
    assert [f.calls for f in fakes.values()] == [[], []]
    assert conn.calls == []


@DEGRADED
def test_degraded_loader_ready_seven_windows(
    rule_id: str, key: str, reason: str, own: str, other: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nguồn ready: gọi ĐÚNG hàm của luật (12 → `b2_llm_rate`, 13 → `b3_llm_rate`) 7 lần, mỗi lần một ngày VN trọn
    `[r − 1 ngày, r)`, cũ → mới (Q-M9-B2-1, 15); dict có đúng 7 mốc nên luật nhận được (Q-M9-B2-20)."""
    pending_only(monkeypatch, key, False)
    values = [0.1, None, 0.2, 0.31, 0.0, 0.5, 0.3]
    mine, theirs = FakeRate(values), FakeRate([])
    monkeypatch.setattr(rules_data, own, mine)
    monkeypatch.setattr(rules_data, other, theirs)
    conn = RecordingConn()
    data = load(rule_id, conn)
    assert mine.calls == [(conn, frm, to) for frm, to in WINDOWS]
    assert theirs.calls == []
    assert data == dict(zip(MARKS, values, strict=True))
    fn = {"b2_degraded": b2_degraded, "b3_degraded": b3_degraded}[rule_id]
    assert [d.window_start for d in fn(data, CTX)] == [MARKS[3], MARKS[5]]  # 0,31 và 0,5 > 0,30; 0,3 bằng → không


# ---- luật 7 reflex_approval ------------------------------------------------------------------------------------------------


def _row(*, log_id: int | None, detail: object, by: str = "u-1") -> SimpleNamespace:
    return SimpleNamespace(
        status="approved", decided_by=by, decided_at=D0, reminder_2_at=None, b16_log_id=log_id, b16_detail=detail
    )


def test_reflex_loader_binds() -> None:
    """Bind chỉ là mốc + hằng: `since = d0 − 7 ngày` (`daily_since`, mốc dưới của mốc cũ nhất), step B16, quyết định của
    người `("approved", "rejected")` — `HUMAN_DECISIONS` là tuple nên thứ tự cố định."""
    conn = RecordingConn()
    assert load("reflex_approval", conn) == []
    [(sql, params)] = conn.calls
    assert sql == rules_data.REFLEX_SQL.text
    assert params == {"since": SINCE, "step": "B16", "decisions": ["approved", "rejected"]}


def test_reflex_loader_maps_rows() -> None:
    """Không có dòng B16 khớp → `b16 = None`; có dòng mà `detail` không phải object → `{}`; object → nguyên văn. Hai ca
    đầu đều ra "mơ hồ" ở luật, nhưng loader giữ phân biệt (Q-M9-B2-6)."""
    view = {"decided_without_view": False, "view_duration": 12.0, "decided_as": "primary"}
    conn = RecordingConn([_row(log_id=None, detail=None), _row(log_id=7, detail=[1]), _row(log_id=8, detail=view)])
    out = load("reflex_approval", conn)
    assert [d.b16 for d in out] == [None, {}, view]
    assert out[0] == ApprovalDecision(status="approved", decided_by="u-1", decided_at=D0, reminder_2_at=None, b16=None)


def test_reflex_loader_pending_no_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    """`approval_view` là nguồn từng pending (tới 4c) → loader kiểm `is_pending`; pending → `Pending`, không SQL."""
    pending_only(monkeypatch, "approval_view", True)
    conn = RecordingConn()
    assert load("reflex_approval", conn) == Pending("approval_view_not_recorded")
    assert conn.calls == []


def test_reflex_sql_shape() -> None:
    """Ghim từng điều kiện nối B16 ↔ phiếu (Q-M9-B2-6) — test PG thấy kết quả, test này thấy điều kiện nào mất:
    - cột `approval_result = status`, KHÔNG theo `event` (ca `action_plan_changed_since_approval`, #14 5955436721);
    - dòng B16 không sớm hơn phiếu; TRƯỚC (nghiêm ngặt) mốc bắt đầu phiếu kế tiếp (Q-M9-B2-23);
    - LEFT JOIN (thiếu dòng B16 vẫn giữ phiếu → mơ hồ); dòng ĐẦU TIÊN; lọc status ở cả lớp trong và lớp ngoài."""
    sql = rules_data.REFLEX_SQL.text
    assert re.search(r"\ba\.approval_result = p\.status\b", sql)
    assert re.search(r"\ba\.created_at >= p\.created_at\b", sql)
    assert re.search(r"\(p\.next_start IS NULL OR p\.next_start > a\.created_at\)", sql)
    assert re.search(
        r"lead\(COALESCE\(q\.decided_at, q\.created_at\)\)\s+OVER \(PARTITION BY q\.ticket_id "
        r"ORDER BY q\.created_at, q\.approval_id\)",
        sql,
    )
    assert len(re.findall(r"\b\w\.status = ANY\(:decisions\) AND \w\.decided_at >= :since\b", sql)) == 2
    assert re.search(r"\bLEFT JOIN LATERAL \(", sql)
    assert re.search(r"ORDER BY a\.created_at, a\.log_id\s+LIMIT 1\b", sql)
    assert re.search(r"\ba\.step = :step\b", sql)
    assert not re.search(r"\bevent\b", sql)


def test_approval_step_matches_graph() -> None:
    """`monitor` không import `graph` → hằng sao chép; lệch bước là luật 7 không thấy dòng B16 nào (mọi phiếu mơ hồ)."""
    assert rules_data.APPROVAL_STEP == WAITS["approval_wait"][1]
