"""Chỉ số dashboard nghiệp vụ (kế hoạch M9 5.1; hợp đồng mục 3 — `WeightedRate`, `escalation_rate_weighted`).

- Chỉ đọc qua `AsyncConnection` của engine `app_monitor`. Ticket đếm qua `v_leaf` (`is_parent = false`, D-30).
- Cửa sổ `[frm, to)` tính theo `created_at` của lá. `frm`/`to` naive, hoặc `frm >= to` → `ValueError`.
- Mẫu số mọi tỉ lệ: chỉ lá đã kết thúc (`final_state IS NOT NULL`) — lá đang chạy chưa biết kết cục.
- Tỉ lệ có mẫu số 0 → `None`, không bao giờ 0 (kế hoạch M9 4.3). Nguồn pending → `null` + tên trong `unavailable`.
- `override_count` đếm DÒNG audit (không lọc `final_state`), cửa sổ theo lá; cửa sổ trống → 0, không `None`.
- Điểm log 4 = `v_decisions` (step `B13/B14`); `decided_by` là cột `audit_logs` (`rule`/`llm`), không phải
  `approvals.decided_by`.
- Own (`approver_id`, Q-M9-5 / Q-M9-A1-6): chỉ tính lá có phiếu `approvals.approver_id = approver_id`, kể cả phiếu
  hết hạn; chỉ trả `OWN_KEYS`.
- Số đếm tử/mẫu (D13, giao diện hiện "(a/b)"): 3 tỉ lệ đơn đếm bằng MỘT câu riêng `ratio_counts`, dùng chung mảnh FILTER
  (`_AUTOMATED`/`_ESCALATED`/`_DEFLECTED`) với hàm tỉ lệ — giá trị tỉ lệ không đổi. Câu đếm và câu tỉ lệ chạy trên cùng
  `conn` của `read_snapshot` (REPEATABLE READ, READ ONLY) nên a/b khớp tỉ lệ. Weighted: a/b CHỈ theo nhóm N3 (không có tử
  tổng — tử tổng / cỡ mẫu là `raw`, đặt cạnh `weighted` dễ hiểu sai). Own: 3 khoá là số đếm → không tử/mẫu, chỉ `sample`.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.override import OVERRIDE_EVENT, OVERRIDE_STEP
from app.monitor.metrics import (
    E1_OTHER,
    E1_REASONS,
    E5_SENSITIVE_REASONS,
    GROUPS,
    N3_SENSITIVITY,
    N3_WEIGHTS,
    is_pending,
)
from app.monitor.queries.common import DONE as _DONE
from app.monitor.queries.common import LEAF_WINDOW as _LEAF_WINDOW
from app.monitor.queries.common import ratio as _ratio
from app.monitor.queries.common import scalar_row as _scalar_row
from app.monitor.queries.common import window_params as _params
from app.monitor.views import V_DECISIONS, V_LEAF

BUSINESS_METRICS: tuple[str, ...] = (
    "automation_rate", "escalation_rate_raw", "escalation_rate_weighted", "deflection_rate",
    "approval_expired_count", "decided_by_distribution", "top_matched_rules", "override_count", "e1_split",
    "e3_cases",
)  # fmt: skip
OWN_KEYS: tuple[str, ...] = ("approval_expired_count", "decided_by_distribution", "top_matched_rules")
COUNTED_KEYS: tuple[str, ...] = (
    "automation_rate", "escalation_rate_raw", "escalation_rate_weighted", "deflection_rate",
)  # fmt: skip
TOP_RULES_LIMIT = 10
E3_CASES_LIMIT = 100
EXCERPT_MAX = 200

# Độ nhạy của MỘT dòng điểm log 4 (Q-M9-1, Q-M9-A1-4). `decision` và `risk_level` lệch nhau thì lấy cái nhạy hơn. Dùng ở
# hai chỗ: nhánh ELSE của nhóm N3 (dưới) và chọn dòng đại diện của lá (`_point4_per_leaf`) — tự nó KHÔNG phải nhóm N3.
_SEVERITY_SQL = (
    "CASE WHEN d.policy_decision = 'deny' OR d.risk_level = 'high' THEN 3 "
    "WHEN d.policy_decision = 'approval_required' OR d.risk_level = 'medium' THEN 2 ELSE 1 END"
)
# Nhóm N3 của LÁ — chỗ DUY NHẤT gán nhóm (F12, #45; test ghim chỉ `escalation_rate_weighted` dùng). Lá E5 có dòng
# escalation E5 MỚI NHẤT mang reason_detail thuộc `E5_SENSITIVE_REASONS` (:e5_sensitive) → 3, trên mọi dòng điểm log 4
# (không đọc `detail`, không xét policy_decision/risk_level). Còn lại: MAX `_SEVERITY_SQL` trên mọi dòng của lá; lá không có
# dòng nào (không tới M5) → routine. Dòng mới nhất: cùng cách `e1_split`, `ai.e2_llm_count`.
_LEAF_N3_SEV_SQL = (
    "CASE WHEN t.exit_code = 'E5' AND (SELECT e.reason_detail FROM escalations e WHERE e.ticket_id = t.ticket_id "
    "AND e.exit_code = 'E5' ORDER BY e.created_at DESC, e.escalation_id DESC LIMIT 1) "
    "= ANY(CAST(:e5_sensitive AS text[])) THEN 3 "
    f"ELSE COALESCE((SELECT max({_SEVERITY_SQL}) FROM {V_DECISIONS} d WHERE d.ticket_id = t.ticket_id), 1) END"
)
_SEVERITY_GROUP: Mapping[int, str] = {1: "routine", 2: "approval", 3: "sensitive"}

_OWN = "EXISTS (SELECT 1 FROM approvals ap WHERE ap.ticket_id = t.ticket_id AND ap.approver_id = :approver_id)"

# Tử số của 3 tỉ lệ đơn — dùng chung cho hàm tỉ lệ và `ratio_counts` (một nguồn điều kiện). Thứ tự = cột của `ratio_counts`.
_SIMPLE_RATIOS: tuple[str, ...] = ("automation_rate", "escalation_rate_raw", "deflection_rate")
_AUTOMATED = (
    "t.final_state = 'S_RESOLVED' "
    "AND NOT EXISTS (SELECT 1 FROM approvals a WHERE a.ticket_id = t.ticket_id) "
    "AND NOT EXISTS (SELECT 1 FROM escalations e WHERE e.ticket_id = t.ticket_id)"
)
_ESCALATED = "t.exit_code IS NOT NULL"
_DEFLECTED = "t.resolution_path = 'deflected'"


@dataclass(frozen=True)
class WeightedRate:
    raw: float | None  # #lá có exit_code / #lá
    weighted: float | None  # 70/20/10 — luật 1 dùng số này; chuẩn hoá lại trên nhóm có lá; None chỉ khi 0 lá
    by_group: Mapping[str, float | None]  # "routine" | "approval" | "sensitive"; nhóm 0 lá → None
    sensitivity: Mapping[str, float | None]  # "60/30/10", "80/15/5"


@dataclass(frozen=True)
class RatioCount:
    num: int
    den: int  # #lá đã kết thúc trong cửa sổ; 0 → tỉ lệ None


@dataclass(frozen=True)
class GroupCount:
    num: int  # #lá của nhóm có exit_code
    den: int  # #lá của nhóm
    weight: float  # trọng số danh nghĩa `N3_WEIGHTS` (chuẩn hoá lại trên nhóm có lá là việc của `weigh`)


@dataclass(frozen=True)
class WeightedCount:
    den: int  # cỡ mẫu = #lá đã kết thúc; KHÔNG có tử tổng — a/b của weighted chỉ hiện theo nhóm
    by_group: Mapping[str, GroupCount]


@dataclass(frozen=True)
class CountedWeightedRate(WeightedRate):
    """`WeightedRate` + số đếm theo nhóm (D13) — lớp con vì chữ ký và 4 trường của `WeightedRate` bị ghim (hợp đồng mục 3).
    Luật 1 / drift chỉ đọc `weighted` / `raw`. Lưu ý: dataclass so `==` theo lớp → không bằng `WeightedRate(...)` cùng giá
    trị; `business_metrics` đổi về `WeightedRate` gốc trước khi đưa ra response."""

    count: WeightedCount


@dataclass(frozen=True)
class RuleCount:
    rule_id: str
    count: int


@dataclass(frozen=True)
class E1Split:
    total: int  # số lá E1 = tổng `counts`
    counts: Mapping[str, int]  # các khóa E1_REASONS (reason_detail nguyên văn) + "other"
    shares: Mapping[str, float | None]  # count / total; total 0 → None


@dataclass(frozen=True)
class E3Case:
    ticket_id: str
    intent: str | None
    created_at: datetime
    kb_version: str | None  # dòng audit gần nhất của lá có kb_version khác null; không có → None (vẫn giữ ca)
    request_excerpt: str  # redacted_request, ≤ 200 ký tự


@dataclass(frozen=True)
class E3Cases:
    items: tuple[E3Case, ...]  # mới nhất trước, tối đa E3_CASES_LIMIT
    truncated: bool  # còn ca ngoài E3_CASES_LIMIT (review PR #22, Q-M9-A3-4) — không cắt im lặng


@dataclass(frozen=True)
class BusinessMetrics:
    values: Mapping[str, Any]  # all: đủ 10 khóa; own: đúng OWN_KEYS
    unavailable: tuple[str, ...]
    counts: Mapping[str, RatioCount | WeightedCount] = field(default_factory=dict)  # all: COUNTED_KEYS không pending
    sample: int | None = None  # own: #lá own trong cửa sổ (cho "chưa đủ dữ liệu"); all: None


def _own(params: dict[str, Any], approver_id: str | None) -> str:
    if approver_id is None:
        return ""
    params["approver_id"] = approver_id
    return f" AND {_OWN}"


def weigh(counts: Mapping[str, tuple[int, int]], weights: Mapping[str, float]) -> float | None:
    """Σ w_g·rate_g / Σ w_g, chỉ trên các nhóm có ≥ 1 lá (Q-M9-A1-3). `counts[g] = (#lá, #lá có exit_code)`.
    Mọi nhóm 0 lá → None. Không chuẩn hoá thì thiếu nhóm "sensitive" sẽ kéo số xuống → luật 1 không nổ (FN)."""
    num = den = 0.0
    for group in GROUPS:
        leaves, escalated = counts.get(group, (0, 0))
        if leaves:
            num += weights[group] * escalated / leaves
            den += weights[group]
    return None if den == 0 else num / den


async def automation_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """#lá `S_RESOLVED` không có dòng `approvals` và không có dòng `escalations` / #lá đã kết thúc (P8 §6.2). Ca
    deflected (`S_RESOLVED`, `resolution_path='deflected'` — audit/final.py) được tính."""
    row = await _scalar_row(conn, (
        f"SELECT count(*), count(*) FILTER (WHERE {_AUTOMATED}) "
        f"FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND {_DONE}"
    ), _params(frm, to))  # fmt: skip
    return _ratio(row[1], row[0])


async def escalation_rate_raw(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """#lá có `exit_code` / #lá đã kết thúc."""
    row = await _scalar_row(conn, (
        f"SELECT count(*), count(*) FILTER (WHERE {_ESCALATED}) "
        f"FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND {_DONE}"
    ), _params(frm, to))  # fmt: skip
    return _ratio(row[1], row[0])


