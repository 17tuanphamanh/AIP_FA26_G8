"""SSE tiến trình ticket: `GET /api/tickets/{id}/events` (text/event-stream) cho màn chat nhân viên.

Nguồn sự kiện = DB (`audit_logs` + checkpoint/`tickets` đã lưu), KHÔNG đổi runner: `ainvoke` chạy `durability="sync"` và worker có thể
chạy tiếp lượt ở tiến trình khác, nên `astream_events` của một tiến trình không thấy hết. Vòng đọc mỗi `SSE_POLL_MS` lấy các dòng audit
mới theo `log_id` tăng dần (ticket + con của nó, gộp theo `log_id`), đổi chúng thành sự kiện qua BẢNG TRẮNG dưới đây.

Quyền: như `GET /api/tickets/{id}` (`ticket:read:own` + `_readable` — không có / không đọc được → cùng một 404). `ENABLE_SSE=false`
(mặc định) → 404 trước mọi kiểm khác (route coi như không tồn tại).

Sự kiện JSON `{type, step, label, at, data?}` (+ `child_id` khi sự kiện của ticket con); tên SSE `event:` = `type`:
- `status` — bước bắt đầu/xong/lỗi. `step` là khoá giai đoạn thân thiện (`safety`, `understand`, …), `data.state` ∈ active|done|failed.
- `tool_call` — công cụ chẩn đoán (B6) / thao tác thực thi (B17): tên thân thiện + `data.ok`; KHÔNG tham số, KHÔNG kết quả chi tiết.
- `thought` — lý do đã chuẩn hoá từ MẪU CÂU CỐ ĐỊNH theo (step, event, to_status[, luật]); không phải suy luận của LLM, không mã luật,
  xác suất, ngưỡng.
- `token` / `message_end` — chữ của tin trả lời ĐÃ LƯU trong `conversation` của checkpoint (đã qua output guard), cụm 2–4 từ nhịp
  ~30 ms; `message_end` kèm `message_id` (= "<kind>:<thứ tự>") để frontend khớp với tin chính thức.
- `waiting` (`data.waiting_for`) / `done` — sự kiện cuối; stream đóng ngay sau đó.

Danh sách trắng: dòng audit không có trong bảng → bỏ. Nhãn chỉ ghép từ bảng cố định + `intent` thuộc tập đóng; không bao giờ chép chữ
người dùng, `detail`, `reason`, `query`, `note`, `matched_rule_id`… vào sự kiện.

`id:` SSE = `log_id` của dòng audit sinh ra sự kiện. Sự kiện cuối của một dòng mang `id: <log_id>`; sự kiện trước nó mang `<log_id>.<k>`
(k = số sự kiện của dòng đã gửi) để nối lại GIỮA chừng một dòng (vd. giữa các cụm token) không mất, không trùng. `Last-Event-ID`
= `N` → tiếp từ dòng > N; `N.k` → gửi nốt sự kiện thứ k+1… của dòng N rồi tiếp. Kết nối mới KHÔNG có `Last-Event-ID`: phát lại lịch sử
trạng thái nhưng KHÔNG phát token cho tin đã có sẵn lúc kết nối (đã hiện qua GET).

Đóng stream: ticket có `final_state` VÀ graph đã dừng hẳn (`snapshot.next` rỗng — B20 lưu xong tin escalation), hoặc đang chờ
(`waiting_for`). Snapshot đọc TRƯỚC khi đọc audit nên mọi dòng ghi trước checkpoint đã được phát. Tối đa `MAX_STREAM_S` (10 phút).
Heartbeat: dòng comment `: hb` mỗi `SSE_HEARTBEAT_S` giây im lặng.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.desk import Desk, get_desk
from app.api.tickets import WAITING_FOR, _readable
from app.auth.deps import require
from app.auth.models import Principal
from app.domain.messages import TRIAGE_ORIGIN
from app.domain.states import S_ASSESSING, S_ESCALATED, S_EXECUTING

log = logging.getLogger(__name__)
router = APIRouter()

MAX_STREAM_S: Final = 600.0  # giới hạn thời gian một kết nối
TOKEN_INTERVAL_S: Final = 0.03  # nhịp giữa hai cụm token
STALL_S: Final = 5.0  # dòng báo "đã có tin" mà checkpoint chưa có tin quá chừng này → bỏ phần token, đi tiếp
FEED_LIMIT: Final = 200
CONVERSATION_CAP: Final = 20  # `append_capped(20)` ở domain/ticket_state.py
CHUNK_SIZES: Final = (3, 2, 4, 2, 3)  # số từ mỗi cụm token, lặp vòng (2–4)

# ---------------------------------------------------------------------------------------------------------------------
# BẢNG TRẮNG — (step, event[, to_status]) → nhãn tiếng Việt. Dòng audit ngoài bảng bị bỏ.
# ---------------------------------------------------------------------------------------------------------------------

type State = str  # "active" | "done" | "failed"


@dataclass(frozen=True)
class Stat:
    stage: str  # `step` của sự kiện status
    state: State
    label: str  # có thể chứa `{intent}`


@dataclass(frozen=True)
class Entry:
    statuses: tuple[Stat, ...] = ()
    thought: str | None = None


INTENT_LABEL: Final[Mapping[str, str]] = {  # tập đóng `INTENTS`
    "vpn": "VPN", "account": "tài khoản", "software": "cài đặt phần mềm", "access": "quyền truy cập",
    "it_help": "hỏi đáp IT",  # D-57 (lô Q12): intent chỉ-trả-lời
}  # fmt: skip

S_ = Stat
TABLE: Final[Mapping[tuple[str, str, str | None], Entry]] = {
    ("B1", "identity_established", None): Entry((S_("safety", "active", "Đang kiểm tra an toàn"),)),
    ("B2", "screened", None): Entry((
        S_("safety", "done", "Đã kiểm tra an toàn"), S_("understand", "active", "Đang tìm hiểu yêu cầu"),
    )),
    ("B3", "intent_classified", None): Entry((
        S_("understand", "done", "Đã hiểu yêu cầu: {intent}"), S_("diagnose", "active", "Đang kiểm tra hệ thống"),
    )),
    ("B5", "split", None): Entry(
        (S_("understand", "done", "Đã hiểu yêu cầu: nhiều ý"), S_("diagnose", "active", "Đang xử lý từng ý")),
        "Yêu cầu có nhiều ý nên được tách ra xử lý riêng từng ý",
    ),
    # Q1 (D-56): câu hỏi phân loại của B3 — chờ người dùng như câu hỏi B11; trả lời → sàng lọc lại từ đầu
    ("B3", "triage_asked", None): Entry(
        (S_("clarify", "active", "Cần bạn cho biết đang gặp việc gì"),), "Yêu cầu chưa rõ loại việc nên cần hỏi lại một câu",
    ),
    ("B11", "triage_reply", None): Entry((S_("clarify", "done", "Đã nhận câu trả lời của bạn"),)),
    ("B5", "child_started", None): Entry((S_("diagnose", "active", "Đang kiểm tra hệ thống"),)),
    ("B6", "diagnosed", None): Entry((
        S_("diagnose", "done", "Đã kiểm tra hệ thống"), S_("lookup", "active", "Đang tra cứu hướng dẫn"),
    )),
    ("B6", "diagnosis_skipped", None): Entry((S_("lookup", "active", "Đang tra cứu hướng dẫn"),)),
    # D-57 (lô Q12): câu hỏi IT chung — không có gì để kiểm tra trên hệ thống, đi thẳng tra cứu hướng dẫn
    ("B6", "diagnosis_not_applicable", None): Entry((S_("lookup", "active", "Đang tra cứu hướng dẫn"),)),
    ("B7", "tool_system_error", None): Entry((S_("diagnose", "failed", "Chưa kiểm tra được hệ thống"),)),
    ("B8", "retrieved", None): Entry(
        (S_("lookup", "done", "Đã tìm thấy hướng dẫn liên quan"),),
        "Hướng dẫn phù hợp được tìm thấy trong tài liệu nội bộ",
    ),
    ("B8", "retrieval_error", None): Entry((S_("lookup", "failed", "Chưa tra cứu được hướng dẫn"),)),
    ("B9", "no_evidence", None): Entry(
        (S_("lookup", "failed", "Chưa tìm thấy hướng dẫn phù hợp"),),
        "Chưa có tài liệu nội bộ phù hợp với yêu cầu này",
    ),
    ("B10", "needs_action", None): Entry(
        (S_("plan", "active", "Đang chuẩn bị thao tác"),), "Yêu cầu cần một thao tác cụ thể trên hệ thống",
    ),
    ("B10", "deflected_info_only", None): Entry(
        (S_("answer", "done", "Đã có hướng dẫn cho bạn"),), "Yêu cầu chỉ cần hướng dẫn, không cần thao tác trên hệ thống",
    ),
    ("B11", "asked", None): Entry(
        (S_("clarify", "active", "Cần bạn bổ sung thông tin"),), "Còn thiếu thông tin để thực hiện chính xác",
    ),
    ("B11", "user_replied", None): Entry((S_("clarify", "done", "Đã nhận thông tin bạn bổ sung"),)),
    ("B11", "action_built", None): Entry((
        S_("plan", "done", "Đã chuẩn bị thao tác"), S_("assess", "active", "Đang đánh giá chính sách"),
    )),
    # B12–B14: nhãn theo trạng thái ĐÍCH (đường đi), không theo quyết định/luật/xác suất.
    ("B13/B14", "risk_decided", S_EXECUTING): Entry(
        (S_("assess", "done", "Đã đánh giá chính sách"), S_("execute", "active", "Đang thực hiện")),
        "Thao tác nằm trong phạm vi được phép tự thực hiện",
    ),
    ("B13/B14", "risk_decided", S_ASSESSING): Entry(
        (S_("assess", "done", "Đã đánh giá chính sách"), S_("approval", "active", "Đang chuẩn bị gửi IT duyệt")),
        "Thao tác này cần IT duyệt trước khi thực hiện",
    ),
    ("B13/B14", "risk_decided", S_ESCALATED): Entry(
        (S_("assess", "done", "Đã đánh giá chính sách"),), "Thao tác này cần kỹ thuật viên xử lý trực tiếp",
    ),
    ("B15", "queued", None): Entry((S_("approval", "active", "Đang chờ IT duyệt"),)),
    ("B16", "approved", None): Entry(
        (S_("approval", "done", "IT đã duyệt"), S_("execute", "active", "Đang thực hiện")), "Yêu cầu đã được IT duyệt",
    ),
    ("B16", "rejected", None): Entry((S_("approval", "failed", "Yêu cầu không được duyệt"),)),
    ("B16", "approval_timeout", None): Entry((S_("approval", "failed", "Quá hạn chờ IT duyệt"),)),
    ("B17", "exec_failed", None): Entry((S_("execute", "failed", "Thực hiện chưa thành công"),)),
    ("B18", "executed_ok", None): Entry((S_("execute", "done", "Đã thực hiện xong"),)),
}  # fmt: skip

# Ngoại lệ của `thought` khi dòng B13/B14 → duyệt: câu theo NHÓM luật (khoá = id luật chỉ để chọn câu, không bao giờ phát ra).
APPROVAL_THOUGHT_BY_RULE: Final[Mapping[str, str]] = {
    "R17": "Thiết bị chưa được đăng ký nên cần IT duyệt",
    "R18": "Yêu cầu ngoài giờ hành chính nên cần IT duyệt",
}

TOOL_LABEL: Final[Mapping[str, str]] = {  # công cụ ĐỌC của B6 (`tools.specs`)
    "check_account_status": "Kiểm tra trạng thái tài khoản",
    "check_lockout_history": "Kiểm tra lịch sử khoá tài khoản",
    "check_privilege_level": "Kiểm tra mức quyền tài khoản",
    "check_device_registered": "Kiểm tra thiết bị đã đăng ký",
    "check_vpn_cert_expiry": "Kiểm tra chứng chỉ VPN",
    "check_last_connection": "Kiểm tra lần kết nối gần nhất",
    "check_catalog_entry": "Tra danh mục phần mềm",
    "check_license_available": "Kiểm tra giấy phép còn lại",
    "check_installed_list": "Kiểm tra phần mềm đã cài",
    "check_current_permissions": "Kiểm tra quyền hiện có",
    "check_resource_sensitivity": "Kiểm tra mức nhạy cảm của tài nguyên",
    "check_manager_chain": "Kiểm tra người quản lý",
}
ACTION_LABEL: Final[Mapping[str, str]] = {  # thao tác GHI của B17 (`domain.action.PARAMS_BY_ACTION`)
    "renew_vpn_cert": "Gia hạn chứng chỉ VPN",
    "reissue_vpn_access": "Cấp lại quyền truy cập VPN",
    "check_vpn_status": "Kiểm tra trạng thái VPN",
    "reset_password": "Đặt lại mật khẩu",
    "unlock_account": "Mở khoá tài khoản",
    "install_software": "Cài đặt phần mềm",
    "view_permissions": "Xem quyền truy cập",
    "grant_permission": "Cấp quyền truy cập",
    "extend_permission": "Gia hạn quyền truy cập",
}

DONE_LABEL: Final[Mapping[str, str]] = {  # `final_state` — cùng chữ với frontend `STATUS_LABEL` (E0 chỉ câu trung tính)
    "S_RESOLVED": "Hoàn tất",
    "S_ESCALATED": "Đã chuyển kỹ thuật viên hỗ trợ",
    "S_REJECTED": "Yêu cầu không được duyệt",
    "S_BLOCKED": "Yêu cầu này không thể xử lý tự động",
}
DONE_FALLBACK: Final = "Đã xử lý xong"
WAITING_LABEL: Final[Mapping[str, str]] = {
    "clarify": "Cần bạn bổ sung thông tin",
    "approval": "Đang chờ IT duyệt",
    "confirm": "Chờ bạn xác nhận kết quả",
    "reply": "Cần bạn phản hồi từng ý",
}

# Dòng audit sinh ra MỘT tin trả lời cho người dùng → loại tin trong `conversation` (digest của cha: giao diện sẵn có lo, không stream).
MESSAGE_KIND: Final[Mapping[tuple[str, str], str]] = {
    ("B10", "deflected_info_only"): "answer",
    ("B11", "asked"): "question",
    ("B3", "triage_asked"): "question",  # Q1: tin `origin="triage"` — `pick_message` tách khỏi câu hỏi B11
    ("B18", "executed_ok"): "result",
    ("B16", "rejected"): "rejection",
}


def message_kind(step: str, event: str, exit_code: str | None) -> str | None:
    if step == "B20":
        return "escalation" if exit_code else None
    return MESSAGE_KIND.get((step, event))


# ---------------------------------------------------------------------------------------------------------------------
# Nguồn dữ liệu
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedRow:
    """Phần dòng `audit_logs` mà SSE được phép dùng — KHÔNG có `detail` thô, `reason`, `query`, `note`."""

    log_id: int
    ticket_id: str
    step: str
    event: str
    to_status: str | None
    created_at: datetime
    intent: str | None = None
    matched_rule_id: str | None = None  # chỉ để chọn câu `thought`, không phát ra
    exit_code: str | None = None
    tools_called: tuple[str, ...] = ()  # B6
    tool_errors: tuple[str, ...] = ()  # tên công cụ lỗi (đã bỏ phần loại lỗi)
    success: bool | None = None  # B17/B18
    action_type: str | None = None  # `intended_action.type` gần nhất ≤ dòng này
    ordinal: int | None = None  # dòng tin trả lời: thứ tự trong cùng (ticket, step, event)
    total: int | None = None


class AuditFeed(Protocol):
    async def rows_after(self, root_id: str, after: int, limit: int) -> list[FeedRow]:
        """Dòng audit của `root_id` VÀ ticket con của nó có `log_id > after`, tăng dần."""
        ...


_ROWS = text(
    "SELECT a.log_id, a.ticket_id, a.step, a.event, a.to_status, a.created_at, a.intent, a.matched_rule_id, a.exit_code, "
    "a.detail->'tools_called' AS tools_called, a.detail->'tool_errors' AS tool_errors, a.detail->'success' AS success, "
    "(SELECT x.intended_action->>'type' FROM audit_logs x WHERE x.ticket_id = a.ticket_id AND x.intended_action IS NOT NULL "
    " AND x.log_id <= a.log_id ORDER BY x.log_id DESC LIMIT 1) AS action_type "
    "FROM audit_logs a WHERE a.log_id > :after AND (a.ticket_id = :t OR a.ticket_id IN "
    "(SELECT c.ticket_id FROM tickets c WHERE c.parent_ticket_id = :t)) ORDER BY a.log_id LIMIT :limit"
)
_ORDINAL = text(
    "SELECT count(*) FILTER (WHERE log_id <= :id) AS ordinal, count(*) AS total FROM audit_logs "
    "WHERE ticket_id = :t AND step = :s AND event = :e AND (:s <> 'B20' OR exit_code IS NOT NULL)"
)


def _strs(value: Any) -> tuple[str, ...]:
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()


class SqlAuditFeed:
    """Đọc `audit_logs` bằng role `app_rw` (có SELECT) — chỉ các cột trong `FeedRow`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def rows_after(self, root_id: str, after: int, limit: int) -> list[FeedRow]:
        async with self._engine.connect() as conn:
            found = (await conn.execute(_ROWS, {"t": root_id, "after": after, "limit": limit})).all()
            rows: list[FeedRow] = []
            for r in found:
                ordinal = total = None
                if r.ticket_id == root_id and message_kind(r.step, r.event, r.exit_code) is not None:
                    counted = (await conn.execute(
                        _ORDINAL, {"id": r.log_id, "t": r.ticket_id, "s": r.step, "e": r.event}
                    )).one()
                    ordinal, total = int(counted.ordinal), int(counted.total)
                errors = tuple(e.split(":", 1)[0].strip() for e in _strs(r.tool_errors))
                rows.append(FeedRow(
                    log_id=int(r.log_id), ticket_id=r.ticket_id, step=r.step, event=r.event, to_status=r.to_status,
                    created_at=r.created_at, intent=r.intent, matched_rule_id=r.matched_rule_id, exit_code=r.exit_code,
                    tools_called=_strs(r.tools_called), tool_errors=errors,
                    success=r.success if isinstance(r.success, bool) else None, action_type=r.action_type,
                    ordinal=ordinal, total=total,
                ))  # fmt: skip
        return rows


