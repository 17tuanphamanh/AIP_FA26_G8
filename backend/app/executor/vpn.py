"""`VpnExecutor` — điểm ghi duy nhất cho hành động VPN (B17, phase3 11.4 bước 4–5; B17-B18 §2, §5). Chỉ dựng ở API process
(`main.py`, P7); worker giữ `RefusingExecutor`.

Trình tự (node B17 đã kiểm lại luật/hash/người — bước 1–3):
1. Ticket đã có `begun` (mọi lượt — B17 đã hỏi ở bước 0, đây là lớp thứ hai; đứng trước cả kế hoạch rỗng — soát lại DỪNG 2
   NGHI-a) → `ExecutionInterrupted` (E7 `exec_interrupted`, 0 lời gọi ghi).
2. `PLAN[action.type]` rỗng (`check_vpn_status`, 3-Q31) → thành công, không `begun`, 0 lời gọi ghi.
3. **P4:** phải còn đủ TRỌN timeout cho MỌI bước ghi của kế hoạch — TRƯỚC khi INSERT `begun`; không đủ → `TurnBudgetExceeded`
   (E2 `turn_budget_exceeded`, 0 dòng `begun`, 0 lời gọi ghi). Registry còn kiểm lại từng lời gọi (`full=True`).
4. Mỗi bước: INSERT `begun` (commit riêng) → gọi tool ghi ĐÚNG 1 lần (retries=0 — registry, không vòng lặp nào ở đây).
5. Lỗi ở bước k (gồm 404/409 — dữ liệu của hệ thống đích, P5 6.1) → hoàn tác các bước đã xong theo thứ tự ngược nếu
   `action.reversible` (`undone`/`undo_failed`), không thì `not_attempted` → `ExecutionResult(success=False)` + `handoff_note`
   4 phần. Chứng chỉ cũ bị mock thu hồi khi cấp mới KHÔNG được khôi phục — ghi rõ khi phải hoàn tác.

**P6 (luật 8.9):** `handoff_note`, `rollback_details`, `transaction_log.detail` và `outputs` chỉ ghép từ tên tool, mã lỗi thuộc
tập ĐÓNG (`error_kind`), định danh (`user_id`, `device_id` đã qua `sanitize_slots`, `serial` qua regex) và ngày — chuỗi lỗi
httpx/nội dung phản hồi của hệ thống ngoài KHÔNG bao giờ được chép vào.
"""

from collections.abc import Mapping
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from app.core.clock import Clock
from app.core.turn_budget import TurnBudgetExceeded, cap_timeout
from app.domain.action import Action
from app.domain.messages import DEVICE_ID
from app.domain.ticket_state import ExecutionResult
from app.executor.errors import ExecutionInterrupted
from app.executor.plans import PLAN, Step, step_args, undo_args
from app.executor.txlog import TxLog
from app.tools.registry import ToolResult
from app.tools.specs import REGISTRY, ToolSpec

WRITE_STEP = "B17"
# Tên lớp lỗi httpx mà registry ghi vào `ToolResult.error` (`f"{type(e).__name__}: …"`) khi hết thời gian
TIMEOUT_ERRORS = frozenset({"TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"})

type RollbackStatus = Literal["undone", "partial", "undo_failed", "not_attempted", "none_needed"]


class WriteCaller(Protocol):
    async def call(self, name: str, args: Mapping[str, Any], *, caller_step: str) -> ToolResult: ...


def error_kind(error: str) -> str:
    """Chuỗi lỗi của registry → mã thuộc tập ĐÓNG (P6): không bao giờ trả lại chữ của hệ thống ngoài."""
    if error in ("circuit_open", "turn_budget_exceeded"):
        return error
    name = error.split(":", 1)[0]
    if name in TIMEOUT_ERRORS:
        return "timeout"
    if name == "ConnectError":
        return "connect_error"
    if error.startswith("HTTPStatusError: "):
        code = error.removeprefix("HTTPStatusError: ").split(" ", 1)[0]
        if code in ("404", "409", "429"):
            return f"http_{code}"
        if code.isdigit() and code.startswith("5"):
            return "http_5xx"
    return "other"


