"""Notify-email — phần không cần DB: soạn thư, bọc notifier (B10/B16/B18/B20 có, B11 không), khoá effect, Settings (E6), gửi SMTP
(STARTTLS bắt buộc, chứng chỉ), job `send_emails` (sent / thử lại / failed / skipped, log không lộ thân/địa chỉ), job worker, đồng
bộ email AD. Phần SQL (cùng transaction, rollback, UNIQUE, skipped, SKIP LOCKED) ở `tests/integration/test_email_outbox_pg.py`."""

import logging
import smtplib
import ssl
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Self

import pytest
from app.auth.store import clean_email
from app.core.clock import FakeClock
from app.core.hashing import sha256_key
from app.db.models import EMAIL_KINDS, EMAIL_STATUSES
from app.db.runtime import bind_effect
from app.guard.privacy import RegexPrivacyGuard
from app.notify import email as mail
from app.notify.notifier import (
    ApproverEmailNotice,
    EmailingNotifier,
    email_outbox_from_settings,
)
from app.notify.outbox import ClaimedEmail
from app.notify.smtp import (
    EMAIL_MAX_ATTEMPTS,
    EmailSendJob,
    SmtpSender,
    StartTlsUnavailable,
    backoff,
)
from app.settings import Settings
from app.tools.models import AdUser
from app.worker import SEND_EMAILS_JOB, setup_email_jobs
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import SecretStr, ValidationError

TICKET = "3f2a9c1e-0b7d-4e55-9a10-6c2d8e4f7a11"
NOW = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)
BODY = "Đã reset phiên VPN của bạn. Vui lòng kết nối lại."
ADDRESS = "nguyen.van.a@congty-abc.vn"
SECRET_PW = "mat-khau-gia-de-thu"  # chuỗi giả, không phải mật khẩu thật

EMAIL_ENV = {
    "email_enabled": True, "smtp_host": "smtp.example.test", "smtp_from": "desk@congty-abc.vn",
    "email_link_base_url": "https://desk.congty-abc.vn/", "smtp_username": "desk@congty-abc.vn",
    "smtp_password": SecretStr(SECRET_PW),
}  # fmt: skip


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="test", **over)  # type: ignore[call-arg]


# ---- soạn thư (E4) ---------------------------------------------------------------------------------------------------


def test_kinds_match_db_check() -> None:
    assert set(mail.USER_KIND_BY_STEP.values()) | set(mail.APPROVER_KIND.values()) == set(EMAIL_KINDS)
    assert set(mail.TITLES) == set(EMAIL_KINDS)
    assert EMAIL_STATUSES == ("pending", "sent", "failed", "skipped")


def test_user_kind_by_step_excludes_b11() -> None:
    assert {s: mail.user_kind(s) for s in ("B10", "B16", "B18", "B20")} == {
        "B10": "answer", "B16": "rejection", "B18": "result", "B20": "escalation",
    }  # fmt: skip
    assert mail.user_kind("B11") is None
    assert mail.user_kind("B5") is None


def test_subject_format() -> None:
    assert mail.subject("result", TICKET) == "[IT Service Desk] Kết quả xử lý yêu cầu của bạn — 3F2A9C1E"
    assert mail.subject("approval_new", TICKET).startswith("[IT Service Desk] Có yêu cầu mới cần bạn phê duyệt — ")


def test_body_is_chat_text_plus_role_link() -> None:
    base = "https://desk.congty-abc.vn"
    assert mail.with_link(BODY, mail.user_link(base, TICKET)) == f"{BODY}\n\nXem chi tiết: {base}/chat/{TICKET}"
    assert mail.approver_link(base, "42") == f"{base}/approvals/42"


def test_approver_text_has_no_user_text_and_vn_deadline() -> None:
    out = mail.approver_text("approval_reminder_2", TICKET, datetime(2026, 10, 24, 3, 30, tzinfo=UTC))
    assert out == "Nhắc lần 2: một yêu cầu sắp hết hạn phê duyệt (ticket 3F2A9C1E). Hạn phê duyệt: 10:30 24/10/2026 (giờ Việt Nam)."


