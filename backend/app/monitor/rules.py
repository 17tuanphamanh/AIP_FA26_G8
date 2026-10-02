"""Khung luật cảnh báo M9 (P9 mục 6) — đăng ký luật và tiện ích thuần; KHÔNG I/O.

Luật là hàm thuần `(data, ctx) -> list[AlertDraft]`: `data` do loader (`evaluator.loader`, chỉ SELECT qua
engine monitor) đọc sẵn; hàm luật không truy vấn, không ghi, không đọc đồng hồ — mốc "bây giờ" duy nhất là
`ctx.now`, worker lấy từ `Clock` của app (một nguồn đồng hồ, chạy lại ra đúng khoá cũ). Hàm `async def` bị từ
chối ngay lúc đăng ký: không có `await` thì không có I/O lọt vào luật.

Đăng ký trùng `rule_id` → `DuplicateRuleError` lúc import: hai luật cùng id ghi chung khoá chống trùng
`(rule_id, subject, window_start)` → cảnh báo của luật này che mất cảnh báo của luật kia (bỏ sót).

Người nhận (`audience`, chốt Q-M9-B1-9 ở #13) khai báo BẮT BUỘC ngay ở `@rule` và chỉ nằm trong `RuleSpec` — không
ghi vào `alerts.detail`: một nguồn sự thật cạnh luật, đổi người nhận không cần migration, không có dòng cũ mang
người nhận sai. A3 đọc `REGISTRY` để lọc `/api/alerts`.
"""

import inspect
import statistics
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, get_args
from zoneinfo import ZoneInfo

from app.core.hashing import sha256_key
from app.domain.alerts import (
    BRUTEFORCE_RULE_ID,
    SUBJECT_MAX,
    AlertDraft,
    bruteforce_alert,
    bruteforce_subject,
)
from app.monitor.window import bucket_start

type Every = Literal["minute", "hourly", "daily", "weekly"]
EVERY_VALUES: tuple[str, ...] = get_args(Every.__value__)

type Audience = Literal["manager", "dev", "ops"]  # Trưởng BP / dev / vận hành (kế hoạch chung M9 mục 6)
AUDIENCE_VALUES: tuple[str, ...] = get_args(Audience.__value__)

type RuleFn = Callable[[Any, RuleContext], list[AlertDraft]]

HOURS_7D = 168  # trung vị theo giờ của 7 ngày trước giờ đang xét (luật 4, 6)


class DuplicateRuleError(ValueError):
    """Hai luật (hoặc hai loader) cùng id."""


@dataclass(frozen=True)
class RuleContext:
    now: datetime  # từ Clock của app — một nguồn đồng hồ
    tz: ZoneInfo  # VN_TZ (Q-M9-2)
    cap_usd: float  # config/llm.yaml spend.cap_usd — worker đọc, truyền vào
    warn_ratio: float  # spend.warn_ratio

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("RuleContext.now cần datetime có múi giờ")


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    every: Every
    fn: RuleFn
    audience: tuple[Audience, ...]


REGISTRY: dict[str, RuleSpec] = {}  # thứ tự đăng ký = thứ tự chạy


