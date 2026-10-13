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
  `spans` theo hợp đồng dự kiến của Q-M9-4 từ `now − 24 giờ` (Q-M9-B2-12). Không lọc `V_LEAF` (Q-M9-B2-22, chốt PR #31):
  breaker mở là sự cố của hệ thống đích, không phải chỉ số đếm ticket — như luật 15.
- Luật 14 (job giờ; Q-M9-6, Q-M9-B2-7/16/17): Σ `llm_calls.cost_usd` TOÀN BẢNG, `COALESCE(…, 0)`, không cửa sổ, không
  `V_LEAF`, không tham số bind — cùng cách gateway tính trần (`llm/store.py` `spend_total`; monitor không import `llm`).
  `cost_usd` là `double precision` → psycopg trả `float`, không chuyển kiểu.
- Luật 1: gọi `escalation_rate_weighted(conn, *rolling_7d_window(ctx))` của A1, trả nguyên `WeightedRate` — không tự
  tính lại (một nguồn sự thật). Chỉ mốc `d0` (Q-M9-B2-15).
- Luật 12/13: `is_pending("b2_classifier")` / `is_pending("b3_cascade")` → `Pending`, KHÔNG gọi hàm A (Q-M9-B2-1,
  Q-M9-9). Khi ready: `{r: rate(conn, *day_window(r, tz)) for r in daily_marks(ctx)}` — dict dựng từ chính
  `daily_marks` (Q-M9-B2-15, 20). Q-M9-B2-25 (chốt PR #31): lý do Pending của luật 12 `injection_clf_not_enabled`
  (luật 13 `cascade_not_enabled` theo Q-M9-9).
- Luật 7 (Q-M9-B2-3, 6, 15): gốc `approvals`, `status ∈ HUMAN_DECISIONS`, `decided_at ≥ daily_since(ctx)`; LATERAL lấy
  dòng B16 đầu tiên cùng `ticket_id`, cột `approval_result = status` (không theo `event` — ca
  `action_plan_changed_since_approval` vẫn khớp), `created_at ≥ phiếu.created_at`. Không có dòng → `b16 = None`;
  `detail` không phải object → `{}`.
  Q-M9-B2-23 (chốt PR #31): thêm chặn trên — dòng B16 phải có `created_at` TRƯỚC `COALESCE(decided_at, created_at)` của
  phiếu kế tiếp cùng ticket (so nghiêm ngặt: `decided_at` và `created_at` dòng B16 cùng lấy `clock.now()`, có thể bằng
  nhau). Không có chặn này thì phiếu thiếu B16 mượn dòng của phiếu sau → có thể xếp "bình thường" (sót); có chặn thì ca
  đó thành mơ hồ (báo thừa). Với CHẶN TRÊN, lệch đồng hồ (phiếu sau còn pending → `next_start` là `now()` của DB) chỉ
  làm mất dòng khớp → mơ hồ, tức báo thừa.
  Hạn chế đã biết của MỐC DƯỚI Q-M9-B2-6 (nêu trong PR): `a.created_at` theo đồng hồ app, `approvals.created_at` là
  `now()` của DB — lệch có hai hướng: (1) DB nhanh hơn app → dòng B16 của chính phiếu rơi dưới mốc → mơ hồ (báo thừa);
  (2) app nhanh hơn DB quá khoảng giữa dòng B16 của phiếu trước và lúc tạo phiếu sau → dòng B16 của phiếu TRƯỚC lọt qua
  mốc dưới của phiếu SAU → phiếu sau nối nhầm → CÓ THỂ SÓT. Hướng (2) hiện không xảy ra: một lá có tối đa một phiếu
  (`domain/states.py`: không đường nào quay lại `S_PENDING_APPROVAL`).
  Q-M9-B2-24 (chốt PR #31): KHÔNG lọc `V_LEAF` — D-30 áp cho luật đếm ticket, luật 7 đếm PHIẾU theo người quyết;
  ticket cha không có phiếu (states.py), sau này có thì lọc là sót. `is_pending("approval_view")` (nguồn từng pending
  tới 4c, file chia việc mục 3); Q-M9-B2-25 (chốt PR #31): lý do `approval_view_not_recorded`.
- Luật 8 `drift` (B3, chốt #15 comment 12/10): `drift_counts(conn, frm, to)` đếm 6 phân bố của MỘT tuần (công khai —
  dashboard dùng lại, Q-M9-B3-4/9); `drift_scores` ra PSI (Q-M9-B3-8); loader đánh giá `weekly_marks(ctx)`. Mọi câu qua
  `V_LEAF` (D-30); mốc bin là hằng code, không đọc `config/` (Q-M9-B3-2). Ba ngoại lệ có chủ ý so với quy ước trên:
  (1) Chặn trên `t.created_at < :to` (Q-M9-B3-15): `to` là mốc tuần ĐÃ KHÉP tính từ `week_start`, không phải `now` —
  Q-M9-B1-12 cấm chặn trên theo `now` ở luật sự kiện; không có tham số `now`.
  (2) Đọc KHOÁ JSON `detail->'confidence'` (điểm log 1), không phải cột `audit_logs.confidence` (cột chưa từng ghi).
  (3) Ép `::numeric` CHỈ trong nhánh `THEN` sau `jsonb_typeof(...) = 'number'` (Q-M9-B3-16): số JSONB luôn ép được sang
  `numeric`, `CASE` không chạy nhánh khi điều kiện sai → không có lỗi ép kiểu in giá trị; chuỗi/bool/`null`/`detail` không
  phải object bị loại. `numeric` (không `float8`): không tràn, 0,3 rơi đúng bin [0,3; 0,4).
  Tham số bind: mốc tuần + hằng code (`intents`, `steps`, `e3`, `step`, `event`). `escalation` gọi
  `escalation_rate_weighted(...).raw` của A1 (không tự đếm lại); số mẫu = số lá đã kết thúc, CÙNG mẫu số (`DRIFT_DONE`,
  `DRIFT_LEAF_WINDOW` bằng chữ với `common.DONE`, `common.LEAF_WINDOW` — test đối chiếu). `is_pending("override_count")`
  (nguồn pending tới 4d) chỉ bỏ phân bố `override`, không bỏ cả luật (Q-M9-B3-3).
"""

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import INTENTS
from app.domain.alerts import BRUTEFORCE_RULE_ID
from app.domain.exit_codes import ExitCode
from app.domain.override import OVERRIDE_EVENT, OVERRIDE_STEP
from app.monitor.drift import DriftScore, score, score_rate
from app.monitor.evaluator import Pending, loader
from app.monitor.metrics import is_pending
from app.monitor.queries.ai import b2_llm_rate, b3_llm_rate
from app.monitor.queries.business import WeightedRate, escalation_rate_weighted
from app.monitor.rules import (
    BURST_WINDOW,
    DRIFT_DISTRIBUTIONS,
    HUMAN_DECISIONS,
    LOOKBACK,
    RECONCILE_TOLERANCE,
    ApprovalDecision,
    BruteforceData,
    DriftWeek,
    ExistingAlert,
    FinalizeFailed,
    RuleContext,
    SecurityEvent,
    TicketExit,
    ToolSpan,
    baseline_window,
    daily_marks,
    daily_since,
    day_window,
    rolling_7d_window,
    spike_since,
    week_window,
    weekly_marks,
)
from app.monitor.views import V_LEAF

log = logging.getLogger(__name__)

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


# ---- B3 luật tuần: 8 drift (chốt Q-M9-B3-1…11 ở #15) -------------------------------------------------------------------
#
# Mốc bin CỐ ĐỊNH trong code (Q-M9-B3-2, tách vai D-43: không đọc `config/`). Hằng render vào SQL lúc import (như `V_LEAF`).

# Cùng chữ với `queries/common.py` `LEAF_WINDOW`, `DONE` (A) — test đối chiếu: e3_rate và số mẫu escalation phải CÙNG mẫu
# số với `escalation_rate_weighted(...).raw`. Không import lúc chạy: `common` ngoài hợp đồng mục 3.
DRIFT_LEAF_WINDOW = "t.created_at >= :frm AND t.created_at < :to"
DRIFT_DONE = "t.final_state IS NOT NULL"
DRIFT_NONE = "none"  # intent NULL (chưa phân loại, ngoài phạm vi)
DRIFT_OTHER = "other"  # intent ngoài INTENTS
DRIFT_INTENT_BINS: tuple[str, ...] = (*INTENTS, DRIFT_NONE, DRIFT_OTHER)
UNIT_LO = 0  # confidence, top_score: UNIT_BINS bin đều trên [UNIT_LO; UNIT_HI], bin cuối đóng (1,0 vào bin 10)
UNIT_HI = 1
UNIT_BINS = 10
CONFIDENCE_STEPS: tuple[str, ...] = ("B3", "B4")  # điểm log 1 (ca E1 ghi ở B4) — như `ai.b3_llm_rate`
TOP_SCORE_STEP = "B8"  # điểm log 3 (`graph/nodes/b08_retrieve.py` `point3`)
TOP_SCORE_BINS = UNIT_BINS + 2  # thêm bin < UNIT_LO (chỉ số 0) và bin > UNIT_HI (chỉ số UNIT_BINS + 1)


def _json_number(key: str) -> tuple[str, str]:
    """(điều kiện, giá trị) của khoá `detail.<key>`: chỉ ép `::numeric` sau khi `jsonb_typeof` xác nhận là số."""
    return f"jsonb_typeof(a.detail->'{key}') = 'number'", f"(a.detail->'{key}')::numeric"


def _unit_bucket(value: str) -> str:
    return f"width_bucket({value}, {UNIT_LO}, {UNIT_HI}, {UNIT_BINS})"


_CONF_IS_NUM, _CONF = _json_number("confidence")
_TOP_IS_NUM, _TOP = _json_number("top_score")
# Q-M9-B3-12 [Đề xuất]: confidence ngoài [0; 1] KẸP vào bin biên (1 hoặc UNIT_BINS) — bỏ thì sót lệch kiểu "model trả 1,5".
_CONF_BIN = (
    f"CASE WHEN {_CONF_IS_NUM} THEN LEAST(GREATEST({_unit_bucket(_CONF)}, 1), {UNIT_BINS}) END"
)
_TOP_BIN = (
    f"CASE WHEN {_TOP_IS_NUM} THEN CASE WHEN {_TOP} < {UNIT_LO} THEN 0 WHEN {_TOP} > {UNIT_HI} THEN {UNIT_BINS + 1} "
    f"ELSE LEAST({_unit_bucket(_TOP)}, {UNIT_BINS}) END END"
)


def _audit_bins_sql(bin_expr: str) -> str:
    """Đếm theo DÒNG audit (Q-M9-B2-27) của lá tạo trong tuần; dòng không phải số (bin NULL) bị loại."""
    return f"""
SELECT s.bin, count(*) AS n
FROM (
    SELECT {bin_expr} AS bin
    FROM audit_logs a
    JOIN {V_LEAF} t ON t.ticket_id = a.ticket_id
    WHERE {DRIFT_LEAF_WINDOW} AND a.step = ANY(:steps)
) s
WHERE s.bin IS NOT NULL
GROUP BY s.bin
"""


# Lá TẠO trong tuần (theo bảng chốt Q-M9-B3-2, không lọc kết thúc — Q-M9-B3-14): lá chưa qua B3 có intent NULL → "none".
DRIFT_INTENT_SQL = text(f"""
SELECT CASE WHEN t.intent IS NULL THEN '{DRIFT_NONE}' WHEN t.intent = ANY(:intents) THEN t.intent
            ELSE '{DRIFT_OTHER}' END AS bin,
       count(*) AS n
FROM {V_LEAF} t
WHERE {DRIFT_LEAF_WINDOW}
GROUP BY 1
""")

DRIFT_CONFIDENCE_SQL = text(_audit_bins_sql(_CONF_BIN))
DRIFT_TOP_SCORE_SQL = text(_audit_bins_sql(_TOP_BIN))

DRIFT_DONE_SQL = text(f"""
SELECT count(*) AS n, count(*) FILTER (WHERE t.exit_code = :e3) AS hit
FROM {V_LEAF} t
WHERE {DRIFT_LEAF_WINDOW} AND {DRIFT_DONE}
""")

DRIFT_OVERRIDE_SQL = text(f"""
SELECT count(*) AS n,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM audit_logs a WHERE a.ticket_id = t.ticket_id AND a.step = :step AND a.event = :event
       )) AS hit
FROM {V_LEAF} t
WHERE {DRIFT_LEAF_WINDOW} AND {DRIFT_DONE}
""")


@dataclass(frozen=True)
class DriftCounts:
    """Số đếm 6 phân bố của MỘT tuần (`drift_counts`). `bins`: tên phân bố → số đếm theo bin, thứ tự cố định (`intent`
    theo `DRIFT_INTENT_BINS`; `confidence` UNIT_BINS bin; `top_score` TOP_SCORE_BINS bin; `e3_rate`, `override` = (có,
    không)). `escalation` không có số đếm: tỉ lệ `escalation_raw` của A1 + `leaves_done` (mẫu số chung). Phân bố có nguồn
    pending nằm trong `pending`, không có trong `bins`."""

    bins: Mapping[str, tuple[int, ...]]
    escalation_raw: float | None
    leaves_done: int
    pending: tuple[str, ...]


def _bin_counts(rows: Sequence[Any], size: int, offset: int) -> tuple[int, ...]:
    """Dòng `(chỉ số bin, số đếm)` → tuple đủ `size` bin (bin không có dòng = 0). Chỉ số ngoài dải → lỗi (SQL lệch mốc
    bin là bug, không gộp im lặng)."""
    counts = [0] * size
    for index, n in rows:
        if not isinstance(index, int) or not 0 <= index - offset < size:
            raise ValueError("drift_counts: chỉ số bin ngoài dải")
        counts[index - offset] += n
    return tuple(counts)


def _intent_counts(rows: Sequence[Any]) -> tuple[int, ...]:
    counts = dict.fromkeys(DRIFT_INTENT_BINS, 0)
    for name, n in rows:
        if name not in counts:
            raise ValueError("drift_counts: bin intent lạ")
        counts[name] += n
    return tuple(counts.values())


async def drift_counts(conn: AsyncConnection, frm: datetime, to: datetime) -> DriftCounts:
    """Đếm 6 phân bố của luật 8 trong cửa sổ `[frm, to)` theo `created_at` của LÁ (`v_leaf`). Công khai: dashboard
    (khối `drift`, Q-M9-B3-4) gọi cùng hàm cho tuần mốc/tuần đo rồi `drift_scores`. `frm`/`to` naive hoặc `frm >= to` →
    `ValueError` trước khi chạm DB. `override` pending (`is_pending("override_count")`) → không chạy câu ghi đè."""
    for ts in (frm, to):
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("drift_counts: cần datetime có múi giờ")
    if frm >= to:
        raise ValueError("drift_counts: cửa sổ rỗng")
    window = {"frm": frm, "to": to}
    intent = (await conn.execute(DRIFT_INTENT_SQL, {**window, "intents": list(INTENTS)})).all()
    confidence = (await conn.execute(DRIFT_CONFIDENCE_SQL, {**window, "steps": list(CONFIDENCE_STEPS)})).all()
    top_score = (await conn.execute(DRIFT_TOP_SCORE_SQL, {**window, "steps": [TOP_SCORE_STEP]})).all()
    done = (await conn.execute(DRIFT_DONE_SQL, {**window, "e3": ExitCode.E3.value})).one()
    bins: dict[str, tuple[int, ...]] = {
        "intent": _intent_counts(intent),
        "confidence": _bin_counts(confidence, UNIT_BINS, 1),
        "top_score": _bin_counts(top_score, TOP_SCORE_BINS, 0),
        "e3_rate": (done.hit, done.n - done.hit),
    }
    pending: tuple[str, ...] = ()
    if is_pending("override_count"):
        pending = ("override",)
    else:
        row = (await conn.execute(DRIFT_OVERRIDE_SQL, {**window, "step": OVERRIDE_STEP, "event": OVERRIDE_EVENT})).one()
        bins["override"] = (row.hit, row.n - row.hit)
    raw = (await escalation_rate_weighted(conn, frm, to)).raw
    return DriftCounts(bins=bins, escalation_raw=raw, leaves_done=done.n, pending=pending)


def drift_scores(expected: DriftCounts, actual: DriftCounts) -> DriftWeek:
    """Tuần mốc (`expected`) so tuần đo (`actual`) → PSI từng phân bố (thuần, không I/O). Phân bố pending ở một trong hai
    phía → `skipped`. `escalation` → `score_rate` trên tỉ lệ của A với số mẫu `leaves_done`; còn lại → `score`."""
    skipped = tuple(name for name in DRIFT_DISTRIBUTIONS if name in expected.pending or name in actual.pending)
    scores: dict[str, DriftScore | None] = {}
    for name in DRIFT_DISTRIBUTIONS:
        if name in skipped:
            continue
        if name == "escalation":
            scores[name] = score_rate(
                expected.escalation_raw, expected.leaves_done, actual.escalation_raw, actual.leaves_done
            )
        else:
            scores[name] = score(expected.bins[name], actual.bins[name])
    return DriftWeek(scores=scores, skipped=skipped)


@loader("drift")
async def load_drift(conn: AsyncConnection, ctx: RuleContext) -> dict[datetime, DriftWeek]:
    """`{m: drift_scores(tuần mốc, tuần đo)}` cho `m ∈ weekly_marks(ctx)` (dict dựng từ chính `weekly_marks`). Đếm theo
    cửa sổ, mỗi cửa sổ một lần: tuần `[W − 14, W − 7)` vừa là tuần đo của mốc `W − 7` vừa là tuần mốc của `W` → 3 lượt
    đếm, hai mốc thấy cùng số. Nguồn ghi đè pending → log INFO (Q-M9-B3-13), luật vẫn chạy 5 phân bố còn lại."""
    cache: dict[tuple[datetime, datetime], DriftCounts] = {}
    out: dict[datetime, DriftWeek] = {}
    for m in weekly_marks(ctx):
        pair: list[DriftCounts] = []
        for window in (baseline_window(m, ctx.tz), week_window(m, ctx.tz)):
            if window not in cache:
                cache[window] = await drift_counts(conn, *window)
            pair.append(cache[window])
        out[m] = drift_scores(*pair)
    if any(counts.pending for counts in cache.values()):
        log.info("luật drift bỏ phân bố override: nguồn chưa có (override_count)")
    return out