@pytest.mark.parametrize("base", ["http://localhost:5173", "https://desk.congty-abc.vn"])
def test_privacy_guard_keeps_normal_body(base: str) -> None:
    """Thân bình thường (tin chat + link có UUID) qua guard KHÔNG bị đổi, không bị coi là bí mật — không thì mọi thư thành skipped."""
    guard = RegexPrivacyGuard.from_settings(_settings())
    for body in (mail.with_link(BODY, mail.user_link(base, TICKET)),
                 mail.with_link(mail.approver_text("approval_new", TICKET, NOW), mail.approver_link(base, "1234"))):  # fmt: skip
        out = guard.redact_text(body)
        assert (out.secrets_found, out.text) == (0, body)


def test_mask_address() -> None:
    assert mail.mask_address(ADDRESS) == "n***@congty-abc.vn"
    assert mail.mask_address(None) is None
    assert mail.mask_address("khong-co-a-cong") == "***"


# ---- bọc notifier (E3) ----------------------------------------------------------------------------------------------


@dataclass
class FakeOutbox:
    users: list[dict[str, Any]] = field(default_factory=list)
    approvers: list[dict[str, Any]] = field(default_factory=list)

    async def enqueue_user(self, **kw: Any) -> int:
        self.users.append(kw)
        return len(self.users)

    async def enqueue_approver(self, **kw: Any) -> int:
        self.approvers.append(kw)
        return len(self.approvers)


class Inner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
        self.calls.append((ticket_id, text, needs))
        return f"noop:{ticket_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("step", "kind"), [("B10", "answer"), ("B16", "rejection"), ("B18", "result"), ("B20", "escalation")])
async def test_notifier_writes_one_outbox_row_with_effect_key(step: str, kind: str) -> None:
    inner, outbox = Inner(), FakeOutbox()
    notifier = EmailingNotifier(inner, outbox)
    with bind_effect(step, "k" * 64):
        ref = await notifier.notify_user(TICKET, BODY, "confirm")
    assert ref == f"noop:{TICKET}"  # result_ref của tin chat không đổi
    assert inner.calls == [(TICKET, BODY, "confirm")]  # tin chat y nguyên
    assert outbox.users == [{"ticket_id": TICKET, "kind": kind, "text": BODY, "effect_key": "k" * 64}]


@pytest.mark.asyncio
async def test_notifier_never_emails_b11_question() -> None:
    inner, outbox = Inner(), FakeOutbox()
    with bind_effect("B11", "q" * 64):
        await EmailingNotifier(inner, outbox).notify_user(TICKET, "Bạn dùng VPN trên máy nào?", "answer")
    assert inner.calls and outbox.users == []


@pytest.mark.asyncio
async def test_notifier_outside_effect_no_email() -> None:
    inner, outbox = Inner(), FakeOutbox()
    await EmailingNotifier(inner, outbox).notify_user(TICKET, BODY)
    assert inner.calls and outbox.users == []


@pytest.mark.asyncio
async def test_approver_notice_key_inside_and_outside_effect() -> None:
    logged: list[tuple[str, str, str]] = []

    async def log_notice(approval_id: str, approver_id: str, kind: str = "new") -> str:
        logged.append((approval_id, approver_id, kind))
        return f"log:{approval_id}"

    outbox = FakeOutbox()
    notice = ApproverEmailNotice(outbox, log_notice)  # type: ignore[arg-type]
    with bind_effect("B15", "e" * 64):
        assert await notice("7", "l1_01", "new") == "log:7"
    await notice("7", "l1_02", "reminder_2")
    await notice("7", "l1_02", "reminder_2")  # worker chạy lại: cùng khoá → UNIQUE chặn ở DB
    assert logged == [("7", "l1_01", "new"), ("7", "l1_02", "reminder_2"), ("7", "l1_02", "reminder_2")]
    keys = [a["effect_key"] for a in outbox.approvers]
    assert keys[0] == "e" * 64
    assert keys[1] == keys[2] == sha256_key("email", "7", "l1_02", "reminder_2")
    assert [a["kind"] for a in outbox.approvers] == ["new", "reminder_2", "reminder_2"]


# ---- Settings (E6) --------------------------------------------------------------------------------------------------


def test_email_off_by_default() -> None:
    s = _settings()
    assert s.email_enabled is False and s.email_active is False
    assert (s.smtp_port, s.smtp_starttls, s.email_send_interval_seconds) == (587, True, 15.0)


def test_email_enabled_complete_config() -> None:
    s = _settings(**EMAIL_ENV)
    assert s.email_active is True
    assert s.email_link_base_url == "https://desk.congty-abc.vn"  # bỏ "/" cuối
    assert SECRET_PW not in repr(s) and SECRET_PW not in str(s)


