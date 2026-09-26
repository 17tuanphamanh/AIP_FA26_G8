"""Tầng 3 — kiểm theo từng bản ghi (P6 mục 5.3). Hàm thuần: route (Phase 2/4) gọi các hàm này rồi
tự trả mã HTTP và ghi `permission_denied`. Nhận Protocol theo cấu trúc để không phụ thuộc bảng/ORM.

- `can_read_ticket` sai → route trả **404**, không 403: không lộ ticket có tồn tại (D-02, TC30).
- `can_decide_approval` = `may_decide_as` (sai → 403) + còn `pending`, chưa quá hạn (route duyệt tách
  riêng phần này → 409 + `late_event`, TC27 — 2b-3 Q3).
- `can_close_escalation` → "forbidden" (403) hoặc "unprocessable" (422: L2 hoàn tất ca deny).
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.auth.models import Principal
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


@dataclass(frozen=True)
class ApprovalParties:
    """Các bên để kiểm 3 xung đột lợi ích [Chốt B15]. `approver_manager_id` None = không biết."""

    requester_id: str
    approver_manager_id: str | None
    action_targets: Collection[str]  # user_id mà hành động nhắm tới (target/requested_for)


class EscalationLike(Protocol):
    @property
    def is_deny_case(self) -> bool: ...


def can_read_ticket(p: Principal, t: TicketLike) -> bool:
    return t.requester_id == p.user_id or p.has("ticket:read:any")


def approval_conflict(approver_id: str, parties: ApprovalParties) -> str | None:
    """`self` | `boss_of_approver` | `targets_approver` | None (P7 2.6 conflict_type)."""
    if parties.requester_id == approver_id:
        return "self"
    if parties.approver_manager_id is not None and parties.approver_manager_id == parties.requester_id:
        return "boss_of_approver"
    if approver_id in parties.action_targets:
        return "targets_approver"
    return None


def may_decide_as(p: Principal, a: ApprovalLike, parties: ApprovalParties) -> bool:
    """Phần "ai" của `can_decide_approval`: có quyền, đúng người được giao, không xung đột → sai = 403.
    Phần "khi nào" (còn `pending`, chưa quá hạn) route duyệt kiểm riêng → 409 (TC27, 2b-3 Q3)."""
    return (
        p.has("approval:decide")
        and a.approver_id == p.user_id
        and approval_conflict(p.user_id, parties) is None
    )


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
