"""`POST /api/approvals/{id}/decision` — đúng handler B15-B16 mục 5 (2b-Q3, 2b-3 chốt e, f).

Thứ tự:
1. 413 (middleware) → `require("approval:decide")` (L2, employee → 403).
2. Transaction NGẮN `lock_row` (`FOR UPDATE`, chỉ đọc + kiểm):
   - không có phiếu → 404;
   - `approval_role` None (không phải người được giao, dự phòng chưa qua nhắc 2 — 4c P4, xung đột lợi ích) → 403 +
     `permission_denied`. Xung đột dùng CÙNG
     `domain.approval.conflict_type` với B15; chuỗi quản lý của người quyết dựng từ bảng `users` (`manager_id`, ≤ 5 cấp, chặn
     vòng — `domain.approval.manager_chain`, Phase 4 P4);
   - phiếu không còn `pending` → `already_decided`; `clock.now() >= deadline` (Clock của APP, bằng hạn
     là muộn) → `expired` → `record_late` + 409 (TC27).
3. Body: `rejected` thiếu `note` → 422. `reason_code` chỉ nhận mã trong `ReasonCode` (danh sách CỐ ĐỊNH, PLAN-3e
   Q-3e-13): ô này không qua privacy guard mà nằm nguyên văn trong checkpoint → chuỗi tự do (vd mật khẩu dán nhầm)
   bị 422 `invalid_request`, không lưu gì.
4. Privacy guard trên `note` (3e, phase3 mục 8.3): lỗi → 503, có bí mật → `privacy_secret_redacted` trước
   `start_event`; body 202 thêm `notices` (PLAN-3e Q-3e-6).
5. `start_event(S_PENDING_APPROVAL)` → 202. Route KHÔNG ghi quyết định: B16 ghi (`approvals.close` có
   điều kiện) khi graph chạy — trước đó phiếu vẫn `pending`. `approver_id` chỉ lấy từ token.

Bấm muộn KHÔNG đổi `approvals.status` (quyết định 2b-3 Q2 — lệch câu "phiếu `late_ignored`" của B15
mục 10): phiếu `pending` quá hạn phải còn `pending` để worker bắn timeout (E6); đổi đi thì ticket kẹt
ở `S_PENDING_APPROVAL` mãi mãi. Dấu vết bấm muộn nằm ở audit `late_event` (`reason`, `approval_id`,
`clicked_by`).

`view_started_at` tuỳ chọn, chỉ ghi log; `view_duration` tính phía server từ `first_viewed_at` (route xem
phiếu ở Phase 4 mới ghi cột này → 2b luôn None). Lệch B15 mục 4 (`DecisionIn` bắt buộc) — ghi PROGRESS.

Phase 4 4c DỪNG 2 (phase4 6.1 P4–P6, PLAN-4c TQ-9…12): MỘT hàm vai trò `authz.approval_role` cho cả 3 route — người được giao
(`primary`) hoặc dự phòng SAU nhắc 2 (`backup`), không xung đột.
- `GET /api/approvals?mine=1[&status=…]` (hộp thư, P5): `require("approval:decide")` → `mine`/`status` kiểm tay SAU quyền (422
  không lộ input) → `SqlApprovals.inbox` (lọc vai trò ở SQL, nối dòng audit B15 `queued`) → lọc xung đột → ≤ 50 mục.
- `GET /api/approvals/{id}` (xem phiếu, P6): 403 tầng 2 → 404 (không có / không được giao — CÙNG thân; bản ghi có thật thì
  `permission_denied`) → manager (`audit:read:all`) xem `viewer` không ghi → `hash_action(action) != action_plan_hash` → 409
  `plan_changed`, không trả bản nào → người được giao / dự phòng ghi `first_viewed_at` lần đầu → `ApprovalView`.
"""

import logging
from datetime import datetime
from typing import Annotated, Any, Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.desk import (
    Desk,
    UserDirectory,
    get_desk,
    parse_body,
    record_redacted,
    redact,
)
from app.api.errors import InvalidRequest
from app.auth.authz import ApprovalParties, RoleAs, approval_role
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.approval import manager_chain
from app.domain.messages import ReasonCode
from app.domain.states import S_PENDING_APPROVAL
from app.graph.late_event import record_late, start_event
from app.settings import get_action_metadata

log = logging.getLogger(__name__)
router = APIRouter()

NOTE_MAX = 1000
INBOX_LIMIT = 50  # P5
REQUEST_SUMMARY_MAX = 500  # P6: tickets.redacted_request[:500]
NOT_FOUND = "not_found"
type InboxStatus = Literal["pending", "approved", "rejected", "timeout"]
type LateReason = Literal["expired", "already_decided"]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    reason_code: ReasonCode | None = None  # mã cố định (domain.messages — một nguồn với nhãn tin từ chối B16) — KHÔNG chữ tự do
    view_started_at: datetime | None = None  # tuỳ chọn; chỉ log