def test_email_enabled_missing_vars_refuses_with_names() -> None:
    with pytest.raises(ValidationError) as err:
        _settings(email_enabled=True)
    msg = str(err.value)
    assert "SMTP_HOST" in msg and "SMTP_FROM" in msg and "EMAIL_LINK_BASE_URL" in msg and "từ chối khởi động" in msg


@pytest.mark.parametrize("drop", ["smtp_host", "smtp_from", "email_link_base_url"])
def test_each_required_var_refuses(drop: str) -> None:
    with pytest.raises(ValidationError, match=drop.upper()):
        _settings(**{k: v for k, v in EMAIL_ENV.items() if k != drop})


def test_username_password_go_together() -> None:
    with pytest.raises(ValidationError, match="SMTP_PASSWORD"):
        _settings(**{k: v for k, v in EMAIL_ENV.items() if k != "smtp_password"})
    with pytest.raises(ValidationError, match="SMTP_USERNAME"):
        _settings(**{k: v for k, v in EMAIL_ENV.items() if k != "smtp_username"})


def test_credentials_without_starttls_refused() -> None:
    with pytest.raises(ValidationError, match="SMTP_STARTTLS=false"):
        _settings(**EMAIL_ENV, smtp_starttls=False)


def test_bad_from_and_link_refused() -> None:
    with pytest.raises(ValidationError, match="SMTP_FROM"):
        _settings(**{**EMAIL_ENV, "smtp_from": "khong-phai-email"})
    with pytest.raises(ValidationError, match="EMAIL_LINK_BASE_URL"):
        _settings(**{**EMAIL_ENV, "email_link_base_url": "javascript:alert(1)"})


def test_eval_mode_always_off_even_without_vars() -> None:
    s = _settings(email_enabled=True, eval_mode=True)  # thiếu biến vẫn khởi động được: EVAL_MODE tắt email
    assert s.email_active is False
    assert email_outbox_from_settings(s, None, None, None) is None  # type: ignore[arg-type]
    full = _settings(**EMAIL_ENV, eval_mode=True)
    assert full.email_active is False
    assert email_outbox_from_settings(full, None, None, None) is None  # type: ignore[arg-type]


def test_outbox_built_only_when_active() -> None:
    assert email_outbox_from_settings(_settings(), None, None, None) is None  # type: ignore[arg-type]
    assert email_outbox_from_settings(_settings(**EMAIL_ENV), None, None, None) is not None  # type: ignore[arg-type]


def test_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "EMAIL_ENABLED": "true", "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_STARTTLS": "true",
        "SMTP_USERNAME": "a@gmail.com", "SMTP_PASSWORD": SECRET_PW, "SMTP_FROM": "a@gmail.com",
        "EMAIL_LINK_BASE_URL": "http://localhost:5173", "EMAIL_SEND_INTERVAL_SECONDS": "30",
    }.items():  # fmt: skip
        monkeypatch.setenv(name, value)
    s = _settings()
    assert s.email_active and s.smtp_host == "smtp.gmail.com" and s.email_send_interval_seconds == 30.0
    assert s.smtp_password is not None and s.smtp_password.get_secret_value() == SECRET_PW


# ---- SMTP (E5) ------------------------------------------------------------------------------------------------------


class FakeSmtp:
    """Thay `smtplib.SMTP`: ghi lại thứ tự lệnh; `starttls_ok=False` = máy chủ không quảng bá STARTTLS."""

    instances: ClassVar[list["FakeSmtp"]] = []

    def __init__(self, host: str, port: int, timeout: float, *, starttls_ok: bool = True, fail: Exception | None = None):
        self.host, self.port, self.timeout = host, port, timeout
        self.ops: list[Any] = []
        self.starttls_ok = starttls_ok
        self.fail = fail
        self.thread = threading.current_thread()
        FakeSmtp.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *a: object) -> None:
        self.ops.append("quit")

    def ehlo(self) -> None:
        self.ops.append("ehlo")

    def has_extn(self, name: str) -> bool:
        return name == "starttls" and self.starttls_ok

    def starttls(self, context: ssl.SSLContext) -> None:
        self.ops.append(("starttls", context))

    def login(self, user: str, password: str) -> None:
        self.ops.append(("login", user, password))

    def send_message(self, msg: Any) -> None:
        if self.fail is not None:
            raise self.fail
        self.ops.append(("send", msg))