async def escalation_rate_weighted(conn: AsyncConnection, frm: datetime, to: datetime) -> CountedWeightedRate:
    """Escalation rate theo nhóm N3 (70/20/10) + độ nhạy 60/30/10, 80/15/5 — luật 1 dùng `weighted`. Nhóm của lá:
    `_LEAF_N3_SEV_SQL` (F12: E5 `llm_high_risk` → sensitive)."""
    params = {**_params(frm, to), "e5_sensitive": list(E5_SENSITIVE_REASONS)}
    rows = (await conn.execute(text(
        "SELECT g.sev, count(*), count(*) FILTER (WHERE g.exit_code IS NOT NULL) FROM ("
        f"SELECT t.exit_code, {_LEAF_N3_SEV_SQL} AS sev "
        f"FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND {_DONE}) g GROUP BY g.sev"
    ), params)).all()  # fmt: skip
    counts = {g: (0, 0) for g in GROUPS} | {_SEVERITY_GROUP[sev]: (n, esc) for sev, n, esc in rows}
    return CountedWeightedRate(
        raw=_ratio(sum(esc for _, esc in counts.values()), sum(n for n, _ in counts.values())),
        weighted=weigh(counts, N3_WEIGHTS),
        by_group={g: _ratio(esc, n) for g, (n, esc) in counts.items()},
        sensitivity={name: weigh(counts, w) for name, w in N3_SENSITIVITY.items()},
        count=WeightedCount(
            den=sum(n for n, _ in counts.values()),
            by_group={g: GroupCount(num=esc, den=n, weight=N3_WEIGHTS[g]) for g, (n, esc) in counts.items()},
        ),
    )


