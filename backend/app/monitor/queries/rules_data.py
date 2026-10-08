"""Loader dữ liệu cho luật cảnh báo M9 (B1: 7 luật theo sự kiện; B2: luật 60 s 4, 5, 6, luật giờ 14, luật ngày 1, 7, 12,
13 — file chia việc mục 6, kế hoạch chung 4.4, 6).

Mỗi loader đọc qua `conn` của engine `app_monitor` (chỉ SELECT) và trả đúng kiểu dữ liệu mà hàm luật trong `rules.py`
nhận. Chốt áp ở đây (#13, PR #20):
- Lookback 24 giờ tính từ `ctx.now` (Clock của app) — không đọc đồng hồ ở đây. KHÔNG có chặn trên theo `now`
  (Q-M9-B1-12): sự kiện có thời điểm sau `now` (lệch đồng hồ giữa tiến trình) vẫn được đọc; `window_start` lấy từ DB nên
  khoá ổn định qua các lần chạy. Lọc thì cảnh báo an ninh chậm đúng bằng độ lệch (lệch xa thì mất hẳn).
- Luật 2/16: ticket chọn theo dòng E0/E7 trong lookback, nhưng `first_at` = MIN trên MỌI dòng E0/E7 của ticket — cắt
  24 giờ thì dòng đầu trôi ra ngoài làm khoá đổi → cảnh báo trùng. Đếm ticket qua `V_LEAF` (D-30).
- Luật 15 KHÔNG lọc `V_LEAF` (Q-M9-B1-4): ticket cha kẹt ở B20 cũng phải báo.
- Luật 3 đọc `alerts` lùi thêm `RECONCILE_TOLERANCE` (cảnh báo của auth có `window_start ≤ occurred_at`, sát mốc 24 giờ
  vẫn phải thấy); lọc `rule_id` ở SQL VÀ luật tự kiểm — `ExistingAlert.rule_id` lấy từ cột của dòng (Q-M9-B1-11, 13).
- Luật 10 đọc lùi thêm `BURST_WINDOW` để cửa sổ trượt ở mốc 24 giờ đủ lịch sử.
- Luật 11 chạy truy vấn thật, KHÔNG gọi `is_pending` (`policy_saved` không có trong `PENDING_SOURCES` → KeyError).
  Chưa có nơi ghi (Phase 7) → 0 sự kiện, 0 draft.
- Không đọc 4 cột `audit_logs` chưa từng được ghi (`confidence`, `query`, `success`, `action_plan_hash_matched`).
- Không ép kiểu dữ liệu đọc ra (lỗi ép kiểu in nguyên giá trị vào traceback); `->>` trả text, không CAST trên JSON.
  Tham số bind chỉ là mốc thời gian và hằng code — lỗi SQL in tham số cũng không lộ dữ liệu.
- Luật 4/6 (B2, chốt #14 comment 5959974287): dùng lại `_ticket_exits` (`first_at` = thời điểm RA MÃ, qua `V_LEAF`;
  Q-M9-B2-5), mốc dưới `spike_since(ctx)` của `rules.py` (168 giờ trước giờ cũ nhất được đánh giá — một nguồn cho mốc).
  Không gộp hai lần đọc E9/E6: mỗi luật một loader, một savepoint — lỗi của luật này không kéo luật kia.
- Luật 5: `is_pending("tool_spans")` → `Pending`, KHÔNG chạy SQL (span tool chưa ghi DB, Q-M9-4). Khi nguồn ready: đọc
  `spans` theo hợp đồng dự kiến của Q-M9-4 từ `now − 24 giờ` (Q-M9-B2-12). Không lọc `V_LEAF` (Q-M9-B2-22, đề xuất):
  breaker mở là sự cố của hệ thống đích, không phải chỉ số đếm ticket — như luật 15.
- Luật 14 (job giờ; Q-M9-6, Q-M9-B2-7/16/17): Σ `llm_calls.cost_usd` TOÀN BẢNG, `COALESCE(…, 0)`, không cửa sổ, không
  `V_LEAF`, không tham số bind — cùng cách gateway tính trần (`llm/store.py` `spend_total`; monitor không import `llm`).
  `cost_usd` là `double precision` → psycopg trả `float`, không chuyển kiểu.
- Luật 1: gọi `escalation_rate_weighted(conn, *rolling_7d_window(ctx))` của A1, trả nguyên `WeightedRate` — không tự
  tính lại (một nguồn sự thật). Chỉ mốc `d0` (Q-M9-B2-15).
- Luật 12/13: `is_pending("b2_classifier")` / `is_pending("b3_cascade")` → `Pending`, KHÔNG gọi hàm A (Q-M9-B2-1,
  Q-M9-9). Khi ready: `{r: rate(conn, *day_window(r, tz)) for r in daily_marks(ctx)}` — dict dựng từ chính
  `daily_marks` (Q-M9-B2-15, 20). [Đề xuất] Q-M9-B2-25: lý do Pending của luật 12 `injection_clf_not_enabled` là tên tự
  đặt (luật 13 `cascade_not_enabled` theo Q-M9-9).
- Luật 7 (Q-M9-B2-3, 6, 15): gốc `approvals`, `status ∈ HUMAN_DECISIONS`, `decided_at ≥ daily_since(ctx)`; LATERAL lấy
  dòng B16 đầu tiên cùng `ticket_id`, cột `approval_result = status` (không theo `event` — ca
  `action_plan_changed_since_approval` vẫn khớp), `created_at ≥ phiếu.created_at`. Không có dòng → `b16 = None`;
  `detail` không phải object → `{}`.
  [Đề xuất] Q-M9-B2-23: thêm chặn trên — dòng B16 phải có `created_at` TRƯỚC `COALESCE(decided_at, created_at)` của
  phiếu kế tiếp cùng ticket (so nghiêm ngặt: `decided_at` và `created_at` dòng B16 cùng lấy `clock.now()`, có thể bằng
  nhau). Không có chặn này thì phiếu thiếu B16 mượn dòng của phiếu sau → có thể xếp "bình thường" (sót); có chặn thì ca
  đó thành mơ hồ (báo thừa). Với CHẶN TRÊN, lệch đồng hồ (phiếu sau còn pending → `next_start` là `now()` của DB) chỉ
  làm mất dòng khớp → mơ hồ, tức báo thừa.
  Hạn chế đã biết của MỐC DƯỚI Q-M9-B2-6 (nêu trong PR): `a.created_at` theo đồng hồ app, `approvals.created_at` là
  `now()` của DB — lệch có hai hướng: (1) DB nhanh hơn app → dòng B16 của chính phiếu rơi dưới mốc → mơ hồ (báo thừa);
  (2) app nhanh hơn DB quá khoảng giữa dòng B16 của phiếu trước và lúc tạo phiếu sau → dòng B16 của phiếu TRƯỚC lọt qua
  mốc dưới của phiếu SAU → phiếu sau nối nhầm → CÓ THỂ SÓT. Hướng (2) hiện không xảy ra: một lá có tối đa một phiếu
  (`domain/states.py`: không đường nào quay lại `S_PENDING_APPROVAL`).
  [Đề xuất] Q-M9-B2-24: KHÔNG lọc `V_LEAF` — D-30 áp cho luật đếm ticket, luật 7 đếm PHIẾU theo người quyết; ticket cha
  không có phiếu (states.py), sau này có thì lọc là sót. `is_pending("approval_view")` (nguồn từng pending tới 4c, file
  chia việc mục 3); [Đề xuất] Q-M9-B2-25: lý do `approval_view_not_recorded` là tên tự đặt.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.alerts import BRUTEFORCE_RULE_ID
from app.domain.exit_codes import ExitCode
from app.monitor.evaluator import Pending, loader
from app.monitor.metrics import is_pending
from app.monitor.queries.ai import b2_llm_rate, b3_llm_rate
from app.monitor.queries.business import WeightedRate, escalation_rate_weighted
from app.monitor.rules import (
    BURST_WINDOW,
    HUMAN_DECISIONS,
    LOOKBACK,
    RECONCILE_TOLERANCE,
    ApprovalDecision,
    BruteforceData,
    ExistingAlert,
    FinalizeFailed,
    RuleContext,
    SecurityEvent,
    TicketExit,
    ToolSpan,
    daily_marks,
    daily_since,
    day_window,
    rolling_7d_window,
    spike_since,
)
from app.monitor.views import V_LEAF

# graph/runner.py `FINALIZE_FAILED` — monitor không import graph; test đối chiếu hai hằng.
FINALIZE_FAILED_STEP = "B20"
FINALIZE_FAILED_EVENT = "finalize_failed_permanent"
# tools/registry.py `CIRCUIT_OPEN` — monitor không import tools; test đối chiếu hai hằng.
BREAKER_ERROR = "circuit_open"
# graph/late_event.py `WAITS["approval_wait"]` — bước ghi điểm log 6; monitor không import graph; test đối chiếu.
APPROVAL_STEP = "B16"

type DayRate = Callable[[AsyncConnection, datetime, datetime], Awaitable[float | None]]

TICKET_EXIT_SQL = text(f"""
SELECT DISTINCT ON (a.ticket_id)
       a.ticket_id, a.created_at AS first_at, a.step,
       COALESCE(a.detail->>'escalation_reason_detail', a.block_reason) AS reason_detail,
       max(a.created_at) OVER (PARTITION BY a.ticket_id) AS last_at
