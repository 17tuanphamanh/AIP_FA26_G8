"""`GET /api/me/notifications` — thông báo trong app cho nhân viên (P10 mục 3.1 [Chốt 16.1]).

Suy ra từ dữ liệu sẵn có (`db/notifications.py`): phiếu duyệt đã quyết và ca L2 đã đóng, CHỈ ticket của người đang đăng nhập (lọc
ở SQL). Server không lưu "đã đọc". Quyền: `ticket:read:own` (mọi vai trò). Thứ tự kiểm: 401 → 403 → 422 tham số → 503 nguồn.

`text` là câu tiếng Việt thường, ghép từ bảng cố định bên dưới — không mã E*/R*/B*/S_*, không tên trường, không mã luật:
- Ca L2 đã đóng → câu theo `result` (`CLOSED_TEXT`) cho MỌI mã thoát. D-98 (TA chốt 17/11) bỏ câu trung tính riêng cho ca nghi tấn công
  (E0, E1 `injection_suspected`): người dùng được biết kết quả xử lý như mọi ca khác.
- Lý do từ chối của L1 (`approvals.note`, đã che lúc ghi — `approval_wait.py`) chỉ vào `text` khi qua `OutputGuard.violation`, đúng cổng
  của tin từ chối B16; vi phạm → bỏ câu ghi chú.
- D-99 (17/11): thêm `escalation_claimed` (đã có người nhận ca) và `escalation_raised` (đã chuyển cấp 3 — câu theo `raise_target`, không
  chép ghi chú nội bộ); ca đóng kèm lời nhắn người dùng (`escalations.user_message`, đã che lúc ghi) khi qua `OutputGuard` lần nữa; ca
  `reopened_as_new` có ticket mới → câu "đã mở lại thành yêu cầu mới" + `new_ticket_id` thật (trước D-99 luôn null).
"""

from datetime import UTC
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.alerts import (  # CHUNG thân lỗi với alerts: một schema OpenAPI, không tên trùng
    ErrorDetail,
    InvalidRequestBody,
)
from app.api.errors import InvalidRequest
from app.auth.deps import require
from app.auth.models import Principal
from app.db.notifications import (
    NotificationRow,
    NotificationSource,
    decode_cursor,
    encode_cursor,
)
from app.guard.output import OutputGuard

router = APIRouter()

LIMIT_DEFAULT = 20
LIMIT_MAX = 50
AFTER_MAX = 512

type Kind = Literal["approval_decided", "escalation_closed", "escalation_claimed", "escalation_raised"]
type Result = Literal["approved", "rejected", "completed", "confirmed_denial", "reopened_as_new", "in_progress", "raised"]

APPROVED_TEXT = "Yêu cầu của bạn đã được phê duyệt. Hệ thống đang thực hiện và sẽ báo kết quả cho bạn."
REJECTED_TEXT = "Yêu cầu của bạn chưa được duyệt."
NOTE_PREFIX = "Ghi chú của người duyệt:"  # như `domain.messages.rejection_text`
CLOSED_TEXT: dict[str, str] = {
    "completed": "Bộ phận IT đã xử lý xong yêu cầu của bạn.",
    "confirmed_denial": "Bộ phận IT đã xem xét và xác nhận không thực hiện yêu cầu này.",
    "reopened_as_new": "Kỹ thuật viên đề nghị bạn gửi một yêu cầu mới cho việc này.",
}
# D-99
REOPENED_TEXT = "Kỹ thuật viên đã mở lại yêu cầu của bạn thành một yêu cầu mới, hệ thống đang xử lý lại từ đầu."
USER_MESSAGE_PREFIX = "Lời nhắn từ bộ phận IT:"
CLAIMED_TEXT: dict[int, str] = {
    2: "Kỹ thuật viên đã nhận yêu cầu của bạn và đang xử lý.",
    3: "Trưởng bộ phận IT đã nhận yêu cầu của bạn và đang xử lý.",
}
RAISED_TEXT: dict[str, str] = {
    "it_manager": "Yêu cầu của bạn cần Trưởng bộ phận IT quyết định, nên kỹ thuật viên đã chuyển lên cấp cao hơn. Kết quả sẽ báo bạn tại đây.",
    "vendor": (
        "Yêu cầu của bạn cần bộ phận chuyên trách hoặc nhà cung cấp xử lý, nên kỹ thuật viên đã chuyển tiếp. Kết quả sẽ báo bạn tại đây."
    ),
}


