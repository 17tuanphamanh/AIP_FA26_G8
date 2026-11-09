"""Gửi email qua SMTP + job worker `send_emails` (notify-email).

`SmtpSender`: `smtplib` (đồng bộ) chạy trong `asyncio.to_thread` — không chặn vòng sự kiện của worker. Timeout 15 s mỗi thao tác
socket. `SMTP_STARTTLS=true` → STARTTLS BẮT BUỘC: máy chủ không quảng bá STARTTLS → `StartTlsUnavailable` (không bao giờ rơi về kênh
rõ); TLS dùng `ssl.create_default_context()` (kiểm chứng chỉ + tên máy). Có tài khoản → `login` SAU STARTTLS. Mật khẩu chỉ lấy từ
`SecretStr` lúc login, không log.

`EmailSendJob.run` (mỗi `EMAIL_SEND_INTERVAL_SECONDS`, mặc định 15 s): `claim` tối đa `EMAIL_BATCH` (20) dòng `pending` (FOR UPDATE SKIP
LOCKED + hạn giữ chỗ), gửi lần lượt. Thành công → `sent`. Người nhận không còn địa chỉ → `skipped`. Lỗi → `attempts + 1`,
`last_error_class` = TÊN LỚP exception, thử lại sau backoff `EMAIL_BACKOFF_BASE_S · 2^(attempts−1)` (trần `EMAIL_BACKOFF_MAX_S`); đủ
`EMAIL_MAX_ATTEMPTS` (5) lần lỗi → `failed`. Log chỉ id dòng, loại, tên lớp lỗi, số lần — KHÔNG thân, KHÔNG địa chỉ, KHÔNG thông điệp
exception (có thể chứa địa chỉ/phản hồi máy chủ).
"""

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Final, Protocol

from pydantic import SecretStr

from app.core.clock import Clock
from app.notify.outbox import ClaimedEmail, SqlEmailOutbox
from app.settings import Settings

log = logging.getLogger(__name__)

SMTP_TIMEOUT_S: Final = 15.0
EMAIL_BATCH: Final = 20
EMAIL_MAX_ATTEMPTS: Final = 5
EMAIL_BACKOFF_BASE_S: Final = 60.0
EMAIL_BACKOFF_MAX_S: Final = 3600.0
EMAIL_CLAIM_LEASE: Final = timedelta(minutes=10)  # > EMAIL_BATCH × thời gian xấu nhất một thư — worker khác không lấy lại dòng đang gửi


class StartTlsUnavailable(Exception):
    """SMTP_STARTTLS=true mà máy chủ không hỗ trợ STARTTLS — không gửi (không hạ xuống kênh rõ)."""


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


type SmtpFactory = Callable[..., smtplib.SMTP]


class SmtpSender:
    def __init__(
        self, *, host: str, port: int, starttls: bool, username: str | None, password: SecretStr | None, sender: str,
        timeout: float = SMTP_TIMEOUT_S, smtp_factory: SmtpFactory = smtplib.SMTP,
        tls_context: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    ) -> None:  # fmt: skip
        if username is not None and not starttls:
            raise ValueError("SMTP có tài khoản phải bật STARTTLS")
        self._host = host
        self._port = port
        self._starttls = starttls
        self._username = username
        self._password = password
        self._sender = sender
        self._timeout = timeout
        self._smtp = smtp_factory
        self._tls_context = tls_context

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmtpSender":
        assert settings.smtp_host is not None and settings.smtp_from is not None  # Settings._email_config đã bắt
        return cls(
            host=settings.smtp_host, port=settings.smtp_port, starttls=settings.smtp_starttls,
            username=settings.smtp_username, password=settings.smtp_password, sender=settings.smtp_from,
        )  # fmt: skip

    def _message(self, to: str, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self._sender
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=self._sender.rpartition("@")[2] or None)
        msg.set_content(body)
        return msg

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = self._message(to, subject, body)
        with self._smtp(self._host, self._port, timeout=self._timeout) as smtp:
            smtp.ehlo()
            if self._starttls:
                if not smtp.has_extn("starttls"):
                    raise StartTlsUnavailable("máy chủ SMTP không hỗ trợ STARTTLS")
                smtp.starttls(context=self._tls_context())
                smtp.ehlo()
            if self._username is not None and self._password is not None:
                smtp.login(self._username, self._password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)


def backoff(attempts: int) -> timedelta:
    """Độ trễ trước lần thử kế tiếp sau `attempts` lần lỗi (≥ 1)."""
    return timedelta(seconds=min(EMAIL_BACKOFF_BASE_S * 2 ** max(attempts - 1, 0), EMAIL_BACKOFF_MAX_S))


@dataclass
class SendReport:
    sent: int = 0
    retried: int = 0
    failed: int = 0
    skipped: int = 0


class EmailSendJob:
    def __init__(
        self, outbox: SqlEmailOutbox, sender: EmailSender, clock: Clock, *, batch: int = EMAIL_BATCH,
        max_attempts: int = EMAIL_MAX_ATTEMPTS,
    ) -> None:  # fmt: skip
        self._outbox = outbox
        self._sender = sender
        self._clock = clock
        self._batch = batch
        self._max_attempts = max_attempts

    async def run(self) -> SendReport:
        report = SendReport()
        for email in await self._outbox.claim(self._clock.now(), self._batch, EMAIL_CLAIM_LEASE):
            try:
                await self._one(email, report)
            except Exception as exc:  # noqa: BLE001 — một dòng lỗi (ghi trạng thái) không chặn dòng khác
                log.error("send_emails: không cập nhật được email %d: %s", email.id, type(exc).__name__)
        if report.sent or report.retried or report.failed or report.skipped:
            log.info("send_emails: gửi=%d thử_lại=%d failed=%d skipped=%d", report.sent, report.retried, report.failed,
                     report.skipped)  # fmt: skip
        return report

    async def _one(self, email: ClaimedEmail, report: SendReport) -> None:
        if email.address is None:
            await self._outbox.mark_skipped(email.id, "NoRecipientEmail")
            report.skipped += 1
            return
        try:
            await self._sender.send(email.address, email.subject, email.body)
        except Exception as exc:  # noqa: BLE001 — lỗi gửi là dữ liệu (thử lại / failed), không làm sập job
            attempts = email.attempts + 1
            error = type(exc).__name__
            if attempts >= self._max_attempts:
                await self._outbox.mark_failed(email.id, attempts=attempts, error_class=error)
                report.failed += 1
                log.warning("send_emails: email %d (%s) failed sau %d lần: %s", email.id, email.kind, attempts, error)
            else:
                await self._outbox.mark_retry(
                    email.id, attempts=attempts, error_class=error, next_at=self._clock.now() + backoff(attempts)
                )
                report.retried += 1
                log.warning("send_emails: email %d (%s) lỗi lần %d: %s — thử lại sau", email.id, email.kind, attempts, error)
            return
        await self._outbox.mark_sent(email.id, self._clock.now())
        report.sent += 1