FROM audit_logs a
JOIN {V_LEAF} l ON l.ticket_id = a.ticket_id
WHERE a.exit_code = :code
  AND a.ticket_id IN (SELECT r.ticket_id FROM audit_logs r WHERE r.exit_code = :code AND r.created_at >= :since)
ORDER BY a.ticket_id, a.created_at, a.log_id
""")

FINALIZE_FAILED_SQL = text("""
SELECT a.ticket_id, a.created_at, a.detail->>'node' AS node
FROM audit_logs a
WHERE a.step = :step AND a.event = :event AND a.created_at >= :since
ORDER BY a.created_at, a.log_id
""")

EVENTS_SQL = text("""
SELECT event_id, occurred_at, user_id, username_attempted, detail
FROM security_events
WHERE event_type = :event_type AND occurred_at >= :since
ORDER BY occurred_at, event_id
""")

LOCKS_SQL = text("""
SELECT event_id, occurred_at, user_id, username_attempted, detail
FROM security_events
WHERE event_type = :event_type AND detail->>'reason' = :reason AND occurred_at >= :since
ORDER BY occurred_at, event_id
""")

ALERTS_SQL = text("""
SELECT rule_id, subject, window_start
FROM alerts
WHERE rule_id = :rule_id AND window_start >= :since
ORDER BY window_start, alert_id
""")

TOOL_SPAN_SQL = text("""
SELECT s.name, s.started_at
FROM spans s
WHERE s.span_type = :span_type AND s.status = :status AND s.attributes->>'error' = :error
  AND s.started_at >= :since
