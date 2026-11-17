"""Route ticket (P10 "Phải có"; B01 mục 2, B02 mục 2, B19 mục 2; 2b-3).

`POST /api/tickets` → 202: privacy guard (D-07) → `tickets.create` (ticket + lượt `submit` + sự kiện
`privacy_secret_redacted` nếu có, MỘT transaction, `created_at` từ Clock của app) → `runner.run_new` chạy nền.

Privacy guard (3e, phase3 mục 8.3): guard lỗi → 503 `{"error":"privacy_guard_unavailable"}`, không INSERT, không
`start_event`. Body 202 có `notices` (thông báo đã che bí mật/PII). Tin nhắn sau có bí mật → `privacy_secret_redacted`
ghi TRƯỚC `start_event` (lỗi ghi → 503).

`POST /api/tickets/{id}/messages` | `/confirm` → 202, thứ tự kiểm CHỐT (2b-3 a, b):
  413 (middleware) → quyền (`require`) → 429 theo tài khoản (Phase 5 gói 2b, `api/ratelimit.py`) → không có / không đọc được → 404
  (giống hệt nhau) → không phải chủ → 403 → ticket con → 409 → body sai → 422 → guard → `start_event` (409 sự kiện muộn / 503 bận).
  `POST /api/tickets` cũng 429 ngay sau `require` (bộ đếm ticket mới); `/messages`, `/reply`, `/confirm` chung bộ đếm tin nhắn.
  Bị từ chối ở 403/404: chỉ ghi `permission_denied` (404 id giả: không ghi gì), không gọi guard,
  không ghi `turns`/`late_event`.

`POST /api/tickets/{id}/hide` → 204 (P3 menu ⋯ "Xóa"): ẩn ticket gốc của CHÍNH người gọi khỏi `GET /api/tickets` (bảng `ticket_hidden`,
migration 0014) — không xoá/sửa dữ liệu nghiệp vụ, không audit; còn lại → 404 như `GET /{id}`.

`GET /api/tickets/{id}` → `TicketView`: đã có `final_state` thì `status` lấy từ `tickets`, còn mở thì từ
checkpoint; `waiting_for` CHỈ từ checkpoint; đọc checkpoint lỗi → 503 (không đoán). M2 (bn-a): ticket ĐÃ kết thúc mà checkpoint rỗng
(job hạn giữ đã dọn — 90 ngày, P7 mục 4) → 410 `conversation_purged`, SAU kiểm quyền (người không được đọc vẫn 404).

`POST /api/tickets/{id}/override` → 201 (Phase 4 4d P1–P4, TC23; PLAN-4d 2.1): người có `decision:override` ghi lại "đáng lẽ quyết
khác" cho ticket ĐÃ kết thúc — KHÔNG đổi kết quả ticket (một dòng `audit_logs` `step="OVERRIDE"` qua `desk.approvals.record_override`;
không đụng `tickets`, checkpoint, lượt, `start_event`, executor). Thứ tự: 413 → quyền → đăng nhập lại ≤ 10 phút (`recent_login`, 403
`reauth_required`) → 404 (không có / không đọc được) → người gửi tự ghi đè 403 + `permission_denied` → còn mở 409 `ticket_open` → body
422 (`other` thiếu note → `fields: ["note"]`) → trùng quyết định gốc (server suy từ audit, P3) 422 `same_as_original` → guard trên
`note` (503; có bí mật → `privacy_secret_redacted`) → `other` mà note rỗng SAU khi che 422 → ghi; người này đã ghi đè → 409
`already_overridden` (khoá idempotency theo ticket + người, quyết bằng INSERT).
"""