def _sender(**over: Any) -> SmtpSender:
    opts: dict[str, Any] = {"starttls_ok": over.pop("starttls_ok", True), "fail": over.pop("fail", None)}
    kw: dict[str, Any] = {
        "host": "smtp.example.test", "port": 587, "starttls": True, "username": "desk@congty-abc.vn",
        "password": SecretStr(SECRET_PW), "sender": "desk@congty-abc.vn",
        "smtp_factory": lambda host, port, timeout: FakeSmtp(host, port, timeout, **opts), **over,
    }  # fmt: skip
    return SmtpSender(**kw)


@pytest.fixture(autouse=True)
def _reset_smtp() -> None:
    FakeSmtp.instances.clear()


@pytest.mark.asyncio
async def test_smtp_starttls_before_login_then_send_in_thread() -> None:
    await _sender().send(ADDRESS, "[IT Service Desk] x — 3F2A9C1E", BODY)
    (smtp,) = FakeSmtp.instances
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.test", 587, 15.0)
    names = [op if isinstance(op, str) else op[0] for op in smtp.ops]
    assert names == ["ehlo", "starttls", "ehlo", "login", "send", "quit"]
    ctx = smtp.ops[1][1]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True  # kiểm chứng chỉ + tên máy
    assert smtp.ops[3] == ("login", "desk@congty-abc.vn", SECRET_PW)
    msg = smtp.ops[4][1]
    assert (msg["To"], msg["From"], msg["Subject"]) == (ADDRESS, "desk@congty-abc.vn", "[IT Service Desk] x — 3F2A9C1E")
    assert msg.get_content().strip() == BODY
    assert smtp.thread is not threading.main_thread()  # smtplib chạy trong to_thread


@pytest.mark.asyncio
async def test_smtp_refuses_without_starttls_support() -> None:
    with pytest.raises(StartTlsUnavailable):
        await _sender(starttls_ok=False).send(ADDRESS, "s", BODY)
    (smtp,) = FakeSmtp.instances
    assert not [op for op in smtp.ops if isinstance(op, tuple) and op[0] in ("login", "send")]


@pytest.mark.asyncio
async def test_smtp_plain_relay_without_credentials() -> None:
    await _sender(starttls=False, username=None, password=None).send(ADDRESS, "s", BODY)
    (smtp,) = FakeSmtp.instances
    assert [op if isinstance(op, str) else op[0] for op in smtp.ops] == ["ehlo", "send", "quit"]


def test_smtp_credentials_require_starttls() -> None:
    with pytest.raises(ValueError, match="STARTTLS"):
        _sender(starttls=False)


def test_smtp_from_settings() -> None:
    s = SmtpSender.from_settings(_settings(**EMAIL_ENV))
    assert s._host == "smtp.example.test" and s._starttls is True and s._smtp is smtplib.SMTP


# ---- job send_emails (E5) --------------------------------------------------------------------------------------------


class JobOutbox:
    def __init__(self, rows: list[ClaimedEmail]) -> None:
        self.rows = rows
        self.done: list[tuple[Any, ...]] = []
        self.claims: list[tuple[datetime, int, timedelta]] = []

    async def claim(self, now: datetime, limit: int, lease: timedelta) -> list[ClaimedEmail]:
        self.claims.append((now, limit, lease))
        return self.rows

    async def mark_sent(self, email_id: int, at: datetime) -> None:
        self.done.append(("sent", email_id, at))

    async def mark_skipped(self, email_id: int, reason: str) -> None:
        self.done.append(("skipped", email_id, reason))

    async def mark_retry(self, email_id: int, *, attempts: int, error_class: str, next_at: datetime) -> None:
        self.done.append(("retry", email_id, attempts, error_class, next_at))

    async def mark_failed(self, email_id: int, *, attempts: int, error_class: str) -> None:
        self.done.append(("failed", email_id, attempts, error_class))


