"""Dựng dữ liệu cho test luật cảnh báo M9 (B1 — luật theo sự kiện; B2 — luật 60 s 4, 5, 6, luật ngày 1, 7, 12, 13 và luật
giờ 14). Dùng thêm `monitor_seed` của Dương (không sửa).

Quy ước giống `monitor_seed`: helper `async`, nhận `AsyncConnection` của **app_rw**, **không tự commit** — test seed trong
`async with rw.begin()` rồi mới đọc qua engine `app_monitor`. Riêng `auth_lock` nhận engine (ghi bằng writer thật của
auth, mỗi lần ghi một transaction như auth).

Cô lập (Q-M9-B1-14): loader không có chặn trên theo `now` (Q-M9-B1-12) → test chạy trước thấy dữ liệu "tương lai" của
test khác trong cùng DB. Vì vậy mỗi test một `day(k)` riêng, mọi đối tượng sinh bằng `new_id()`, và mọi assert (kể cả
"0 draft / 0 dòng") chỉ xét subject của chính test.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.audit.alerts import AlertWriter
from app.audit.security_events import SecurityEventWriter
from app.core.clock import FakeClock
from app.db.security_events import check_event
from app.domain.alerts import bruteforce_alert
from app.monitor.window import bucket_start
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from tests.integration import monitor_seed as seed

BASE = datetime(2031, 1, 1, 12, 0, tzinfo=UTC)
B1_RULES: tuple[str, ...] = (
    "injection_detected", "password_bruteforce", "refresh_reuse", "permission_denied_burst", "policy_saved",
    "finalize_failed", "execution_failed",
)  # fmt: skip
_EXIT_CODE = {"injection_detected": "E0", "execution_failed": "E7"}
_BURST_STEP = timedelta(seconds=10)  # luật 10: 11 sự kiện cách 10 s, sự kiện cuối ở `at`


def day(k: int) -> datetime:
    """Mốc `now` riêng cho test thứ k — cách nhau 3 ngày (> lookback 24 giờ + lùi 5 phút)."""
    return BASE + timedelta(days=3 * k)


async def security_event(
    conn: AsyncConnection,
    event_type: str,
    *,
    occurred_at: datetime,
    user_id: str | None = None,
    username: str | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    """Một dòng `security_events` (bảng append-only). Kiểm như writer thật (`check_event`); `user_id` có FK → tạo user.
    Trả `event_id`."""
    payload = dict(detail or {})
    check_event(event_type, payload)
    if user_id is not None:
        await seed.ensure_user(conn, user_id)
    result = await conn.execute(text(
        "INSERT INTO security_events (occurred_at, event_type, user_id, username_attempted, detail) "
        "VALUES (:at, :t, :u, :n, CAST(:d AS jsonb)) RETURNING event_id"
    ), {"at": occurred_at, "t": event_type, "u": user_id, "n": username, "d": json.dumps(payload)})  # fmt: skip
    return int(result.scalar_one())


async def alert(
    conn: AsyncConnection,
    *,
    rule_id: str,
    subject: str,
    window_start: datetime,
    severity: str = "critical",
    detail: dict[str, Any] | None = None,
) -> int:
    """Một dòng `alerts` dựng tay (vd cảnh báo của luật khác cùng subject). Trả `alert_id`."""
    result = await conn.execute(text(
        "INSERT INTO alerts (rule_id, subject, severity, window_start, detail) "
        "VALUES (:r, :s, :sev, :w, CAST(:d AS jsonb)) RETURNING alert_id"
    ), {"r": rule_id, "s": subject, "sev": severity, "w": window_start, "d": json.dumps(detail or {})})  # fmt: skip
    return int(result.scalar_one())


async def auth_lock(
    rw: AsyncEngine, *, user_id: str | None, username: str, at: datetime, skew: timedelta = timedelta(milliseconds=3)
) -> datetime:
    """Đợt khoá do auth ghi, ĐÚNG THỨ TỰ và đúng hàm của auth (`auth/service.py` `_check_threshold`): `lock_start = at`
    (now của auth, lấy trước khi gọi AD) → sự kiện `account_locked` (threshold) ghi SAU, `occurred_at = at + skew` →
    cảnh báo `bruteforce_alert(lock_start=at, source="login")`. Hai transaction riêng như auth. Trả `occurred_at`.
    `user_id` (nếu có) phải đã tồn tại trong `users`."""
    clock = FakeClock(at + skew)
    await SecurityEventWriter(rw, clock).record(
        "account_locked", user_id=user_id, username_attempted=username, detail={"reason": "threshold", "failures": 5}
    )
    await AlertWriter(rw, clock).raise_once(
        bruteforce_alert(user_id=user_id, username=username, lock_start=at, source="login")
    )
    return at + skew


async def exit_row(
    conn: AsyncConnection, ticket_id: str, *, code: str, at: datetime, step: str | None = None,
    reason: str | None = None,
) -> int:  # fmt: skip
    """Dòng `audit_logs` mang `exit_code` như `goto()` ghi: E0 ở B2 → cột `block_reason`; còn lại →
    `detail.escalation_reason_detail` (`graph/goto.py` `_DETAIL_FIELDS`)."""
    if code == "E0" and (step or "B2") == "B2":
        return await seed.audit_row(
            conn, ticket_id, step="B2", event="injection_detected", created_at=at, exit_code=code,
            block_reason=reason or "injection_detected",
        )  # fmt: skip
    step = step or "B17"
    detail = {"escalation_reason_detail": reason or ("injection_in_reply" if code == "E0" else "exec_interrupted")}
    return await seed.audit_row(conn, ticket_id, step=step, event="transition", created_at=at, exit_code=code,
                                detail=detail)  # fmt: skip


async def finalize_row(conn: AsyncConnection, ticket_id: str, *, at: datetime, event: str = "finalize_failed_permanent") -> int:
    """Dòng audit B20 như `graph/runner.py` ghi khi lượt kẹt ở B20 (`detail.node`)."""
    return await seed.audit_row(conn, ticket_id, step="B20", event=event, created_at=at,
                                detail={"node": "b20_audit", "recover_attempts": 3})  # fmt: skip


async def seed_rule(conn: AsyncConnection, rule_id: str, *, at: datetime) -> tuple[str, datetime]:
    """Một nguồn của luật `rule_id` tại thời điểm `at` (đối tượng mới, `new_id`). Trả `(subject, window_start kỳ vọng)`."""
    if rule_id in _EXIT_CODE:
        code = _EXIT_CODE[rule_id]
        ticket = await seed.leaf_ticket(conn, created_at=at, exit_code=code)
        await exit_row(conn, ticket, code=code, at=at)
        return ticket, at
    if rule_id == "finalize_failed":
        ticket = await seed.leaf_ticket(conn, created_at=at)
        await finalize_row(conn, ticket, at=at)
        return ticket, at
    if rule_id == "policy_saved":
        version = seed.new_id("v")
        await security_event(conn, "policy_saved", occurred_at=at, detail={"version": version})
        return version, at
    user = seed.new_id("u")
    if rule_id == "password_bruteforce":
        await security_event(conn, "account_locked", occurred_at=at, user_id=user,
                             detail={"reason": "threshold", "failures": 5})  # fmt: skip
        return user, at
    if rule_id == "refresh_reuse":
        await security_event(conn, "refresh_reuse_detected", occurred_at=at, user_id=user,
                             detail={"revoked_sessions": 2})  # fmt: skip
        return user, at
    if rule_id == "permission_denied_burst":
        for i in range(11):
            await security_event(conn, "permission_denied", occurred_at=at - (10 - i) * _BURST_STEP, user_id=user)
        return user, bucket_start(at, 5)
    raise ValueError(f"luật lạ {rule_id!r}")


async def seed_noise(conn: AsyncConnection, rule_id: str, *, at: datetime) -> str:
    """Dữ liệu GẦN giống nguồn của luật nhưng KHÔNG được ra cảnh báo. Trả subject sẽ bị kiểm "0 draft"."""
    if rule_id in _EXIT_CODE:
        ticket = await seed.leaf_ticket(conn, created_at=at, exit_code="E5")
        await exit_row(conn, ticket, code="E5", at=at, step="B12", reason="llm_layer_disabled")
        return ticket
    if rule_id == "finalize_failed":
        ticket = await seed.leaf_ticket(conn, created_at=at)
        await finalize_row(conn, ticket, at=at, event="unhandled_exception")
        return ticket
    if rule_id == "policy_saved":
        version = seed.new_id("v")
        await security_event(conn, "role_changed", occurred_at=at, detail={"version": version})
        return version
    user = seed.new_id("u")
    if rule_id == "password_bruteforce":  # đang khoá (still_locked) — không phải lần khoá mới
        await security_event(conn, "account_locked", occurred_at=at, user_id=user, detail={"reason": "still_locked"})
    elif rule_id == "refresh_reuse":
        await security_event(conn, "token_refreshed", occurred_at=at, user_id=user)
    elif rule_id == "permission_denied_burst":  # 10 sự kiện / 5 phút — đúng ngưỡng, không vượt
        for i in range(10):
            await security_event(conn, "permission_denied", occurred_at=at - i * _BURST_STEP, user_id=user)
    else:
        raise ValueError(f"luật lạ {rule_id!r}")
    return user


# ---- B2 GĐ2 cụm 1: luật 60 s 4 `e9_spike`, 6 `e6_spike` (tổng hợp), 5 `breaker_open` --------------------------------
#
# Luật 4/6 đếm TOÀN HỆ THỐNG (subject `SYSTEM_SUBJECT`) → không cô lập được theo subject như B1: mỗi ca một mốc
# `spike_now(k)` riêng, cách nhau 10 ngày > đọc lùi 192,5 giờ (`spike_since`) + 25 giờ đánh giá. Phút 30 của giờ.

SPIKE_BASE = datetime(2032, 1, 1, 12, 30, tzinfo=UTC)
SPIKE_SLOT = timedelta(days=10)
# Dòng audit như code thật ghi: E9 `graph/boundary.py` (step = node, event unhandled_exception); E6
# `graph/nodes/approval_wait.py` (step B16, event approval_timeout, approval_result timeout).
_SPIKE_ROW: dict[str, dict[str, Any]] = {
    "E9": {"step": "B9", "event": "unhandled_exception"},
    "E6": {"step": "B16", "event": "approval_timeout", "approval_result": "timeout"},
}


def spike_now(k: int) -> datetime:
    return SPIKE_BASE + k * SPIKE_SLOT


async def spike_row(conn: AsyncConnection, ticket_id: str, code: str, *, at: datetime) -> int:
    """Một dòng `audit_logs` mang mã E9/E6 của ticket có sẵn (vd dòng thứ hai của cùng lá)."""
    return await seed.audit_row(conn, ticket_id, created_at=at, exit_code=code, **_SPIKE_ROW[code])


async def spike_leaf(conn: AsyncConnection, code: str, *, at: datetime, created_at: datetime | None = None) -> str:
    """Một lá ra mã `code` lúc `at` (ticket tạo lúc `created_at`, mặc định `at`). Trả `ticket_id`."""
    ticket = await seed.leaf_ticket(conn, created_at=created_at or at, exit_code=code)
    await spike_row(conn, ticket, code, at=at)
    return ticket


async def spike_leaves(conn: AsyncConnection, code: str, *, hour: datetime, n: int) -> list[str]:
    """`n` lá ra mã ở giờ `hour`, phút 10, 11, …"""
    return [await spike_leaf(conn, code, at=hour + timedelta(minutes=10 + i)) for i in range(n)]


async def spike_parent(conn: AsyncConnection, code: str, *, at: datetime) -> str:
    """Ticket CHA (`is_parent = true`) mang dòng mã — luật đếm qua `v_leaf` không được tính nó. Trả id cha."""
    parent, _ = await seed.parent_with_children(conn, created_at=at, n=1, parent_exit_code=code)
    await spike_row(conn, parent, code, at=at)
    return parent


async def tool_span(
    conn: AsyncConnection, *, name: str, at: datetime, error: str = "circuit_open", span_type: str = "tool",
    status: str = "error",
) -> str:  # fmt: skip
    """Span tool theo hợp đồng dự kiến của luật 5 (Q-M9-4): `attributes.error`. `monitor_seed.span` không ghi
    `attributes` nên dựng riêng ở đây. Trả `span_id`."""
    ticket = await seed.leaf_ticket(conn, created_at=at)
    turn_id = await seed.turn(conn, ticket, started_at=at)
    span_id = seed.new_id("sp")[:32]
    await conn.execute(text(
        "INSERT INTO spans (span_id, trace_id, turn_id, span_type, name, started_at, duration_ms, status, attributes) "
        "VALUES (:id, :trace, :u, :ty, :n, :s, 0, :st, CAST(:a AS jsonb))"
    ), {
        "id": span_id, "trace": span_id, "u": turn_id, "ty": span_type, "n": name, "s": at, "st": status,
        "a": json.dumps({"error": error}),
    })  # fmt: skip
    return span_id


# ---- B2 GĐ2 cụm 2: luật ngày 1, 7, 12, 13 và luật giờ 14 ---------------------------------------------------------------
#
# Luật 1/12/13 đếm TOÀN HỆ THỐNG → mỗi ca một mốc `daily_now(k)` riêng, cách nhau 30 ngày (> 7 ngày đọc lùi + 7 mốc).
# `daily_now(k)` luôn 19:00 UTC = 02:00 giờ VN (giờ job ngày) → `d0` = `daily_now(k) − 2 giờ`. Lá của luật 7/12/13 để
# `final_state` NULL (đang chạy) → không vào mẫu số luật 1.

DAILY_BASE = datetime(2033, 1, 10, 19, 0, tzinfo=UTC)
DAILY_SLOT = timedelta(days=30)
# `detail` điểm log 6 như `graph/nodes/approval_wait.py` `_point6` (nhánh quyết định của người).
FAST_B16: dict[str, Any] = {
    "view_duration": None, "decided_without_view": True, "decided_as": "primary", "reason_code": None,
    "close_applied": 1,
}  # fmt: skip
NORMAL_B16: dict[str, Any] = {
    "view_duration": 30.0, "decided_without_view": False, "decided_as": "primary", "reason_code": None,
    "close_applied": 1,
}  # fmt: skip
_B16_EVENT = {"approved": "approved", "rejected": "rejected", "timeout": "approval_timeout"}  # approval_wait.py


def daily_now(k: int) -> datetime:
    return DAILY_BASE + k * DAILY_SLOT


async def n3_leaf(conn: AsyncConnection, *, group: str, escalated: bool, created_at: datetime) -> str:
    """Một lá ĐÃ KẾT THÚC cho `escalation_rate_weighted` (nhóm N3 theo điểm log 4 — Q-M9-1): `routine` không có dòng
    điểm log 4, `approval` → `approval_required`, `sensitive` → `deny`. Escalate → `S_ESCALATED` + E5, còn lại
    `S_RESOLVED`. Trả `ticket_id`."""
    ticket = await seed.leaf_ticket(
        conn, created_at=created_at, final_state="S_ESCALATED" if escalated else "S_RESOLVED",
        exit_code="E5" if escalated else None,
    )  # fmt: skip
    decision = {"routine": None, "approval": "approval_required", "sensitive": "deny"}[group]
    if decision is not None:
        await seed.audit_point4(conn, ticket, created_at=created_at, policy_decision=decision)
    return ticket


async def b16_row(
    conn: AsyncConnection, ticket_id: str, *, at: datetime, approval_result: str, event: str, detail: object
) -> int:
    """Dòng audit B16 (điểm log 6). `detail` có thể KHÔNG phải object JSON (mảng, chuỗi) — `monitor_seed.audit_row` chỉ
    nhận dict nên ghi riêng ở đây. Trả `log_id`."""
    result = await conn.execute(text(
        "INSERT INTO audit_logs (ticket_id, step, event, created_at, approval_result, detail) "
        "VALUES (:t, 'B16', :e, :c, :r, CAST(:d AS jsonb)) RETURNING log_id"
    ), {"t": ticket_id, "e": event, "c": at, "r": approval_result, "d": json.dumps(detail)})  # fmt: skip
    return int(result.scalar_one())


async def reflex_decision(
    conn: AsyncConnection,
    *,
    approver: str,
    decided_at: datetime,
    b16: object = FAST_B16,
    with_b16: bool = True,
    status: str = "approved",
    event: str | None = None,
    ticket_id: str | None = None,
    created_at: datetime | None = None,
    b16_at: datetime | None = None,
    reminder_2_at: datetime | None = None,
) -> str:
    """Một phiếu đã quyết như code thật: `approvals` (`decided_by` = người quyết, `decided_at`; timeout thì không có người
    quyết) + dòng B16 cột `approval_result = status` lúc `b16_at` (mặc định `decided_at + 1 s`). `with_b16=False` → không
    có dòng B16. `ticket_id` có sẵn → phiếu thứ hai của ticket đó. Trả `ticket_id`."""
    created = created_at or decided_at - timedelta(hours=1)
    ticket = ticket_id or await seed.leaf_ticket(conn, created_at=created)
    approval_id = await seed.approval(
        conn, ticket, approver_id=approver, created_at=created, status=status,
        decided_by=None if status == "timeout" else approver, decided_at=decided_at,
        note="ghi chú thử" if status == "rejected" else None,
    )  # fmt: skip
    if reminder_2_at is not None:
        await conn.execute(
            text("UPDATE approvals SET reminder_2_at = :r WHERE approval_id = :a"), {"r": reminder_2_at, "a": approval_id}
        )
    if with_b16:
        await b16_row(
            conn, ticket, at=b16_at or decided_at + timedelta(seconds=1), approval_result=status,
            event=event or _B16_EVENT[status], detail=b16,
        )  # fmt: skip
    return ticket


async def b2_point(conn: AsyncConnection, *, created_at: datetime, layer: str) -> str:
    """Lá có dòng B2 `detail.screening.layer_decided = layer` (nguồn `b2_llm_rate`). Trả `ticket_id`."""
    ticket = await seed.leaf_ticket(conn, created_at=created_at)
    await seed.audit_row(conn, ticket, step="B2", event="screened", created_at=created_at,
                         detail={"screening": {"layer_decided": layer}})  # fmt: skip
    return ticket


async def b3_point(conn: AsyncConnection, *, created_at: datetime, layer: str) -> str:
    """Lá có dòng điểm log 1 step B3 `detail.layer = layer` (nguồn `b3_llm_rate`). Trả `ticket_id`."""
    ticket = await seed.leaf_ticket(conn, created_at=created_at)
    await seed.audit_row(conn, ticket, step="B3", event="intent_classified", created_at=created_at,
                         detail={"layer": layer})  # fmt: skip
    return ticket


async def llm_cost(conn: AsyncConnection, *, cost_usd: float | None, at: datetime, parent: bool = False) -> int:
    """Một lời gọi LLM tốn `cost_usd` lúc `at`, của một lá (mặc định) hoặc của ticket CHA (luật 14 cộng cả hai — tổng
    toàn bảng như gateway). Trả `call_id`."""
    if parent:
        ticket, _ = await seed.parent_with_children(conn, created_at=at, n=1)
    else:
        ticket = await seed.leaf_ticket(conn, created_at=at)
    return await seed.llm_call_for(conn, ticket, created_at=at, cost_usd=cost_usd)


# ---- B3 cụm 3: luật tuần 8 drift ------------------------------------------------------------------------------------
#
# Luật 8 đếm TOÀN HỆ THỐNG theo tuần → mỗi ca một `weekly_now(k)` riêng. `WEEKLY_BASE` = 2036-01-06T19:00Z = 02:00 thứ Hai
# 07/01/2036 giờ VN (giờ job tuần, cụm 4; lịch: 01/01/2036 là thứ Ba). `W = weekly_now(k) − 2 giờ`. Mỗi lượt đọc lùi 3
# tuần `[W − 21 ngày, W)` → cách nhau 8 tuần là không chồng (và sau mọi mốc của B1/B2: 2031–2035).

WEEKLY_BASE = datetime(2036, 1, 6, 19, 0, tzinfo=UTC)
WEEKLY_SLOT = timedelta(weeks=8)


def weekly_now(k: int) -> datetime:
    return WEEKLY_BASE + k * WEEKLY_SLOT


def week_mark(k: int) -> datetime:
    """`W` của ca k: 00:00 thứ Hai VN = `weekly_now(k) − 2 giờ` (VN không đổi giờ)."""
    return weekly_now(k) - timedelta(hours=2)


async def drift_leaf(
    conn: AsyncConnection, *, created_at: datetime, intent: str | None = None, done: bool = True,
    exit_code: str | None = None, override: bool = False,
) -> str:  # fmt: skip
    """Một lá cho luật 8: `done` → đã kết thúc (`S_RESOLVED`, hoặc `S_ESCALATED` khi có `exit_code`), không thì đang chạy
    (`final_state` NULL). `override` → thêm một dòng ghi đè như 4d (`monitor_seed.override`). Trả `ticket_id`."""
    final_state = None if not done else "S_ESCALATED" if exit_code else "S_RESOLVED"
    ticket = await seed.leaf_ticket(
        conn, created_at=created_at, intent=intent, exit_code=exit_code, final_state=final_state
    )
    if override:
        await seed.override(conn, ticket, created_at=created_at + timedelta(hours=1))
    return ticket


async def drift_leaves(conn: AsyncConnection, n: int, *, created_at: datetime, **fields: Any) -> list[str]:
    """`n` lá giống nhau, cách nhau 1 phút từ `created_at`."""
    return [await drift_leaf(conn, created_at=created_at + timedelta(minutes=i), **fields) for i in range(n)]


async def audit_raw(
    conn: AsyncConnection, ticket_id: str, *, step: str, event: str, created_at: datetime, detail_json: str
) -> int:
    """Dòng audit với `detail` là JSON TÙY Ý (số, chuỗi, mảng, object có khoá sai kiểu) — `monitor_seed.audit_row` chỉ
    nhận dict. `detail_json` là chuỗi JSON đã dựng sẵn. Trả `log_id`."""
    result = await conn.execute(text(
        "INSERT INTO audit_logs (ticket_id, step, event, created_at, detail) "
        "VALUES (:t, :s, :e, :c, CAST(:d AS jsonb)) RETURNING log_id"
    ), {"t": ticket_id, "s": step, "e": event, "c": created_at, "d": detail_json})  # fmt: skip
    return int(result.scalar_one())