async def deflection_rate(conn: AsyncConnection, frm: datetime, to: datetime) -> float | None:
    """#lá `resolution_path = 'deflected'` / #lá đã kết thúc."""
    row = await _scalar_row(conn, (
        f"SELECT count(*), count(*) FILTER (WHERE {_DEFLECTED}) "
        f"FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND {_DONE}"
    ), _params(frm, to))  # fmt: skip
    return _ratio(row[1], row[0])


async def ratio_counts(conn: AsyncConnection, frm: datetime, to: datetime) -> dict[str, RatioCount]:
    """(tử, mẫu) của 3 tỉ lệ đơn trong MỘT câu, cùng mảnh FILTER + cùng mẫu số với hàm tỉ lệ."""
    row = await _scalar_row(conn, (
        f"SELECT count(*), count(*) FILTER (WHERE {_AUTOMATED}), count(*) FILTER (WHERE {_ESCALATED}), "
        f"count(*) FILTER (WHERE {_DEFLECTED}) FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND {_DONE}"
    ), _params(frm, to))  # fmt: skip
    return {key: RatioCount(num=int(num), den=int(row[0])) for key, num in zip(_SIMPLE_RATIOS, row[1:], strict=True)}


async def own_sample(conn: AsyncConnection, frm: datetime, to: datetime, *, approver_id: str) -> int:
    """#lá own trong cửa sổ — cùng cửa sổ + điều kiện phiếu như 3 hàm own (không lọc `final_state`). Chỉ để giao diện báo
    "chưa đủ dữ liệu"; 3 khoá own là số đếm, không có tử/mẫu."""
    params = _params(frm, to)
    own = _own(params, approver_id)
    row = await _scalar_row(conn, f"SELECT count(*) FROM {V_LEAF} t WHERE {_LEAF_WINDOW}{own}", params)
    return int(row[0])