class VpnExecutor:
    def __init__(
        self,
        registry: WriteCaller,
        txlog: TxLog,
        clock: Clock,
        *,
        tz: str,
        plans: Mapping[str, tuple[Step, ...]] | None = None,
        specs: Mapping[str, ToolSpec] = REGISTRY,
    ) -> None:
        self._registry = registry
        self._txlog = txlog
        self._clock = clock
        self._tz = ZoneInfo(tz)  # ngày hết hạn hiển thị theo giờ địa phương (một nguồn: policy.business_hours.tz)
        self._plans = PLAN if plans is None else plans
        self._specs = specs

    async def execute(self, ticket_id: str, turn_id: str, action: Action) -> ExecutionResult:
        steps = self._plans[action.type]  # thiếu = cấu hình lệch mà check_plans bỏ sót → KeyError → E9
        if await self._txlog.has_begun(ticket_id):
            raise ExecutionInterrupted(f"ticket {ticket_id}: transaction_log đã có begun")
        if not steps:
            return _result(True, [], None, "none_needed", [], None, {})
        need = sum(self._specs[s.tool].timeout_s for s in steps)
        cap_timeout(need, self._clock, what="executor:plan", full=True)  # P4 — TRƯỚC begun
        done: list[tuple[Step, Any]] = []
        for step in steps:
            await self._txlog.begin(ticket_id, turn_id, step.tool)
            try:
                result = await self._registry.call(step.tool, step_args(step.tool, action), caller_step=WRITE_STEP)
            except TurnBudgetExceeded:
                if not done:
                    raise  # bước đầu: chưa ghi gì → E2 (P4)
                # soát S12 NGHI-6a (kế hoạch nhiều bước): đã ghi bước trước → KHÔNG thoát kiểu E2 mà hoàn tác + E7 có handoff
                result = ToolResult(step.tool, None, "turn_budget_exceeded", 0, False)
            if result.error is not None:
                kind = error_kind(result.error)
                status, details = await self._rollback(ticket_id, turn_id, action, done)
                note = _handoff(action, [s.tool for s, _ in done], step.tool, kind, status, details)
                return _result(False, [s.tool for s, _ in done], step.tool, status, details, note, {})
            done.append((step, result.data))
        return _result(True, [s.tool for s, _ in done], None, "none_needed", [], None, self._outputs(done[-1][1]))

    async def _rollback(
        self, ticket_id: str, turn_id: str, action: Action, done: list[tuple[Step, Any]]
    ) -> tuple[RollbackStatus, list[tuple[str, str]]]:
        if not done:
            return "none_needed", []
        if not action.reversible:
            return "not_attempted", []  # [Chốt sửa vòng 2]: không gọi undo cho hành động không hoàn tác được
        details: list[tuple[str, str]] = []
        for step, data in reversed(done):
            if step.undo is None:
                details.append((step.tool, "UNDO_FAILED: no_undo"))
                continue
            try:
                r = await self._registry.call(step.undo, undo_args(step.undo, action, data), caller_step=WRITE_STEP)
                failure = None if r.error is None else error_kind(r.error)
            except TurnBudgetExceeded:
                failure = "turn_budget_exceeded"
            if failure is None:
                await self._txlog.undone(ticket_id, turn_id, step.tool)
                details.append((step.tool, "undone"))
            else:
                await self._txlog.undo_failed(ticket_id, turn_id, step.tool, f"UNDO_FAILED: {failure}")
                details.append((step.tool, f"UNDO_FAILED: {failure}"))
        ok = sum(1 for _, d in details if d == "undone")
        return ("undone" if ok == len(details) else "undo_failed" if ok == 0 else "partial"), details

    def _outputs(self, data: Any) -> dict[str, str]:
        """Kết quả bước cấp (`tools.models.Cert`) → `serial`, `expires_on` (ngày địa phương). `ExecutionResult` lọc lại regex."""
        serial = getattr(data, "serial", None)
        expires = getattr(data, "expires_at", None)
        out: dict[str, str] = {}
        if isinstance(serial, str):
            out["serial"] = serial
        if expires is not None:
            out["expires_on"] = expires.astimezone(self._tz).date().isoformat()
        return out


def _result(
    success: bool, steps_done: list[str], failed: str | None, rollback: RollbackStatus,
    details: list[tuple[str, str]], note: str | None, outputs: dict[str, str],
) -> ExecutionResult:  # fmt: skip
    return ExecutionResult(
        success=success, steps_done=steps_done, failed_step=failed, rollback_status=rollback,
        rollback_details=details, action_plan_hash_matched=None, handoff_note=note, outputs=outputs,
    )  # fmt: skip


def _handoff(
    action: Action, done: list[str], failed: str, kind: str, rollback: RollbackStatus, details: list[tuple[str, str]]
) -> str:
    """Ghi chú bàn giao 4 phần (B17 §0.3, phase3 11.4 bước 5) — chỉ tên tool, mã lỗi tập đóng, định danh."""
    raw = str(action.params.get("device_id", ""))
    device = raw if DEVICE_ID.fullmatch(raw) else "—"  # soát S12 NGHI-5: máy do B6 suy từ hệ thống ngoài cũng qua regex
    undo = {
        "none_needed": "không cần (chưa bước ghi nào thành công)",
        "not_attempted": "không thực hiện (hành động không hoàn tác được)",
    }.get(rollback) or "; ".join(f"{tool}: {status}" for tool, status in details)
    manual = f"kiểm tra chứng chỉ VPN của {action.requested_for} cho máy {device} trên VPN gateway"
    if kind == "http_409":
        manual += "; máy chưa đăng ký — đăng ký máy trước (quy trình Phase 4) rồi mới cấp"
    elif kind == "http_404":
        manual += "; máy không thuộc người này — không cấp, xác minh lại với người dùng"
    else:
        manual += f"; thực hiện {action.type} bằng tay nếu vẫn cần"
    if any(status == "undone" for _, status in details):
        manual += "; chứng chỉ cũ đã bị thu hồi khi cấp và KHÔNG được khôi phục — cấp lại nếu người dùng cần"
    return (
        f"Đã làm: {', '.join(done) or 'chưa bước nào'}. Lỗi ở bước: {failed} ({kind}). Hoàn tác: {undo}. "
        f"L2 cần làm tay: {manual}."
    )