# ---------------------------------------------------------------------------------------------------------------------
# Dựng sự kiện
# ---------------------------------------------------------------------------------------------------------------------


def _iso(moment: datetime) -> str:
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def _event(
    kind: str, step: str, label: str, at: str, data: Mapping[str, Any] | None = None, child_id: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"type": kind, "step": step, "label": label, "at": at}
    if data is not None:
        body["data"] = dict(data)
    if child_id is not None:
        body["child_id"] = child_id
    return body


def chunk_text(body: str) -> list[str]:
    """Cắt thành cụm 2–4 từ; nối lại các cụm == `body` nguyên văn (giữ xuống dòng, khoảng trắng)."""
    words = re.findall(r"\S+\s*", body)
    if not words:
        return []
    words[0] = body[: len(body) - len(body.lstrip())] + words[0]
    groups: list[list[str]] = []
    i = 0
    while i < len(words):
        size = CHUNK_SIZES[len(groups) % len(CHUNK_SIZES)]
        groups.append(words[i : i + size])
        i += size
    if len(groups) > 1 and len(groups[-1]) == 1:  # cụm cuối 1 từ → gộp vào cụm trước, hoặc chia lại để mọi cụm ≥ 2 từ
        last = groups.pop()
        if len(groups[-1]) < 4:
            groups[-1] += last
        else:
            groups[-1], last = groups[-1][:-1], [groups[-1][-1], *last]
            groups.append(last)
    return ["".join(g) for g in groups]


