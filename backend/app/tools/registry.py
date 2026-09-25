"""ToolRegistry — cổng duy nhất ra hệ thống ngoài (P5 mục 2, [Chốt 17.3]).

`call()` đi 8 bước: tra ToolSpec → kiểm `caller_step` → tool ghi chỉ từ B17 → validate input →
breaker → gọi (đọc: `call_with_retry`; ghi: 1 lần, không retry) → validate output → log span.

Kiểu trả [Chốt P5 mục 6.1]: lỗi hệ thống ngoài KHÔNG raise — luôn trả `ToolResult` (breaker mở →
`error="circuit_open"`), node đi E2. Chỉ lỗi **hợp đồng** mới raise (`ToolContractError`): tool lạ,
`caller_step` không được phép (`ForbiddenToolCall`), input/output sai schema, 4xx ngoài 404/429 —
đó là lỗi lập trình, rơi xuống E9 là đúng.

Tool ghi gặp 404/409 [Chốt P5 mục 6.1, bản 1.4]: thất bại thực thi → `error` (B17 đi E7), không
raise, không tính vào breaker. Breaker đếm theo lời gọi registry (sau retry), không theo HTTP attempt.
"""

import logging
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, RootModel, ValidationError

from app.core.clock import Clock
from app.tools.breaker import BreakerBoard, CircuitBreaker
from app.tools.retry import call_with_retry
from app.tools.specs import REGISTRY, ToolSpec, ToolSpecError

log = logging.getLogger(__name__)

# Handler nhận input đã validate và timeout của tool, trả JSON thô của hệ thống ngoài; lỗi mạng/HTTP
# thì để httpx raise — registry phân loại.
Handler = Callable[[Any, float], Awaitable[Any]]

CIRCUIT_OPEN = "circuit_open"
WRITE_FAILURE_CODES = frozenset({404, 409})


class ToolContractError(Exception):
    """Lỗi hợp đồng khi gọi tool — lỗi lập trình, không retry, không đổi thành E2."""


class ForbiddenToolCall(ToolContractError):
    """Bước hiện tại không được gọi tool này (ví dụ tool ghi gọi từ B6)."""


@dataclass(frozen=True)
class ToolResult:
    tool: str
    data: Any | None  # model đã validate; None khi lỗi hoặc 404
    error: str | None  # "circuit_open" | "TimeoutException: …" | None
    attempts: int  # → tool_retry_count (điểm log 2, 3)
    empty: bool  # 404 / rỗng = dữ liệu hợp lệ, KHÔNG phải lỗi (E2 ≠ E3)

    def __iter__(self) -> Iterator[Any]:  # cho B01/B17: data, err, _ = await registry.call(...)
        return iter((self.data, self.error, self.attempts))


class ToolRegistry:
    def __init__(
        self,
        handlers: Mapping[str, Handler],
        *,
        breakers: BreakerBoard,
        clock: Clock,
        specs: Mapping[str, ToolSpec] = REGISTRY,
    ) -> None:
        unknown = sorted(set(handlers) - set(specs))
        if unknown:
            raise ToolSpecError(f"handler cho tool chưa khai báo: {unknown}")
        self._handlers = dict(handlers)
        self._breakers = breakers
        self._clock = clock
        self._specs = specs

    async def call(self, name: str, args: Mapping[str, Any] | BaseModel, *, caller_step: str) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolContractError(f"tool chưa khai báo: {name}")
        if caller_step not in spec.allowed_steps:
            raise ForbiddenToolCall(f"{name} không được gọi từ {caller_step}")
        if spec.kind == "write" and caller_step != "B17":  # thừa với validate_specs — cố ý giữ
            raise ForbiddenToolCall(f"tool ghi {name} chỉ được gọi từ B17")
        try:
            raw = args.model_dump() if isinstance(args, BaseModel) else args
            inp = spec.input_model.model_validate(raw)
        except ValidationError as e:
            raise ToolContractError(f"{name}: input sai schema: {e}") from e
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolContractError(f"{name}: chưa gắn handler vào registry này")

        breaker = self._breakers[spec.target_system]
        if not breaker.allow():
            result = ToolResult(name, None, CIRCUIT_OPEN, 0, False)
            self._span(spec, caller_step, result, 0.0)
            return result

        started = time.perf_counter()
        try:
            outcome = await self._invoke(spec, handler, inp, breaker)
        except ToolContractError:
            raise
        except BaseException:
            breaker.record_failure()  # lỗi chưa lường trước: không để half-open kẹt lượt thử
            raise
        result = self._finish(spec, breaker, outcome)
        self._span(spec, caller_step, result, time.perf_counter() - started)
        return result

    # Tool nội bộ (ad_get_user…) đi cùng một cổng — tên riêng chỉ để đọc code B1/B11/B17 rõ ý.
    call_internal = call

    async def _invoke(
        self, spec: ToolSpec, handler: Handler, inp: BaseModel, breaker: CircuitBreaker
    ) -> "_Outcome":
        if spec.kind == "read":
            try:
                data, error, attempts = await call_with_retry(
                    handler, inp, spec.timeout_s, retries=spec.retries, clock=self._clock
                )
            except httpx.HTTPStatusError as e:
                breaker.record_success()  # hệ thống ngoài vẫn trả lời — lỗi là ở phía ta
                raise ToolContractError(f"{spec.name}: HTTP {e.response.status_code}") from e
            return _Outcome(data, error, attempts, "success" if error is None else "failure")
        try:  # ghi: 1 lần, KHÔNG retry [Chốt 17.3]
            return _Outcome(await handler(inp, spec.timeout_s), None, 0, "success")
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            return _Outcome(None, f"{type(e).__name__}: {e}", 0, "failure")
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            error = f"HTTPStatusError: {code} {_detail(e.response)}".rstrip()
            if code in WRITE_FAILURE_CODES:  # trạng thái nghiệp vụ của hệ thống đích → không tính
                return _Outcome(None, error, 0, "neutral")
            if code == 429 or code >= 500:
                return _Outcome(None, error, 0, "failure")
            breaker.record_success()
            raise ToolContractError(f"{spec.name}: HTTP {code}") from e

    def _finish(self, spec: ToolSpec, breaker: CircuitBreaker, out: "_Outcome") -> ToolResult:
        if out.breaker == "success":
            breaker.record_success()
        elif out.breaker == "failure":
            breaker.record_failure()
        else:
            breaker.record_neutral()
        if out.error is not None:
            return ToolResult(spec.name, None, out.error, out.attempts, False)
        if out.data is None:  # 404 ở tool đọc
            return ToolResult(spec.name, None, None, out.attempts, True)
        try:
            model = spec.output_model.model_validate(out.data)
        except ValidationError as e:
            raise ToolContractError(f"{spec.name}: output sai schema: {e}") from e
        empty = isinstance(model, RootModel) and not model.root
        return ToolResult(spec.name, model, None, out.attempts, empty)

    @staticmethod
    def _span(spec: ToolSpec, step: str, result: ToolResult, seconds: float) -> None:
        # Span "tool:<name>" thật (bảng spans) làm ở Phase 2 (P1 mục 9); tạm ghi log một dòng.
        log.info(
            "tool:%s step=%s attempts=%d empty=%s error=%s ms=%.0f",
            spec.name, step, result.attempts, result.empty, result.error, seconds * 1000,
        )  # fmt: skip


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("detail", "")) if isinstance(body, dict) else ""


@dataclass(frozen=True)
class _Outcome:
    data: Any
    error: str | None
    attempts: int
    breaker: Literal["success", "failure", "neutral"]  # ghi gì vào breaker
