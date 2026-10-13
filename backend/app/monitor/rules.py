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
import math
import statistics
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypeGuard, get_args
from zoneinfo import ZoneInfo

from app.core.hashing import sha256_key
from app.domain.alerts import (
    BRUTEFORCE_RULE_ID,
    SUBJECT_MAX,
    SYSTEM_SUBJECT,
    AlertDraft,
    bruteforce_alert,
    bruteforce_subject,
)
from app.monitor.window import bucket_start, day_start, hour_start, week_start

if TYPE_CHECKING:  # chỉ lấy KIỂU của luồng A (một nguồn); lúc chạy không nạp module I/O (sqlalchemy) vào luật thuần
    from app.monitor.drift import DriftScore  # numpy — chỉ loader nạp
    from app.monitor.queries.business import WeightedRate

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


# ---- luật tổng hợp chu kỳ ngày, job 02:00 giờ VN (B2 — chốt Q-M9-B2-1 ở #14) ---------------------------------------
#
# Cửa sổ dữ liệu KẾT THÚC ở `d0 = day_start(ctx.now, ctx.tz)` (ngày VN trọn): job chạy 02:00 VN, đo `[d0, now)` thì chỉ
# có 2 giờ đêm → gần như không có lá → chỉ số `None` → luật không bao giờ nổ (bỏ sót). `window_start` = `d0`: chạy lại
# trong cùng ngày ra đúng khoá cũ. Loader (GĐ2) lấy mốc từ CHÍNH các helper dưới đây — một nguồn cho mốc.
# Chỉ số `None` (luật 1: không có lá; luật 12/13: mẫu số 0 dòng audit) → không nổ, không phải lỗi.
# Đánh giá bù (Q-M9-B2-15, chốt #14 comment 5959974287, phương án nhẹ): luật 7, 12, 13 đánh giá `DAILY_MARKS` = 7 mốc
# `r = d0 − k ngày` (k = 0…6), mỗi mốc lấy `[r − 1 ngày, r)`, `window_start = r` → worker chết qua vài mốc 02:00 thì
# ngày bị lỡ vẫn được đánh giá; khoá theo `r` nên chạy lại không trùng. Luật 1 CHỈ `r = d0` (cửa sổ 7 ngày chồng nhau,
# bù sẽ ra nhiều cảnh báo cho cùng một hiện tượng).
# Luật tổng hợp: subject luôn là hằng `SYSTEM_SUBJECT` (không viết chuỗi rỗng trần — test AST ghim).

ESCALATION_THRESHOLD = 0.40  # luật 1: weighted > 0,40 (bằng ngưỡng → không báo)
ESCALATION_DAYS = 7  # luật 1: 7 ngày VN trọn
DEGRADED_THRESHOLD = 0.30  # luật 12, 13: > 0,30 (bằng ngưỡng → không báo)
DAILY_MARKS = 7  # Q-M9-B2-15: luật 7, 12, 13 đánh giá 7 mốc ngày gần nhất (kể cả d0)


def days_before(d0: datetime, k: int, tz: ZoneInfo) -> datetime:
    """00:00 theo `tz` của ngày lịch thứ `k` trước ngày chứa `d0`, kiểu UTC. Trừ `k` ngày trên giờ ĐỊA PHƯƠNG rồi chuẩn
    hoá bằng `day_start` — KHÔNG trừ `24 h × k` trên UTC (ngày đổi giờ dài 23 giờ → rơi sang ngày trước nữa)."""
    return day_start(d0.astimezone(tz) - timedelta(days=k), tz)