async def approval_expired_count(
    conn: AsyncConnection, frm: datetime, to: datetime, *, approver_id: str | None = None
) -> int:
    """#lá `exit_code = 'E6'` (own: chỉ lá có phiếu giao cho `approver_id`)."""
    params = _params(frm, to)
    own = _own(params, approver_id)
    row = await _scalar_row(
        conn, f"SELECT count(*) FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND t.exit_code = 'E6'{own}", params
    )
    return int(row[0])


def _point4_per_leaf(own: str) -> str:
    """Mỗi lá trong cửa sổ đúng MỘT dòng điểm log 4: dòng nhạy nhất; hòa → mới nhất (`created_at`, rồi `log_id`)."""
    return (
        f"SELECT DISTINCT ON (d.ticket_id) d.decided_by, d.matched_rule_id FROM {V_DECISIONS} d "
        f"JOIN {V_LEAF} t ON t.ticket_id = d.ticket_id WHERE {_LEAF_WINDOW}{own} "
        f"ORDER BY d.ticket_id, {_SEVERITY_SQL} DESC, d.created_at DESC, d.log_id DESC"
    )


async def decided_by_distribution(
    conn: AsyncConnection, frm: datetime, to: datetime, *, approver_id: str | None = None
) -> dict[str, int]:
    """Số lá theo `decided_by` (`rule`/`llm`) của dòng điểm log 4 đại diện cho lá."""
    params = _params(frm, to)
    own = _own(params, approver_id)
    rows = (await conn.execute(text(
        f"SELECT x.decided_by, count(*) FROM ({_point4_per_leaf(own)}) x "
        "WHERE x.decided_by IS NOT NULL GROUP BY x.decided_by ORDER BY x.decided_by"
    ), params)).all()  # fmt: skip
    return {decided_by: int(n) for decided_by, n in rows}


