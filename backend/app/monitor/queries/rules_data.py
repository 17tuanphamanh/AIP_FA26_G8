"""Loader dữ liệu cho luật cảnh báo M9 (B1: 7 luật theo sự kiện; B2: luật 60 s 4, 5, 6 — file chia việc mục 6, kế hoạch
chung 4.4, 6).

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
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.alerts import BRUTEFORCE_RULE_ID
from app.domain.exit_codes import ExitCode
from app.monitor.evaluator import Pending, loader
from app.monitor.metrics import is_pending
from app.monitor.rules import (
    BURST_WINDOW,
    LOOKBACK,
    RECONCILE_TOLERANCE,
    BruteforceData,
    ExistingAlert,
    FinalizeFailed,
    RuleContext,
    SecurityEvent,
    TicketExit,
    ToolSpan,
    spike_since,
)
from app.monitor.views import V_LEAF

# graph/runner.py `FINALIZE_FAILED` — monitor không import graph; test đối chiếu hai hằng.
FINALIZE_FAILED_STEP = "B20"
FINALIZE_FAILED_EVENT = "finalize_failed_permanent"
# tools/registry.py `CIRCUIT_OPEN` — monitor không import tools; test đối chiếu hai hằng.
BREAKER_ERROR = "circuit_open"

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