class InboxItem(BaseModel):
    """Một mục hộp thư (P5) — ĐÚNG 10 khoá."""

    approval_id: str
    ticket_id: str
    status: str
    created_at: datetime
    deadline: datetime
    reminder_1_at: datetime | None
    reminder_2_at: datetime | None
    role_as: RoleAs
    action_type: str | None  # intended_action.type của dòng audit B15 `queued` (B15 giả không ghi → None)
    device_id: str | None  # phần sau "device:" của intended_action.target


class RequesterView(BaseModel):
    role: str
    department: str | None


class ProcedureRef(BaseModel):
    doc_id: str
    title: str | None


class ApprovalView(BaseModel):
    """Phiếu cho người duyệt (P6) — ĐÚNG 12 khoá; `action`/`facts` là object ĐÃ BĂM (G4-13)."""

    approval_id: str
    ticket_id: str
    status: str
    deadline: datetime
    requester: RequesterView
    request_summary: str
    action: dict[str, Any]
    action_plan_hash: str
    risk: dict[str, Any] | None
    facts: dict[str, Any]
    role_as: Literal["primary", "backup", "viewer"]
    procedure: ProcedureRef | None  # None: action_type không có trong action_metadata (hành động giả)


def _action(values: dict[str, Any]) -> Action | None:
    action = values.get("intended_action")
    return None if action is None else Action.model_validate(action)


def _as_json(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)


def _audit_action(approval_id: str, raw: dict[str, Any] | None) -> Action | None:
    """`intended_action` của dòng audit B15 (hộp thư) — hỏng/thiếu → None (route quyết/xem kiểm lại bằng checkpoint). Hỏng thì ghi
    log (soát 4c R3: đổi schema `Action` làm yếu lọc xung đột ở hộp thư mà không ai biết) — chỉ id phiếu, không nội dung."""
    if raw is None:
        return None
    try:
        return Action.model_validate(raw)
    except ValidationError:
        log.warning("hộp thư: intended_action của dòng audit B15 không hợp lệ (phiếu %s) — bỏ kiểm targets_approver", approval_id)
        return None


async def _chain_from_users(users: UserDirectory, user_id: str) -> tuple[str, ...]:
    """Chuỗi quản lý của người quyết theo bảng `users` (không có dòng → rỗng; sếp không có dòng → dừng ở đó)."""

    async def fetch_manager(uid: str) -> str | None:
        row = await users.get_user(uid)
        return None if row is None else row.manager_id

    me = await users.get_user(user_id)
    return await manager_chain(user_id, me.manager_id if me else None, fetch_manager)