async def top_matched_rules(
    conn: AsyncConnection, frm: datetime, to: datetime, *, approver_id: str | None = None
) -> list[RuleCount]:
    """Top 10 `matched_rule_id` của dòng điểm log 4 đại diện cho lá, theo số lá; bằng số → `rule_id` tăng dần."""
    params = {**_params(frm, to), "limit": TOP_RULES_LIMIT}
    own = _own(params, approver_id)
    rows = (await conn.execute(text(
        f"SELECT x.matched_rule_id, count(*) AS n FROM ({_point4_per_leaf(own)}) x "
        "WHERE x.matched_rule_id IS NOT NULL GROUP BY x.matched_rule_id ORDER BY n DESC, x.matched_rule_id "
        "LIMIT :limit"
    ), params)).all()  # fmt: skip
    return [RuleCount(rule_id=rule_id, count=int(n)) for rule_id, n in rows]


async def override_count(conn: AsyncConnection, frm: datetime, to: datetime) -> int:
    """Số dòng ghi đè L1 của lá trong cửa sổ: dòng `audit_logs` do 4d ghi (`OVERRIDE_STEP`, `OVERRIDE_EVENT`), nối `v_leaf`.
    Đếm DÒNG, không đếm ticket (một lá có thể bị nhiều người ghi đè); không lọc `final_state` (ghi đè chỉ có trên ticket đã
    kết thúc, và đây là chỉ số theo dòng audit — Q-M9-A2-7). Cửa sổ theo `created_at` của LÁ như mọi chỉ số nghiệp vụ,
    không theo thời điểm ghi đè: ghi đè muộn có thể làm số của kỳ cũ tăng (đã chốt). Cửa sổ trống → 0 (đã đo, không có)."""
    params = {**_params(frm, to), "step": OVERRIDE_STEP, "event": OVERRIDE_EVENT}
    row = await _scalar_row(conn, (
        f"SELECT count(*) FROM audit_logs a JOIN {V_LEAF} t ON t.ticket_id = a.ticket_id "
        f"WHERE {_LEAF_WINDOW} AND a.step = :step AND a.event = :event"
    ), params)  # fmt: skip
    return int(row[0])


async def e1_split(conn: AsyncConnection, frm: datetime, to: datetime) -> E1Split:
    """Lá E1 tách theo `escalations.reason_detail` nguyên văn (dòng E1 mới nhất của lá) → các khóa `E1_REASONS` +
    `other` (reason_detail khác hoặc không có dòng); tổng = số lá E1 đã kết thúc."""
    rows = (await conn.execute(text(
        "SELECT (SELECT e.reason_detail FROM escalations e WHERE e.ticket_id = t.ticket_id AND e.exit_code = 'E1' "
        "ORDER BY e.created_at DESC, e.escalation_id DESC LIMIT 1) AS reason, count(*) "
        f"FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND {_DONE} AND t.exit_code = 'E1' GROUP BY 1"
    ), _params(frm, to))).all()  # fmt: skip
    counts = dict.fromkeys((*E1_REASONS, E1_OTHER), 0)
    for reason, n in rows:
        counts[reason if reason in E1_REASONS else E1_OTHER] += int(n)
    total = sum(counts.values())
    return E1Split(total=total, counts=counts, shares={k: _ratio(v, total) for k, v in counts.items()})