import logging
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from langgraph.types import StateSnapshot
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from app.api.alerts import (  # CHUNG thân lỗi (một schema OpenAPI, như notifications)
    ErrorDetail,
    InvalidRequestBody,
)
from app.api.desk import (
    SECRET_EVENT,
    Desk,
    get_desk,
    load_json_body,
    parse_body,
    record_redacted,
    redact,
    redact_reply_items,
)
from app.api.errors import InvalidRequest, error_fields
from app.api.notifications import output_guard
from app.api.ratelimit import limit_messages, limit_tickets
from app.api.strategy import snapshot_for_new_ticket
from app.auth.authz import can_override, can_read_ticket
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.core.ids import new_ticket_id, new_turn_id
from app.db.tickets import NewTicket, TicketRow
from app.domain.children import children_progress
from app.domain.messages import (  # Q1: TEXT_MAX một nguồn ở domain (câu ghép sau câu hỏi phân loại cũng dùng)
    TEXT_MAX,
    child_title,
)
from app.domain.override import (
    Decision,
    OverrideReason,
    OverrideRecord,
    original_decision,
)
from app.domain.session_memory import can_follow, follow_up_open, prior_label_hint
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_NEW
from app.graph.late_event import InvalidReply, Validate, start_event
from app.guard import injection
from app.guard.normalize import l0
from app.guard.screen import hit_payload, reply_hits

log = logging.getLogger(__name__)
router = APIRouter()

NOTE_MAX = 1000
CHILD_MESSAGE = "Vui lòng trả lời trong hội thoại chung"  # P1 mục 6.1, D-31
_CHILD_INDEX = re.compile(r"[0-9]{1,2}")  # khoá `items` của `/reply` = id con `<cha>-<i>`: phần sau `<cha>-` CHỈ là số (T20b, soát lượt 4)
NOT_FOUND = "not_found"
PURGED = "conversation_purged"  # M2: 410 — hội thoại đã dọn theo hạn giữ

type WaitingFor = Literal["clarify", "approval", "confirm", "reply"]
WAITING_FOR: dict[str, WaitingFor] = {
    "clarify_wait": "clarify", "approval_wait": "approval", "confirm_wait": "confirm",
    "parent_reply_wait": "reply",
}  # fmt: skip


def _not_blank(value: str) -> str:
    """Kiểm thử 11/11: câu chỉ có khoảng trắng hoặc ký tự vô hình (zero-width, soft hyphen — `Cf`) từng tạo ticket rồi
    ra E9 ("Hệ thống đang gặp sự cố") vì guard L0 xoá hết chữ — chặn ở cửa (422 `fields`). Dùng ĐÚNG `l0` của guard
    để "rỗng" ở cửa trùng "rỗng" sau chuẩn hoá. Chỉ kiểm, không đổi văn bản (văn bản lưu vẫn đi qua guard như cũ)."""
    if not l0(value).strip():
        raise ValueError("blank")
    return value


type UserText = Annotated[str, Field(min_length=1, max_length=TEXT_MAX), AfterValidator(_not_blank)]


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: UserText
    # Q13b (D-79): "Hỏi tiếp" từ ticket ĐÃ kết thúc của chính người gửi. Cờ `ENABLE_SESSION_MEMORY` tắt → 422 (như trước lô: khoá lạ).
    follows_ticket_id: str | None = Field(default=None, min_length=1, max_length=64)


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: UserText


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class ReplyAnswer(BaseModel):
    """Một ý `needs=answer` của `/reply` (T20b P11, 5.2.6)."""

    model_config = ConfigDict(extra="forbid")
    answer: UserText


class ReplyConfirm(BaseModel):
    """Một ý `needs=confirm` của `/reply` — "Đã ổn" / "Chưa ổn" + ghi chú."""

    model_config = ConfigDict(extra="forbid")
    confirmed: bool
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class ReplyIn(BaseModel):
    """`{items: {[child_id]: {answer} | {confirmed, note?}}}` — `extra="forbid"` mọi tầng (5.2.6)."""

    model_config = ConfigDict(extra="forbid")
    items: dict[str, ReplyAnswer | ReplyConfirm] = Field(min_length=1)


