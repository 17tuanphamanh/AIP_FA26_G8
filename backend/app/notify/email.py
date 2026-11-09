"""Soạn email (notify-email) — hàm THUẦN, không DB, không mạng.

- Loại email (`EmailKind`, khớp CHECK `email_outbox.kind` của migration 0012): tin người dùng theo bước gọi `notify_user` —
  B10 `answer` (câu trả lời cuối của ticket thông tin), B16 `rejection`, B18 `result`, B20 `escalation`. B11 (câu hỏi bổ sung) và
  mọi bước khác KHÔNG có trong bảng → không email (`user_kind` trả None). Người duyệt: `new` (B15), `reminder_1`/`reminder_2`
  (worker nhắc 50 %/80 %).
- Tiêu đề: `[IT Service Desk] <tiêu đề theo loại> — <mã ticket rút gọn>` (8 ký tự đầu của `ticket_id`, chữ hoa).
- Thân: ĐÚNG văn bản chat đã qua guard + dòng `Xem chi tiết: <EMAIL_LINK_BASE_URL>/<đường dẫn frontend theo vai>` — người dùng
  `/chat/<ticket_id>`, người duyệt `/approvals/<approval_id>` (route của `frontend/src/App.tsx`). Người duyệt không có tin chat → thân
  theo mẫu cố định, không chữ người dùng.
- `mask_address`: dạng che cho log / API quản trị (`a***@congty-abc.vn`) — không bao giờ trả địa chỉ đầy đủ.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo

type EmailKind = Literal[
    "answer", "rejection", "result", "escalation", "approval_new", "approval_reminder_1", "approval_reminder_2"
]
type ApproverNoticeKind = Literal["new", "reminder_1", "reminder_2"]

SUBJECT_PREFIX: Final = "[IT Service Desk]"
SHORT_ID_LEN: Final = 8

# KHÔNG có "B11": câu hỏi bổ sung không gửi email (người dùng trả lời trong chat).
USER_KIND_BY_STEP: Final[Mapping[str, EmailKind]] = {
    "B10": "answer", "B16": "rejection", "B18": "result", "B20": "escalation",
}  # fmt: skip
APPROVER_KIND: Final[Mapping[ApproverNoticeKind, EmailKind]] = {
    "new": "approval_new", "reminder_1": "approval_reminder_1", "reminder_2": "approval_reminder_2",
}  # fmt: skip
TITLES: Final[Mapping[EmailKind, str]] = {
    "answer": "Câu trả lời cho yêu cầu của bạn",
    "rejection": "Yêu cầu của bạn không được phê duyệt",
    "result": "Kết quả xử lý yêu cầu của bạn",
    "escalation": "Yêu cầu của bạn đã được chuyển cho kỹ thuật viên",
    "approval_new": "Có yêu cầu mới cần bạn phê duyệt",
    "approval_reminder_1": "Nhắc lần 1: yêu cầu đang chờ bạn phê duyệt",
    "approval_reminder_2": "Nhắc lần 2: yêu cầu sắp hết hạn phê duyệt",
}
_APPROVER_LEAD: Final[Mapping[EmailKind, str]] = {
    "approval_new": "Có một yêu cầu mới cần bạn phê duyệt",
    "approval_reminder_1": "Nhắc lần 1: một yêu cầu vẫn đang chờ bạn phê duyệt",
    "approval_reminder_2": "Nhắc lần 2: một yêu cầu sắp hết hạn phê duyệt",
}
DISPLAY_TZ: Final = ZoneInfo("Asia/Ho_Chi_Minh")


def user_kind(step: str) -> EmailKind | None:
    """Loại email theo bước gọi `notify_user`; None = bước này không gửi email (B11, bước lạ)."""
    return USER_KIND_BY_STEP.get(step)


def short_ticket(ticket_id: str) -> str:
    return ticket_id[:SHORT_ID_LEN].upper()


def subject(kind: EmailKind, ticket_id: str | None) -> str:
    tail = f" — {short_ticket(ticket_id)}" if ticket_id else ""
    return f"{SUBJECT_PREFIX} {TITLES[kind]}{tail}"


def user_link(base_url: str, ticket_id: str) -> str:
    return f"{base_url}/chat/{ticket_id}"


def approver_link(base_url: str, approval_id: str) -> str:
    return f"{base_url}/approvals/{approval_id}"


def with_link(text: str, url: str) -> str:
    return f"{text.rstrip()}\n\nXem chi tiết: {url}"


def approver_text(kind: EmailKind, ticket_id: str | None, deadline: datetime | None) -> str:
    """Thân thông báo người duyệt (không có tin chat): chỉ mã ticket + hạn duyệt (giờ Việt Nam)."""
    parts = [_APPROVER_LEAD[kind] + (f" (ticket {short_ticket(ticket_id)})." if ticket_id else ".")]
    if deadline is not None:
        parts.append(f"Hạn phê duyệt: {deadline.astimezone(DISPLAY_TZ):%H:%M %d/%m/%Y} (giờ Việt Nam).")
    return " ".join(parts)


def mask_address(address: str | None) -> str | None:
    """`nguyen.van.a@congty-abc.vn` → `n***@congty-abc.vn`; không có `@` → `***`."""
    if not address:
        return None
    local, sep, domain = address.rpartition("@")
    if not sep or not local:
        return "***"
    return f"{local[0]}***@{domain}"
