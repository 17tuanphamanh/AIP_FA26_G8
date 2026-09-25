"""Log JSON một dòng, tự gắn ticket_id / turn_id / trace_id của lượt đang chạy."""

import json
import logging
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


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = _context.get({})
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **{key: ctx.get(key) for key in _CONTEXT_KEYS},
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int | str = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
