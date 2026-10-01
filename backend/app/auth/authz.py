"""Tầng 3 — kiểm theo từng bản ghi (P6 mục 5.3). Hàm thuần: route (Phase 2/4) gọi các hàm này rồi
tự trả mã HTTP và ghi `permission_denied`. Nhận Protocol theo cấu trúc để không phụ thuộc bảng/ORM.

- `can_read_ticket` sai → route trả **404**, không 403: không lộ ticket có tồn tại (D-02, TC30).
- `can_decide_approval` = `may_decide_as` (sai → 403) + còn `pending`, chưa quá hạn (route duyệt tách
  riêng phần này → 409 + `late_event`, TC27 — 2b-3 Q3).
- `approval_role` (Phase 4 4c P4, TQ-9): MỘT định nghĩa "tôi quyết/xem phiếu này với vai trò gì" cho route quyết, xem phiếu, hộp
  thư — `primary` (người được giao) | `backup` (dự phòng, CHỈ sau nhắc 2 — Q-4-O) | None; luôn kèm không xung đột lợi ích.
- `can_close_escalation` → "forbidden" (403) hoặc "unprocessable" (422: L2 hoàn tất ca deny).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

type RoleAs = Literal["primary", "backup"]

from app.auth.models import Principal
from app.domain.action import Action
from app.domain.approval import ConflictType, conflict_type
from app.domain.context import RequesterContext


class TicketLike(Protocol):
    @property
    def requester_id(self) -> str: ...


class ApprovalLike(Protocol):
    @property
    def approver_id(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def deadline(self) -> datetime: ...
    @property
    def backup_approver_id(self) -> str | None: ...
    @property
    def reminder_2_at(self) -> datetime | None: ...


@dataclass(frozen=True)
class ApprovalParties:
    """Các bên để kiểm 3 xung đột lợi ích [Chốt B15]. `approver_chain` = chuỗi quản lý của người quyết (sếp trực tiếp trước,
    ≤ 5 cấp — Q-4-R; route dựng từ bảng `users`, B15 từ AD). `action` None = state không có hành động."""

    requester_id: str
    approver_chain: tuple[str, ...]
    action: Action | None


class EscalationLike(Protocol):
    @property
    def is_deny_case(self) -> bool: ...


def can_read_ticket(p: Principal, t: TicketLike) -> bool:
    return t.requester_id == p.user_id or p.has("ticket:read:any")


def approval_conflict(approver_id: str, parties: ApprovalParties) -> ConflictType | None:
    """`self` | `boss_of_approver` | `targets_approver` | None (P7 2.6 conflict_type) — MỘT định nghĩa dùng chung với B15
    (`domain.approval.conflict_type`, phase4 5.1 P4)."""
    return conflict_type(parties.requester_id, approver_id, parties.approver_chain, parties.action)


def approval_role(p: Principal, a: ApprovalLike, parties: ApprovalParties) -> RoleAs | None:
    """Có `approval:decide` + (người được giao → `primary` | dự phòng VÀ đã nhắc lần 2 → `backup`) + không xung đột (4b P4). None =
    không được quyết/xem như người duyệt."""
    if not p.has("approval:decide"):
        return None
    role: RoleAs
    if a.approver_id == p.user_id:
        role = "primary"
    elif a.backup_approver_id is not None and a.backup_approver_id == p.user_id and a.reminder_2_at is not None:
        role = "backup"
    else:
        return None
    return role if approval_conflict(p.user_id, parties) is None else None


def may_decide_as(p: Principal, a: ApprovalLike, parties: ApprovalParties) -> bool:
    """Phần "ai" của `can_decide_approval` (= `approval_role` khác None): có quyền, người được giao HOẶC dự phòng sau nhắc 2, không xung
    đột → sai = 403. Phần "khi nào" (còn `pending`, chưa quá hạn) route duyệt kiểm riêng → 409 (TC27, 2b-3 Q3)."""
    return approval_role(p, a, parties) is not None


def can_decide_approval(
    p: Principal, a: ApprovalLike, parties: ApprovalParties, *, now: datetime
) -> bool:
    return may_decide_as(p, a, parties) and a.status == "pending" and now < a.deadline


def can_override(p: Principal, t: TicketLike) -> bool:
    return p.has("decision:override") and p.user_id != t.requester_id


def can_close_escalation(
    p: Principal, e: EscalationLike, result: str
) -> Literal["allow", "forbidden", "unprocessable"]:
    if not p.has("escalation:handle"):
        return "forbidden"
    if e.is_deny_case and result == "completed":  # L2 không hoàn tất hành động bị deny [Chốt]
        return "unprocessable"
    return "allow"


def can_read_audit(p: Principal, *, approver_id: str | None) -> bool:
    """`approver_id` None = xem toàn bộ; có giá trị = phần audit của phiếu người đó đã duyệt."""
    if p.has("audit:read:all"):
        return True
    return p.has("audit:read:own") and approver_id == p.user_id


@dataclass(frozen=True)
class ToolTarget:
    user_id: str
    target_is_other: bool  # gắn vào ngữ cảnh cho M5 (D-16)


def scope_tool_target(ctx: RequesterContext, target: str | None) -> ToolTarget:
    """Tool chẩn đoán mặc định chỉ tra người gửi; tra người khác thì đánh dấu cho M5 [Đề xuất D-16]."""
    if target is None or target == ctx.user_id:
        return ToolTarget(ctx.user_id, False)
    return ToolTarget(target, True)
