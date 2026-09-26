"""B1 — xác lập danh tính và ngữ cảnh người gửi (B01 mục 5, D-01). Không gọi LLM, KHÔNG đọc
`redacted_request` (bất biến riêng của B1); role chỉ lấy từ nhóm AD (bất biến 11).

Đăng nhập và đếm lần sai nằm ở middleware (P6). Ở đây, tại thời điểm xử lý:

1. phiên (họ token) hết hạn / bị thu hồi       → S_BLOCKED `invalid_credentials`
2. AD lỗi sau retry (hoặc breaker mở)          → S_ESCALATED E2 `identity_unverifiable` — không kết
                                                 luận gì về người dùng, không E9
3. AD không còn người này (404)                → S_BLOCKED `invalid_credentials`
4. đang bị khoá do dò mật khẩu                → cảnh báo Trưởng BP (idempotent) + S_BLOCKED
                                                 `repeated_auth_failure`
5. disabled / terminated                       → S_BLOCKED `invalid_credentials`
6. nhóm AD không ánh xạ được role              → S_ESCALATED E2 `role_unmappable` — lỗi cấu hình AD,
                                                 không phải lỗi người dùng; KHÔNG BAO GIỜ mặc định
                                                 employee (quyết định Q7, 26/09/2026)
7. còn lại: `RequesterContext.from_ad` (frozen) → S_SCREENING
"""

from typing import Any

from app.domain.alerts import bruteforce_alert
from app.domain.context import RequesterContext, role_from_groups
from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import S_BLOCKED, S_ESCALATED, S_SCREENING
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn

INACTIVE = frozenset({"disabled", "terminated"})
AD_ERROR_NOTE = "Không xác minh được danh tính: AD lỗi sau retry"
ROLE_NOTE = "Không ánh xạ được role từ nhóm AD của người gửi — cần kiểm tra cấu hình nhóm AD"


def make(deps: NodeDeps) -> NodeFn:
    async def blocked(state: Any, event: str, reason: BlockReason, close: CloseReason) -> Any:
        return await goto(
            state, S_BLOCKED, next_node="b20_audit", step="B1", event=event,
            block_reason=reason.value, close_reason=close.value,
        )  # fmt: skip

    async def invalid(state: Any, event: str) -> Any:
        return await blocked(
            state, event, BlockReason.INVALID_CREDENTIALS, CloseReason.BLOCKED_INVALID_CREDENTIALS
        )

    async def b01_identity(state: Any) -> dict[str, Any]:
        now = current_run().clock.now()
        session_id = state.get("session_id")
        session = await deps.identity.active_session(session_id, now) if session_id else None
        if session is None:
            return await invalid(state, "session_invalid")

        user, err, _ = await deps.directory.call(
            "ad_get_user", {"user_id": session.user_id}, caller_step="B1"
        )
        if err:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B1", event="identity_unverifiable",
                exit_code=ExitCode.E2.value, escalation_reason_detail="identity_unverifiable",
                escalation_note=AD_ERROR_NOTE, audit_detail={"tool_error": str(err)[:200]},
            )  # fmt: skip
        if user is None:
            return await invalid(state, "user_not_found")

        locked_until = await deps.identity.locked_until(user.user_id)
        if locked_until is not None and locked_until > now:
            await deps.alerts.raise_once(
                bruteforce_alert(
                    user_id=user.user_id, username=user.username,
                    lock_start=locked_until - deps.lockout, source="B1",
                    ticket_id=state["ticket_id"],
                )
            )  # fmt: skip
            return await blocked(
                state, "repeated_auth_failure", BlockReason.REPEATED_AUTH_FAILURE,
                CloseReason.BLOCKED_REPEATED_AUTH_FAILURE,
            )  # fmt: skip

        if user.employment_status in INACTIVE:
            return await invalid(state, "account_disabled")

        if role_from_groups(user.groups) is None:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B1", event="role_unmappable",
                exit_code=ExitCode.E2.value, escalation_reason_detail="role_unmappable",
                escalation_note=ROLE_NOTE,
            )  # fmt: skip

        ctx = RequesterContext.from_ad(user, now=now)
        return await goto(
            state, S_SCREENING, next_node="b02_screen", step="B1", event="identity_established",
            requester_context=ctx,
        )  # fmt: skip

    return b01_identity
