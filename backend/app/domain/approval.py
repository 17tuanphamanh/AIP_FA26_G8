"""Chọn người duyệt + xung đột lợi ích (Phase 4 chặng 4b — phase4 3.1, 5.1 P1–P4, P6). THUẦN: không I/O. Tra AD / bảng
`users` đi qua hàm do nơi gọi TIÊM vào — B15: registry `ad_get_user` (bước `B15_APPROVER`); route duyệt: bảng `users`.

- `conflict_type` là MỘT định nghĩa cho cả B15 lẫn route duyệt (`auth/authz.approval_conflict` gọi lại): `self` →
  `boss_of_approver` (người gửi nằm trong CHUỖI quản lý của ứng viên, ≤ 5 cấp — Q-4-R) → `targets_approver`
  (`action.requested_for` là ứng viên) → None.
- `valid(ad, role)`: `active` VÀ nhóm AD ra đúng role (`l1` cho primary/backup, `manager` cho head). `probation` không hợp lệ;
  không tìm thấy (`None`) = `not_found`, KHÔNG phải lỗi. Lỗi hệ thống khi tra → `ApproverLookupError` (B15 → E2).
- `choose_approver` theo [Chốt] B15 (Q-4-L): xung đột → Trưởng BP; hết L1 hợp lệ → Trưởng BP; Trưởng BP cũng xung đột/không
  hợp lệ → `Refuse` (E5 `no_valid_approver`, 0 phiếu). Mỗi người tra tối đa một lần (`memo_lookup`).
- `next_reminder` (Phase 4 4c P3): mốc nhắc 50 % / 80 % của khoảng `created_at → deadline`. Đã qua mốc 2 thì KHÔNG BAO GIỜ nhắc 1
  (worker chết lâu → chỉ nhắc 2); tới hạn thì không nhắc gì (hết hạn → E6, không nhắc muộn).
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.domain.action import Action
from app.domain.context import AdAttributes, role_from_groups

ConflictType = Literal["self", "boss_of_approver", "targets_approver"]
InvalidReason = Literal["not_found", "inactive", "wrong_group"]
RejectReason = Literal["not_found", "inactive", "wrong_group", "self", "boss_of_approver", "targets_approver"]
ChoiceReason = Literal["normal", "conflict", "no_valid_l1"]
ApproverRole = Literal["l1", "manager"]
ReminderN = Literal[1, 2]

MAX_CHAIN_DEPTH = 5  # Q-4-R: chuỗi quản lý tối đa 5 cấp (cùng giới hạn `_ensure_manager` của auth)
ROSTER_ID = r"^[a-z0-9_]{3,64}$"  # P1
# 4c P3 [Chốt B15-B16 §4: nhắc 50 % / 80 % SLA] — MỘT nguồn cho `next_reminder` và câu lọc `SqlDeadlineStore.due_reminders`.
REMINDER_FRACTIONS: dict[ReminderN, float] = {1: 0.5, 2: 0.8}
type RosterId = Annotated[str, StringConstraints(pattern=ROSTER_ID)]

# Tra một người: None = không có (404/rỗng); lỗi hệ thống → ném `ApproverLookupError`.
type Lookup[U: AdAttributes] = Callable[[str], Awaitable[U | None]]
# Sếp trực tiếp của một người: None = không có sếp HOẶC không tìm thấy người đó (dừng chuỗi); lỗi → ném.
type FetchManager = Callable[[str], Awaitable[str | None]]


class ApproverLookupError(Exception):
    """Tra người duyệt/chuỗi quản lý lỗi HỆ THỐNG (sau retry) — khác "không tìm thấy" (E2 ≠ E3/E5)."""


class Roster(BaseModel):
    """Một dòng `config/approvers.yaml` (P1): người duyệt chính, dự phòng (L1) và Trưởng BP (manager) của một intent. Khoá lạ,
    id sai mẫu, hai vai trùng người → không nạp (backend/worker từ chối khởi động)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: RosterId
    backup: RosterId
    head: RosterId

    @model_validator(mode="after")
    def _three_people(self) -> "Roster":
        if len({self.primary, self.backup, self.head}) != 3:
            raise ValueError("approvers: primary, backup, head phải là 3 người khác nhau")
        return self


@dataclass(frozen=True)
class Rejected:
    user_id: str
    reason: RejectReason


@dataclass(frozen=True)
class Choice[U: AdAttributes]:
    approver: U
    backup: U | None
    conflict_detected: bool
    conflict_type: ConflictType | None
    reason: ChoiceReason
    rejected: tuple[Rejected, ...] = ()

    @property
    def to_sync(self) -> tuple[U, ...]:
        """Người cần có dòng `users` TRƯỚC khi tạo phiếu (FK `approver_id`, `backup_approver_id` — Q-4-N)."""
        return (self.approver,) if self.backup is None else (self.approver, self.backup)


@dataclass(frozen=True)
class Refuse:
    rejected: tuple[Rejected, ...] = field(default=())
    reason_detail: Literal["no_valid_approver"] = "no_valid_approver"


def action_has_device_target(action: Action) -> bool:
    """P6: hành động nhắm vào một máy (`target` dạng `device:…`)."""
    return action.target.startswith("device:")


def invalid_reason(ad: AdAttributes | None, role: ApproverRole) -> InvalidReason | None:
    """None = hợp lệ để duyệt với vai `role`; ngược lại lý do bị loại (P2). `probation` cũng là `inactive`."""
    if ad is None:
        return "not_found"
    if ad.employment_status != "active":
        return "inactive"
    if role_from_groups(ad.groups) != role:
        return "wrong_group"
    return None


