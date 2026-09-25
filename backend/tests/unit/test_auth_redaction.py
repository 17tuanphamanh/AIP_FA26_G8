"""Lọc bí mật khỏi log (P6 mục 7) và chặn `detail` nhạy cảm trong security_events (P7 2.3)."""

import io
import json
import logging

import jwt
import pytest
from app.audit.security_events import check_event
from app.core.logging import REDACTED, JsonFormatter, RedactSecretsFilter, redact

# Sinh lúc chạy, không để chuỗi JWT trong mã nguồn (gitleaks pre-commit sẽ chặn).
JWT = jwt.encode({"sub": "nv001"}, "k" * 32, algorithm="HS256")


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (f"token {JWT} hết hạn", JWT),
        ("Authorization: Bearer abc.def-ghi", "abc.def-ghi"),
        ("password=Hunter2!", "Hunter2!"),
        ('{"password": "Hunter2!"}', "Hunter2!"),
        ("cookie refresh=rt-123456; csrf=cs-987", "rt-123456"),
        ("cookie refresh=rt-123456; csrf=cs-987", "cs-987"),
        ("otp: 123456", "123456"),
    ],
    ids=["jwt", "bearer", "password_kv", "password_json", "refresh_cookie", "csrf_cookie", "otp"],
)
def test_redact(text: str, secret: str) -> None:
    out = redact(text)
    assert secret not in out and REDACTED in out


def test_redact_keeps_normal_text() -> None:
    assert redact("đăng nhập thất bại cho an.nv") == "đăng nhập thất bại cho an.nv"


def test_filter_and_formatter_redact_args_and_exception() -> None:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactSecretsFilter())
    log = logging.getLogger("test.redact")
    log.addHandler(handler)
    log.propagate = False
    try:
        log.warning("gọi AD password=%s token=%s", "Hunter2!", JWT)
        try:
            raise ValueError(f"lỗi với {JWT}")
        except ValueError:
            log.exception("hỏng")
    finally:
        log.removeHandler(handler)
        log.propagate = True
    out = buf.getvalue()
    assert "Hunter2!" not in out and JWT not in out
    first = json.loads(out.splitlines()[0])
    assert first["msg"].startswith("gọi AD password=")


def test_each_layer_redacts_on_its_own() -> None:
    """Hai lớp độc lập: filter (cho mọi formatter) và JsonFormatter (khi filter không được gắn)."""
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "password=%s %s", ("Hunter2!", JWT), None)
    plain = logging.Formatter("%(message)s")
    assert RedactSecretsFilter().filter(record)
    assert "Hunter2!" not in plain.format(record) and JWT not in plain.format(record)

    raw = logging.LogRecord("t", logging.INFO, __file__, 1, "password=%s %s", ("Hunter2!", JWT), None)
    out = JsonFormatter().format(raw)  # không qua filter
    assert "Hunter2!" not in out and JWT not in out


@pytest.mark.parametrize("key", ["password", "refresh_token", "otp", "mfa_secret", "otpauth_uri", "csrf"])
def test_check_event_rejects_sensitive_detail_keys(key: str) -> None:
    with pytest.raises(ValueError, match="nhạy cảm"):
        check_event("login_failed", {key: "x"})


def test_check_event_rejects_token_values_and_unknown_type() -> None:
    with pytest.raises(ValueError, match="token"):
        check_event("logout", {"note": JWT})
    with pytest.raises(ValueError, match="lạ"):
        check_event("hacked", {})
    check_event("mfa_enrolled", {"by": "ops", "reason": "cấp mới"})
    check_event("permission_denied", {"perm": "ticket:read:any", "reason": "role"})
    check_event("login_failed", {"security_level": "x"})  # "security" không bị bắt nhầm là "uri"
