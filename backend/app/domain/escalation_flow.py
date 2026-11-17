"""Vòng xử lý sau khi chuyển IT (D-99, Tuấn Anh chốt 17/11/2026: phần 1–5, L3 = Trưởng bộ phận IT) — luật THUẦN, một nguồn cho route,
store, thông báo và giao diện.

1. Nhận ca: người xử lý cấp đang giữ ca (L1/L2 với cấp 2 — `escalation:handle`; Trưởng IT với cấp 3 — `escalation:handle:l3`) bấm "Nhận ca" →
   `assigned_to/assigned_at`. Ca đã có người khác nhận → 409 (không giành ca; muốn đổi người thì người đang giữ chuyển cấp hoặc đóng).
   Người gửi ticket không tự nhận / tự đóng / tự chuyển ca của mình (như Q5a).
2. Đóng ca kèm lời nhắn cho người dùng (`user_message`, tuỳ chọn, ≤ 500 ký tự, đã che + qua cổng tin trả lời) — tách khỏi `close_note`
   (ghi chú nội bộ cho IT, như cũ).
3. Chuyển cấp 3 (chỉ từ cấp 2, ca còn mở): `raise_target` ∈ {it_manager, vendor} + ghi chú lý do (nội bộ, đã che) → `tier = 3`, bỏ người
   nhận cũ. Ca cấp 3 rời hàng đợi L2, vào hàng đợi Trưởng IT; người dùng được báo đã chuyển cấp cao hơn và vì sao (câu cố định theo
   `raise_target`, không chép ghi chú nội bộ).
4. `reopened_as_new` tạo ticket THẬT (phương án (A) của B20 cổng 7): cùng người gửi, cùng nội dung đã che, chạy lại từ đầu.
5. Hạn xử lý theo mức ưu tiên (`exit_code_priority.rank`): `due_at` = mốc bắt đầu của cấp đang giữ (tạo ca, hoặc lúc chuyển cấp 3) +
   số giờ theo bảng dưới (giờ thực, chưa trừ ngoài giờ — demo). Quá hạn chỉ để HIỂN THỊ, không tự đổi gì.
"""

from datetime import datetime, timedelta
from typing import Final, Literal, get_args

type RaiseTarget = Literal["it_manager", "vendor"]
RAISE_TARGETS: Final = get_args(RaiseTarget.__value__)
type Tier = Literal[2, 3]

USER_MESSAGE_MAX: Final = 500  # = CHECK `escalations.user_message` (0018)
RAISE_NOTE_MAX: Final = 1000  # = CHECK `escalations.raise_note` (0018)

# rank (bảng `exit_code_priority` của 0001) → giờ xử lý ở cấp 2. Rank lạ → `DEFAULT_SLA_HOURS`.
SLA_HOURS_BY_RANK: Final = {1: 2, 2: 1, 3: 4, 4: 4, 5: 8, 6: 24}
DEFAULT_SLA_HOURS: Final = 24
L3_SLA_HOURS: Final = 24  # ca cấp 3 tính lại từ lúc chuyển cấp


def due_at(
    *, created_at: datetime, rank: int, tier: int, raised_at: datetime | None
) -> datetime:
    if tier == 3 and raised_at is not None:
        return raised_at + timedelta(hours=L3_SLA_HOURS)
    return created_at + timedelta(hours=SLA_HOURS_BY_RANK.get(rank, DEFAULT_SLA_HOURS))


def is_overdue(*, due: datetime, now: datetime, closed_at: datetime | None) -> bool:
    return closed_at is None and now > due