class OverrideIn(BaseModel):
    """4d P2: mã cố định (không chữ tự do ngoài `note`, mà `note` qua privacy guard trước khi vào audit)."""

    model_config = ConfigDict(extra="forbid")
    override_decision: Decision
    reason_code: OverrideReason
    note: str | None = Field(default=None, max_length=NOTE_MAX)  # BẮT BUỘC khi reason_code="other" (kiểm trong route)


class Accepted(BaseModel):
    ticket_id: str
    status: str
    notices: list[str] = []  # phase3 mục 8.3 — nguyên văn `RedactionResult.notices`


class HandlingView(BaseModel):
    """D-99: một ca chuyển IT, nhìn từ phía người gửi. `stage`: waiting (chưa ai nhận) | claimed | raised (đã chuyển cấp 3, chưa ai nhận)
    | closed. `user_message` chỉ có khi qua `OutputGuard` (như thông báo). Không lộ ghi chú nội bộ, người xử lý, mã luật."""

    ticket_id: str
    stage: Literal["waiting", "claimed", "raised", "closed"]
    tier: Literal[2, 3]
    raise_target: Literal["it_manager", "vendor"] | None
    close_result: Literal["completed", "confirmed_denial", "reopened_as_new"] | None
    user_message: str | None
    new_ticket_id: str | None
    updated_at: datetime


class TicketView(BaseModel):
    """Đúng tập trường trả cho người dùng — không lộ state nội bộ khác của checkpoint."""

    ticket_id: str
    status: str
    waiting_for: WaitingFor | None
    conversation: list[dict[str, Any]]
    exit_code: str | None
    close_reason: str | None
    final_state: str | None
    created_at: datetime
    closed_at: datetime | None
    # T20b P11 (5.2.6): ticket cha → tiến độ từng ý (chỉ từ DB + checkpoint CHA); ticket thường/con → None
    children_progress: list[dict[str, Any]] | None = None
    # R3: hạn của LẦN CHỜ HIỆN TẠI (UTC) — approval: `approvals.deadline` của phiếu `pending`; clarify/confirm: dòng `wait_deadlines`
    # chưa bắn (đúng dòng worker bắn timeout). Đã kết thúc / không chờ / con chờ clarify-confirm (hạn do cha giữ — không có dòng) → None.
    # Ticket CHA chưa kết thúc: (1) hạn chờ riêng của cha (`wait_deadlines` của cha); (2) không có → hạn SỚM NHẤT các phiếu `pending` của
    # con; (3) không có → None. Quá hạn mà worker chưa bắn → vẫn trả mốc (trong quá khứ). Không mặc định: OpenAPI ghi bắt buộc (có thể null).
    deadline: datetime | None
    server_now: datetime  # giờ máy chủ (`desk.clock`, có múi giờ) — FE tính đồng hồ đếm ngược theo giờ máy chủ, không theo giờ máy khách
    # be-api8-cau-dau (nợ API #8 / Q-fe-18): câu yêu cầu đầu — `tickets.redacted_request` (bản ĐÃ CHE, D-07; không bao giờ raw) cắt
    # REQUEST_TEXT_MAX ký tự. Ticket con mà `redacted_request` trùng nguyên câu của cha (B5 seed khi span không hợp lệ) → None.
    request_text: str | None = None
    # Q13b (D-79): FE mở ô "Hỏi tiếp về yêu cầu này" — cờ `ENABLE_SESSION_MEMORY` bật VÀ ticket đã kết thúc VÀ là ticket GỐC VÀ người đọc là
    # CHỦ ticket (L1/L2 đọc được ticket người khác nhưng không hỏi tiếp thay).
    can_follow_up: bool = False
    # D-99 (17/11): tiến độ xử lý của bộ phận IT cho từng ca của ticket (và con của nó) — None khi không có ca / nguồn ca không có.
    handling: list[HandlingView] | None = None


REQUEST_TEXT_MAX = 500
LIST_LIMIT_DEFAULT = 20
LIST_LIMIT_MAX = 50