def status_events(row: FeedRow, at: str, child_id: str | None) -> list[dict[str, Any]]:
    """tool_call → thought → status của MỘT dòng audit. Dòng ngoài bảng trắng → [] (hoặc chỉ tool_call)."""
    out: list[dict[str, Any]] = []
    out += _tool_events(row, at, child_id)
    entry = TABLE.get((row.step, row.event, row.to_status)) or TABLE.get((row.step, row.event, None))
    if entry is None:
        return out
    thought = entry.thought
    if (row.step, row.event, row.to_status) == ("B13/B14", "risk_decided", S_ASSESSING):
        thought = APPROVAL_THOUGHT_BY_RULE.get(row.matched_rule_id or "", thought)
    if thought is not None:
        out.append(_event("thought", entry.statuses[0].stage if entry.statuses else row.step, thought, at, None, child_id))
    for st in entry.statuses:
        label = st.label.format(intent=INTENT_LABEL.get(row.intent or "", "")).rstrip(": ") if "{intent}" in st.label else st.label
        out.append(_event("status", st.stage, label, at, {"state": st.state}, child_id))
    return out


def _tool_events(row: FeedRow, at: str, child_id: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if row.step in ("B6", "B7"):
        for name in row.tools_called:
            label = TOOL_LABEL.get(name)  # công cụ lạ → bỏ
            if label is not None:
                out.append(_event("tool_call", "diagnose", label, at, {"ok": name not in row.tool_errors}, child_id))
    elif (row.step, row.event) in (("B18", "executed_ok"), ("B17", "exec_failed")):
        label = ACTION_LABEL.get(row.action_type or "")
        if label is not None:
            ok = row.success if row.success is not None else row.event == "executed_ok"
            out.append(_event("tool_call", "execute", label, at, {"ok": ok}, child_id))
    return out


def message_events(message_id: str, body: str, at: str) -> list[dict[str, Any]]:
    out = [_event("token", "answer", "", at, {"message_id": message_id, "text": piece}) for piece in chunk_text(body)]
    out.append(_event("message_end", "answer", "", at, {"message_id": message_id}))
    return out


def pick_message(conversation: Sequence[Mapping[str, Any]], row: FeedRow) -> Mapping[str, Any] | None:
    """Tin của dòng `row`: tin trợ lý thứ `row.ordinal` cùng loại trong `conversation`; chưa lưu → None.
    `conversation` đầy (đã cắt 20 tin cuối) → xếp theo đuôi (giả định mọi dòng đã lưu tin)."""
    kind = message_kind(row.step, row.event, row.exit_code)
    if kind is None or row.ordinal is None:
        return None
    triage = (row.step, row.event) == ("B3", "triage_asked")  # Q1: thứ tự đếm theo (step, event) → chỉ so với tin CÙNG nguồn
    mine = [m for m in conversation if m.get("role") == "assistant" and m.get("kind") == kind
            and (kind != "question" or (m.get("origin") == TRIAGE_ORIGIN) == triage)]  # fmt: skip
    idx = row.ordinal - 1
    if len(conversation) >= CONVERSATION_CAP and row.total is not None:
        idx -= max(0, row.total - len(mine))
    if idx < 0 or idx >= len(mine) or not isinstance(mine[idx].get("text"), str):
        return None
    return mine[idx]


def parse_last_event_id(raw: str | None) -> tuple[int, int]:
    """`N` → (N, 0): tiếp từ dòng > N. `N.k` → (N-1, k): phát lại dòng N bỏ k sự kiện đầu. Sai dạng → (0, 0)."""
    m = re.fullmatch(r"(\d{1,18})(?:\.(\d{1,6}))?", (raw or "").strip())
    if m is None:
        return 0, 0
    n, k = int(m.group(1)), int(m.group(2) or 0)
    return (max(0, n - 1), k) if m.group(2) is not None else (n, 0)


def frame(event: Mapping[str, Any], event_id: str | None) -> bytes:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


# ---------------------------------------------------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------------------------------------------------


async def _sse_enabled(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None)
    if settings is None or not settings.enable_sse:
        raise HTTPException(404, "not_found")


def get_feed(request: Request) -> AuditFeed:
    feed: AuditFeed | None = getattr(request.app.state, "events_feed", None)
    if feed is None:
        raise HTTPException(503, "runtime_unavailable")
    return feed


@router.get("/api/tickets/{ticket_id}/events")
async def ticket_events(
    ticket_id: str,
    request: Request,
    _on: Annotated[None, Depends(_sse_enabled)],
    p: Annotated[Principal, Depends(require("ticket:read:own"))],
    desk: Annotated[Desk, Depends(get_desk)],
    feed: Annotated[AuditFeed, Depends(get_feed)],
) -> StreamingResponse:
    await _readable(request, p, desk, ticket_id)
    settings = request.app.state.settings
    after, skip = parse_last_event_id(request.headers.get("last-event-id"))
    body = _stream(
        request, desk, feed, ticket_id, after=after, skip=skip, fresh=request.headers.get("last-event-id") is None,
        poll_s=settings.sse_poll_ms / 1000, heartbeat_s=settings.sse_heartbeat_s,
    )  # fmt: skip
    return StreamingResponse(body, media_type="text/event-stream", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })  # fmt: skip


