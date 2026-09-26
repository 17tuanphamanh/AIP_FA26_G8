"""Bản nháp cảnh báo (`alerts`, P9 mục 6) — kiểu thuần, dùng chung cho mọi nơi sinh cảnh báo.

Khoá chống trùng `(rule_id, subject, window_start)` (migration 0004): `subject` là đối tượng của cảnh
báo — user_id với luật theo người, ticket_id với luật theo ticket, `SYSTEM_SUBJECT` ('') với luật tổng
hợp. Thiếu `subject` thì hai người bị khoá cùng lúc bị gộp thành một cảnh báo = bỏ sót sự cố an ninh;
cột không có DEFAULT nên INSERT quên `subject` lỗi ngay.

`window_start` của B1 = `locked_until − LOCKOUT`: đổi LOCKOUT giữa một đợt khoá thì B1 tính ra khoá
khác auth → thêm một cảnh báo thừa (False Positive, chấp nhận — không bao giờ mất cảnh báo).

Luật dò mật khẩu (P9 luật 3) có HAI nơi sinh — auth lúc khoá và B1 khi ticket của người đang bị khoá
chạy tới (quyết định Q1, 26/09/2026) — nên khoá phải tính cùng một cách ở cả hai: `bruteforce_alert`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.core.hashing import sha256_key

BRUTEFORCE_RULE_ID = "password_bruteforce"  # P9 luật 3 "Dò mật khẩu" — Trưởng BP (ngay)
SUBJECT_MAX = 64  # alerts.subject VARCHAR(64)
SYSTEM_SUBJECT = ""  # luật tổng hợp (không gắn người/ticket) — truyền tường minh, cột không có DEFAULT

type Severity = Literal["info", "warning", "critical"]


@dataclass(frozen=True)
class AlertDraft:
    rule_id: str
    subject: str  # user_id | ticket_id | SYSTEM_SUBJECT (luật tổng hợp)
    window_start: datetime
    severity: Severity
    value: float | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


def bruteforce_subject(user_id: str | None, username: str) -> str:
    """user_id nếu biết; username chưa có dòng `users` (không tồn tại) → định danh theo username."""
    if user_id is not None:
        return user_id
    subject = f"username:{username}"
    return subject if len(subject) <= SUBJECT_MAX else f"username#{sha256_key(username)[:40]}"


def bruteforce_alert(
    *, user_id: str | None, username: str, lock_start: datetime, source: str,
    ticket_id: str | None = None,
) -> AlertDraft:  # fmt: skip
    """Một cảnh báo cho một đợt khoá: `window_start` = thời điểm bắt đầu khoá (auth: lúc khoá;
    B1: `locked_until − LOCKOUT`) — hai nơi sinh ra cùng khoá, DB giữ đúng một dòng."""
    detail: dict[str, Any] = {"user_id": user_id, "username": username, "source": source}
    if ticket_id is not None:
        detail["ticket_id"] = ticket_id
    return AlertDraft(
        rule_id=BRUTEFORCE_RULE_ID, subject=bruteforce_subject(user_id, username),
        window_start=lock_start, severity="critical", detail=detail,
    )  # fmt: skip