async def e3_cases(conn: AsyncConnection, frm: datetime, to: datetime) -> E3Cases:
    """Lá E3 (lỗ hổng KB), mới nhất trước, tối đa 100; lấy 101 dòng để biết còn ca ngoài giới hạn (`truncated`)."""
    params = {**_params(frm, to), "limit": E3_CASES_LIMIT + 1, "excerpt": EXCERPT_MAX}
    rows = (await conn.execute(text(
        "SELECT t.ticket_id, t.intent, t.created_at, "
        "(SELECT a.kb_version FROM audit_logs a WHERE a.ticket_id = t.ticket_id AND a.kb_version IS NOT NULL "
        "ORDER BY a.created_at DESC, a.log_id DESC LIMIT 1) AS kb_version, left(t.redacted_request, :excerpt) "
        f"FROM {V_LEAF} t WHERE {_LEAF_WINDOW} AND t.exit_code = 'E3' "
        "ORDER BY t.created_at DESC, t.ticket_id LIMIT :limit"
    ), params)).all()  # fmt: skip
    items = tuple(
        E3Case(ticket_id=tid, intent=intent, created_at=at, kb_version=kb, request_excerpt=excerpt)
        for tid, intent, at, kb, excerpt in rows[:E3_CASES_LIMIT]
    )
    return E3Cases(items=items, truncated=len(rows) > E3_CASES_LIMIT)


# Khóa → truy vấn `(conn, frm, to)`; khóa trong OWN_KEYS nhận thêm `approver_id=`. None = chưa có nguồn: khóa đó PHẢI
# pending trong METRIC_SOURCES (test ghim).
QUERIES: Mapping[str, Callable[..., Awaitable[Any]] | None] = {
    "automation_rate": automation_rate,
    "escalation_rate_raw": escalation_rate_raw,
    "escalation_rate_weighted": escalation_rate_weighted,
    "deflection_rate": deflection_rate,
    "approval_expired_count": approval_expired_count,
    "decided_by_distribution": decided_by_distribution,
    "top_matched_rules": top_matched_rules,
    "override_count": override_count,
    "e1_split": e1_split,
    "e3_cases": e3_cases,
}


async def business_metrics(
    conn: AsyncConnection, frm: datetime, to: datetime, *, approver_id: str | None = None
) -> BusinessMetrics:
    """Gom chỉ số cho `/api/dashboard/business`. `approver_id=None` → đủ 10 khóa. Có `approver_id` (own) → đúng
    `OWN_KEYS`, khóa khác KHÔNG có (không 0, không null). Số đếm (D13): all → `counts` cho `COUNTED_KEYS` không pending;
    own → `sample`. Mọi câu chạy trên cùng `conn` (route: một snapshot)."""
    _params(frm, to)
    keys = BUSINESS_METRICS if approver_id is None else OWN_KEYS
    values: dict[str, Any] = {}
    counts: dict[str, RatioCount | WeightedCount] = {}
    unavailable: list[str] = []
    for key in keys:
        query = QUERIES[key]
        if is_pending(key):
            values[key] = None
            unavailable.append(key)
        elif query is None:
            raise RuntimeError(f"{key}: METRIC_SOURCES ghi ready nhưng chưa có truy vấn")
        elif approver_id is None:
            values[key] = await query(conn, frm, to)
        else:
            values[key] = await query(conn, frm, to, approver_id=approver_id)
        got = values[key]
        if isinstance(got, CountedWeightedRate):  # response giữ `WeightedRate` gốc, số đếm sang `counts`
            counts[key] = got.count
            values[key] = WeightedRate(raw=got.raw, weighted=got.weighted, by_group=got.by_group, sensitivity=got.sensitivity)
    if approver_id is not None:
        sample = await own_sample(conn, frm, to, approver_id=approver_id)
        return BusinessMetrics(values=values, unavailable=tuple(unavailable), sample=sample)
    if any(k not in unavailable for k in _SIMPLE_RATIOS):
        counted = await ratio_counts(conn, frm, to)
        counts.update({k: c for k, c in counted.items() if k not in unavailable})
    return BusinessMetrics(values=values, unavailable=tuple(unavailable), counts=counts)
