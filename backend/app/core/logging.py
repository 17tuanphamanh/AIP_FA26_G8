"""Log JSON một dòng, tự gắn ticket_id / turn_id / trace_id của lượt đang chạy.

Lọc bí mật trước khi ghi (P6 mục 7): chuỗi dạng JWT, `password=…`/`"password": "…"`, cookie
`refresh=`/`csrf=`, header `Authorization: Bearer …` → `[REDACTED]`. Đây là lưới an toàn cuối;
code vẫn không được log những thứ này.
"""

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_CONTEXT_KEYS = ("ticket_id", "turn_id", "trace_id")
_context: ContextVar[dict[str, str]] = ContextVar("log_context")


@contextmanager
def bind_log_context(**fields: str) -> Iterator[None]:
    """Gắn ngữ cảnh cho mọi log trong khối; lồng nhau thì khối trong ghi đè khối ngoài."""
    unknown = set(fields) - set(_CONTEXT_KEYS)
    if unknown:
        raise ValueError(f"Khóa ngữ cảnh log không hỗ trợ: {sorted(unknown)}")
    token = _context.set({**_context.get({}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


REDACTED = "[REDACTED]"
_SECRET_PATTERNS = (
    re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]*"),  # JWT
    re.compile(r"(?i)(bearer\s+)\S+"),
    re.compile(r"(?i)((?:password|passwd|pwd|otp|secret|refresh|csrf)[\"']?\s*[=:]\s*[\"']?)[^\"'\s,;&}]+"),
)


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + REDACTED, text)
    return text


class RedactSecretsFilter(logging.Filter):
    """Che bí mật trong message đã format (gồm cả args) — gắn vào handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = _context.get({})
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            **{key: ctx.get(key) for key in _CONTEXT_KEYS},
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


# Thư viện ghi INFO quá dày: APScheduler ghi 2 dòng mỗi lần chạy job (~10 dòng/phút ở worker).
# Lỗi của job vẫn hiện: job tự log.exception ở logger `app.*`, APScheduler báo lỗi ở mức ERROR.
QUIET_LOGGERS: dict[str, int] = {"apscheduler": logging.WARNING}


def configure_logging(level: int | str = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactSecretsFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name, quiet_level in QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(quiet_level)
