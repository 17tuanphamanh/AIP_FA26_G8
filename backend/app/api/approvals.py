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
     là muộn) → `expired`; ticket CON mà ticket CHA đã có `final_state` → `parent_closed` (Q4 soát 12/11, V11) →
     `record_late` + 409 (TC27); phiếu giữ `pending`.
2b. Q2 (soát 12/11, agent 13 F1): NGOÀI transaction (không giữ khoá dòng khi gọi AD), hỏi AD người quyết (`AuthService.idp`):
   không còn hợp lệ làm l1 LẪN Trưởng BP (`domain.approval.invalid_reason` — CÙNG tiêu chí B17 `approver_no_longer_valid`:
   không có, không `active`, nhóm không ra role) → 403 + `permission_denied` (`reason=approver_<lý do>`); AD không trả lời → 503
   `identity_unavailable` (fail-closed). Phiếu giữ `pending`, không `start_event`. Đóng khe "nghỉ việc sau khi đăng nhập vẫn duyệt
   được tới hết phiên" (bảng `users` chỉ đồng bộ lúc đăng nhập).
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

F6 (màn duyệt, `response_model=ApprovalView` cho FE gen:api): thêm `affected` + `risk_view`, thứ tự lỗi KHÔNG đổi.
- `affected` = người BỊ TÁC ĐỘNG (`Action.requested_for`, D-41) theo bảng `users` (bản sao AD đồng bộ LÚC ĐĂNG NHẬP — người chưa từng đăng
  nhập không có dòng). `manager.status="known"` CHỈ khi có dòng VÀ `manager_id` khác NULL; mọi ca khác `"unknown"` — `manager_id` NULL
  mang hai nghĩa "không có sếp" / "không biết" (việc treo 25) nên không bao giờ có giá trị "không có quản lý". Đọc `users` lỗi → lỗi nổi
  lên (lỗi hệ thống ≠ "không biết"); đọc TRƯỚC `mark_viewed` nên lỗi không để lại `first_viewed_at`.
- `risk_view` = `RiskDecision` của checkpoint + `calibrated` (`calibrated_prob` khác null) + `auto_allowed` (`route == "AUTO"`); `risk`
  thô giữ nguyên. Backend không sinh chữ hiển thị: "chưa hiệu chỉnh, không tự xử lý" là chữ của FE khi `decided_by == "llm"` và
  `calibrated` false.

P3 tuần 8: `matched_rules` ở GỐC `ApprovalView` (khối `policy` không có ở đây) — mọi luật khớp của đánh giá B13/B14 mà phiếu dựa vào
(`desk.approvals.policy_matches(ticket, lúc tạo phiếu)`), dựng bằng CÙNG hàm với trace (`api/matched_rules.py`). Dòng không có
`all_matched` dạng list / không có dòng → BỎ khoá (`response_model_exclude_unset`; mọi trường khác luôn gán tường minh). Đọc TRƯỚC
`mark_viewed` (như `affected`).
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
from app.api.matched_rules import MatchedRule, matched_rules, rule_index
from app.auth.authz import ApprovalParties, RoleAs, approval_role
from app.auth.deps import deny, get_auth, require
from app.auth.models import Principal
from app.auth.ports import IdentityUnavailable
from app.core.hashing import hash_action
from app.domain.action import Action
from app.domain.approval import invalid_reason, manager_chain
from app.domain.messages import ReasonCode
from app.domain.states import S_PENDING_APPROVAL
from app.domain.ticket_state import RiskDecision
from app.graph.late_event import record_late, start_event
from app.settings import get_action_metadata

log = logging.getLogger(__name__)
router = APIRouter()

NOTE_MAX = 1000
INBOX_LIMIT = 50  # P5
REQUEST_SUMMARY_MAX = 500  # P6: tickets.redacted_request[:500]
NOT_FOUND = "not_found"
type InboxStatus = Literal["pending", "approved", "rejected", "timeout"]
type LateReason = Literal["expired", "already_decided", "parent_closed"]


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
    """Người GỬI yêu cầu. Q3 (soát 12/11, agent 13 V3): + `user_id` (từ ticket, phía server) và `full_name` (bảng `users`; chưa có
    dòng → null) để người duyệt biết AI gửi — nhất là khi người bị tác động khác người gửi. `role`/`department`: bản chụp B1 (B15 §4)."""

    user_id: str
    full_name: str | None
    role: str
    department: str | None


class ProcedureRef(BaseModel):
    doc_id: str
    title: str | None


class ManagerRef(BaseModel):
    """Quản lý của người bị tác động: `known` ⇔ có dòng `users` VÀ `manager_id` khác NULL; `unknown` → `user_id`/`full_name` null.
    `full_name` null khi `known` mà dòng của sếp chưa có (chưa từng đăng nhập)."""

    status: Literal["known", "unknown"]
    user_id: str | None
    full_name: str | None


class AffectedView(BaseModel):
    """Người BỊ TÁC ĐỘNG (`Action.requested_for`) — có thể khác người gửi (account/access, slot `target_user`)."""

    user_id: str
    is_requester: bool
    department: str | None  # không có dòng `users` → null
    manager: ManagerRef


class RiskView(RiskDecision):
    """`RiskDecision` (cùng tên trường, cùng enum — một nguồn) + 2 cờ suy ra; FE ghép chữ hiển thị từ các cờ này."""

    calibrated: bool  # calibrated_prob khác null
    auto_allowed: bool  # route == "AUTO"