def day_window(r: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """`[r − 1 ngày lịch, r)` — ngày `tz` trọn kết thúc ở mốc `r` (ngày đổi giờ dài 23/25 giờ vẫn đúng)."""
    return days_before(r, 1, tz), r


def daily_marks(ctx: RuleContext) -> list[datetime]:
    """Các mốc luật 7, 12, 13 đánh giá ở lượt này, CŨ → MỚI: `r = days_before(d0, k)`, k = 6…0; phần tử cuối = `d0`."""
    d0 = day_start(ctx.now, ctx.tz)
    return [days_before(d0, k, ctx.tz) for k in range(DAILY_MARKS - 1, -1, -1)]


def daily_since(ctx: RuleContext) -> datetime:
    """Mốc dưới loader 7 (GĐ2) đọc: đầu cửa sổ của mốc cũ nhất = `days_before(d0, 7)`."""
    return days_before(day_start(ctx.now, ctx.tz), DAILY_MARKS, ctx.tz)


def prev_day_window(ctx: RuleContext) -> tuple[datetime, datetime]:
    """`[d0 − 1 ngày, d0)` — trọn ngày VN hôm trước (cửa sổ của mốc `d0`)."""
    return day_window(day_start(ctx.now, ctx.tz), ctx.tz)


def rolling_7d_window(ctx: RuleContext) -> tuple[datetime, datetime]:
    """Luật 1: `[d0 − 7 ngày, d0)` — 7 ngày VN trọn."""
    d0 = day_start(ctx.now, ctx.tz)
    return days_before(d0, ESCALATION_DAYS, ctx.tz), d0


@rule("escalation_rate_high", "daily", audience=("manager",))
def escalation_rate_high(data: "WeightedRate | None", ctx: RuleContext) -> list[AlertDraft]:
    """Luật 1 — escalation rate CÓ TRỌNG SỐ (nhóm N3 70/20/10) của 7 ngày VN trọn > 0,40 → Trưởng BP. Đọc `weighted`,
    không đọc `raw`: tỉ lệ thô bị nhóm đông (routine) chi phối, che tỉ lệ escalate cao của nhóm nhạy cảm.
    `data` = `escalation_rate_weighted(conn, *rolling_7d_window(ctx))` (A1, loader GĐ2). 0 lá → `weighted` None."""
    if data is None or data.weighted is None:
        return []  # không có lá trong cửa sổ: không đo được, không phải lỗi
    weighted = data.weighted
    if weighted > ESCALATION_THRESHOLD:
        _, d0 = rolling_7d_window(ctx)
        return [
            AlertDraft(
                rule_id="escalation_rate_high", subject=SYSTEM_SUBJECT, window_start=d0, severity="warning",
                value=weighted, detail={
                    "weighted": weighted, "raw": data.raw, "threshold": ESCALATION_THRESHOLD, "days": ESCALATION_DAYS,
                },
            )
        ]  # fmt: skip
    return []


def _degraded(rule_id: str, data: Mapping[datetime, float | None], ctx: RuleContext) -> list[AlertDraft]:
    marks = daily_marks(ctx)
    if set(data) != set(marks):  # Q-M9-B2-20: loader dựng dict từ chính daily_marks → lệch là bug, không im lặng
        raise ValueError(f"luật {rule_id}: mốc dữ liệu lệch daily_marks")  # không in giá trị
    drafts: list[AlertDraft] = []
    for r in marks:
        rate = data[r]
        if rate is None:
            continue  # mẫu số 0 dòng audit trong ngày (vd không có lá): không đo được, không phải lỗi
        if rate > DEGRADED_THRESHOLD:
            drafts.append(
                AlertDraft(
                    rule_id=rule_id, subject=SYSTEM_SUBJECT, window_start=r, severity="warning", value=rate,
                    detail={"rate": rate, "threshold": DEGRADED_THRESHOLD},
                )
            )  # fmt: skip
    return drafts


@rule("b2_degraded", "daily", audience=("dev",))
def b2_degraded(data: Mapping[datetime, float | None], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 12 — tỉ lệ DÒNG audit step B2 do tầng LLM quyết của một ngày VN > 0,30, đúng cách `b2_llm_rate` (A2) đếm:
    `count(*)` dòng B2 có `layer_decided = 'llm'` hoặc event `guard_unavailable` / dòng B2 có `layer_decided` hoặc
    `guard_unavailable`, của lá tạo trong ngày — đếm dòng, không đếm lá phân biệt (một lá nhiều lượt B2 tính nhiều
    lần). Theo dòng audit: chốt Q-M9-B2-27 (PR #31, một nguồn với A2). `data` = `{r: b2_llm_rate(conn,
    *day_window(r, ctx.tz)) for r in daily_marks(ctx)}` (A2) — mỗi mốc vượt một draft, `window_start = r`
    (Q-M9-B2-15). Tập mốc lệch `daily_marks(ctx)` → `ValueError` (Q-M9-B2-20). Loader GĐ2 trả `Pending` tới Phase 5
    (`is_pending("b2_classifier")`, Q-M9-A2-8): Phase 3–4 chưa có injection-clf nên số ≈ 1,0 — báo mỗi ngày một điều
    đã biết."""
    return _degraded("b2_degraded", data, ctx)


@rule("b3_degraded", "daily", audience=("dev",))
def b3_degraded(data: Mapping[datetime, float | None], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 13 (D-32) — tỉ lệ DÒNG audit điểm log 1 (step B3, B4) do tầng LLM quyết của một ngày VN > 0,30, đúng cách
    `b3_llm_rate` (A2) đếm: `count(*)` dòng có `detail.layer = 'llm'` / dòng có `detail.layer` khác NULL, của lá tạo
    trong ngày — đếm dòng, không đếm lá phân biệt. Theo dòng audit: chốt Q-M9-B2-27 (PR #31, một nguồn với A2). `data`
    như luật 12 với `b3_llm_rate`. Loader GĐ2 trả `Pending` tới Phase 5 (`is_pending("b3_cascade")`, Q-M9-9)."""
    return _degraded("b3_degraded", data, ctx)


# ---- luật 7 `reflex_approval` (kế hoạch chung mục 6 luật 7; chốt Q-M9-B2-3, 6, 15 ở #14; Q-M9-B2-21 chốt PR #31) -----

REFLEX_MIN = 3  # ≥ 3 phiếu "< 5 giây" của một người trong một ngày
REFLEX_SECONDS = 5.0  # view_duration < 5 (đúng 5,0 → không tính)
HUMAN_DECISIONS = ("approved", "rejected")  # bỏ timeout / late_ignored / pending (approvals.status)
APPROVER_ROLES = ("primary", "backup")  # auth/authz.py `approval_role`

type ReflexKind = Literal["fast", "ambiguous", "normal"]


@dataclass(frozen=True)
class ApprovalDecision:
    """Luật 7 — một quyết định trên phiếu (gốc `approvals`, mỗi phần tử một phiếu) + `detail` dòng audit B16 khớp
    (loader GĐ2: LATERAL cùng ticket_id, `approval_result = status`, `created_at ≥ phiếu.created_at` — Q-M9-B2-6).
    Q-M9-B2-23 (chốt PR #31): dòng B16 phải có `created_at` TRƯỚC (nghiêm ngặt) `COALESCE(decided_at, created_at)` của
    phiếu kế tiếp cùng ticket — phiếu thiếu B16 không mượn dòng của phiếu sau (mượn thì có thể xếp "bình thường" = sót).
    Với chặn trên, lệch đồng hồ (phiếu sau còn pending → mốc là `now()` của DB) chỉ làm mất dòng khớp → mơ hồ (báo thừa).
    Hạn chế đã biết của MỐC DƯỚI Q-M9-B2-6 (nêu trong PR): dòng B16 theo đồng hồ app, `approvals.created_at` là `now()`
    của DB — (1) DB nhanh hơn app → dòng B16 của chính phiếu rơi dưới mốc → mơ hồ (báo thừa); (2) app nhanh hơn DB quá
    khoảng giữa dòng B16 của phiếu trước và lúc tạo phiếu sau → dòng của phiếu TRƯỚC lọt qua mốc dưới của phiếu SAU →
    phiếu sau nối nhầm → CÓ THỂ SÓT. (2) hiện không xảy ra: một lá có tối đa một phiếu (`domain/states.py`).
    Không mang `approval_id`/`ticket_id`: luật không đọc; nối B16 đúng phiếu là việc của SQL."""

    status: str  # approvals.status — luật TỰ lọc HUMAN_DECISIONS (loader cũng lọc)
    decided_by: str | None  # người quyết (dòng B16 không có người quyết)
    decided_at: datetime  # xếp vào mốc (Q-M9-B2-3)
    reminder_2_at: datetime | None
    b16: Mapping[str, Any] | None  # detail dòng B16; None = không có dòng khớp


def _seconds(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _reflex_kind(d: ApprovalDecision) -> ReflexKind:
    """Thứ tự cố định: chắc chắn "< 5 giây" (fast) xét TRƯỚC mơ hồ — đã nhắc 2 mà xem < 5 giây thì dưới 5 giây dù ai xem,
    không cộng vào `ambiguous_views`. Không ép kiểu (lỗi ép kiểu in giá trị vào traceback)."""
    if d.b16 is None:
        return "ambiguous"  # Q-M9-B2-6: không có dòng B16 → mơ hồ (báo thừa)
    without, view, role = d.b16.get("decided_without_view"), d.b16.get("view_duration"), d.b16.get("decided_as")
    if without is True:
        return "fast"  # không xem (kế hoạch chung mục 6)
    if _seconds(view):
        if not math.isfinite(view):
            return "ambiguous"  # NaN/±inf: sai kiểu → mơ hồ; không kiểm thì `nan < 5` là False → sót
        if view < REFLEX_SECONDS:
            return "fast"  # âm hữu hạn (lệch đồng hồ giữa route xem và route duyệt) vẫn tính: báo thừa
    if not isinstance(without, bool) or not _seconds(view) or role not in APPROVER_ROLES:
        return "ambiguous"  # Q-M9-B2-6: trường sai kiểu / tự mâu thuẫn → mơ hồ (báo thừa)
    if role == "primary" and d.reminder_2_at is not None:
        return "ambiguous"  # first_viewed_at là cột chung: lần xem có thể là của dự phòng (Việc treo 28 Phase 4)
    return "normal"


def _approver_subject(user_id: str | None) -> str:
    """user_id khi 1…64 ký tự; NULL/rỗng → `user:` (gộp chung, Q-M9-B2-21); dài hơn → băm (`_bounded`)."""
    return user_id if user_id and len(user_id) <= SUBJECT_MAX else _bounded("user", user_id or "")


@rule("reflex_approval", "daily", audience=("manager",))
def reflex_approval(data: Sequence[ApprovalDecision], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 7 — một người quyết có ≥ 3 phiếu "xem < 5 giây" trong một ngày VN → Trưởng BP. Nguồn chính là audit B16,
    KHÔNG dùng `approvals.first_viewed_at` (cột chung chính/dự phòng). Chỉ quyết định của người (`approved`/`rejected`);
    lọc theo cột `approval_result` ở loader, không theo `event` — ca `action_plan_changed_since_approval` (4d dừng 2)
    vẫn là một quyết định duyệt.

    Một phiếu bị tính khi: không xem (`decided_without_view`), `view_duration < 5`, hoặc MƠ HỒ — người chính quyết sau
    nhắc 2 (lần xem có thể của dự phòng), không có dòng B16, trường sai kiểu hay không hữu hạn (Q-M9-B2-6). Ca mơ hồ
    đếm vào `detail.ambiguous_views`.

    Đánh giá 7 mốc ngày (Q-M9-B2-15): mỗi mốc `r` lấy phiếu có `decided_at ∈ [r − 1 ngày, r)` (Q-M9-B2-3),
    `window_start = r` — chạy lại không trùng; worker chết qua vài mốc 02:00 vẫn đánh giá ngày bị lỡ. `data` = phiếu có
    `decided_at ≥ daily_since(ctx)` (loader GĐ2; chặn trên nối B16 theo phiếu kế tiếp — Q-M9-B2-23).

    subject = người quyết (`decided_by`); nhóm theo subject ĐÃ tính (Q-M9-B2-21: NULL và rỗng gộp vào `user:` — tách
    theo phiếu thì không bao giờ đủ 3). Báo thừa có chủ ý: thiếu B16 / sai kiểu → tính; hai phiếu nối tiếp của một
    ticket → hai phiếu; `view_duration` âm → tính. `detail` chỉ có số đếm và ngưỡng."""
    drafts: list[AlertDraft] = []
    for r in daily_marks(ctx):
        lo, hi = day_window(r, ctx.tz)
        per: dict[str, tuple[int, int]] = {}
        for d in data:
            if d.status not in HUMAN_DECISIONS or not lo <= d.decided_at < hi:
                continue
            kind = _reflex_kind(d)
            if kind == "normal":
                continue
            subject = _approver_subject(d.decided_by)
            count, ambiguous = per.get(subject, (0, 0))
            per[subject] = (count + 1, ambiguous + (kind == "ambiguous"))
        for subject, (count, ambiguous) in sorted(per.items()):
            if count >= REFLEX_MIN:
                drafts.append(
                    AlertDraft(
                        rule_id="reflex_approval", subject=subject, window_start=r, severity="warning", value=count,
                        detail={"count": count, "ambiguous_views": ambiguous, "threshold": REFLEX_MIN},
                    )
                )  # fmt: skip
    return drafts


# ---- luật tổng hợp chu kỳ giờ (B2 — kế hoạch chung mục 6 luật 14; Q-M9-6) -------------------------------------------

BUDGET_EPS = 1e-9  # Q-M9-B2-7: 38 × 0,8 = 30.400000000000002 → `30.4 >= 38*0.8` là False (đúng 80% không báo)


@rule("llm_budget", "hourly", audience=("dev", "manager", "ops"))
def llm_budget(data: float | None, ctx: RuleContext) -> list[AlertDraft]:
    """Luật 14 (N1) — TỔNG chi LLM ≥ `warn_ratio × cap_usd` → cả nhóm. `data` = Σ `llm_calls.cost_usd` TOÀN BẢNG
    (loader GĐ2: `COALESCE(sum, 0)`, không cửa sổ, không `v_leaf`) — cùng cách gateway tính trần (`llm/store.py`
    `spend_total`): trần là của cả đồ án. KHÔNG phải chi phí theo ngày, KHÔNG dùng `cost_per_day` (A2, chỉ lá).
    Đánh giá mỗi giờ; `window_start` = đầu ngày `tz` của `ctx.now` (Q-M9-6) → nhắc một lần mỗi ngày. Tổng chỉ tăng
    (cost ≥ 0) nên worker chết qua nhiều ngày không làm mất cảnh báo đầu tiên.

    Đã chốt (#14, comment 5959974287):
    - Q-M9-B2-7: so với `ngưỡng − BUDGET_EPS` (1e-9), không so `≥` trần — số thực làm đúng 80% không báo.
    - Q-M9-B2-16: tổng `None`/NaN/inf/âm → `ValueError` (luật vào `failed_rules`), không trả `[]`: loader `COALESCE`
      nên chỉ lỗi mới ra các giá trị này; trả `[]` là tắt im lặng luật ngân sách (FN).
    - Q-M9-B2-17: một mức; vượt trần trong cùng ngày đã báo 80% là cùng khoá → không ra dòng mới."""
    if data is None or not math.isfinite(data) or data < 0:
        raise ValueError("luật llm_budget: tổng chi không hợp lệ")  # không in giá trị (chỉ tên luật)
    if data >= ctx.warn_ratio * ctx.cap_usd - BUDGET_EPS:
        return [
            AlertDraft(
                rule_id="llm_budget", subject=SYSTEM_SUBJECT, window_start=day_start(ctx.now, ctx.tz),
                severity="critical", value=data,
                detail={"spent_usd": data, "cap_usd": ctx.cap_usd, "warn_ratio": ctx.warn_ratio},
            )
        ]  # fmt: skip
    return []


# ---- luật B2 chu kỳ 60 giây: 4 `e9_spike`, 6 `e6_spike`, 5 `breaker_open` (chốt Q-M9-B2-2, 5, 12 ở #14) -------------
#
# Đăng ký "minute" cùng commit với loader (Q-M9-B2-10): luật minute thiếu loader → `MissingLoaderError` → job phút ra
# `luật_lỗi` mỗi phút. Người nhận theo kế hoạch chung mục 6: 4 → dev, 5 → ops, 6 → manager. Luật 5: loader trả `Pending`
# tới khi `tool_spans` ready (`is_pending`, Q-M9-4) → `skipped_rules`, không báo.

SPIKE_RECHECK_HOURS = 24  # Q-M9-B2-2: mỗi lượt đánh giá lại 24 giờ trước + giờ hiện tại
SPIKE_FACTOR = 3  # luật 4, 6: count > 3 × trung vị
SPIKE_MINIMUM = 3  # luật 4, 6: tối thiểu 3 ca
HOUR = timedelta(hours=1)
BREAKER_GAP = timedelta(seconds=60)  # luật 5 (Q-M9-4): "đợt" = chuỗi span cách nhau < 60 s


def spike_hours(ctx: RuleContext) -> list[datetime]:
    """Các giờ luật 4/6 đánh giá ở lượt này, cũ → mới: `hour_start(now) − 24 giờ … hour_start(now)` (25 giờ)."""
    current = hour_start(ctx.now)
    return [current - k * HOUR for k in range(SPIKE_RECHECK_HOURS, -1, -1)]


def spike_since(ctx: RuleContext) -> datetime:
    """Mốc dưới loader 4/6 (GĐ2) đọc: 168 giờ trước giờ cũ nhất được đánh giá — đủ trung vị cho mọi giờ."""
    return spike_hours(ctx)[0] - HOURS_7D * HOUR


def _spike_drafts(rule_id: str, data: Sequence[TicketExit], ctx: RuleContext) -> list[AlertDraft]:
    per_hour = Counter(hour_start(t.first_at) for t in data)
    drafts: list[AlertDraft] = []
    for h in spike_hours(ctx):
        count = per_hour[h]
        median = hourly_median([per_hour[h - k * HOUR] for k in range(1, HOURS_7D + 1)])  # [h − 168 giờ, h)
        if spike(count, median, SPIKE_FACTOR, SPIKE_MINIMUM):
            drafts.append(
                AlertDraft(
                    rule_id=rule_id, subject=SYSTEM_SUBJECT, window_start=h, severity="warning", value=count,
                    detail={"count": count, "median": median, "factor": SPIKE_FACTOR, "minimum": SPIKE_MINIMUM},
                )
            )  # fmt: skip
    return drafts


@rule("e9_spike", "minute", audience=("dev",))
def e9_spike(data: Sequence[TicketExit], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 4 — số lá E9 trong một giờ > 3 × trung vị theo giờ của 168 giờ TRƯỚC giờ đó (giờ trống = 0) VÀ ≥ 3 ca →
    dev. Đúng bằng ngưỡng → không báo (kế hoạch chung mục 6).

    Mốc của lá = `first_at` (MIN `created_at` các dòng E9 của lá, `_ticket_exits` qua `V_LEAF`), không phải
    `tickets.created_at`, không gọi `e9_count` của A2 (Q-M9-B2-5). Chạy mỗi phút, đánh giá lại 24 giờ trước + giờ hiện
    tại (Q-M9-B2-2): worker chết qua mốc giờ vẫn bắt được; `window_start` = đầu giờ được đánh giá (không phải
    `ctx.now`) → chạy lại không trùng. Với một giờ cố định, cửa sổ trung vị cố định và số ca chỉ tăng → không dao động.
    Giờ sau giờ hiện tại (lệch đồng hồ) chưa đánh giá; tới giờ đó thì được đánh giá, không mất.

    Hạn chế đã biết (Q-M9-B2-2, không xử lý ở B2): đợt tăng vắt qua mốc giờ có thể không vượt ngưỡng ở cả hai giờ."""
    return _spike_drafts("e9_spike", data, ctx)


@rule("e6_spike", "minute", audience=("manager",))
def e6_spike(data: Sequence[TicketExit], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 6 — như luật 4 với lá E6 → Trưởng BP. E6 ghi lúc HẾT HẠN chờ duyệt (sau `tickets.created_at` cả giờ
    SLA): đếm theo giờ ra mã, đếm theo giờ tạo ticket thì giờ đã đánh giá không bao giờ thấy ca đến muộn (Q-M9-B2-5).
    Cùng hạn chế đã biết của luật 4."""
    return _spike_drafts("e6_spike", data, ctx)


@dataclass(frozen=True)
class ToolSpan:
    """Luật 5 — một span tool `circuit_open`. Hợp đồng dự kiến (Q-M9-4): `spans.span_type='tool'`, `status='error'`,
    `attributes.error='circuit_open'`. `tools/registry.py::_span` hiện chỉ ghi log → loader GĐ2 trả `Pending` theo
    `is_pending("tool_spans")`; hàm luật không biết gì về pending (loader trả `Pending` → evaluator không gọi luật)."""

    name: str  # spans.name (≤ 128 ký tự)
    started_at: datetime


@rule("breaker_open", "minute", audience=("ops",))
def breaker_open(data: Sequence[ToolSpan], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 5 — mỗi ĐỢT `circuit_open` của một tool một cảnh báo → vận hành. Đợt = chuỗi span cùng tên mà hai span
    LIỀN NHAU cách nhau < 60 s (đúng 60 s là đợt mới). `window_start` = `started_at` của span đầu đợt (lấy từ DB).

    subject = `spans.name` (Q-M9-B2-12); dài hơn 64 ký tự hoặc rỗng → `_bounded("tool", …)` (rỗng thì thành `tool:`,
    không trùng `SYSTEM_SUBJECT`). Báo khi span CUỐI của đợt còn trong lookback 24 giờ; không chặn trên theo `now`
    (Q-M9-B1-12). Loader đọc từ `now − 24 giờ` nên đợt vắt qua mốc lookback có thể ra khoá mới — báo thừa một lần,
    đã chấp nhận (Q-M9-B2-12). Breaker khoá theo hệ thống đích: nhiều tool cùng hệ thống → mỗi tool một cảnh báo
    (báo thừa, không bỏ sót)."""
    by_tool: dict[str, list[datetime]] = {}
    for s in data:
        by_tool.setdefault(s.name, []).append(s.started_at)
    drafts: list[AlertDraft] = []
    for name, times in by_tool.items():
        times.sort()
        bursts: list[list[datetime]] = []
        for t in times:
            if bursts and t - bursts[-1][-1] < BREAKER_GAP:
                bursts[-1].append(t)
            else:
                bursts.append([t])
        subject = name if 0 < len(name) <= SUBJECT_MAX else _bounded("tool", name)
        for burst in bursts:
            if _recent(burst[-1], ctx):
                drafts.append(
                    AlertDraft(
                        rule_id="breaker_open", subject=subject, window_start=burst[0], severity="warning",
                        value=len(burst), detail={"count": len(burst)},
                    )
                )  # fmt: skip
    return _unique(drafts)


# ---- luật 8 `drift`, chu kỳ tuần (B3 — chốt Q-M9-B3-1…11 ở #15, comment 12/10) -----------------------------------------
#
# Tuần đo của mốc `m` = `[m − 7 ngày, m)`, tuần mốc = `[m − 14 ngày, m − 7 ngày)` (Q-M9-B3-1 (a)); `W = week_start(now)`.
# Job chạy 02:00 thứ Hai VN (cụm 4) — đo `[W, now)` thì chỉ có 2 giờ (cùng lý do Q-M9-B2-1). Đánh giá 2 mốc `W − 7 ngày`
# và `W` (Q-M9-B3-7): lượt tuần bị lỡ vẫn được đánh giá, trễ một tuần; khoá theo mốc nên chạy lại không trùng. Phần "tuần
# đo" của hai mốc không chồng nhau → không báo trùng một hiện tượng. Trừ ngày LỊCH theo `tz` (`days_before`), không trừ
# 168 giờ trên UTC. Loader tính PSI (`drift.score`, `drift.score_rate`); luật chỉ so ngưỡng (Q-M9-B3-8).

DRIFT_THRESHOLD = 0.2  # luật 8: PSI > 0,2 (bằng ngưỡng → không báo)
WEEKLY_MARKS = 2  # Q-M9-B3-7: mốc W − 1 tuần và W
WEEK_DAYS = 7
# Q-M9-B3-2: 6 phân bố — tên là `subject` của cảnh báo (một nguồn cho luật, loader và dashboard).
DRIFT_DISTRIBUTIONS: tuple[str, ...] = ("intent", "confidence", "top_score", "e3_rate", "escalation", "override")


def week_window(m: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Tuần ĐO của mốc `m`: `[m − 7 ngày lịch, m)` (tuần VN trọn kết thúc ở `m`)."""
    return days_before(m, WEEK_DAYS, tz), m


def baseline_window(m: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Tuần MỐC của mốc `m`: `[m − 14 ngày lịch, m − 7 ngày lịch)` — tuần liền trước tuần đo (Q-M9-B3-1 (a))."""
    return days_before(m, 2 * WEEK_DAYS, tz), days_before(m, WEEK_DAYS, tz)


def weekly_marks(ctx: RuleContext) -> list[datetime]:
    """Các mốc luật 8 đánh giá ở lượt này, CŨ → MỚI: `W − 7 ngày lịch`, `W` với `W = week_start(ctx.now, ctx.tz)`."""
    w = week_start(ctx.now, ctx.tz)
    return [days_before(w, WEEK_DAYS * k, ctx.tz) for k in range(WEEKLY_MARKS - 1, -1, -1)]


@dataclass(frozen=True)
class DriftWeek:
    """Luật 8 — kết quả của MỘT mốc: PSI từng phân bố (`None` = một phía 0 mẫu, không đo được) + phân bố bỏ qua vì nguồn
    pending (Q-M9-B3-3: chỉ bỏ phân bố đó, không bỏ cả luật). `scores` và `skipped` rời nhau, hợp lại đúng
    `DRIFT_DISTRIBUTIONS` — luật kiểm, lệch là bug của loader (lặng lẽ thiếu một phân bố = bỏ sót)."""

    scores: Mapping[str, "DriftScore | None"]
    skipped: tuple[str, ...]


@rule("drift", "weekly", audience=("manager",))
def drift(data: Mapping[datetime, DriftWeek], ctx: RuleContext) -> list[AlertDraft]:
    """Luật 8 — PSI của một phân bố giữa tuần mốc và tuần đo > 0,2 → Trưởng BP. Mỗi (mốc, phân bố) vượt một draft:
    subject = tên phân bố, `window_start` = mốc `m` (không phải `ctx.now`). Bằng đúng 0,2 → không báo.

    `data` = `{m: DriftWeek}` cho `m ∈ weekly_marks(ctx)` (loader `rules_data.load_drift`); tập mốc lệch → `ValueError`.
    Phân bố: `intent` (lá tạo trong tuần), `confidence` (dòng audit B3/B4), `top_score` (dòng audit B8), `e3_rate`,
    `escalation` (`escalation_rate_weighted(...).raw` của A1, số mẫu = số lá đã kết thúc), `override` (lá đã kết thúc có
    dòng ghi đè) — mọi đếm ticket qua `v_leaf`.

    Hạn chế đã biết:
    - Chỉ bắt lệch TUẦN-SO-TUẦN, không bắt lệch chậm và đều qua nhiều tuần (Q-M9-B3-1 (a): tuần mốc cuốn chiếu).
    - Q-M9-B3-6 (A): không đặt cỡ mẫu tối thiểu, chỉ bỏ khi một phía 0 mẫu; `detail` ghi số mẫu hai phía. Mô phỏng (hai
      tuần cùng một phân bố, không lệch thật, 2000 lần): tỉ lệ PSI > 0,2 chỉ do ngẫu nhiên với 10 bin là 98% / 86% / 38% /
      2% khi mỗi tuần 30 / 50 / 100 / 200 mẫu; với 2 bin là 7% khi 30, 2% khi 50 — ít dữ liệu thì báo nhầm nhiều.
    - Số mẫu của `escalation` đếm bằng câu SQL riêng, job đọc READ COMMITTED → có thể lệch mẫu số của A vài lá (lá kết
      thúc giữa hai câu); PSI vẫn tính trên đúng tỉ lệ của A."""
    marks = weekly_marks(ctx)
    if set(data) != set(marks):
        raise ValueError("luật drift: mốc dữ liệu lệch weekly_marks")  # không in giá trị
    drafts: list[AlertDraft] = []
    for m in marks:
        week = data[m]
        names, skipped = set(week.scores), set(week.skipped)
        if names & skipped or names | skipped != set(DRIFT_DISTRIBUTIONS):
            raise ValueError("luật drift: phân bố lệch DRIFT_DISTRIBUTIONS")
        for name in DRIFT_DISTRIBUTIONS:
            score = week.scores.get(name)
            if score is None:
                continue  # bỏ qua vì pending, hoặc một phía 0 mẫu: không đo được, không phải lỗi
            if score.psi > DRIFT_THRESHOLD:
                drafts.append(
                    AlertDraft(
                        rule_id="drift", subject=name, window_start=m, severity="warning", value=score.psi,
                        detail={
                            "psi": score.psi, "threshold": DRIFT_THRESHOLD, "n_expected": score.n_expected,
                            "n_actual": score.n_actual,
                        },
                    )
                )  # fmt: skip
    return drafts