def rule[F: RuleFn](rule_id: str, every: Every, *, audience: tuple[Audience, ...]) -> Callable[[F], F]:
    """Đăng ký luật vào `REGISTRY`; trả nguyên hàm (test gọi thẳng được). Sai → lỗi ngay lúc import.

    `audience`: tuple khác rỗng, không trùng, mỗi phần tử ∈ `AUDIENCE_VALUES`. Chuỗi trần (`"dev"`) bị từ chối —
    không để `"dev"` bị hiểu thành ba người nhận `d`, `e`, `v`."""
    if not rule_id:
        raise ValueError("rule_id rỗng")
    if every not in EVERY_VALUES:
        raise ValueError(f"every không hợp lệ: {every!r}")
    _check_audience(rule_id, audience)

    def register(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            raise TypeError(f"luật {rule_id}: hàm luật phải thuần (không async) — I/O đi qua loader")
        if rule_id in REGISTRY:
            raise DuplicateRuleError(f"luật {rule_id} đăng ký hai lần")
        REGISTRY[rule_id] = RuleSpec(rule_id, every, fn, audience)
        return fn

    return register


def _check_audience(rule_id: str, audience: object) -> None:
    if not isinstance(audience, tuple):
        raise TypeError(f"luật {rule_id}: audience phải là tuple")
    if not audience:
        raise ValueError(f"luật {rule_id}: audience rỗng")
    if any(a not in AUDIENCE_VALUES for a in audience):
        raise ValueError(f"luật {rule_id}: audience lạ {audience!r}")
    if len(set(audience)) != len(audience):
        raise ValueError(f"luật {rule_id}: audience trùng {audience!r}")


def hourly_median(counts_168h: Sequence[int]) -> float:
    """Trung vị số ca theo giờ trong 168 giờ; giờ không có ca = 0.

    Nhận số ca của các giờ CÓ ca (SQL `GROUP BY` giờ bỏ qua giờ trống) — tự đệm 0 cho đủ 168 giờ. Truyền đủ
    168 phần tử (có số 0) cũng ra cùng kết quả. Bỏ giờ trống thì trung vị bị đẩy lên → spike thật bị che (FN).
    """
    if len(counts_168h) > HOURS_7D:
        raise ValueError(f"quá {HOURS_7D} giờ: {len(counts_168h)}")
    if any(c < 0 for c in counts_168h):
        raise ValueError("số ca âm")
    return float(statistics.median([*counts_168h, *[0] * (HOURS_7D - len(counts_168h))]))


def spike(count: int, median: float, factor: float = 3, minimum: int = 3) -> bool:
    """`count > factor × median AND count ≥ minimum` (kế hoạch chung mục 6; P9 luật 4).

    Đúng bằng ngưỡng → không báo. `minimum` chặn báo nhiễu khi trung vị = 0 (1 ca đã vượt 3 × 0).
    """
    return count > factor * median and count >= minimum


# ---- luật theo sự kiện, job 60 giây (B1 — kế hoạch chung M9 mục 4.4, 6; chốt Q-M9-B1-x ở #13) -----------------
#
# Chung cho cả 7 luật:
# - Quét lại `LOOKBACK` (24 giờ, tính cả mốc biên) mỗi lần chạy, không chỉ "từ lần trước" → worker chết 1 giờ vẫn
#   không mất cảnh báo; chạy lại không trùng nhờ khoá `(rule_id, subject, window_start)`.
# - `window_start` = thời điểm LẤY TỪ DB (không bao giờ `ctx.now`) → chạy lại ra đúng khoá cũ.
# - `subject` luôn tường minh; không có đối tượng thì định danh theo sự kiện (`event:<id>`) chứ không gộp về "".
# - Không ép kiểu dữ liệu đọc từ DB (`int(…)`, `float(…)`): lỗi của chúng in nguyên giá trị vào traceback mà
#   evaluator ghi log (review #12 mục 3) — chỉ nhận giá trị đúng kiểu, sai kiểu thì bỏ trường đó khỏi `detail`.

LOOKBACK = timedelta(hours=24)
BURST_MINUTES = 5  # luật 10: cửa sổ trượt 5 phút, khoá theo khung 5 phút
BURST_WINDOW = timedelta(minutes=BURST_MINUTES)
BURST_LIMIT = 10  # luật 10: > 10 sự kiện (tức ≥ 11)
RECONCILE_TOLERANCE = timedelta(seconds=60)  # luật 3: |window_start − occurred_at| ≤ 60 s là "đã có cảnh báo"
RECONCILE_GRACE = timedelta(seconds=60)  # luật 3: chỉ đối soát sự kiện cũ hơn 60 s (Q-M9-B1-3)


@dataclass(frozen=True)
class TicketExit:
    """Luật 2, 16 — một ticket LÁ (`v_leaf`) có dòng `audit_logs` mang `exit_code` của luật, mọi step."""

    ticket_id: str
    first_at: datetime  # created_at NHỎ NHẤT trên mọi dòng mang mã đó của ticket → window_start (khoá ổn định)
    last_at: datetime  # created_at lớn nhất → còn trong lookback hay không
    step: str  # step của dòng sớm nhất
    reason_detail: str | None  # detail.escalation_reason_detail (hoặc block_reason) của dòng sớm nhất


@dataclass(frozen=True)
class SecurityEvent:
    """Luật 9, 10, 11 — một dòng `security_events`."""

    event_id: int
    occurred_at: datetime
    user_id: str | None
    username: str | None  # username_attempted (username ma đã là "h:" + HMAC)
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class ExistingAlert:
    """Luật 3 — dòng `alerts` đã có (auth, B01 hoặc lần đối soát trước). `rule_id` KHÔNG có mặc định (Q-M9-B1-11):
    loader phải mang theo để luật tự kiểm — cảnh báo luật khác cùng subject không được che đợt khoá (review #13)."""

    rule_id: str
    subject: str
    window_start: datetime


@dataclass(frozen=True)
class BruteforceData:
    locks: Sequence[SecurityEvent]  # chỉ `account_locked` có detail.reason = 'threshold'
    alerts: Sequence[ExistingAlert]


@dataclass(frozen=True)
class FinalizeFailed:
    """Luật 15 — dòng audit B20 `finalize_failed_permanent` (graph/runner.py)."""

    ticket_id: str
    created_at: datetime
    node: str | None


def _recent(at: datetime, ctx: RuleContext) -> bool:
    return at >= ctx.now - LOOKBACK


def _unique(drafts: list[AlertDraft]) -> list[AlertDraft]:
    """Giữ draft đầu tiên của mỗi khoá `(subject, window_start)` — DB cũng chỉ giữ một dòng."""
    seen: set[tuple[str, datetime]] = set()
    out: list[AlertDraft] = []
    for d in drafts:
        if (d.subject, d.window_start) not in seen:
            seen.add((d.subject, d.window_start))
            out.append(d)
    return out


def _bounded(prefix: str, value: str) -> str:
    """`prefix:value` nếu vừa `alerts.subject`; dài hơn → băm (cùng cách với `bruteforce_subject`)."""
    subject = f"{prefix}:{value}"
    return subject if len(subject) <= SUBJECT_MAX else f"{prefix}#{sha256_key(value)[:40]}"


def _ticket_exit_drafts(rule_id: str, data: Sequence[TicketExit], ctx: RuleContext) -> list[AlertDraft]:
    return _unique([
        AlertDraft(
            rule_id=rule_id, subject=t.ticket_id, window_start=t.first_at, severity="critical",
            detail={"ticket_id": t.ticket_id, "step": t.step, "reason_detail": t.reason_detail},
        )
        for t in data
        if _recent(t.last_at, ctx)
    ])  # fmt: skip


@rule("injection_detected", "minute", audience=("manager",))
def injection_detected(data: Sequence[TicketExit], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 2 — mỗi lá E0, MỌI step (Q-M9-B1-1): B2 `injection_detected` (S_BLOCKED) và B11/B19 `injection_in_reply`
    (S_ESCALATED). Tấn công qua câu trả lời bổ sung/xác nhận vẫn là tấn công — chỉ bắt ở B2 là bỏ sót."""
    return _ticket_exit_drafts("injection_detected", data, ctx)


@rule("password_bruteforce", "minute", audience=("manager",))
def password_bruteforce(data: BruteforceData, ctx: RuleContext) -> list[AlertDraft]:
    """Luật 3 — ĐỐI SOÁT, lưới an toàn cho cảnh báo auth ghi lúc khoá (Chốt 2b-1).

    Auth ghi cảnh báo với `lock_start = now` của auth, lấy TRƯỚC khi gọi AD (auth/service.py `login`), còn `occurred_at`
    của sự kiện là một lần gọi đồng hồ SAU đó (audit/security_events.py) → độ lệch = độ trễ AD (+ ghi DB), luôn
    `window_start ≤ occurred_at`. Dựng khoá từ `occurred_at` rồi trông vào ON CONFLICT sẽ ra khoá khác → cảnh báo trùng.
    Vì vậy: tìm cảnh báo cùng subject có `|window_start − occurred_at| ≤ 60 s` VÀ `rule_id = password_bruteforce` (luật
    tự kiểm, không trông vào loader: cảnh báo `refresh_reuse` cùng user lệch < 60 s mà được tính là khớp thì đợt khoá
    bị bỏ sót); có → bỏ qua; không → draft `bruteforce_alert(lock_start=occurred_at)`. AD chậm hơn 60 s → báo trùng
    (báo thừa, chấp nhận — không bỏ sót).

    Chỉ xét sự kiện cũ hơn 60 s (Q-M9-B1-3): auth ghi sự kiện rồi mới ghi cảnh báo, hai transaction — đọc vào khe
    giữa sẽ tạo bản trùng. Chờ 60 s chỉ làm lưới an toàn chậm một nhịp, không mất cảnh báo (lookback 24 giờ).

    Tra theo `dict[subject] → [window_start]` dựng một lần (review #20: duyệt khoá × cảnh báo, 5000 × 5000 ≈ 0,7 s chặn
    event loop worker). Mỗi khoá vẫn duyệt tuyến tính các cảnh báo CỦA subject đó — chấp nhận (vài cảnh báo/người/
    ngày)."""
    settled = ctx.now - RECONCILE_GRACE
    known: dict[str, list[datetime]] = {}
    for a in data.alerts:
        if a.rule_id == BRUTEFORCE_RULE_ID:
            known.setdefault(a.subject, []).append(a.window_start)
    drafts: list[AlertDraft] = []
    for e in data.locks:
        if not (_recent(e.occurred_at, ctx) and e.occurred_at <= settled):
            continue
        username = e.username or ""
        subject = bruteforce_subject(e.user_id, username)
        if any(abs(w - e.occurred_at) <= RECONCILE_TOLERANCE for w in known.get(subject, ())):
            continue
        drafts.append(
            bruteforce_alert(user_id=e.user_id, username=username, lock_start=e.occurred_at, source="m9_reconcile")
        )
    return _unique(drafts)


@rule("refresh_reuse", "minute", audience=("manager",))
def refresh_reuse(data: Sequence[SecurityEvent], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 9 — mỗi `refresh_reuse_detected` một cảnh báo. subject = user_id (Q-M9-8: sự kiện không có
    `token_family_id`); writer duy nhất luôn có user_id — thiếu thì định danh theo sự kiện, không gộp."""
    drafts = []
    for e in data:
        if not _recent(e.occurred_at, ctx):
            continue
        revoked = e.detail.get("revoked_sessions")
        detail: dict[str, Any] = {"event_id": e.event_id}
        if isinstance(revoked, int) and not isinstance(revoked, bool):
            detail["revoked_sessions"] = revoked
        subject = e.user_id if e.user_id is not None else f"event:{e.event_id}"
        drafts.append(
            AlertDraft(
                rule_id="refresh_reuse", subject=subject, window_start=e.occurred_at, severity="critical", detail=detail
            )
        )
    return _unique(drafts)


@rule("permission_denied_burst", "minute", audience=("manager",))
def permission_denied_burst(data: Sequence[SecurityEvent], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 10 — > 10 `permission_denied` của MỘT người trong cửa sổ trượt đóng `[t − 5 phút, t]` (Q-M9-B1-2: ở biên
    đếm dư một sự kiện an toàn hơn đếm thiếu). `window_start` = đầu khung 5 phút chứa sự kiện thứ 11.

    `data` có thể chứa sự kiện trước lookback (loader đọc lùi thêm 5 phút): chúng được ĐẾM để cửa sổ trượt đủ lịch
    sử, nhưng chỉ phát cảnh báo khi sự kiện kích hoạt nằm trong lookback. Một đợt vắt qua ranh giới khung 5 phút →
    2 cảnh báo (báo thừa, chấp nhận).

    O(n log n) mỗi đối tượng (review #13: bản `sum(...)` cũ O(n²), 10k sự kiện ~5 s chặn event loop của worker — kẻ
    tấn công spam route bị cấm là treo được job): sắp một lần, đếm `[t − 5 phút, t]` bằng `bisect` — `bisect_right`
    tính cả sự kiện TRÙNG thời điểm `t` đứng sau. Kích hoạt cùng khung với lần trước thì bỏ qua sớm (khung chỉ tăng
    theo thời gian → giữ đúng lần kích hoạt đầu của khung, như `_unique`)."""
    by_subject: dict[str, list[datetime]] = {}
    for e in data:
        # user_id; không có → `username:<…>` như luật 3 (quá 64 ký tự thì băm). Không có cả hai (writer hiện tại không
        # sinh) → gộp chung `username:` — tách theo sự kiện thì không bao giờ đủ 11 = bỏ sót.
        by_subject.setdefault(bruteforce_subject(e.user_id, e.username or ""), []).append(e.occurred_at)
    drafts: list[AlertDraft] = []
    for subject, times in by_subject.items():
        times.sort()
        last_bucket: datetime | None = None
        for i in range(BURST_LIMIT, len(times)):
            t = times[i]
            if t - times[i - BURST_LIMIT] > BURST_WINDOW or not _recent(t, ctx):
                continue
            bucket = bucket_start(t, BURST_MINUTES)
            if bucket == last_bucket:
                continue
            last_bucket = bucket
            count = bisect_right(times, t) - bisect_left(times, t - BURST_WINDOW)  # đóng hai đầu
            drafts.append(
                AlertDraft(
                    rule_id="permission_denied_burst", subject=subject, window_start=bucket_start(t, BURST_MINUTES),
                    severity="warning", value=count, detail={"count": count, "threshold": BURST_LIMIT},
                )
            )  # fmt: skip
    return _unique(drafts)


@rule("policy_saved", "minute", audience=("manager",))
def policy_saved(data: Sequence[SecurityEvent], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 11 — mỗi `policy_saved` một cảnh báo. Nguồn chưa có nơi ghi (Phase 7): loader vẫn chạy truy vấn thật (KHÔNG
    gọi `is_pending` — `policy_saved` không có trong `PENDING_SOURCES`, chốt 02/10 ở #13) → 0 sự kiện, 0 draft.
    subject = `detail.version` (Q-M9-B1-5); thiếu → `event:<event_id>`; luôn ≤ 64 ký tự — không bao giờ gộp hai lần lưu
    policy thành một cảnh báo."""
    drafts = []
    for e in data:
        if not _recent(e.occurred_at, ctx):
            continue
        version = e.detail.get("version")
        if isinstance(version, str | int) and not isinstance(version, bool) and str(version):
            subject = str(version) if len(str(version)) <= SUBJECT_MAX else _bounded("version", str(version))
        else:
            subject = f"event:{e.event_id}"
        drafts.append(
            AlertDraft(
                rule_id="policy_saved", subject=subject, window_start=e.occurred_at, severity="info",
                detail={"event_id": e.event_id},
            )
        )  # fmt: skip
    return _unique(drafts)


@rule("finalize_failed", "minute", audience=("dev",))
def finalize_failed(data: Sequence[FinalizeFailed], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 15 — mỗi audit B20 `finalize_failed_permanent`. KHÔNG lọc `v_leaf`: ngoại lệ có chủ ý của D-30
    (Q-M9-B1-4). D-30 nói về CHỈ SỐ (đếm ticket); đây là sự cố theo sự kiện — ticket cha kẹt ở B20 có thể biến
    khỏi hàng đợi, lọc lá là bỏ sót."""
    return _unique([
        AlertDraft(
            rule_id="finalize_failed", subject=f.ticket_id, window_start=f.created_at, severity="critical",
            detail={"ticket_id": f.ticket_id, "node": f.node},
        )
        for f in data
        if _recent(f.created_at, ctx)
    ])  # fmt: skip


@rule("execution_failed", "minute", audience=("manager", "ops"))
def execution_failed(data: Sequence[TicketExit], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 16 (Q-M9-3) — mỗi lá E7, MỌI `reason_detail` (`exec_interrupted` của B17, `execution_interrupted` của
    runner/boundary, `exec_failed`…). `window_start` = created_at nhỏ nhất của dòng E7 (không lọc step — hai đường
    ghi khác step); ticket còn dòng E7 trong lookback thì vẫn ra đúng khoá cũ dù dòng đầu đã quá 24 giờ."""
    return _ticket_exit_drafts("execution_failed", data, ctx)