def valid(ad: AdAttributes | None, role: ApproverRole) -> bool:
    return invalid_reason(ad, role) is None


def memo_lookup[U: AdAttributes](lookup: Lookup[U]) -> Lookup[U]:
    """Bọc `lookup`: mỗi `user_id` gọi tối đa một lần (kết quả None cũng nhớ); lỗi KHÔNG nhớ (ném lại mỗi lần)."""
    seen: dict[str, U | None] = {}

    async def cached(user_id: str) -> U | None:
        if user_id not in seen:
            seen[user_id] = await lookup(user_id)  # ném → không ghi gì vào `seen`
        return seen[user_id]

    return cached


async def manager_chain(user_id: str, first_manager_id: str | None, fetch_manager: FetchManager) -> tuple[str, ...]:
    """Chuỗi quản lý của `user_id`: (sếp trực tiếp, sếp của sếp, …) — tối đa `MAX_CHAIN_DEPTH` người; dừng khi hết sếp, không tìm
    thấy, hoặc gặp lại người đã có (vòng, kể cả chính `user_id`). Lỗi của `fetch_manager` lan ra."""
    chain: list[str] = []
    current = first_manager_id
    while current is not None and current != user_id and current not in chain:
        chain.append(current)
        if len(chain) == MAX_CHAIN_DEPTH:
            break
        current = await fetch_manager(current)
    return tuple(chain)


def conflict_type(requester_id: str, cand_id: str, cand_chain: Sequence[str], action: Action | None) -> ConflictType | None:
    """`self` → `boss_of_approver` (requester ∈ chuỗi của ứng viên) → `targets_approver` (`action.requested_for == cand_id`)."""
    if requester_id == cand_id:
        return "self"
    if requester_id in cand_chain:
        return "boss_of_approver"
    if action is not None and action.requested_for == cand_id:
        return "targets_approver"
    return None


async def choose_approver[U: AdAttributes](
    roster: Roster, requester_id: str, action: Action, lookup: Lookup[U]
) -> Choice[U] | Refuse:
    """Thuật toán phase4 3.1 (không gồm chốt phòng thủ P6 — node làm TRƯỚC mọi lời tra). `rejected` theo thứ tự đánh giá, mỗi
    người một lần. Lỗi tra (kể cả giữa chuỗi quản lý) → `ApproverLookupError` lan ra — KHÔNG coi là "không hợp lệ"."""
    lookup = memo_lookup(lookup)
    rejected: list[Rejected] = []

    def reject(user_id: str, reason: RejectReason) -> None:
        if all(r.user_id != user_id for r in rejected):
            rejected.append(Rejected(user_id, reason))

    async def fetch_manager(user_id: str) -> str | None:
        ad = await lookup(user_id)
        return None if ad is None else ad.manager_id

    async def conflict_of(cand: U) -> ConflictType | None:
        chain = await manager_chain(cand.user_id, cand.manager_id, fetch_manager)
        return conflict_type(requester_id, cand.user_id, chain, action)

    async def usable_head() -> U | None:
        """Trưởng BP hợp lệ (vai manager) và không xung đột; không thì ghi vào `rejected`, trả None."""
        head = await lookup(roster.head)
        reason = invalid_reason(head, "manager")
        if head is None or reason is not None:
            reject(roster.head, reason or "not_found")
            return None
        head_conflict = await conflict_of(head)
        if head_conflict is not None:
            reject(roster.head, head_conflict)
            return None
        return head

    valid_l1: list[U] = []
    for user_id in (roster.primary, roster.backup):
        ad = await lookup(user_id)
        reason = invalid_reason(ad, "l1")
        if ad is not None and reason is None:
            valid_l1.append(ad)
        else:
            reject(user_id, reason or "not_found")
    first = valid_l1[0] if valid_l1 else None
    conflict = await conflict_of(first) if first is not None else None
    if first is None or conflict is not None:  # [Chốt] xung đột → Trưởng BP; hết L1 hợp lệ → Trưởng BP
        if first is not None and conflict is not None:
            reject(first.user_id, conflict)
        head = await usable_head()
        if head is None:
            return Refuse(tuple(rejected))
        return Choice(
            approver=head, backup=None, conflict_detected=conflict is not None, conflict_type=conflict,
            reason="conflict" if conflict is not None else "no_valid_l1", rejected=tuple(rejected),
        )  # fmt: skip
    backup: U | None = None
    for cand in valid_l1[1:]:
        cand_conflict = await conflict_of(cand)
        if cand_conflict is None:
            backup = cand
            break
        reject(cand.user_id, cand_conflict)
    if backup is None:
        backup = await usable_head()
    return Choice(
        approver=first, backup=backup, conflict_detected=False, conflict_type=None, reason="normal",
        rejected=tuple(rejected),
    )  # fmt: skip


def next_reminder(
    created_at: datetime, deadline: datetime, reminder_1_at: datetime | None, reminder_2_at: datetime | None, now: datetime
) -> ReminderN | None:
    """Nhắc nào đến lượt lúc `now` (biên tính `>=`): `now >= deadline` → None; qua mốc 2 → 2 nếu chưa nhắc 2, không thì None
    (KHÔNG nhắc 1 sau mốc 2); qua mốc 1 → 1 nếu chưa nhắc 1. Thuần — worker đánh dấu nguyên tử bằng `mark_reminder_once`."""
    if now >= deadline:
        return None
    span = deadline - created_at
    if now >= created_at + span * REMINDER_FRACTIONS[2]:
        return 2 if reminder_2_at is None else None
    if now >= created_at + span * REMINDER_FRACTIONS[1]:
        return 1 if reminder_1_at is None else None
    return None
