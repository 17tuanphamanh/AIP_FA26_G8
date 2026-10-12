"""Tin nhắn trong `conversation` (phase3 mục 10.2, 3-Q28 bản 1.1; chốt P9 3g) — theo khuôn B20 `{role, kind, text, ref}`.

- `kind` ∈ `answer` (B10), `question` (B11), `result` (B18), `rejection` (B16 — Phase 4 4c P1), `escalation` (B20 — đã có). `needs` như
  tham số `notify_user`.
- `sources` CHỈ ở `answer`, mỗi nguồn ĐÚNG 3 khoá `chunk_id`, `title`, `heading_path` — không đoạn trích, không bằng chứng
  đã mở rộng (P9).
- Tin người dùng `{role: "user", text}`: `text` là bản ĐÃ CHE (P3) — node chỉ gọi `user_msg` với văn bản đã qua guard.
- Tin kết quả B18 (3h, phase3 11.4 bước 6; P6): theo MẪU, không LLM — chỉ ghép enum (`cert_status`), định danh máy (regex),
  số ngày và ngày hết hạn từ `ExecutionResult.outputs` (đã lọc regex ở model — Q-3h-2). `action_type` lạ → `ValueError` (E9).

`conversation` giữ 20 tin cuối (reducer `append_capped(20)` ở `ticket_state.py`); `GET /api/tickets/{id}` đọc từ checkpoint.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final, Literal

from app.domain.action import FactValue
from app.domain.ticket_state import ChunkRef, Msg

MSG_KINDS: Final = ("answer", "question", "result", "rejection", "escalation")
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
CERT_STATUS_TEXT: Final = {"valid": "còn hiệu lực", "expired": "đã hết hạn", "revoked": "đã bị thu hồi", "none": "chưa có"}
ASK_CONFIRM: Final = "Bạn thử kết nối lại rồi xác nhận giúp mình nhé."
RESULT_ACTIONS: Final = frozenset({"renew_vpn_cert", "reissue_vpn_access", "check_vpn_status"})  # có mẫu ở `result_text`


def _until(outputs: Mapping[str, str]) -> str:
    expires = outputs.get("expires_on")
    return f", hiệu lực tới {date.fromisoformat(expires):%d/%m/%Y}" if expires else ""


def result_text(action_type: str, device_id: str, outputs: Mapping[str, str], facts: Mapping[str, FactValue]) -> str:
    device = f"máy {device_id}" if DEVICE_ID.fullmatch(device_id) else "máy của bạn"
    if action_type == "renew_vpn_cert":
        return f"Đã gia hạn chứng chỉ VPN cho {device}{_until(outputs)}. {ASK_CONFIRM}"
    if action_type == "reissue_vpn_access":
        return f"Đã cấp lại quyền truy cập VPN cho {device}{_until(outputs)}. {ASK_CONFIRM}"
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
    raise ValueError(f"không có mẫu tin kết quả cho {action_type!r}")


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
    # Phase 5 T22a (phase5 4.7b, test d4): nhãn cho 6 hành động khai báo (chưa bật). Nợ T20: `rejection_text` ghép "cho máy …"
    # — sai nghĩa với đích không phải máy (`user:`, `folder:`).
    "reset_password": "đặt lại mật khẩu",
    "unlock_account": "mở khoá tài khoản",
    "install_software": "cài đặt phần mềm",
    "view_permissions": "xem quyền truy cập",
    "grant_permission": "cấp quyền truy cập",
    "extend_permission": "gia hạn quyền truy cập",
}


def rejection_text(action_type: str, device_id: str, reason_code: str | None, note: str | None) -> str:
    """Tin từ chối theo mẫu (P1). `note` None = không kèm câu ghi chú (output guard chặn). `note` phải là bản ĐÃ CHE."""
    label = ACTION_LABELS.get(action_type)
    if label is None:
        head = "Yêu cầu của bạn chưa được duyệt."
    else:
        device = f"máy {device_id}" if DEVICE_ID.fullmatch(device_id) else "máy của bạn"
        head = f"Yêu cầu {label} cho {device} chưa được duyệt."
    reason = REASON_LABELS.get(reason_code, NO_REASON) if reason_code is not None else NO_REASON
    text = f"{head} Lý do: {reason}."
    return text if note is None else f"{text} Ghi chú của người duyệt: {note}"


def rejection_msg(text: str, ref: str | None) -> Msg:
    return {"role": "assistant", "kind": "rejection", "text": text, "ref": ref, "needs": "none"}