class TicketListItem(BaseModel):
    """P3 "Gần đây" — một dòng của `GET /api/tickets`: CHỈ cột bảng `tickets` (không checkpoint). `request_text` như `TicketView`
    (bản ĐÃ CHE, cắt `REQUEST_TEXT_MAX` — không bao giờ câu gốc)."""

    ticket_id: str
    request_text: str | None
    final_state: str | None
    exit_code: str | None
    created_at: datetime
    closed_at: datetime | None


class TicketList(BaseModel):
    items: list[TicketListItem]


HIDE_ERRORS: dict[int | str, dict[str, Any]] = {401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 404: {"model": ErrorDetail}}
LIST_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 422: {"model": InvalidRequestBody}, 503: {"model": ErrorDetail},
}  # fmt: skip


def request_text_of(row: TicketRow, parent_request: str | None) -> str | None:
    """Câu đầu hiển thị cho ticket: bản đã che, cắt `REQUEST_TEXT_MAX`; con trùng nguyên câu cha → None (không lặp câu của cha)."""
    text = row.redacted_request
    if row.parent_ticket_id is not None and parent_request is not None and text.strip() == parent_request.strip():
        return None
    return text[:REQUEST_TEXT_MAX] or None


def _accepted(ticket_id: str, status: str, notices: list[str]) -> JSONResponse:
    body = Accepted(ticket_id=ticket_id, status=status, notices=notices)
    return JSONResponse(body.model_dump(), status_code=202)


async def _readable(request: Request, p: Principal, desk: Desk, ticket_id: str) -> TicketRow:
    """Không có, hoặc có mà không được đọc → CÙNG một 404 (không lộ ticket tồn tại — D-02, TC30)."""
    row = await desk.tickets.get(ticket_id)
    if row is None:
        raise HTTPException(404, NOT_FOUND)
    if not can_read_ticket(p, row):
        await deny(request, p, "ticket:read:any", ticket_id=ticket_id)
        raise HTTPException(404, NOT_FOUND)
    return row


async def _owned_leaf(
    request: Request, p: Principal, desk: Desk, ticket_id: str, perm: str
) -> TicketRow:
    row = await _readable(request, p, desk, ticket_id)
    if row.requester_id != p.user_id:  # đọc được (l1, l2…) nhưng không phải chủ ticket
        await deny(request, p, perm, ticket_id=ticket_id, reason="not_owner")
        raise HTTPException(403, "forbidden")
    if row.parent_ticket_id is not None:
        raise HTTPException(409, CHILD_MESSAGE)
    return row