class ApprovalView(BaseModel):
    """Phiếu cho người duyệt (P6) — ĐÚNG 14 khoá (12 khoá P6 + F6 `affected`, `risk_view`); `action`/`facts` là object ĐÃ BĂM
    (G4-13)."""

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
    affected: AffectedView
    risk_view: RiskView | None  # None ⇔ `risk` None
    matched_rules: list[MatchedRule] | None = None  # P3 tuần 8: chỉ gán khi có dữ liệu B13/B14; không gán → route bỏ khoá


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


async def _affected(users: UserDirectory, affected_id: str, requester_id: str) -> AffectedView:
    """F6: người bị tác động + quản lý theo bảng `users`. Lỗi đọc KHÔNG nuốt thành `unknown` (lỗi hệ thống ≠ "không biết")."""
    me = await users.get_user(affected_id)
    manager = ManagerRef(status="unknown", user_id=None, full_name=None)
    if me is not None and me.manager_id is not None:
        boss = await users.get_user(me.manager_id)
        manager = ManagerRef(status="known", user_id=me.manager_id, full_name=boss.full_name if boss else None)
    return AffectedView(
        user_id=affected_id, is_requester=affected_id == requester_id, department=me.department if me else None, manager=manager,
    )  # fmt: skip


def _risk_view(raw: Any) -> RiskView | None:
    if raw is None:
        return None
    risk = RiskDecision.model_validate(raw)  # checkpoint giữ model hoặc dict — hỏng thì lỗi nổi lên, không đoán
    return RiskView(**dict(risk), calibrated=risk.calibrated_prob is not None, auto_allowed=risk.route == "AUTO")


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
        elif ticket is not None and ticket.parent_ticket_id is not None:
            parent = await desk.tickets.get(ticket.parent_ticket_id)
            if parent is not None and parent.final_state is not None:
                late = "parent_closed"  # Q4 (soát 12/11, V11): cha đã kết thúc → không cho con chạy tiếp; phiếu giữ pending
        ticket_id, actual = a.ticket_id, (snap.values or {}).get("status")
        first_viewed_at = a.first_viewed_at
    if late is not None:
        await record_late(
            desk.runner, ticket_id, expected_status=S_PENDING_APPROVAL, actual_status=actual,
            event_kind="decision", source="user",
            extra={"approval_id": approval_id, "clicked_by": p.user_id, "reason": late},
        )  # fmt: skip
        raise HTTPException(409, "Yêu cầu đã chuyển sang bước khác")
    if (gone := await _approver_gone(request, p)) is not None:
        await deny(request, p, "approval:decide", approval_id=approval_id, reason=f"approver_{gone}")
        raise HTTPException(403, "forbidden")

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


async def _approver_gone(request: Request, p: Principal) -> str | None:
    """Q2: lý do người quyết KHÔNG còn hợp lệ trong AD (hợp lệ làm l1 hoặc Trưởng BP = như B17), None = còn hợp lệ. AD lỗi → 503."""
    try:
        ad = await get_auth(request).idp.get_user(p.user_id)
    except IdentityUnavailable:
        log.warning("quyết phiếu: AD không trả lời khi kiểm người duyệt — 503")
        raise HTTPException(503, "identity_unavailable") from None
    reason = invalid_reason(ad, "l1")
    if reason is None or invalid_reason(ad, "manager") is None:
        return None
    return reason


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


@router.get("/api/approvals/{approval_id}", response_model=ApprovalView, response_model_exclude_unset=True)
async def view_approval(
    approval_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("approval:decide"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> ApprovalView:
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
    # F6: đọc/dựng TRƯỚC mark_viewed — lỗi ở đây không để lại `first_viewed_at`
    affected = await _affected(desk.users, action.requested_for, ticket.requester_id if ticket else "")
    risk_view = _risk_view(values.get("risk"))
    pm = await desk.approvals.policy_matches(a.ticket_id, a.created_at)
    matched = matched_rules(pm.all_matched, pm.matched_rule_id, rule_index()) if pm is not None else None
    if role is not None:  # chỉ người được giao / dự phòng đủ điều kiện ghi lần xem đầu; manager xem không ghi
        await desk.approvals.mark_viewed(approval_id, desk.clock.now())
    meta = (get_action_metadata().root.get(str(values.get("intent"))) or {}).get(action.type)
    procedure = None
    if meta is not None:
        procedure = ProcedureRef(doc_id=meta.procedure_doc, title=await desk.approvals.procedure_title(meta.procedure_doc))
    rc = _as_json(values.get("requester_context")) or {}
    requester_id = ticket.requester_id if ticket else str(rc.get("user_id") or "")
    sender = await desk.users.get_user(requester_id) if requester_id else None  # lỗi đọc nổi lên như `_affected`
    requester = RequesterView(user_id=requester_id, full_name=sender.full_name if sender else None,
                              role=str(rc.get("role") or ""), department=rc.get("department"))  # fmt: skip
    return ApprovalView(
        approval_id=a.approval_id, ticket_id=a.ticket_id, status=a.status, deadline=a.deadline, requester=requester,
        request_summary=(ticket.redacted_request if ticket else "")[:REQUEST_SUMMARY_MAX],
        action=action.model_dump(mode="json"), action_plan_hash=a.action_plan_hash, risk=_as_json(values.get("risk")),
        facts=dict(action.facts), role_as=role or "viewer", procedure=procedure, affected=affected, risk_view=risk_view,
        **({"matched_rules": matched} if matched is not None else {}),
    )  # fmt: skip
