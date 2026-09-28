"""Hợp đồng provider — một request tới MỘT model, không retry, không validate (gateway làm việc đó).

Lỗi hạ tầng → `ProviderError` (gateway quyết định retry theo `limits.retry_on`). Lỗi khác (bug, `ScriptExhausted`)
xuyên qua gateway → E9. Thông điệp `ProviderError` do ta dựng (loại, mã HTTP) — không chép thân phản hồi của provider.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, Protocol

from app.llm.ports import TraceParent


@dataclass(frozen=True)
class ProviderRequest:
    prompt_id: str
    model: str
    messages: list[dict[str, str]]
    json_schema: dict[str, Any]
    schema_name: str
    max_tokens: int
    temperature: float
    timeout_s: float
    attempt: int  # lần thử thứ mấy trên đích này (0 = đầu tiên)
    variables: Mapping[str, Any]  # chỉ ScriptedLLM đọc (kịch bản dạng hàm, 7.5)
    trace: TraceParent | None  # chỉ preset stack đọc (turn_id → ticket, Q-3d-12)


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    tokens_in: int | None  # usage của provider; None → gateway ước lượng
    tokens_out: int | None
    model_version: str | None  # model thật provider báo → llm_calls.model_version


type ErrorKind = Literal["http", "timeout", "connect", "api"]


class ProviderError(Exception):
    """`host` chỉ là tên máy (không scheme, cổng, đường dẫn, query, userinfo) — nhãn lỗi đi vào span/`llm_calls`/log
    nên không được mang theo phần nào của `LLM_BASE_URL` có thể chứa khoá (Tuấn Anh chốt DỪNG 1)."""

    def __init__(
        self, kind: ErrorKind, *, status: int | None = None, retry_after: float | None = None, host: str | None = None
    ) -> None:
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.host = host
        super().__init__(self.label)

    @property
    def label(self) -> str:
        base = f"http:{self.status}" if self.kind == "http" else self.kind
        return f"{base}@{self.host}" if self.host else base


class Provider(Protocol):
    name: str

    async def chat(self, req: ProviderRequest) -> ProviderResponse: ...


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Header `Retry-After`: số giây hoặc HTTP-date (RFC 9110). Sai/âm → None (dùng backoff)."""
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = (at - (now or datetime.now(UTC))).total_seconds()
    return seconds if seconds >= 0 else None