@router.post("/api/tickets", status_code=202)
async def create_ticket(
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:create"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    await limit_tickets(request, p, desk)  # 429 ngay sau `require`, trước đọc thân (gói 2b)
    body = await parse_body(request, TicketIn)
    hint: str | None = None
    if body.follows_ticket_id is not None:  # Q13b (D-79): kiểm TRƯỚC guard/INSERT — sai thì không tạo gì
        if not request.app.state.settings.enable_session_memory:
            raise InvalidRequest(["body.follows_ticket_id"])
        src = await desk.tickets.follow_up_source(body.follows_ticket_id)
        if src is None or not can_follow(src, p.user_id):
            raise HTTPException(404, NOT_FOUND)  # không có / người khác / ticket con / chưa kết thúc: GIỐNG HỆT nhau
        hint = prior_label_hint(src)
    raw_hit = hit_payload(injection.match(body.text))  # D-92: so mẫu trên bản GỐC trước khi che — chỉ mã mẫu đi tiếp, không chữ
    redacted = await redact(desk, request, body.text)
    user = await desk.users.get_user(p.user_id)
    strategy, source = await snapshot_for_new_ticket(request, desk)  # D-67: chụp chiến lược M5 + nguồn lúc TẠO
    ticket_id, turn_id = new_ticket_id(), new_turn_id()
    await desk.tickets.create(
        NewTicket(
            ticket_id=ticket_id, requester_id=p.user_id, requester_role=p.role,
            requester_dept=user.department if user else None, session_id=p.session_id,
            redacted_request=redacted.text, created_at=desk.clock.now(), strategy=strategy, source=source,
        ),
        turn_id=turn_id,
        security_events=[(SECRET_EVENT, {"count": redacted.secrets_found})] if redacted.secrets_found else (),
    )  # fmt: skip
    desk.background.spawn(
        desk.runner.run_new(ticket_id, turn_id, follows_ticket_id=body.follows_ticket_id, prior_hint=hint, raw_screen_hit=raw_hit),
        name=f"submit:{ticket_id}",
    )  # fmt: skip
    return _accepted(ticket_id, S_NEW, redacted.notices)


@router.get("/api/tickets", response_model=TicketList, responses=LIST_ERRORS)
async def list_tickets(
    p: Annotated[Principal, Depends(require("ticket:read:own"))],
    desk: Annotated[Desk, Depends(get_desk)],
    limit: Annotated[int, Query(ge=1, le=LIST_LIMIT_MAX)] = LIST_LIMIT_DEFAULT,
) -> TicketList:
    """P3 "Gần đây": ticket gốc của CHÍNH người gọi — lọc `requester_id = p.user_id` cho MỌI vai (kể cả `ticket:read:any`: danh
    sách không bao giờ có ticket người khác). Chỉ DB (không checkpoint); route đọc như `GET /{id}` — không bộ đếm 429."""
    rows = await desk.tickets.list_own(p.user_id, limit)
    return TicketList(items=[
        TicketListItem(
            ticket_id=r.ticket_id, request_text=request_text_of(r, None), final_state=r.final_state, exit_code=r.exit_code,
            created_at=r.created_at, closed_at=r.closed_at,
        )
        for r in rows
    ])  # fmt: skip


@router.post("/api/tickets/{ticket_id}/hide", status_code=204, responses=HIDE_ERRORS)
async def hide_ticket(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:read:own"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> Response:
    """Ẩn ticket gốc của chính người gọi khỏi danh sách "Gần đây" (`GET /api/tickets`). Không xoá dữ liệu; `GET /{id}` vẫn đọc được.
    Gọi lại vẫn 204. Không có / không phải của người gọi / ticket con → 404 `not_found`."""
    # 404 giống hệt `GET /{id}`: không có → không ghi gì; của người khác (kể cả `ticket:read:any`) → `permission_denied` (`not_owner`);
    # ticket con của mình → không ghi (danh sách không có con). Không ghi audit (tuỳ chọn hiển thị, không phải quyết định của hệ
    # thống — `ticket_hidden.hidden_at` giữ vết; ĐP duyệt 08/11); không 429, không guard (không có chữ người dùng).
    row = await desk.tickets.get(ticket_id)
    if row is None:
        raise HTTPException(404, NOT_FOUND)
    if row.requester_id != p.user_id:
        await deny(request, p, "ticket:read:own", ticket_id=ticket_id, reason="not_owner")
        raise HTTPException(404, NOT_FOUND)
    if row.parent_ticket_id is not None:
        raise HTTPException(404, NOT_FOUND)
    await desk.tickets.hide(p.user_id, ticket_id, desk.clock.now())
    return Response(status_code=204)


@router.get("/api/tickets/{ticket_id}", response_model=TicketView, responses={410: {"description": PURGED}})
async def read_ticket(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:read:own"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> TicketView:
    row = await _readable(request, p, desk, ticket_id)
    try:
        snap = await desk.runner.snapshot(ticket_id)
    except Exception:
        log.exception("đọc checkpoint của ticket %s lỗi", ticket_id)
        raise HTTPException(503, "checkpoint_unavailable") from None
    values = snap.values or {}
    if row.final_state is not None and not values:  # M2: ticket đã kết thúc mà checkpoint rỗng = job hạn giữ đã dọn (90 ngày)
        raise HTTPException(410, PURGED)
    progress = None
    if row.is_parent:  # T20b P11: chỉ DB (`children_progress_rows`) + checkpoint CHA (danh sách con, seed, `awaiting`)
        children = list(values.get("children") or [])
        seeds = values.get("child_seeds") or {}
        awaiting = values.get("awaiting") if snap.next == ("parent_reply_wait",) else None
        progress = children_progress(
            await desk.tickets.children_progress_rows(ticket_id, children),
            {cid: child_title(seeds.get(cid) or {}) for cid in children}, awaiting,
        )  # fmt: skip
    waiting_for = WAITING_FOR.get(snap.next[0]) if snap.next else None
    deadline = None
    if row.final_state is None and row.is_parent:  # cha: hạn riêng → hạn sớm nhất phiếu `pending` của con → None
        deadline = await desk.approvals.parent_deadline(ticket_id)
    elif row.final_state is None and waiting_for in ("approval", "clarify", "confirm"):  # R3
        deadline = await desk.approvals.open_deadline(ticket_id, waiting_for)
    parent = await desk.tickets.get(row.parent_ticket_id) if row.parent_ticket_id is not None else None
    handling = await _handling(request, [ticket_id, *(values.get("children") or [])])
    return TicketView(
        ticket_id=ticket_id,
        status=row.final_state or values.get("status") or S_NEW,
        waiting_for=waiting_for,
        conversation=list(values.get("conversation") or []),
        exit_code=row.exit_code, close_reason=row.close_reason, final_state=row.final_state,
        created_at=row.created_at, closed_at=row.closed_at, children_progress=progress, deadline=deadline,
        server_now=desk.clock.now(), request_text=request_text_of(row, parent.redacted_request if parent else None),
        can_follow_up=bool(
            request.app.state.settings.enable_session_memory and follow_up_open(row.final_state) and row.parent_ticket_id is None
            and row.requester_id == p.user_id
        ),
        handling=handling,
    )  # fmt: skip


def _stage(r: Any) -> str:
    if r.closed_at is not None:
        return "closed"
    if r.assigned_at is not None:
        return "claimed"
    return "raised" if r.tier == 3 else "waiting"


async def _handling(request: Request, ticket_ids: list[str]) -> list[HandlingView] | None:
    """D-99: đọc ca của ticket + con. Nguồn ca không có (test cũ) hoặc lỗi đọc → None (màn chat giữ câu cũ; log tên lớp lỗi)."""
    source = getattr(request.app.state, "escalations", None)
    if source is None or not hasattr(source, "handling_of"):
        return None
    try:
        rows = await source.handling_of(ticket_ids)
    except Exception as exc:  # noqa: BLE001 — phần phụ của màn chat, không chặn đọc ticket
        log.warning("đọc tiến độ xử lý IT lỗi (%s)", type(exc).__name__)
        return None
    if not rows:
        return None
    guard = output_guard(request)
    out = []
    for r in rows:
        msg = (r.user_message or "").strip()
        out.append(HandlingView(
            ticket_id=r.ticket_id, stage=_stage(r), tier=r.tier, raise_target=r.raise_target, close_result=r.close_result,  # type: ignore[arg-type]
            user_message=msg if msg and guard.violation(msg) is None else None, new_ticket_id=r.new_ticket_id,
            updated_at=r.closed_at or r.assigned_at or r.raised_at or r.created_at,
        ))  # fmt: skip
    return out


@router.post("/api/tickets/{ticket_id}/messages", status_code=202)
async def post_message(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:message"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    await limit_messages(request, p, desk)  # 429 trước `_owned_leaf`: id giả vẫn 429 (gói 2b)
    await _owned_leaf(request, p, desk, ticket_id, "ticket:message")
    body = await parse_body(request, MessageIn)
    redacted = await redact(desk, request, body.text)
    await record_redacted(desk, request, p, ticket_id, redacted)
    await start_event(
        desk.runner, ticket_id, S_CLARIFYING,
        {"kind": "user_reply", "text": redacted.text, "screen_hit": hit_payload(injection.match(body.text))},  # D-92: chỉ mã mẫu
        spawn=desk.background.spawn, session_id=p.session_id,
    )  # fmt: skip
    return _accepted(ticket_id, S_CLARIFYING, redacted.notices)


@router.post("/api/tickets/{ticket_id}/confirm", status_code=202)
async def confirm(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:confirm"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    await limit_messages(request, p, desk)  # chung bộ tin nhắn: /confirm sai bước vẫn chạy guard + ghi late_event (gói 2b)
    await _owned_leaf(request, p, desk, ticket_id, "ticket:confirm")
    body = await parse_body(request, ConfirmIn)
    redacted = await redact(desk, request, body.note) if body.note else None
    if redacted is not None:
        await record_redacted(desk, request, p, ticket_id, redacted)
    note = redacted.text if redacted is not None else None
    event = {"kind": "confirmed" if body.confirmed else "unresolved", "note": note,
             "screen_hit": hit_payload(injection.match(body.note)) if body.note else None}  # D-92  # fmt: skip
    await start_event(
        desk.runner, ticket_id, S_CONFIRMING, event, spawn=desk.background.spawn,
        session_id=p.session_id,
    )  # fmt: skip
    return _accepted(ticket_id, S_CONFIRMING, redacted.notices if redacted is not None else [])


async def _reply_body(request: Request, parent_id: str) -> ReplyIn:
    """Như `parse_body` (422 chỉ vị trí trường) + chặn khoá `items` không có dạng `<cha>-<i>` TRƯỚC khi kiểm hình dạng, với vị trí CHUNG
    `body.items` — khoá dict là chữ tự do của người gửi chưa qua guard, không được dội lại trong 422 (soát DỪNG 2 mục 6). Sau bước này mọi
    vị trí trường nêu tên đều là id do hệ thống sinh (`<cha>-<số>`)."""
    data = load_json_body(await request.body())  # JSON hỏng / lồng quá sâu / có NUL → 422 (kiểm thử 12/11)
    items = data.get("items") if isinstance(data, dict) else None
    prefix = f"{parent_id}-"
    if isinstance(items, dict) and any(not (k.startswith(prefix) and _CHILD_INDEX.fullmatch(k[len(prefix):])) for k in items):
        raise InvalidRequest(["body.items"])
    try:
        return ReplyIn.model_validate(data)
    except ValidationError as exc:
        raise InvalidRequest(error_fields(exc.errors(include_url=False, include_input=False))) from None


def _reply_texts(items: Mapping[str, ReplyAnswer | ReplyConfirm]) -> dict[str, str | None]:
    """Chữ GỐC từng ý — CHỈ để `reply_hits` so mẫu (D-92); không đi vào sự kiện/kho."""
    return {cid: item.answer if isinstance(item, ReplyAnswer) else item.note for cid, item in items.items()}


def _items_match(items: dict[str, dict[str, Any]]) -> Validate:
    """Kiểm DƯỚI khoá cha (P11, chốt (c) — chặt): `items` ≡ ĐÚNG tập `awaiting`, mỗi ý đúng loại theo `needs` (`answer` ↔ `{answer}`,
    `confirm` ↔ `{confirmed, note?}`). Lệch → `InvalidReply` (vị trí trường, sắp theo id) — không giao gì, không `late_event`."""

    def check(snap: StateSnapshot) -> None:
        awaiting: dict[str, str] = dict(snap.values.get("awaiting") or {})
        bad = {cid for cid in items.keys() ^ awaiting.keys()}
        bad |= {cid for cid in items.keys() & awaiting.keys() if ("answer" in items[cid]) != (awaiting[cid] == "answer")}
        if bad:
            raise InvalidReply([f"body.items.{cid}" for cid in sorted(bad)])

    return check


@router.post("/api/tickets/{ticket_id}/reply", status_code=202)
async def reply(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:message"))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    """T20b P11 (5.2.6): người dùng trả lời MỘT lần cho mọi ý của tin tổng hợp. Thứ tự kiểm như `/messages`: 413 → quyền → 404 → 403
    (không phải chủ) → 409 `CHILD_MESSAGE` (gọi vào ticket con) → 422 hình dạng body → privacy guard TỪNG `answer`/`note` (503 khi guard
    lỗi; bí mật → MỘT sự kiện `privacy_secret_redacted {count}` tổng) → `start_event(S_CONFIRMING, {"kind":"reply","items":…},
    wait_node="parent_reply_wait", validate=…)`: không ở `parent_reply_wait` (kể cả ticket thường) → 409 + `late_event`; `items` ≠ đúng
    `awaiting` → 422 `{error:"invalid_request", fields:["body.items.<child_id>"]}`. Tin người dùng ghép do NODE ghi (P8), không do route."""
    await limit_messages(request, p, desk)  # chung bộ tin nhắn (gói 2b)
    await _owned_leaf(request, p, desk, ticket_id, "ticket:message")
    body = await _reply_body(request, ticket_id)
    redacted = await redact_reply_items(desk, request, body.items)  # Q-T20b-8: che TỪNG answer/note — test AST N1 tin như `redact`
    await record_redacted(desk, request, p, ticket_id, redacted.result)
    try:
        await start_event(
            desk.runner, ticket_id, S_CONFIRMING,
            {"kind": "reply", "items": redacted.items, "screen_hits": reply_hits(_reply_texts(body.items))},  # D-92: chỉ mã mẫu
            spawn=desk.background.spawn,
            session_id=p.session_id, wait_node="parent_reply_wait", validate=_items_match(redacted.items),
        )  # fmt: skip
    except InvalidReply as exc:
        raise InvalidRequest(exc.fields) from None
    return _accepted(ticket_id, S_CONFIRMING, redacted.result.notices)


@router.post("/api/tickets/{ticket_id}/override", status_code=201)
async def override(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("decision:override", recent_login=True))],
    desk: Annotated[Desk, Depends(get_desk)],
) -> JSONResponse:
    row = await _readable(request, p, desk, ticket_id)
    if not can_override(p, row):  # người gửi tự ghi đè
        await deny(request, p, "decision:override", ticket_id=ticket_id, reason="self_override")
        raise HTTPException(403, "forbidden")
    if row.final_state is None:
        raise HTTPException(409, "ticket_open")
    body = await parse_body(request, OverrideIn)
    if body.reason_code == "other" and not (body.note and body.note.strip()):
        raise InvalidRequest(["note"])
    original = original_decision(await desk.approvals.decision_trail(ticket_id))
    if body.override_decision == original:
        raise HTTPException(422, "same_as_original")  # trước guard: yêu cầu chắc chắn bị từ chối thì không gửi note qua guard
    redacted = await redact(desk, request, body.note) if body.note else None
    if redacted is not None:
        await record_redacted(desk, request, p, ticket_id, redacted)
    note = redacted.text if redacted is not None and redacted.text.strip() else None
    if body.reason_code == "other" and note is None:  # chỉ ký tự vô hình → che xong rỗng (khuôn soát 4c S4b)
        raise InvalidRequest(["note"])
    rec = OverrideRecord(
        ticket_id=ticket_id, overrider_id=p.user_id, original_decision=original, override_decision=body.override_decision,
        reason_code=body.reason_code, note=note, created_at=desk.clock.now(),
    )  # fmt: skip
    if not await desk.approvals.record_override(rec):  # trùng khoá (ticket, người) — quyết bằng kết quả INSERT, không kiểm trước
        raise HTTPException(409, "already_overridden")
    return JSONResponse({
        "ticket_id": ticket_id, "original_decision": original, "override_decision": body.override_decision,
        "reason_code": body.reason_code, "notices": redacted.notices if redacted is not None else [],
    }, status_code=201)  # fmt: skip