class NotificationView(BaseModel):
    id: str  # "appr:<approval_id>" | "esc:<escalation_id>"
    kind: Kind
    ticket_id: str  # ticket con → id của ticket CHA (D-31)
    text: str
    result: Result
    new_ticket_id: str | None  # D-99: ticket mới của `reopened_as_new` (ca đóng trước D-99 / tạo lỗi → null)
    created_at: str  # ISO 8601 có múi giờ (UTC)


class NotificationPage(BaseModel):
    items: list[NotificationView]
    next_cursor: str | None


ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 422: {"model": InvalidRequestBody},
    503: {"model": ErrorDetail},
}  # fmt: skip


def _with_message(base: str, message: str | None, guard: OutputGuard) -> str:
    msg = (message or "").strip()
    return f"{base} {USER_MESSAGE_PREFIX} {msg}" if msg and guard.violation(msg) is None else base


def notification_text(row: NotificationRow, guard: OutputGuard) -> str:
    """Hàm thuần theo bảng cố định — không LLM, không chép chữ nào ngoài `note` / lời nhắn người dùng đã qua cổng."""
    if row.kind == "escalation_claimed":
        return CLAIMED_TEXT.get(row.tier or 2, CLAIMED_TEXT[2])
    if row.kind == "escalation_raised":
        return RAISED_TEXT.get(row.raise_target or "", RAISED_TEXT["it_manager"])
    if row.kind == "escalation_closed":
        base = REOPENED_TEXT if row.result == "reopened_as_new" and row.new_ticket_id else CLOSED_TEXT[row.result]
        return _with_message(base, row.user_message, guard)
    if row.result == "approved":
        return APPROVED_TEXT
    note = (row.note or "").strip()
    if note and guard.violation(note) is None:  # cổng của B16 (`approval_wait._rejected`)
        return f"{REJECTED_TEXT} {NOTE_PREFIX} {note}"
    return REJECTED_TEXT


def _view(row: NotificationRow, guard: OutputGuard) -> NotificationView:
    return NotificationView(
        id=row.id, kind=row.kind, ticket_id=row.ticket_id, text=notification_text(row, guard),  # type: ignore[arg-type]
        result=row.result, new_ticket_id=row.new_ticket_id if row.kind == "escalation_closed" else None,  # type: ignore[arg-type]
        created_at=row.created_at.astimezone(UTC).isoformat(),
    )  # fmt: skip


def get_source(request: Request) -> NotificationSource:
    source: NotificationSource | None = getattr(request.app.state, "notifications", None)
    if source is None:
        raise HTTPException(503, "notifications_unavailable")
    return source


def output_guard(request: Request) -> OutputGuard:
    """Cổng đầu ra dựng một lần từ `Settings` của app (cùng cách `graph/wiring.py`), giữ trên `app.state`."""
    guard: OutputGuard | None = getattr(request.app.state, "notifications_guard", None)
    if guard is None:
        settings = request.app.state.settings
        guard = OutputGuard.from_config(settings.config_dir, settings.output_canaries)
        request.app.state.notifications_guard = guard
    return guard


@router.get("/api/me/notifications", response_model=NotificationPage, responses=ERRORS)
async def my_notifications(
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:read:own"))],
    source: Annotated[NotificationSource, Depends(get_source)],
    limit: Annotated[int, Query(ge=1, le=LIMIT_MAX)] = LIMIT_DEFAULT,
    after: Annotated[str | None, Query(min_length=1, max_length=AFTER_MAX)] = None,
) -> NotificationPage:
    cursor = None
    if after is not None:
        try:
            cursor = decode_cursor(after)
        except ValueError:
            raise InvalidRequest(["query.after"]) from None
    rows = await source.page(p.user_id, limit + 1, cursor)  # +1: có dòng dư ⇒ còn trang sau
    page = rows[:limit]
    guard = output_guard(request)
    return NotificationPage(
        items=[_view(r, guard) for r in page],
        next_cursor=encode_cursor(page[-1]) if len(rows) > limit else None,
    )
