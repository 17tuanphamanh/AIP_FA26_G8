"""Mẫu tin và "hộp thư đi" của mock (F2 — đặt lại mật khẩu qua SMS).

Mock không gửi tin thật: tin được ghi vào `MockState.outbox`; `GET /_admin/outbox` trả danh sách với mật khẩu tạm ĐÃ CHE.
SMS là tin duy nhất mang mật khẩu tạm (nội dung "đã tới điện thoại" người nhận). Email báo chủ tài khoản được dựng từ mẫu
KHÔNG nhận mật khẩu — về cấu trúc không thể lộ mật khẩu tạm.

Không import `app.state` (state import module này — tránh vòng import).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

MASK = "******"

SMS_TEMP_PASSWORD = (
    "[Service Desk] Mat khau tam cua ban: {temp}. Het han sau {ttl} phut, chi dung 1 lan; "
    "doi mat khau ngay khi dang nhap. Khong chia se ma nay voi bat ky ai."
)
EMAIL_SMS_RESET_NOTICE = (
    "Có yêu cầu đặt lại mật khẩu qua SMS lúc {at} tới số {phone}. Mật khẩu tạm đã gửi qua SMS và hết hạn sau {ttl} phút.\n"
    "Nếu không phải bạn yêu cầu, hãy liên hệ ngay bộ phận IT (có thể SIM của bạn đã bị chiếm)."
)


@dataclass
class OutboxMessage:
    channel: Literal["sms", "email"]
    to: str  # sms: số điện thoại trong seed; email: username chủ tài khoản (mock không có địa chỉ email)
    at: datetime
    # SMS chứa mật khẩu tạm — không để lọt vào log qua repr()
    body: str = field(repr=False)
    # chuỗi phải che khi xem qua /_admin/outbox
    secret: str | None = field(default=None, repr=False)

    def view(self) -> dict[str, Any]:
        body = self.body.replace(self.secret, MASK) if self.secret else self.body
        return {"channel": self.channel, "to": self.to, "at": self.at, "body": body}


def mask_phone(phone: str) -> str:
    """Che số điện thoại: 0900000123 → 0900***123."""
    return f"{phone[:4]}***{phone[-3:]}"


def _when(at: datetime) -> str:
    return at.strftime("%d/%m/%Y %H:%M UTC")


def send_temp_password_sms(
    outbox: list[OutboxMessage], phone: str, temp: str, at: datetime, ttl_minutes: int
) -> None:
    body = SMS_TEMP_PASSWORD.format(temp=temp, ttl=ttl_minutes)
    outbox.append(OutboxMessage("sms", phone, at, body, secret=temp))


def send_sms_reset_notice(
    outbox: list[OutboxMessage],
    username: str,
    phone: str,
    at: datetime,
    ttl_minutes: int,
) -> None:
    body = EMAIL_SMS_RESET_NOTICE.format(
        at=_when(at), phone=mask_phone(phone), ttl=ttl_minutes
    )
    outbox.append(OutboxMessage("email", username, at, body))