async def _stream(
    request: Request, desk: Desk, feed: AuditFeed, root: str, *, after: int, skip: int, fresh: bool, poll_s: float,
    heartbeat_s: float,
) -> AsyncIterator[bytes]:
    started = last_sent = time.monotonic()
    existing: dict[str, int] | None = None  # số tin đã có theo loại LÚC KẾT NỐI (kết nối mới → không tokenise lại)
    stalled_at: float | None = None
    while time.monotonic() - started < MAX_STREAM_S:
        if await request.is_disconnected():
            return
        try:
            snap = await desk.runner.snapshot(root)  # TRƯỚC khi đọc audit: dòng ghi trước checkpoint này đều đọc được
            ticket = await desk.tickets.get(root)
            rows = await feed.rows_after(root, after, FEED_LIMIT)
        except Exception:
            log.exception("SSE %s: đọc nguồn sự kiện lỗi", root)
            return
        values = snap.values or {}
        conversation: list[dict[str, Any]] = list(values.get("conversation") or [])
        if existing is None:
            existing = {}
            for m in conversation:
                if m.get("role") == "assistant" and isinstance(m.get("kind"), str):
                    existing[m["kind"]] = existing.get(m["kind"], 0) + 1
        drained = True
        for row in rows:
            child = None if row.ticket_id == root else row.ticket_id
            at = _iso(row.created_at)
            batch = status_events(row, at, child)
            if child is None and (kind := message_kind(row.step, row.event, row.exit_code)) is not None:
                known = fresh and row.ordinal is not None and row.ordinal <= existing.get(kind, 0)
                if not known:
                    message = pick_message(conversation, row)
                    if message is None:
                        stalled_at = stalled_at or time.monotonic()
                        if time.monotonic() - stalled_at < STALL_S:
                            drained = False  # tin chưa lưu: chờ lượt sau, KHÔNG phát token trước khi lưu
                            break
                    else:
                        batch += message_events(f"{kind}:{row.ordinal}", str(message["text"]), at)
            stalled_at = None
            todo = batch[skip:]
            skip = 0
            for k, event in enumerate(todo):
                last = k == len(todo) - 1
                sent_so_far = len(batch) - len(todo) + k + 1
                yield frame(event, str(row.log_id) if last else f"{row.log_id}.{sent_so_far}")
                last_sent = time.monotonic()
                if event["type"] == "token":
                    await asyncio.sleep(TOKEN_INTERVAL_S)
            after = row.log_id
        if drained:
            waiting = WAITING_FOR.get(snap.next[0]) if snap.next else None
            finished = ticket is not None and ticket.final_state is not None and not snap.next
            if finished or waiting is not None:
                yield _terminal(desk, ticket.final_state if ticket else None, waiting, finished)
                return
        if time.monotonic() - last_sent >= heartbeat_s:
            yield b": hb\n\n"
            last_sent = time.monotonic()
        await asyncio.sleep(poll_s)


def _terminal(desk: Desk, final_state: str | None, waiting: str | None, finished: bool) -> bytes:
    at = _iso(desk.clock.now())
    if finished:
        label = DONE_LABEL.get(final_state or "", DONE_FALLBACK)
        return frame(_event("done", "done", label, at), None)
    assert waiting is not None
    return frame(_event("waiting", waiting, WAITING_LABEL[waiting], at, {"waiting_for": waiting}), None)


__all__ = ["AuditFeed", "FeedRow", "SqlAuditFeed", "router"]
