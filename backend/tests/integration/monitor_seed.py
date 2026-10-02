"""Dựng dữ liệu cho test M9 (A1; Duy Anh dùng ở B1/B2 — chữ ký giữ ổn định, cần helper mới → viết ở file của mình).

Cách dùng: mọi helper là `async`, nhận `AsyncConnection` của **app_rw** và **KHÔNG tự commit**. Test phải commit
(`async with rw.begin() as conn: ...`) TRƯỚC khi đọc qua engine `app_monitor` — connection khác không thấy dữ liệu
chưa commit. `audit_logs` chỉ ghi thêm (trigger) → mỗi test dùng cửa sổ thời gian riêng (vd năm 2030) và
`ticket_id` duy nhất (mặc định `new_id()`), mỗi module một DB riêng (`pg.fresh_database`).

Không giả định "ngoài giờ → HITL": điểm log 4 ghi thẳng giá trị truyền vào. Ca 4b R17/R18/R19 (máy người khác/không
tồn tại) → `llm_disabled_case`: E5, 0 phiếu, không HITL. `override_count` pending tới 4d (step `OVERRIDE`, event
`override_recorded`) → không có helper.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SEED_REQUESTER = "seed-requester"
SEED_APPROVERS: tuple[str, ...] = ("seed-l1-a", "seed-l1-b")
_HASH = "0" * 64  # action_plan_hash giả (CHAR(64), NOT NULL)
_LEVEL = {"allow": "low", "approval_required": "medium", "deny": "high"}  # như graph/nodes/b12_assess.py `_LEVEL`


def new_id(prefix: str = "m9") -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


def _jsonb(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


async def ensure_user(
    conn: AsyncConnection, user_id: str, *, username: str | None = None, role: str = "employee"
) -> str:
    """Tạo dòng `users` nếu chưa có (`ON CONFLICT DO NOTHING`). `username` mặc định `seed.<user_id>` (cột UNIQUE);
    `role` ∈ employee | l1 | manager | l2. Trả `user_id`."""
    await conn.execute(
        text("INSERT INTO users (user_id, username, role) VALUES (:u, :n, :r) ON CONFLICT DO NOTHING"),
        {"u": user_id, "n": username or f"seed.{user_id}", "r": role},
    )
    return user_id


async def _ticket(
    conn: AsyncConnection,
    *,
    ticket_id: str,
    created_at: datetime,
    is_parent: bool,
    parent_ticket_id: str | None,
    exit_code: str | None,
    final_state: str | None,
    resolution_path: str | None,
    intent: str | None,
    redacted_request: str,
    requester_id: str,
    closed_at: datetime | None,
) -> str:
    await ensure_user(conn, requester_id)
    await conn.execute(text(
        "INSERT INTO tickets (ticket_id, parent_ticket_id, requester_id, requester_role, redacted_request, intent, "
        "final_state, exit_code, resolution_path, created_at, closed_at, is_parent) VALUES (:t, :p, :u, 'employee', "
        ":req, :intent, :fs, :ec, :rp, :c, :closed, :is_parent)"
    ), {
        "t": ticket_id, "p": parent_ticket_id, "u": requester_id, "req": redacted_request, "intent": intent,
        "fs": final_state, "ec": exit_code, "rp": resolution_path, "c": created_at, "closed": closed_at,
        "is_parent": is_parent,
    })  # fmt: skip
    return ticket_id


async def leaf_ticket(
    conn: AsyncConnection,
    *,
    created_at: datetime,
    exit_code: str | None = None,
    final_state: str | None = None,
    resolution_path: str | None = None,
    intent: str | None = None,
    redacted_request: str = "yêu cầu thử (đã che)",
    ticket_id: str | None = None,
    parent_ticket_id: str | None = None,
    requester_id: str = SEED_REQUESTER,
    closed_at: datetime | None = None,
) -> str:
    """Một ticket lá (`is_parent = false`). Trả `ticket_id`.

    - `final_state` mặc định `None` = ticket đang chạy → KHÔNG vào mẫu số tỉ lệ (chỉ lá đã kết thúc). Lá đã xong thì
      truyền tường minh (`S_RESOLVED` / `S_ESCALATED` / `S_REJECTED` / `S_BLOCKED`).
    - `exit_code` E0–E9; `resolution_path` auto | approved | rejected | escalated | deflected (deflected đi với
      `S_RESOLVED`, như `audit/final.py`); `intent` account | vpn | software | access.
    """
    return await _ticket(
        conn, ticket_id=ticket_id or new_id(), created_at=created_at, is_parent=False,
        parent_ticket_id=parent_ticket_id, exit_code=exit_code, final_state=final_state,
        resolution_path=resolution_path, intent=intent, redacted_request=redacted_request,
        requester_id=requester_id, closed_at=closed_at,
    )  # fmt: skip


async def parent_with_children(
    conn: AsyncConnection,
    n: int = 2,
    *,
    created_at: datetime,
    parent_exit_code: str | None = None,
    parent_final_state: str | None = None,
    **child_fields: Any,
) -> tuple[str, list[str]]:
    """"Câu n ý": 1 ticket cha (`is_parent = true`) + `n` lá con trỏ về cha. Trả `(parent_id, [child_ids])`.

    `parent_exit_code`, `parent_final_state` đặt RIÊNG cho cha (dữ liệu "xấu" cố ý: chỉ số đọc qua `v_leaf` phải bỏ
    cha). `child_fields` = tham số keyword của `leaf_ticket` (trừ `created_at`, `parent_ticket_id`, `ticket_id`),
    áp cho mọi con."""
    parent = await _ticket(
        conn, ticket_id=new_id("m9p"), created_at=created_at, is_parent=True, parent_ticket_id=None,
        exit_code=parent_exit_code, final_state=parent_final_state, resolution_path=None, intent=None,
        redacted_request="câu nhiều ý (đã che)", requester_id=child_fields.get("requester_id", SEED_REQUESTER),
        closed_at=None,
    )  # fmt: skip
    children = [
        await leaf_ticket(conn, created_at=created_at, parent_ticket_id=parent, **child_fields) for _ in range(n)
    ]
    return parent, children


async def audit_row(
    conn: AsyncConnection,
    ticket_id: str,
    *,
    step: str,
    event: str,
    created_at: datetime,
    exit_code: str | None = None,
    detail: dict[str, Any] | None = None,
    **columns: Any,
) -> int:
    """Một dòng `audit_logs` tổng quát (B4 E1, B8 `kb_version`, B16…). `detail` dict → jsonb (mặc định `{}`);
    `columns` = cột khác của `audit_logs` theo tên (vd `kb_version=`, `decided_by=`). Trả `log_id`."""
    for name in columns:
        if not name.isidentifier():
            raise ValueError(f"tên cột không hợp lệ: {name!r}")
    names = ["ticket_id", "step", "event", "created_at", "exit_code", *columns]
    values = [":ticket_id", ":step", ":event", ":created_at", ":exit_code", *(f":{c}" for c in columns)]
    result = await conn.execute(text(
        f"INSERT INTO audit_logs ({', '.join(names)}, detail) VALUES ({', '.join(values)}, CAST(:detail AS jsonb)) "
        "RETURNING log_id"
    ), {
        "ticket_id": ticket_id, "step": step, "event": event, "created_at": created_at, "exit_code": exit_code,
        "detail": _jsonb(detail), **columns,
    })  # fmt: skip
    return int(result.scalar_one())


async def audit_point4(
    conn: AsyncConnection,
    ticket_id: str,
    *,
    created_at: datetime,
    decided_by: str = "rule",
    policy_decision: str | None = "allow",
    risk_level: str | None = None,
    matched_rule_id: str | None = None,
    calibrated_prob: float | None = None,
    exit_code: str | None = None,
    step: str = "B13/B14",
    event: str = "risk_decided",
) -> int:
    """Một dòng điểm log 4 (`v_decisions` đọc step `B13/B14`). `risk_level=None` → suy từ `policy_decision` như
    `b12_assess.py` (allow→low, approval_required→medium, deny→high); muốn `decision` và `risk_level` lệch nhau thì
    truyền cả hai. `decided_by` ∈ rule | llm. Trả `log_id`."""
    level = risk_level if risk_level is not None else _LEVEL.get(policy_decision or "")
    return await audit_row(
        conn, ticket_id, step=step, event=event, created_at=created_at, exit_code=exit_code,
        decided_by=decided_by, policy_decision=policy_decision, risk_level=level, matched_rule_id=matched_rule_id,
        calibrated_prob=calibrated_prob,
    )  # fmt: skip


async def approval(
    conn: AsyncConnection,
    ticket_id: str,
    *,
    approver_id: str,
    created_at: datetime,
    status: str = "pending",
    deadline: datetime | None = None,
    decided_by: str | None = None,
    decided_at: datetime | None = None,
    note: str | None = None,
    conflict_detected: bool = False,
    backup_approver_id: str | None = None,
) -> int:
    """Một phiếu `approvals`. Tự tạo user `approver_id` (và `backup_approver_id`) vai `l1` nếu chưa có.
    `status` ∈ pending | approved | rejected | timeout | late_ignored (`rejected` cần `note`; mỗi ticket tối đa 1 phiếu
    `pending`). `deadline` mặc định `created_at + 1 ngày`. Trả `approval_id`."""
    for user in (approver_id, backup_approver_id):
        if user is not None:
            await ensure_user(conn, user, role="l1")
    result = await conn.execute(text(
        "INSERT INTO approvals (ticket_id, approver_id, backup_approver_id, deadline, action_plan_hash, "
        "conflict_detected, status, note, decided_by, decided_at, created_at) VALUES (:t, :a, :b, :dl, :h, :cd, :s, "
        ":note, :db, :da, :c) RETURNING approval_id"
    ), {
        "t": ticket_id, "a": approver_id, "b": backup_approver_id, "dl": deadline or created_at + timedelta(days=1),
        "h": _HASH, "cd": conflict_detected, "s": status, "note": note, "db": decided_by, "da": decided_at,
        "c": created_at,
    })  # fmt: skip
    return int(result.scalar_one())


async def escalation(
    conn: AsyncConnection,
    ticket_id: str,
    *,
    exit_code: str,
    created_at: datetime,
    reason_detail: str | None = None,
    closed_at: datetime | None = None,
    handoff_note: dict[str, Any] | None = None,
) -> int:
    """Một dòng `escalations`; `priority` lấy từ `exit_code_priority` (seed của 0001). `closed_at=None` = còn mở (vào
    `v_l2_queue`). `reason_detail` nên thuộc `app.domain.exit_codes.REASON_DETAILS`. Trả `escalation_id`."""
    result = await conn.execute(text(
        "INSERT INTO escalations (ticket_id, exit_code, priority, reason_detail, handoff_note, closed_at, created_at) "
        # :ec dùng 2 lần → ép cùng kiểu cả hai chỗ (không ép thì psycopg báo AmbiguousParameter: text vs varchar)
        "VALUES (:t, CAST(:ec AS varchar), (SELECT p.rank FROM exit_code_priority p "
        "WHERE p.exit_code = CAST(:ec AS varchar)), :rd, CAST(:hn AS jsonb), :closed, :c) RETURNING escalation_id"
    ), {
        "t": ticket_id, "ec": exit_code, "rd": reason_detail, "hn": _jsonb(handoff_note), "closed": closed_at,
        "c": created_at,
    })  # fmt: skip
    return int(result.scalar_one())


async def llm_disabled_case(conn: AsyncConnection, *, created_at: datetime, **leaf_fields: Any) -> str:
    """Ca 4b R17/R18/R19 (máy người khác/không tồn tại): không luật nào khớp → lớp LLM rủi ro tắt
    (`b12_assess.py`): điểm log 4 `decided_by='llm'`, `policy_decision=NULL`, `risk_level='high'`, event
    `llm_layer_disabled`; lá E5 `S_ESCALATED`, escalation E5 `llm_layer_disabled`; 0 phiếu, không HITL. Trả
    `ticket_id`."""
    ticket = await leaf_ticket(
        conn, created_at=created_at, exit_code="E5", final_state="S_ESCALATED", resolution_path="escalated",
        **leaf_fields,
    )  # fmt: skip
    await audit_point4(
        conn, ticket, created_at=created_at, decided_by="llm", policy_decision=None, risk_level="high",
        exit_code="E5", event="llm_layer_disabled",
    )  # fmt: skip
    await escalation(conn, ticket, exit_code="E5", created_at=created_at, reason_detail="llm_layer_disabled")
    return ticket
