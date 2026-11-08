"""Tin nhắn trong `conversation` (phase3 mục 10.2, 3-Q28 bản 1.1; chốt P9 3g) — theo khuôn B20 `{role, kind, text, ref}`.

- `kind` ∈ `answer` (B10), `question` (B11), `result` (B18), `rejection` (B16 — Phase 4 4c P1), `escalation` (B20 — đã có). `needs` như
  tham số `notify_user`.
- `sources` CHỈ ở `answer`, mỗi nguồn ĐÚNG 3 khoá `chunk_id`, `title`, `heading_path` — không đoạn trích, không bằng chứng
  đã mở rộng (P9).
- Tin người dùng `{role: "user", text}`: `text` là bản ĐÃ CHE (P3) — node chỉ gọi `user_msg` với văn bản đã qua guard.
- Tin kết quả B18 (3h, phase3 11.4 bước 6; P6): theo MẪU, không LLM — chỉ ghép enum (`cert_status`), định danh máy (regex),
  số ngày và ngày hết hạn từ `ExecutionResult.outputs` (đã lọc regex ở model — Q-3h-2). `action_type` lạ → `ValueError` (E9).
  T24 (P4, bảng 7.3): thêm 6 mẫu account/software/access; `result_text` tự lọc lại `outputs` theo `EXEC_OUTPUT_PATTERNS` và định
  danh trong `params` theo mẫu (lớp thứ hai); `{đích}` = `person_phrase` (Q-T24-2); `view_permissions` đọc dòng quyền từ
  `diagnostics` của B6 qua `permission_rows` (≤ 10 dòng; không có dữ liệu → "chưa đọc được" — Q-T24-5).

`conversation` giữ 20 tin cuối (reducer `append_capped(20)` ở `ticket_state.py`); `GET /api/tickets/{id}` đọc từ checkpoint.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from app.domain.action import SOFTWARE_NAME, Action, FactValue
from app.domain.children import ChildView, summary_text
from app.domain.ticket_state import EXEC_OUTPUT_PATTERNS, ChunkRef, Msg

MSG_KINDS: Final = ("answer", "question", "result", "rejection", "escalation", "duplicate")
SOURCE_KEYS: Final = ("chunk_id", "title", "heading_path")


def source_of(chunk: ChunkRef) -> dict[str, str]:
    return {"chunk_id": chunk.chunk_id, "title": chunk.title, "heading_path": chunk.heading_path}


def answer_msg(text: str, ref: str | None, cited: Sequence[ChunkRef]) -> Msg:
    """Câu trả lời B10; `cited` = các chunk top-5 được trích (không trùng, giữ thứ tự)."""
    seen: dict[str, dict[str, str]] = {}
    for c in cited:
        seen.setdefault(c.chunk_id, source_of(c))
    return {"role": "assistant", "kind": "answer", "text": text, "ref": ref, "needs": "confirm",
            "sources": list(seen.values())}  # fmt: skip


def question_msg(text: str, ref: str | None) -> Msg:
    return {"role": "assistant", "kind": "question", "text": text, "ref": ref, "needs": "answer"}


def user_msg(redacted_text: str) -> Msg:
    return {"role": "user", "text": redacted_text}


DEVICE_ID: Final = re.compile(r"[A-Z]{2,4}-\d{3,5}")  # cùng mẫu `value_rules.device_id` (slots.yaml)
# T20a P11 — cùng mẫu `value_rules.target_user` / `value_rules.resource_path` (slots.yaml; test m1 ghim bằng nhau): định danh
# chỉ được ghép vào tin khi qua mẫu (5.1.8 mục 8 — không chép chữ người dùng ngoài định danh đã qua regex).
USER_ID: Final = re.compile(r"[a-z0-9_]{3,64}")
RESOURCE_PATH: Final = re.compile(r"(?!.*(^|/)\.{1,2}(/|$))[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+){0,4}")
CERT_STATUS_TEXT: Final = {"valid": "còn hiệu lực", "expired": "đã hết hạn", "revoked": "đã bị thu hồi", "none": "chưa có"}
ASK_CONFIRM: Final = "Bạn thử kết nối lại rồi xác nhận giúp mình nhé."
RESULT_ACTIONS: Final = frozenset({
    "renew_vpn_cert", "reissue_vpn_access", "check_vpn_status",
    "reset_password", "unlock_account", "install_software", "view_permissions", "grant_permission", "extend_permission",
})  # có mẫu ở `result_text` — T24 P4: đủ 9  # fmt: skip
# T24 bảng 7.3 / 7.4: `{loại}` của tài khoản (enum `account_type`)
ACCOUNT_TYPE_TEXT: Final[Mapping[str, str]] = {"ad": "đăng nhập (AD)", "email": "email", "erp": "ERP"}
PERMISSION_LEVELS: Final = frozenset({"read", "write", "full"})
MAX_PERMISSION_ROWS: Final = 10
ASK_CONFIRM_LOGIN: Final = "Bạn đăng nhập thử rồi xác nhận giúp mình nhé."
ASK_CONFIRM_OPEN: Final = "Bạn mở thử rồi xác nhận giúp mình nhé."
ASK_CONFIRM_VIEW: Final = "Bạn xem đã đủ chưa rồi xác nhận giúp mình nhé."
# Lô N (N10, ca TC07): đối tượng KHÁC người gửi (`requested_for != requester_id` — đúng quy tắc của `person_phrase`) → người gửi
# không tự thử được; câu xác nhận nói việc của người gửi. Tài khoản dịch vụ = fact `target_is_service_account` (B6
# `check_account_status`; `ACCOUNT_TYPE_TEXT` chỉ có ad/email/erp). Ca tự yêu cầu cho mình dùng câu cũ y nguyên.
ASK_CONFIRM_OTHER: Final = "Bạn nhờ người dùng máy này kết nối lại rồi xác nhận giúp mình nhé."
ASK_CONFIRM_LOGIN_OTHER: Final = "Bạn nhờ người dùng tài khoản này đăng nhập thử rồi xác nhận giúp mình nhé."
ASK_CONFIRM_LOGIN_SERVICE: Final = "Bạn kiểm tra dịch vụ dùng tài khoản này đã đăng nhập lại được chưa rồi xác nhận giúp mình nhé."
ASK_CONFIRM_OPEN_OTHER: Final = "Bạn nhờ người được yêu cầu mở thử rồi xác nhận giúp mình nhé."
ASK_CONFIRM_VIEW_OTHER: Final = "Bạn xem danh sách quyền này đã đủ chưa rồi xác nhận giúp mình nhé."
RESET_SMS_TAIL: Final = "bạn sẽ được yêu cầu đổi mật khẩu khi đăng nhập."
RESET_SMS_TAIL_OTHER: Final = "người dùng tài khoản này sẽ được yêu cầu đổi mật khẩu ở lần đăng nhập tới."
RESET_DEFAULT_OTHER: Final = "Người dùng tài khoản này sẽ được yêu cầu đổi mật khẩu ở lần đăng nhập tới."


def _until(outputs: Mapping[str, str]) -> str:
    expires = outputs.get("expires_on")
    return f", hiệu lực tới {date.fromisoformat(expires):%d/%m/%Y}" if expires else ""


# T24 P4 (TQ-8): một dòng quyền cho mẫu `view_permissions` — (đường dẫn qua `RESOURCE_PATH`, mức enum, ngày hết hạn địa phương
# hoặc None = không thời hạn). Dựng bằng `permission_rows` từ `diagnostics` của B6 (dữ liệu tool).
type PermRow = tuple[str, str, date | None]


def person_phrase(requested_for: str, requester_id: str) -> str:
    """T24 (Q-T24-2): cụm chỉ NGƯỜI bị tác động cho `{đích}` của tin kết quả B18 — người gửi → "bạn"; khác → mã nhân viên (qua
    `USER_ID`); sai mẫu → "người được yêu cầu"."""
    if requested_for == requester_id:
        return "bạn"
    return requested_for if USER_ID.fullmatch(requested_for) else "người được yêu cầu"


def _confirm_texts(action: Action, requester_id: str) -> tuple[str, str, str, str]:
    """(kết nối VPN, đăng nhập, mở thử, xem) — câu xác nhận theo đối tượng: của mình → câu cũ; người khác → câu cho bên thứ ba;
    tài khoản dịch vụ (`target_is_service_account is True`) → câu kiểm dịch vụ cho mẫu đăng nhập."""
    if action.requested_for == requester_id:
        return ASK_CONFIRM, ASK_CONFIRM_LOGIN, ASK_CONFIRM_OPEN, ASK_CONFIRM_VIEW
    service = action.facts.get("target_is_service_account") is True
    login = ASK_CONFIRM_LOGIN_SERVICE if service else ASK_CONFIRM_LOGIN_OTHER
    return ASK_CONFIRM_OTHER, login, ASK_CONFIRM_OPEN_OTHER, ASK_CONFIRM_VIEW_OTHER


def _local_date(raw: object, tz: ZoneInfo) -> date | None:
    """ISO datetime (có múi giờ; không có → coi là UTC) → ngày địa phương. Sai kiểu → TypeError, sai dạng → ValueError."""
    if not isinstance(raw, str):
        raise TypeError("expires_at không phải chuỗi")
    at = datetime.fromisoformat(raw)
    return (at if at.tzinfo is not None else at.replace(tzinfo=UTC)).astimezone(tz).date()


def permission_rows(raw: object, tz: str) -> tuple[PermRow, ...] | None:
    """T24 P4 (TQ-8, Q-T24-5): `diagnostics["check_current_permissions"]` (B6, JSON) → các dòng hợp lệ. Không phải danh sách
    (thiếu khoá, None = 404/không chẩn đoán) → None ("chưa đọc được"); danh sách → dòng sai mẫu bị bỏ (chưa cắt 10)."""
    if not isinstance(raw, list):
        return None
    zone = ZoneInfo(tz)
    rows: list[PermRow] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        path, level, expires = item.get("path"), item.get("level"), item.get("expires_at")
        if not isinstance(path, str) or not RESOURCE_PATH.fullmatch(path) or level not in PERMISSION_LEVELS:
            continue
        try:
            day = None if expires is None else _local_date(expires, zone)
        except (TypeError, ValueError):
            continue
        rows.append((path, str(level), day))
    return tuple(rows)


def _out(outputs: Mapping[str, str], key: str) -> str | None:
    """Giá trị `outputs[key]` CHỈ khi qua mẫu P4 (lớp thứ hai sau `ExecutionResult`); ngày phải là ngày thật."""
    value = outputs.get(key)
    pattern = EXEC_OUTPUT_PATTERNS.get(key)
    if not isinstance(value, str) or pattern is None or not pattern.fullmatch(value):
        return None
    if key == "expires_on":
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
    return value


def _dmy(iso: str | None) -> str | None:
    return None if iso is None else f"{date.fromisoformat(iso):%d/%m/%Y}"


def _reset_delivery(outputs: Mapping[str, str], *, other: bool = False) -> str:
    """Câu kênh nhận mật khẩu tạm — chỉ từ `outputs` đã qua mẫu (`sent_to` chỉ số ĐÃ CHE, phút 1–60); KHÔNG bao giờ mật khẩu.
    sms: mock gửi mật khẩu tạm một lần tới số trong AD. email: chỉ nói điều hệ thống tài khoản xác nhận (mock không gửi gì
    thật ở kênh này). `other` (lô N, N10): tài khoản của người khác → câu đổi mật khẩu (SMS, email, mặc định) nói về người dùng
    tài khoản đó; ca của mình giữ chữ cũ."""
    via = _out(outputs, "delivered_via")
    if via == "sms":
        to = _out(outputs, "sent_to")
        minutes = _out(outputs, "expires_in_minutes")
        return (f"Mật khẩu tạm đã gửi qua SMS tới {f'số {to}' if to else 'số điện thoại đã đăng ký'}"
                f"{f', hiệu lực {minutes} phút' if minutes else ''}, chỉ dùng một lần; "
                f"{RESET_SMS_TAIL_OTHER if other else RESET_SMS_TAIL}")  # fmt: skip
    if via == "email":
        tail = RESET_SMS_TAIL_OTHER if other else "bạn cần đổi mật khẩu ở lần đăng nhập tới."
        return f"Hệ thống tài khoản xác nhận mật khẩu tạm được gửi qua email; {tail}"
    return RESET_DEFAULT_OTHER if other else "Bạn cần đổi mật khẩu ở lần đăng nhập tới."


def _new_action_text(
    action: Action, outputs: Mapping[str, str], requester_id: str, rows: Sequence[PermRow] | None
) -> str:
    """6 mẫu T24 (bảng 7.3) — chỉ enum, định danh qua mẫu, ngày; thiếu giá trị → bỏ cụm."""
    p = action.params
    who = person_phrase(action.requested_for, requester_id)
    _, confirm_login, confirm_open, confirm_view = _confirm_texts(action, requester_id)
    kind = ACCOUNT_TYPE_TEXT.get(str(p.get("account_type")))
    account = f"tài khoản {kind} của {who}" if kind else f"tài khoản của {who}"
    path_raw = str(p.get("resource_path", ""))
    folder = f"thư mục {path_raw}" if RESOURCE_PATH.fullmatch(path_raw) else "thư mục được yêu cầu"
    until = _dmy(_out(outputs, "expires_on"))
    if action.type == "reset_password":
        return f"Đã đặt lại mật khẩu {account}. {_reset_delivery(outputs, other=action.requested_for != requester_id)} {confirm_login}"
    if action.type == "unlock_account":
        return f"Đã mở khoá {account}. {confirm_login}"
    if action.type == "install_software":
        raw_software = str(p.get("software_name", ""))  # Q-T24-7: tên đã chuẩn hoá của Action, KHÔNG lấy tên hệ thống ngoài trả về
        software = raw_software if SOFTWARE_NAME.fullmatch(raw_software) else "phần mềm"
        version = _out(outputs, "version")
        device_id = str(p.get("device_id", ""))
        device = f"máy {device_id}" if DEVICE_ID.fullmatch(device_id) else "máy của bạn"
        return f"Đã cài {software}{f' phiên bản {version}' if version else ''} lên {device}. {confirm_open}"
    if action.type == "view_permissions":
        if rows is None:
            return (f"Mình chưa đọc được danh sách quyền truy cập của {who}. "
                    "Bạn liên hệ IT để kiểm lại rồi xác nhận giúp mình nhé.")  # fmt: skip
        shown = [r for r in rows if RESOURCE_PATH.fullmatch(r[0]) and r[1] in PERMISSION_LEVELS][:MAX_PERMISSION_ROWS]
        listed = "; ".join(
            f"{path} ({level}, {f'hết hạn {day:%d/%m/%Y}' if day is not None else 'không thời hạn'})"
            for path, level, day in shown
        )
        return f"Quyền truy cập hiện có của {who}: {listed or 'chưa thấy quyền nào'}. {confirm_view}"
    if action.type == "grant_permission":
        level = _out(outputs, "level")
        return (f"Đã cấp quyền {f'{level} ' if level else ''}{folder} cho {who}"
                f"{f', hiệu lực tới {until}' if until else ''}. {confirm_open}")  # fmt: skip
    if action.type == "extend_permission":
        return f"Đã gia hạn quyền {folder} của {who}{f' tới {until}' if until else ''}. {confirm_open}"
    raise ValueError(f"không có mẫu tin kết quả cho {action.type!r}")


def result_text(
    action: Action, outputs: Mapping[str, str], facts: Mapping[str, FactValue], *, requester_id: str,
    rows: Sequence[PermRow] | None = (),
) -> str:  # fmt: skip
    """Tin kết quả B18 theo MẪU (P6; T24 P4 bảng 7.3). `rows` chỉ dùng cho `view_permissions` (None = chưa đọc được)."""
    action_type = action.type
    device_id = str(action.params.get("device_id", ""))
    device = f"máy {device_id}" if DEVICE_ID.fullmatch(device_id) else "máy của bạn"
    confirm = _confirm_texts(action, requester_id)[0]
    if action_type == "renew_vpn_cert":
        return f"Đã gia hạn chứng chỉ VPN cho {device}{_until(outputs)}. {confirm}"
    if action_type == "reissue_vpn_access":
        return f"Đã cấp lại quyền truy cập VPN cho {device}{_until(outputs)}. {confirm}"
    if action_type == "check_vpn_status":
        status = facts.get("cert_status")
        cert = CERT_STATUS_TEXT.get(status, "chưa rõ") if isinstance(status, str) else "chưa rõ"
        days = facts.get("cert_days_to_expiry")
        if type(days) is int and status == "valid":
            cert += f", còn {days} ngày"
        elif type(days) is int and status == "expired":
            cert += f", quá hạn {-days} ngày"
        conn = facts.get("last_connection_ok")
        last = "thành công" if conn is True else "không thành công" if conn is False else "chưa có dữ liệu"
        return (f"Chứng chỉ VPN của {device}: {cert}. Lần kết nối gần nhất: {last}. "
                "Bạn xem thông tin này đã đủ chưa rồi xác nhận giúp mình nhé.")  # fmt: skip
    return _new_action_text(action, outputs, requester_id, rows)


def result_msg(text: str, ref: str | None) -> Msg:
    return {"role": "assistant", "kind": "result", "text": text, "ref": ref, "needs": "confirm"}


# Mẫu lý do chọn nhanh khi từ chối (B15-B16 §4, P10 3.2 [Chốt 16.2]; PLAN-3e Q-3e-13) — ô này KHÔNG qua privacy guard nên chỉ nhận
# mã cố định. Route duyệt (`api/approvals.py`) và nhãn tin từ chối dùng CHUNG định nghĩa này.
type ReasonCode = Literal[
    "missing_info", "not_authorized", "policy_violation", "duplicate", "wrong_device", "security_concern", "other",
]  # fmt: skip
REASON_LABELS: Final[Mapping[str, str]] = {
    "missing_info": "thiếu thông tin", "not_authorized": "không đủ thẩm quyền", "policy_violation": "trái chính sách",
    "duplicate": "yêu cầu trùng lặp", "wrong_device": "sai máy", "security_concern": "lo ngại về bảo mật", "other": "lý do khác",
}  # fmt: skip
NO_REASON: Final = "không nêu"
# Nhãn hành động — mọi `action_type` của `config/action_metadata.yaml` phải có (test d4).
ACTION_LABELS: Final[Mapping[str, str]] = {
    "renew_vpn_cert": "gia hạn chứng chỉ VPN",
    "reissue_vpn_access": "cấp lại quyền truy cập VPN",
    "check_vpn_status": "kiểm tra trạng thái VPN",
    # Phase 5 T22a (phase5 4.7b, test d4): nhãn cho 6 hành động khai báo (chưa bật). T20a P11: cụm đích theo `target_phrase`.
    "reset_password": "đặt lại mật khẩu",
    "unlock_account": "mở khoá tài khoản",
    "install_software": "cài đặt phần mềm",
    "view_permissions": "xem quyền truy cập",
    "grant_permission": "cấp quyền truy cập",
    "extend_permission": "gia hạn quyền truy cập",
}


def target_phrase(action: Action, requester_id: str) -> str:
    """T20a P11: cụm chỉ đích của hành động cho tin từ chối, theo tiền tố `action.target`. `device:<id>` → "máy <id>" (sai mẫu →
    "máy của bạn" — giữ chữ VPN cũ); `user:<id>` → "tài khoản của bạn" (id == người gửi) / "tài khoản <id>" (sai mẫu → "tài khoản
    được yêu cầu"); `folder:<path>` → "thư mục <path>" (sai mẫu → "thư mục được yêu cầu"); tiền tố lạ → "" (câu chung)."""
    kind, _, ident = action.target.partition(":")
    if kind == "device":
        return f"máy {ident}" if DEVICE_ID.fullmatch(ident) else "máy của bạn"
    if kind == "user":
        if not USER_ID.fullmatch(ident):
            return "tài khoản được yêu cầu"
        return "tài khoản của bạn" if ident == requester_id else f"tài khoản {ident}"
    if kind == "folder":
        return f"thư mục {ident}" if RESOURCE_PATH.fullmatch(ident) else "thư mục được yêu cầu"
    return ""


def rejection_text(action_type: str, target_phrase: str, reason_code: str | None, note: str | None) -> str:
    """Tin từ chối theo mẫu (P1). `target_phrase` = `target_phrase(action, requester_id)` (T20a P11); rỗng hoặc hành động không
    nhãn → câu chung. `note` None = không kèm câu ghi chú (output guard chặn). `note` phải là bản ĐÃ CHE."""
    label = ACTION_LABELS.get(action_type)
    if label is None or not target_phrase:
        head = "Yêu cầu của bạn chưa được duyệt."
    else:
        head = f"Yêu cầu {label} cho {target_phrase} chưa được duyệt."
    reason = REASON_LABELS.get(reason_code, NO_REASON) if reason_code is not None else NO_REASON
    text = f"{head} Lý do: {reason}."
    return text if note is None else f"{text} Ghi chú của người duyệt: {note}"


def rejection_msg(text: str, ref: str | None) -> Msg:
    return {"role": "assistant", "kind": "rejection", "text": text, "ref": ref, "needs": "none"}


def duplicate_msg(text: str, ref: str | None) -> Msg:
    """M1 — tin báo trùng yêu cầu của B3 (mẫu cố định, không LLM). Không phải `NOTICE_KINDS`: B3 chỉ chạy ở ticket lá, không phải con."""
    return {"role": "assistant", "kind": "duplicate", "text": text, "ref": ref, "needs": "none"}


# ---- Tin tổng hợp của ticket cha (Phase 5 T20b P8, P9 — phase5 5.2.5, 5.2.6; D-31) ----------------------------------------------
# Thuần, theo mẫu, KHÔNG LLM (chốt 10/10 (a)). Tiêu đề ý: `ACTION_LABELS[seed.slots.action]` nếu có, không thì nhãn loại yêu cầu theo
# `seed.intent`; ý E1 (không có `intent`) → `OTHER_LABEL`. Chữ cái đầu viết hoa ("Đặt lại mật khẩu").
INTENT_LABELS: Final[Mapping[str, str]] = {
    "account": "Tài khoản", "vpn": "VPN", "software": "Phần mềm", "access": "Quyền truy cập",
}  # fmt: skip
OTHER_LABEL: Final = "Yêu cầu khác"
# `items[].kind` FE nhận (5.2.6): notice `answer` (B10) hiển thị như `result`.
DIGEST_ITEM_KINDS: Final = ("result", "question", "rejection", "escalation")
CONFIRMED_TEXT: Final = "Đã ổn"
UNRESOLVED_TEXT: Final = "Chưa ổn"


@dataclass(frozen=True)
class Digest:
    """Tin `digest` của một vòng + id các notice vừa gom (cha đánh dấu `delivered_round` CÙNG transaction với `notify_user`)."""

    msg: Msg
    notice_ids: tuple[int, ...]


def child_title(seed: Mapping[str, Any]) -> str:
    """Tiêu đề khối của một ý (P9) từ seed của con (bảng 5.2.3) — không bao giờ do LLM đặt."""
    action = (seed.get("slots") or {}).get("action")
    label = ACTION_LABELS.get(action) if isinstance(action, str) else None
    if label is None:
        intent = seed.get("intent")
        label = INTENT_LABELS.get(intent, OTHER_LABEL) if isinstance(intent, str) else OTHER_LABEL
    return label[:1].upper() + label[1:]


def compose_digest(view: Sequence[ChildView], seeds: Mapping[str, Mapping[str, Any]], *, round_no: int) -> Digest:
    """Tin tổng hợp vòng `round_no` (P9, 5.2.6): `{role:"assistant", kind:"digest", round, text, items:[{child_id, index, title,
    kind, text, needs}]}`. Mỗi notice chưa gửi một item, theo `index` rồi thứ tự tạo; con không có notice mới → không lặp lại.
    `text` = các khối "Ý {index} – {title}: {body}" nối xuống dòng, + câu tổng kết (bảng 5.2.5) khi MỌI con đã kết thúc (vòng cuối không
    còn notice nào → chỉ câu tổng kết). Không chữ nào ngoài `body` notice + mẫu + số."""
    items: list[dict[str, Any]] = []
    ids: list[int] = []
    for child in sorted(view, key=lambda c: c.index):
        title = child_title(seeds.get(child.child_id) or {})
        for n in sorted(child.pending, key=lambda n: (n.created_at, n.notice_id)):
            items.append({
                "child_id": child.child_id, "index": child.index, "title": title,
                "kind": "result" if n.kind == "answer" else n.kind, "text": n.body, "needs": n.needs,
            })  # fmt: skip
            ids.append(n.notice_id)
    lines = [f"Ý {it['index']} – {it['title']}: {it['text']}" for it in items]
    if all(c.final_state is not None for c in view):
        lines.append(summary_text(view))
    msg = {"role": "assistant", "kind": "digest", "round": round_no, "text": "\n".join(lines), "items": items}
    return Digest(msg, tuple(ids))


def reply_text(items: Sequence[tuple[int, Mapping[str, Any]]]) -> str:
    """Tin người dùng ghép của `/reply` (P8, chốt (d)) — `(index, mục ĐÃ CHE của body)` theo thứ tự `index`: `{"answer": s}` →
    "Ý i: s"; `{"confirmed": True}` → "Ý i: Đã ổn"; `{"confirmed": False, "note": g}` → "Ý i: Chưa ổn — g" (ghi chú rỗng/None →
    "Ý i: Chưa ổn"). Nối bằng " · "."""
    parts = []
    for index, item in sorted(items, key=lambda x: x[0]):
        if "answer" in item:
            parts.append(f"Ý {index}: {item['answer']}")
        elif item.get("confirmed"):
            parts.append(f"Ý {index}: {CONFIRMED_TEXT}")
        else:
            note = str(item.get("note") or "").strip()
            parts.append(f"Ý {index}: {UNRESOLVED_TEXT} — {note}" if note else f"Ý {index}: {UNRESOLVED_TEXT}")
    return " · ".join(parts)
