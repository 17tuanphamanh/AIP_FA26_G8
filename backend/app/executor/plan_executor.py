"""`PlanExecutor` — điểm ghi duy nhất ra hệ thống ngoài cho mọi hành động có PLAN (B17, phase3 11.4 bước 4–5; B17-B18 §2,
§5; Phase 5 T24 — D-48, đổi tên từ `VpnExecutor`/`executor/vpn.py`). Chỉ dựng ở API process (`main.py`, P7); worker giữ
`RefusingExecutor`.

Trình tự (node B17 đã kiểm lại luật/hash/người — bước 1–3):
1. Ticket đã có `begun` (mọi lượt — B17 đã hỏi ở bước 0, đây là lớp thứ hai; đứng trước cả kế hoạch rỗng — soát lại DỪNG 2
   NGHI-a) → `ExecutionInterrupted` (E7 `exec_interrupted`, 0 lời gọi ghi).
2. `plan_for(action)` (T24 P2: PLAN đã lọc `when` — bước license chỉ khi `license_paid is not False`) rỗng (`check_vpn_status`,
   `view_permissions` — 3-Q31) → thành công, không `begun`, 0 lời gọi ghi.
3. **P4:** phải còn đủ TRỌN timeout cho MỌI bước ghi của kế hoạch — TRƯỚC khi INSERT `begun`; không đủ → `TurnBudgetExceeded`
   (E2 `turn_budget_exceeded`, 0 dòng `begun`, 0 lời gọi ghi). Registry còn kiểm lại từng lời gọi (`full=True`).
4. Mỗi bước: INSERT `begun` (commit riêng) → gọi tool ghi ĐÚNG 1 lần (retries=0 — registry, không vòng lặp nào ở đây).
5. Lỗi ở bước k (gồm 404/409 — dữ liệu của hệ thống đích, P5 6.1) → hoàn tác các bước đã xong theo thứ tự ngược nếu
   `action.reversible` (`undone`/`undo_failed`/`partial`), không thì `not_attempted` → `ExecutionResult(success=False)` +
   `handoff_note` 4 phần. **T24 P3 (D-48) — hoàn tác theo từng bước:** bước `undo=None` (license trả phí) KHÔNG gọi gì, ghi
   `(tool, "not_reversible")`; mọi bước đã xong đều như vậy → `not_attempted`. Ghi chú bàn giao theo hành động (bảng 7.4). Chứng chỉ cũ bị mock thu hồi khi cấp mới KHÔNG được khôi phục — ghi rõ khi phải hoàn tác. Lỗi mơ hồ (`timeout`,
   `http_5xx`, `other`: lệnh có thể đã tới đích dù báo lỗi) → ghi chú nói rõ "có thể đã được áp dụng".
6. **Chốt FAIL mục 7 (soát DỪNG 3b):** mọi `Exception` phát sinh SAU `begin` (đứt kết nối sau khi gửi — `ReadError`,
   `RemoteProtocolError`…; phản hồi 2xx hỏng hoặc sai schema; lỗi khi hoàn tác) → `ExecutionInterrupted(cause=<tên lớp lỗi>,
   write_calls=<đã gửi>)` → B17 E7 `exec_interrupted` + câu "có thể đã gửi lệnh ghi…" — KHÔNG để lọt lên boundary thành E9 "xử
   lý thủ công" (L2 có thể ghi lần 2). Không bắt `BaseException` (`CancelledError` đi tiếp đường worker). Lỗi TRƯỚC `begun` và
   `TurnBudgetExceeded` (registry kiểm hạn TRƯỚC khi gửi → 0 lời gọi ghi, E2) giữ nguyên.

**P6 (luật 8.9):** `handoff_note`, `rollback_details`, `transaction_log.detail` và `outputs` chỉ ghép từ tên tool, mã lỗi thuộc
tập ĐÓNG (`error_kind`), định danh qua mẫu (`USER_ID`, `DEVICE_ID`, `RESOURCE_PATH`, `SOFTWARE_NAME`; `serial` qua regex), enum
và ngày — chuỗi lỗi
httpx/nội dung phản hồi của hệ thống ngoài KHÔNG bao giờ được chép vào.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from app.core.clock import Clock
from app.core.turn_budget import TurnBudgetExceeded, cap_timeout
from app.domain.action import SOFTWARE_NAME, Action
from app.domain.messages import ACCOUNT_TYPE_TEXT, DEVICE_ID, RESOURCE_PATH, USER_ID
from app.domain.ticket_state import ExecutionResult
from app.executor.errors import ExecutionInterrupted
from app.executor.plans import PLAN, Step, plan_for, step_args, undo_args
from app.executor.txlog import TxLog
from app.tools.models import (
    AssignLicenseResult,
    Cert,
    InstallResult,
    PermissionEntry,
    ResetPasswordResult,
)
from app.tools.registry import ToolResult
from app.tools.specs import REGISTRY, ToolSpec

log = logging.getLogger(__name__)

WRITE_STEP = "B17"
# Mã lỗi mà lệnh ghi CÓ THỂ đã tới đích (dù báo lỗi): hết thời gian chờ phản hồi, 5xx, lỗi lạ. Không thuộc: 404/409/429 (đích từ
# chối), connect_error / circuit_open / turn_budget_exceeded (chưa gửi).
MAYBE_APPLIED_KINDS = frozenset({"timeout", "http_5xx", "other"})
# Tên lớp lỗi httpx mà registry ghi vào `ToolResult.error` (`f"{type(e).__name__}: …"`) khi hết thời gian
TIMEOUT_ERRORS = frozenset({"TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"})

NOT_REVERSIBLE = "not_reversible"  # T24 P3: `rollback_details` của bước không hoàn tác được (không gửi lời gọi nào)

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


@dataclass
class _Progress:
    """Tiến độ của MỘT lần `execute` (không để ở instance — một executor phục vụ mọi ticket)."""

    began: bool = False  # đã INSERT `begun` ít nhất một bước
    sent: int = 0  # lời gọi ghi đã gửi (bước + hoàn tác) — cận trên của số lời gọi tới đích


class PlanExecutor:
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
        steps = plan_for(action, self._plans)  # T24 P2: lọc `when`; thiếu = cấu hình lệch mà check_plans bỏ sót → KeyError → E9
        if await self._txlog.has_begun(ticket_id):
            raise ExecutionInterrupted(f"ticket {ticket_id}: transaction_log đã có begun")
        if not steps:
            return _result(True, [], None, "none_needed", [], None, {})
        need = sum(self._specs[s.tool].timeout_s for s in steps)
        cap_timeout(need, self._clock, what="executor:plan", full=True)  # P4 — TRƯỚC begun
        progress = _Progress()
        try:
            return await self._apply(ticket_id, turn_id, action, steps, progress)
        except TurnBudgetExceeded:
            raise  # registry kiểm hạn TRƯỚC khi gửi → 0 lời gọi ghi → E2 (P4; bước k>1 đã đổi thành lỗi có handoff)
        except Exception as e:
            if not progress.began:
                raise  # trước begun: chưa gửi gì → boundary E9 như cũ
            cause = type(e).__name__  # CHỈ tên lớp lỗi — không str(e), không nội dung phản hồi (luật 8.9)
            log.warning("executor: lỗi sau begun (ticket %s, %s): %s", ticket_id, action.type, cause)
            raise ExecutionInterrupted(f"ticket {ticket_id}: lỗi sau begun ({cause})", cause=cause,
                                       write_calls=progress.sent) from e  # fmt: skip

    async def _apply(
        self, ticket_id: str, turn_id: str, action: Action, steps: tuple[Step, ...], progress: _Progress
    ) -> ExecutionResult:
        done: list[tuple[Step, Any]] = []
        for step in steps:
            await self._txlog.begin(ticket_id, turn_id, step.tool)
            progress.began = True
            progress.sent += 1
            try:
                result = await self._registry.call(step.tool, step_args(step.tool, action), caller_step=WRITE_STEP)
            except TurnBudgetExceeded:
                if not done:
                    raise  # bước đầu: chưa ghi gì → E2 (P4)
                # soát S12 NGHI-6a (kế hoạch nhiều bước): đã ghi bước trước → KHÔNG thoát kiểu E2 mà hoàn tác + E7 có handoff
                result = ToolResult(step.tool, None, "turn_budget_exceeded", 0, False)
            if result.error is not None:
                kind = error_kind(result.error)
                status, details = await self._rollback(ticket_id, turn_id, action, done, progress)
                note = _handoff(action, [s.tool for s, _ in done], step.tool, kind, status, details)
                return _result(False, [s.tool for s, _ in done], step.tool, status, details, note, {})
            done.append((step, result.data))
        return _result(True, [s.tool for s, _ in done], None, "none_needed", [], None, self._outputs([d for _, d in done]))

    async def _rollback(
        self, ticket_id: str, turn_id: str, action: Action, done: list[tuple[Step, Any]], progress: _Progress
    ) -> tuple[RollbackStatus, list[tuple[str, str]]]:
        if not done:
            return "none_needed", []
        if not action.reversible:
            return "not_attempted", []  # [Chốt sửa vòng 2]: không gọi undo cho hành động không hoàn tác được
        details: list[tuple[str, str]] = []
        for step, data in reversed(done):
            if step.undo is None:  # T24 P3: bước không hoàn tác được (license đã cấp) → KHÔNG gọi gì, chỉ ghi nhận
                details.append((step.tool, NOT_REVERSIBLE))
                continue
            progress.sent += 1
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
        if all(d == NOT_REVERSIBLE for _, d in details):
            return "not_attempted", details  # T24 P3: mọi bước đã xong đều không hoàn tác được → không thử gì
        ok = sum(1 for _, d in details if d == "undone")
        return ("undone" if ok == len(details) else "undo_failed" if ok == 0 else "partial"), details

    def _outputs(self, results: list[Any]) -> dict[str, str]:
        """Kết quả MỌI bước đã xong (`tools.models`) → khoá ĐÓNG cho tin B18 (P4): `Cert` → `serial`, `expires_on`;
        `ResetPasswordResult` → `delivered_via`, `expires_in_minutes`, `sent_to`; `AssignLicenseResult` → `license_id`, `software`; `InstallResult` → `software`,
        `version`; `PermissionEntry` (cấp/gia hạn) → `level`, `expires_on`. Ngày theo giờ địa phương. `ExecutionResult` lọc lại regex."""
        out: dict[str, str] = {}
        for data in results:
            if isinstance(data, Cert):
                out["serial"] = data.serial
                out["expires_on"] = self._local_date(data.expires_at)
            elif isinstance(data, ResetPasswordResult):
                out["delivered_via"] = data.delivered_via
                if data.expires_in_minutes is not None:
                    out["expires_in_minutes"] = str(data.expires_in_minutes)
                if data.sent_to is not None:
                    out["sent_to"] = data.sent_to
            elif isinstance(data, AssignLicenseResult):
                out["license_id"] = data.assignment_id
                out["software"] = data.name
            elif isinstance(data, InstallResult):
                out["software"] = data.name
                out["version"] = data.version
            elif isinstance(data, PermissionEntry):
                out["level"] = data.level
                if data.expires_at is not None:
                    out["expires_on"] = self._local_date(data.expires_at)
        return out

    def _local_date(self, at: datetime) -> str:
        return at.astimezone(self._tz).date().isoformat()


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
    """Ghi chú bàn giao 4 phần (B17 §0.3, phase3 11.4 bước 5; T24 P5 bảng 7.4) — chỉ tên tool, mã lỗi tập đóng, định danh qua
    mẫu (`USER_ID`, `DEVICE_ID`, `RESOURCE_PATH`, tên phần mềm chuẩn hoá) và loại tài khoản enum."""
    maybe = kind in MAYBE_APPLIED_KINDS
    if rollback == "none_needed":
        undo = "không cần (chưa bước ghi nào xác nhận thành công)" if maybe else "không cần (chưa bước ghi nào thành công)"
    elif rollback == "not_attempted" and not details:
        undo = "không thực hiện (hành động không hoàn tác được)"
    else:
        undo = "; ".join(f"{tool}: {status}" for tool, status in details)
    manual = _manual(action, done, failed, kind, details)
    if maybe:
        manual = f"lệnh ở bước {failed} có thể đã được áp dụng — kiểm trên hệ thống đích trước khi làm lại; " + manual
    return (
        f"Đã làm: {', '.join(done) or 'chưa bước nào'}. Lỗi ở bước: {failed} ({kind}). Hoàn tác: {undo}. "
        f"L2 cần làm tay: {manual}."
    )


def _ident(pattern: Any, raw: object) -> str:
    """Định danh chỉ vào ghi chú khi khớp mẫu (P6) — sai mẫu → "—"."""
    value = str(raw if raw is not None else "")
    return value if pattern.fullmatch(value) else "—"


def _manual(action: Action, done: list[str], failed: str, kind: str, details: list[tuple[str, str]]) -> str:
    """Phần "L2 cần làm tay" theo hành động (bảng 7.4). VPN: giữ nguyên chữ 3h."""
    p = action.params
    rf = _ident(USER_ID, action.requested_for)
    if action.type in ("reset_password", "unlock_account"):
        kind_text = ACCOUNT_TYPE_TEXT.get(str(p.get("account_type")), "—")
        if kind == "http_404":
            return f"tài khoản {kind_text} của {rf} không tồn tại — xác minh lại với người dùng"
        return f"kiểm tài khoản {kind_text} của {rf} trên AD; thực hiện {action.type} bằng tay nếu vẫn cần"
    if action.type == "install_software":
        software, device = _ident(SOFTWARE_NAME, p.get("software_name")), _ident(DEVICE_ID, p.get("device_id"))
        if failed == "assign_paid_license" and kind == "http_409":
            manual = f"hết license {software} (hoặc không phải phần mềm có phí) — xin thêm license rồi cài lại"
        elif kind == "http_404":
            manual = f"máy {device} hoặc phần mềm {software} không có trên hệ thống — xác minh lại"
        else:
            manual = f"thực hiện {action.type} bằng tay nếu vẫn cần"
        if "assign_paid_license" in done:  # D-48: license đã cấp, không thu hồi qua tool
            manual += (f"; license {software} ĐÃ cấp cho {rf} và KHÔNG được thu hồi tự động — cài bằng tay hoặc thu hồi "
                       "license")  # fmt: skip
        return manual
    if action.type in ("grant_permission", "extend_permission"):
        path = _ident(RESOURCE_PATH, p.get("resource_path"))
        if kind == "http_404" and action.type == "grant_permission":
            return f"thư mục {path} không tồn tại — xác minh lại đường dẫn"
        if kind == "http_404":
            return f"{rf} chưa có quyền trên {path} — không gia hạn được, cân nhắc cấp mới (cần duyệt)"
        return f"thực hiện {action.type} bằng tay nếu vẫn cần"
    device = _ident(DEVICE_ID, p.get("device_id"))  # soát S12 NGHI-5: máy do B6 suy từ hệ thống ngoài cũng qua regex
    manual = f"kiểm tra chứng chỉ VPN của {action.requested_for} cho máy {device} trên VPN gateway"
    if kind == "http_409":
        manual += "; máy chưa đăng ký — đăng ký máy trước (quy trình Phase 4) rồi mới cấp"
    elif kind == "http_404":
        manual += "; máy không thuộc người này — không cấp, xác minh lại với người dùng"
    else:
        manual += f"; thực hiện {action.type} bằng tay nếu vẫn cần"
    if any(status == "undone" for _, status in details):
        manual += "; chứng chỉ cũ đã bị thu hồi khi cấp và KHÔNG được khôi phục — cấp lại nếu người dùng cần"
    return manual