ORDER BY s.name, s.started_at, s.span_id
""")

LLM_SPEND_SQL = text("""
SELECT COALESCE(SUM(c.cost_usd), 0) AS spent
FROM llm_calls c
""")

# `next_start` = mốc bắt đầu của phiếu KẾ TIẾP cùng ticket (Q-M9-B2-23): `lead` trên MỌI phiếu của ticket (kể cả
# pending/timeout), nên lớp trong lấy mọi phiếu của các ticket có quyết định từ `since`. Viết `next_start > …` (không `<`).
REFLEX_SQL = text("""
SELECT p.status, p.decided_by, p.decided_at, p.reminder_2_at, b.log_id AS b16_log_id, b.detail AS b16_detail
FROM (
    SELECT q.ticket_id, q.approval_id, q.status, q.decided_by, q.decided_at, q.reminder_2_at, q.created_at,
           lead(COALESCE(q.decided_at, q.created_at))
               OVER (PARTITION BY q.ticket_id ORDER BY q.created_at, q.approval_id) AS next_start
    FROM approvals q
    WHERE q.ticket_id IN (
        SELECT d.ticket_id FROM approvals d WHERE d.status = ANY(:decisions) AND d.decided_at >= :since
    )
) p
LEFT JOIN LATERAL (
    SELECT a.log_id, a.detail
    FROM audit_logs a
    WHERE a.ticket_id = p.ticket_id AND a.step = :step AND a.approval_result = p.status
      AND a.created_at >= p.created_at
      AND (p.next_start IS NULL OR p.next_start > a.created_at)
    ORDER BY a.created_at, a.log_id
    LIMIT 1
) b ON true
WHERE p.status = ANY(:decisions) AND p.decided_at >= :since
ORDER BY p.decided_at, p.approval_id
""")


def _detail(value: object) -> Mapping[str, Any]:
    """`detail` không phải object JSON → coi như rỗng: luật không ném lỗi, cảnh báo của người khác không bị mất."""
    return value if isinstance(value, Mapping) else {}


async def _ticket_exits(conn: AsyncConnection, code: ExitCode, since: datetime) -> list[TicketExit]:
    rows = await conn.execute(TICKET_EXIT_SQL, {"code": code.value, "since": since})
    return [TicketExit(r.ticket_id, r.first_at, r.last_at, r.step, r.reason_detail) for r in rows]


async def _events(conn: AsyncConnection, event_type: str, since: datetime) -> list[SecurityEvent]:
    rows = await conn.execute(EVENTS_SQL, {"event_type": event_type, "since": since})
    return [SecurityEvent(r.event_id, r.occurred_at, r.user_id, r.username_attempted, _detail(r.detail)) for r in rows]


@loader("injection_detected")
async def load_injection_detected(conn: AsyncConnection, ctx: RuleContext) -> list[TicketExit]:
    return await _ticket_exits(conn, ExitCode.E0, ctx.now - LOOKBACK)


@loader("password_bruteforce")
async def load_password_bruteforce(conn: AsyncConnection, ctx: RuleContext) -> BruteforceData:
    since = ctx.now - LOOKBACK
    locks = await conn.execute(LOCKS_SQL, {"event_type": "account_locked", "reason": "threshold", "since": since})
    alerts = await conn.execute(ALERTS_SQL, {"rule_id": BRUTEFORCE_RULE_ID, "since": since - RECONCILE_TOLERANCE})
    return BruteforceData(
        locks=[
            SecurityEvent(r.event_id, r.occurred_at, r.user_id, r.username_attempted, _detail(r.detail)) for r in locks
        ],
        alerts=[ExistingAlert(rule_id=r.rule_id, subject=r.subject, window_start=r.window_start) for r in alerts],
    )


@loader("refresh_reuse")
async def load_refresh_reuse(conn: AsyncConnection, ctx: RuleContext) -> list[SecurityEvent]:
    return await _events(conn, "refresh_reuse_detected", ctx.now - LOOKBACK)


@loader("permission_denied_burst")
async def load_permission_denied_burst(conn: AsyncConnection, ctx: RuleContext) -> list[SecurityEvent]:
    return await _events(conn, "permission_denied", ctx.now - LOOKBACK - BURST_WINDOW)


@loader("policy_saved")
async def load_policy_saved(conn: AsyncConnection, ctx: RuleContext) -> list[SecurityEvent]:
    return await _events(conn, "policy_saved", ctx.now - LOOKBACK)


@loader("finalize_failed")
async def load_finalize_failed(conn: AsyncConnection, ctx: RuleContext) -> list[FinalizeFailed]:
    rows = await conn.execute(
        FINALIZE_FAILED_SQL,
        {"step": FINALIZE_FAILED_STEP, "event": FINALIZE_FAILED_EVENT, "since": ctx.now - LOOKBACK},
    )
    return [FinalizeFailed(r.ticket_id, r.created_at, r.node) for r in rows]


@loader("execution_failed")
async def load_execution_failed(conn: AsyncConnection, ctx: RuleContext) -> list[TicketExit]:
    return await _ticket_exits(conn, ExitCode.E7, ctx.now - LOOKBACK)


@loader("e9_spike")
async def load_e9_spike(conn: AsyncConnection, ctx: RuleContext) -> list[TicketExit]:
    return await _ticket_exits(conn, ExitCode.E9, spike_since(ctx))


@loader("e6_spike")
async def load_e6_spike(conn: AsyncConnection, ctx: RuleContext) -> list[TicketExit]:
    return await _ticket_exits(conn, ExitCode.E6, spike_since(ctx))


@loader("breaker_open")
async def load_breaker_open(conn: AsyncConnection, ctx: RuleContext) -> list[ToolSpan] | Pending:
    if is_pending("tool_spans"):
        return Pending("tool_spans_not_recorded")
    rows = await conn.execute(
        TOOL_SPAN_SQL,
        {"span_type": "tool", "status": "error", "error": BREAKER_ERROR, "since": ctx.now - LOOKBACK},
    )
    return [ToolSpan(r.name, r.started_at) for r in rows]


# ---- B2 luật giờ / ngày: 14 llm_budget; 1 escalation_rate_high, 7 reflex_approval, 12 b2_degraded, 13 b3_degraded ----


@loader("llm_budget")
async def load_llm_budget(conn: AsyncConnection, ctx: RuleContext) -> float:
    return (await conn.execute(LLM_SPEND_SQL)).scalar_one()


@loader("escalation_rate_high")
async def load_escalation_rate_high(conn: AsyncConnection, ctx: RuleContext) -> WeightedRate:
    return await escalation_rate_weighted(conn, *rolling_7d_window(ctx))


@loader("reflex_approval")
async def load_reflex_approval(conn: AsyncConnection, ctx: RuleContext) -> list[ApprovalDecision] | Pending:
    if is_pending("approval_view"):
        return Pending("approval_view_not_recorded")
    rows = await conn.execute(
        REFLEX_SQL, {"since": daily_since(ctx), "step": APPROVAL_STEP, "decisions": list(HUMAN_DECISIONS)}
    )
    return [
        ApprovalDecision(
            status=r.status, decided_by=r.decided_by, decided_at=r.decided_at, reminder_2_at=r.reminder_2_at,
            b16=None if r.b16_log_id is None else _detail(r.b16_detail),
        )
        for r in rows
    ]  # fmt: skip


async def _daily_rates(conn: AsyncConnection, ctx: RuleContext, rate: DayRate) -> dict[datetime, float | None]:
    return {r: await rate(conn, *day_window(r, ctx.tz)) for r in daily_marks(ctx)}


@loader("b2_degraded")
async def load_b2_degraded(conn: AsyncConnection, ctx: RuleContext) -> dict[datetime, float | None] | Pending:
    if is_pending("b2_classifier"):
        return Pending("injection_clf_not_enabled")
    return await _daily_rates(conn, ctx, b2_llm_rate)


@loader("b3_degraded")
async def load_b3_degraded(conn: AsyncConnection, ctx: RuleContext) -> dict[datetime, float | None] | Pending:
    if is_pending("b3_cascade"):
        return Pending("cascade_not_enabled")
    return await _daily_rates(conn, ctx, b3_llm_rate)