class RecSender:
    def __init__(self, fail: Exception | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append((to, subject, body))


def _row(i: int, *, attempts: int = 0, address: str | None = ADDRESS) -> ClaimedEmail:
    return ClaimedEmail(i, "result", f"subj {i}", f"{BODY} #{i}", attempts, address)


def _job(rows: list[ClaimedEmail], sender: RecSender) -> tuple[EmailSendJob, JobOutbox]:
    outbox = JobOutbox(rows)
    return EmailSendJob(outbox, sender, FakeClock(NOW)), outbox  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_job_sends_and_marks_sent() -> None:
    sender = RecSender()
    job, outbox = _job([_row(1), _row(2)], sender)
    report = await job.run()
    assert outbox.claims == [(NOW, 20, timedelta(minutes=10))]  # tối đa 20 dòng mỗi lượt
    assert sender.sent == [(ADDRESS, "subj 1", f"{BODY} #1"), (ADDRESS, "subj 2", f"{BODY} #2")]
    assert outbox.done == [("sent", 1, NOW), ("sent", 2, NOW)]
    assert report.sent == 2


@pytest.mark.asyncio
async def test_job_skips_when_address_gone() -> None:
    sender = RecSender()
    job, outbox = _job([_row(3, address=None)], sender)
    await job.run()
    assert sender.sent == [] and outbox.done == [("skipped", 3, "NoRecipientEmail")]


@pytest.mark.asyncio
@pytest.mark.parametrize("attempts", [0, 1, 2, 3])
async def test_job_retry_with_backoff(attempts: int) -> None:
    job, outbox = _job([_row(4, attempts=attempts)], RecSender(fail=smtplib.SMTPServerDisconnected("down")))
    await job.run()
    n = attempts + 1
    assert outbox.done == [("retry", 4, n, "SMTPServerDisconnected", NOW + backoff(n))]


@pytest.mark.asyncio
async def test_job_failed_after_max_attempts() -> None:
    job, outbox = _job([_row(5, attempts=EMAIL_MAX_ATTEMPTS - 1)], RecSender(fail=TimeoutError()))
    report = await job.run()
    assert outbox.done == [("failed", 5, EMAIL_MAX_ATTEMPTS, "TimeoutError")]
    assert report.failed == 1


def test_backoff_grows_and_caps() -> None:
    assert [backoff(n).total_seconds() for n in (1, 2, 3, 4, 5)] == [60, 120, 240, 480, 960]
    assert backoff(20) == timedelta(hours=1)


@pytest.mark.asyncio
async def test_job_logs_no_body_address_or_message(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    leak = f"550 mailbox {ADDRESS} unknown"
    job, _ = _job([_row(6), _row(7, attempts=4)], RecSender(fail=smtplib.SMTPRecipientsRefused({ADDRESS: (550, leak.encode())})))
    await job.run()
    text = caplog.text
    assert "SMTPRecipientsRefused" in text
    assert ADDRESS not in text and BODY not in text and "subj" not in text and "550" not in text


# ---- worker (E5) ----------------------------------------------------------------------------------------------------


def test_setup_email_jobs_registers_interval_job() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    s = _settings(**EMAIL_ENV, email_send_interval_seconds=15)
    setup_email_jobs(scheduler, s, object(), FakeClock(NOW))  # type: ignore[arg-type]
    (job,) = scheduler.get_jobs()
    assert job.id == SEND_EMAILS_JOB == "send_emails"
    assert job.trigger.interval == timedelta(seconds=15)
    assert job.max_instances == 1 and job.coalesce is True


# ---- đồng bộ email từ AD (E2) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (ADDRESS, ADDRESS), (f"  {ADDRESS} ", ADDRESS), (None, None), ("", None), ("không hợp lệ", None),
        ("a@b", None), (f"a\n{ADDRESS}", None), ("a" * 250 + "@b.vn", None), (123, None),
    ],
)  # fmt: skip
def test_clean_email(raw: object, want: str | None) -> None:
    assert clean_email(raw) == want


def test_ad_user_email_optional() -> None:
    base: dict[str, Any] = {
        "user_id": "u1", "username": "an.nv", "full_name": "An", "title": "NV", "department": "it", "groups": [],
        "manager_id": None, "employment_status": "active", "hired_at": "2024-01-01", "is_privileged_account": False,
        "account": {"account_type": "ad", "enabled": True, "locked": False, "lock_reason": None,
                    "password_last_set": "2026-01-01T00:00:00Z"},
    }  # fmt: skip
    assert AdUser.model_validate(base).email is None  # mock/AD cũ thiếu trường → None, không lỗi
    assert AdUser.model_validate({**base, "email": ADDRESS}).email == ADDRESS