@router.post("/api/approvals/{approval_id}/decision", status_code=202)
async def decide(
    approval_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("approval:decide"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    now = desk.clock.now()
    late: LateReason | None = None
    async with desk.approvals.lock_row(approval_id) as a:
        if a is None:
            raise HTTPException(404, "not_found")
        ticket = await desk.tickets.get(a.ticket_id)
        snap = await desk.runner.snapshot(a.ticket_id)
        parties = ApprovalParties(
            requester_id=ticket.requester_id if ticket else "",
            approver_chain=await _chain_from_users(desk.users, p.user_id),
            action=_action(dict(snap.values or {})),
        )  # fmt: skip
        role = approval_role(p, a, parties)  # 4c P4: người được giao | dự phòng SAU nhắc 2, không xung đột
        if role is None:
            await deny(request, p, "approval:decide", approval_id=approval_id)
            raise HTTPException(403, "forbidden")
        if a.status != "pending":
            late = "already_decided"
        elif now >= a.deadline:
            late = "expired"
        ticket_id, actual = a.ticket_id, (snap.values or {}).get("status")
        first_viewed_at = a.first_viewed_at
    if late is not None:
        await record_late(
            desk.runner, ticket_id, expected_status=S_PENDING_APPROVAL, actual_status=actual,
            event_kind="decision", source="user",
            extra={"approval_id": approval_id, "clicked_by": p.user_id, "reason": late},
        )  # fmt: skip
        raise HTTPException(409, "Yêu cầu đã chuyển sang bước khác")

    body = await parse_body(request, DecisionIn)
    if body.decision == "rejected" and not (body.note and body.note.strip()):
        raise HTTPException(422, "rejected_requires_note")  # [Chốt cổng 4]
    redacted = await redact(desk, request, body.note) if body.note else None
    if redacted is not None:
        await record_redacted(desk, request, p, ticket_id, redacted)
    note = redacted.text if redacted is not None else None
    if body.decision == "rejected" and not (note and note.strip()):  # soát 4c S4b: chỉ ký tự vô hình → che xong rỗng
        raise HTTPException(422, "rejected_requires_note")
    if body.view_started_at is not None:
        log.info("phiếu %s: client báo bắt đầu xem lúc %s (chỉ log)", approval_id, body.view_started_at)
    event = {
        "kind": body.decision, "note": note, "approver_id": p.user_id, "at": now.isoformat(),
        "reason_code": body.reason_code,
        "view_duration": (now - first_viewed_at).total_seconds() if first_viewed_at else None,
        "decided_as": role,  # 4c P4: điểm log 6 `decided_as`; phiếu GIỮ `approver_id` (người quyết = `decided_by`)
    }  # fmt: skip
    await start_event(
        desk.runner, ticket_id, S_PENDING_APPROVAL, event, spawn=desk.background.spawn,
        session_id=p.session_id,
        # ticket đã rời chờ duyệt (lượt duyệt khác vừa chạy xong) — vẫn đúng MỘT dòng late_event
        late_extra={"approval_id": approval_id, "clicked_by": p.user_id, "reason": "already_decided"},
    )  # fmt: skip
    notices = redacted.notices if redacted is not None else []
    return JSONResponse({"approval_id": approval_id, "ticket_id": ticket_id, "status": "accepted", "notices": notices,
                         "decided_as": role}, status_code=202)  # fmt: skip


@router.get("/api/approvals")
async def inbox(
    request: Request,
    p: Annotated[Principal, Depends(require("approval:decide"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    query = request.query_params
    status = query.get("status")
    bad = [f for f, ok in (("query.mine", query.get("mine") == "1"),
                           ("query.status", status is None or status in get_args(InboxStatus.__value__))) if not ok]  # fmt: skip
    if bad:
        raise InvalidRequest(bad)  # SAU quyền (thứ tự như parse_body); không trả lại giá trị người gửi
    chain = await _chain_from_users(desk.users, p.user_id)
    items = []
    for r in await desk.approvals.inbox(p.user_id, status, INBOX_LIMIT):
        role = approval_role(p, r, ApprovalParties(r.requester_id, chain, _audit_action(r.approval_id, r.intended_action)))
        if role is None:  # xung đột lợi ích (vd người được giao nay nằm trong chuỗi quản lý của người gửi)
            continue
        raw = r.intended_action or {}
        target = raw.get("target")
        items.append(InboxItem(
            approval_id=r.approval_id, ticket_id=r.ticket_id, status=r.status, created_at=r.created_at, deadline=r.deadline,
            reminder_1_at=r.reminder_1_at, reminder_2_at=r.reminder_2_at, role_as=role,
            action_type=raw.get("type") if isinstance(raw.get("type"), str) else None,
            device_id=target.removeprefix("device:") if isinstance(target, str) and target.startswith("device:") else None,
        ))  # fmt: skip
    return JSONResponse({"items": [i.model_dump(mode="json") for i in items]})


@router.get("/api/approvals/{approval_id}")
async def view_approval(
    approval_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("approval:decide"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    a = await desk.approvals.get(approval_id)
    if a is None:
        raise HTTPException(404, NOT_FOUND)
    ticket = await desk.tickets.get(a.ticket_id)
    values = dict((await desk.runner.snapshot(a.ticket_id)).values or {})
    action = _action(values)
    parties = ApprovalParties(ticket.requester_id if ticket else "", await _chain_from_users(desk.users, p.user_id), action)
    role = approval_role(p, a, parties)
    if role is None and not p.has("audit:read:all"):  # L1 khác / dự phòng chưa đủ điều kiện → CÙNG 404 với "không có"
        await deny(request, p, "approval:decide", approval_id=approval_id)
        raise HTTPException(404, NOT_FOUND)
    if action is None or hash_action(action) != a.action_plan_hash:  # G4-13: không bao giờ trả object khác object đã băm
        raise HTTPException(409, "plan_changed")
    if role is not None:  # chỉ người được giao / dự phòng đủ điều kiện ghi lần xem đầu; manager xem không ghi
        await desk.approvals.mark_viewed(approval_id, desk.clock.now())
    meta = (get_action_metadata().root.get(str(values.get("intent"))) or {}).get(action.type)
    procedure = None
    if meta is not None:
        procedure = ProcedureRef(doc_id=meta.procedure_doc, title=await desk.approvals.procedure_title(meta.procedure_doc))
    rc = _as_json(values.get("requester_context")) or {}
    view = ApprovalView(
        approval_id=a.approval_id, ticket_id=a.ticket_id, status=a.status, deadline=a.deadline,
        requester=RequesterView(role=str(rc.get("role") or ""), department=rc.get("department")),
        request_summary=(ticket.redacted_request if ticket else "")[:REQUEST_SUMMARY_MAX],
        action=action.model_dump(mode="json"), action_plan_hash=a.action_plan_hash, risk=_as_json(values.get("risk")),
        facts=dict(action.facts), role_as=role or "viewer", procedure=procedure,
    )  # fmt: skip
    return JSONResponse(view.model_dump(mode="json"))
