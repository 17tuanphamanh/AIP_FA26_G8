"""Cổng lưu trữ của runtime (P1) và phụ thuộc của node thật — bản SQL ở `app/db/runtime.py`,
`app/db/identity.py`, `app/audit/writer.py`, `app/audit/alerts.py`; bản in-memory cùng hợp đồng ở
`backend/tests/fakes/graph.py` để test graph không cần Postgres.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.approval.store import ApprovalRow, InboxRow, OpenWaitKind, PolicyMatchRow
from app.db.identity import LiveSession
from app.db.runtime import (
    DueReminder,
    DueWait,
    OpenTurn,
    OrphanChild,
    ReminderTarget,
    WaitKind,
)
from app.db.tickets import NewEvents, NewTicket, TicketRow
from app.domain.alerts import AlertDraft
from app.domain.approval import ReminderN
from app.domain.children import ChildHandoffRow, ChildProgressRow, ChildView
from app.domain.dedup import OpenCandidate
from app.domain.final import FinalSummary
from app.domain.override import DecisionTrail, OverrideRecord
from app.tools.registry import ToolResult

# bản ghi dữ liệu dùng chung với store SQL
__all__ = [
    "ApprovalRow", "DueWait", "LiveSession", "NewTicket", "OpenTurn", "TicketRow", "ToolResult",
    "WaitKind",
]  # fmt: skip


class AuditSink(Protocol):
    async def record(self, row: Mapping[str, Any], *, lineage: Mapping[str, Any] | None = None) -> bool:
        """INSERT `audit_logs`; `idempotency_key` trùng → bỏ qua (ON CONFLICT DO NOTHING).

        Trả True nếu SAU lệnh ghi có dòng mang khoá đó (vừa ghi hoặc đã có) — kiểm trong CÙNG
        transaction với INSERT (cấm 4, P1 mục 5.1.1). Dòng không khoá: luôn ghi, trả True.
        `lineage` (3g, Q-3g-3): dòng `lineage` của bước, ghi trong CÙNG transaction, idempotent theo
        (ticket_id, turn_id, step, prompt_id)."""
        ...


class EffectStore(Protocol):
    async def run_once(
        self,
        *,
        key: str,
        ticket_id: str,
        kind: str,
        step: str,
        turn_id: str,
        call: Callable[[], Awaitable[Any]],
    ) -> str | None:
        """Khoá chưa có → ghi `side_effects`, gọi `call()` đúng một lần, lưu `result_ref`, cùng
        một transaction. Khoá đã có → trả `result_ref` cũ, KHÔNG gọi `call` (D-18)."""
        ...

    async def peek(self, key: str) -> str | None:
        """`result_ref` của khoá đã ghi (đã commit); chưa có → None. Chỉ SELECT (Phase 4 4b P9)."""
        ...


@dataclass
class SpanRecord:
    span_id: str
    trace_id: str
    turn_id: str
    span_type: str  # node | llm | tool | rag
    name: str
    started_at: datetime
    parent_span_id: str | None = None
    duration_ms: int | None = None
    status: str = "ok"  # ok | error | interrupted
    attributes: dict[str, Any] = field(default_factory=dict)


class SpanSink(Protocol):
    async def write(self, span: SpanRecord) -> None: ...


class TurnStore(Protocol):
    async def start(
        self, *, turn_id: str, ticket_id: str, session_id: str | None, event_type: str, at: datetime
    ) -> None: ...

    async def end(self, turn_id: str, at: datetime) -> None: ...

    async def is_open(self, turn_id: str) -> bool: ...

    async def bump_recover_attempts(self, turn_id: str) -> int | None:
        """`recover_attempts + 1` của lượt còn mở, trả giá trị mới; lượt đã đóng → None (2b-Q6)."""
        ...

    async def stale(self, before: datetime, limit: int) -> list[OpenTurn]:
        """Lượt chưa kết thúc (`ended_at IS NULL`) bắt đầu trước `before` (P1 mục 7)."""
        ...


class DeadlineStore(Protocol):
    async def set(self, ticket_id: str, kind: str, deadline: datetime, created_turn: str) -> str:
        """Đặt hạn chờ `clarify`/`confirm` (`wait_deadlines`). Hạn cũ chưa bắn của cùng ticket +
        kind bị đánh dấu đã bắn (bị thay) — để hạn vòng hỏi trước không cắt ngang vòng sau."""
        ...

    async def due(self, now: datetime, limit: int) -> list[DueWait]:
        """Hạn đã qua, chưa bắn: `wait_deadlines` + `approvals` đang `pending` (hạn duyệt nằm ở
        `approvals.deadline` [Chốt], P7 2.5). Worker không đọc checkpoint."""
        ...

    async def mark_fired(self, due: DueWait, at: datetime) -> None:
        """Đánh dấu hạn đã bắn. Hạn duyệt (ca 409 — ticket đã đi tiếp): đóng phiếu `timeout` + `decided_at` (4c A11)."""
        ...

    async def due_reminders(self, now: datetime, limit: int) -> list[DueReminder]:
        """4c P3 (Q-4c-2 = A): phiếu `pending`, `deadline > now`, đã qua mốc 1, còn cột nhắc NULL. Chỉ đọc."""
        ...

    async def parents_to_wake(self, limit: int) -> list[str]:
        """Phase 5 T20b P12 (a), chỉ đọc DB: cha `is_parent`, `final_state IS NULL` mà (1) số con đã khởi động (dòng `child_submit` của cha,
        khác `result_ref`) < số con (Q-T20b-7 — bắt cả con có `turns` mà thread rỗng), HOẶC (2) MỌI con đã dừng theo đúng điều kiện
        `children_view` (`final_state` VÀ không còn lượt mở, hoặc notice chưa gửi `needs ≠ none`) — NGHI-2."""
        ...

    async def orphan_children(
        self, now: datetime, limit: int, *, clarify_hours: int, confirm_hours: int
    ) -> list[OrphanChild]:
        """Phase 5 T20b P12 (b) (DỪNG 2; mở rộng Q-T20b-5 (iii)): con `final_state IS NULL` mà cha ĐÃ có `final_state`, có notice
        `needs ≠ none` (ĐÃ gửi hay chưa — con đã nhận digest rồi đứng chờ cũng tính) — `needs` = của notice đó mới nhất; con đang có phiếu
        duyệt `pending` → bỏ (chờ L1, không chờ người dùng; giao `timeout` sẽ chỉ ra `late_event` mỗi chu kỳ). Q-T20b-9 (ii): CHỈ khi đã
        quá hạn thường tính từ `delivered_at` của notice đó (chưa gửi → `created_at`): `answer` → `clarify_hours`, `confirm` →
        `confirm_hours` — nhãn `close_reason` của con (`resolved_auto_timeout_48h`, E4 hết hạn hỏi lại) giữ đúng nghĩa. Worker không đọc
        checkpoint."""
        ...

    async def mark_reminder_once(self, approval_id: str, n: ReminderN, now: datetime) -> ReminderTarget | None:
        """Đặt `reminder_n_at = now` NẾU phiếu còn `pending`, cột đó NULL, chưa tới hạn — trả người nhận khi bên này thắng, None
        khi không (worker khác đã đặt / phiếu đã đóng / quá hạn). Chỉ gửi khi có dòng."""
        ...


class TicketLock(Protocol):
    def hold(self, ticket_id: str) -> AbstractAsyncContextManager[None]:
        """Khoá theo ticket suốt một lượt (D-19). Hết `lock_timeout` → `TicketBusy`."""
        ...


class TicketBusy(Exception):
    """Ticket đang bị lượt khác giữ khoá quá `lock_timeout` — lỗi tạm, thử lại chu kỳ sau."""


# ---- phụ thuộc của node thật ------------------------------------------------------------------


class IdentityReads(Protocol):
    """B1 (B01 mục 5): phiên còn sống (theo họ token) + khoá do dò mật khẩu (`users.locked_until`)."""

    async def active_session(self, session_id: str, now: datetime) -> LiveSession | None: ...

    async def locked_until(self, user_id: str) -> datetime | None: ...


class ToolCaller(Protocol):
    """`tools.registry.ToolRegistry` khớp theo cấu trúc: lỗi hệ thống ngoài → `ToolResult.error`,
    không raise (P5 mục 6.1)."""

    async def call(
        self, name: str, args: Mapping[str, Any], *, caller_step: str
    ) -> ToolResult: ...


class AlertSink(Protocol):
    """`audit.alerts.AlertWriter` — idempotent theo `(rule_id, subject, window_start)`."""

    async def raise_once(self, draft: AlertDraft) -> bool: ...


class TicketReader(Protocol):
    """Runner dựng state đầu của ticket từ dòng `tickets` (lượt `submit` chạy nền, hoặc worker phục
    hồi lượt chết trước checkpoint đầu tiên — 2b-3)."""

    async def get(self, ticket_id: str) -> TicketRow | None: ...


class TicketStore(TicketReader, Protocol):
    """`db/tickets.SqlTicketStore` — B20 đọc `created_at`, số lượt, ghi kết quả cuối MỘT lần."""

    async def created_at(self, ticket_id: str) -> datetime: ...

    async def strategy_of(self, ticket_id: str) -> str | None:
        """D-67: chiến lược M5 đã CHỤP lúc tạo ticket (B12 đọc, không đọc từ `NodeDeps`). None = ticket cũ / không ghi → `hybrid`."""
        ...

    async def count_turns(self, ticket_id: str) -> int: ...

    async def open_candidates(self, requester_id: str, *, since: datetime) -> list[OpenCandidate]:
        """M1 (B3 báo trùng yêu cầu): ticket của `requester_id` tạo từ `since`, kèm `intent` lấy từ dòng audit B3 `intent_classified`
        (`tickets.intent` chỉ được ghi ở B20, ticket còn mở thì NULL). Chỉ đọc. Trả TẬP CHA — có thể thừa (đã đóng, là cha, chưa có
        intent…); người gọi lọc lại bằng `domain.dedup.pick_duplicate` (nơi duy nhất quyết định)."""
        ...

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        """Ghi nếu `final_state IS NULL`; luôn trả dòng ĐANG CÓ (vừa ghi hoặc từ lần trước)."""
        ...

    # ---- Phase 5 T20b (P3, P7; TQ-6): ticket con — B5 tạo, `parent_wait` đối soát từ DB (D-17) -----------------------------

    async def create_child(
        self, child_id: str, *, parent_id: str, redacted_request: str, created_at: datetime, intents: int, intent_type: str
    ) -> str:
        """Dòng `tickets` của con: chép `requester_id/role/dept`, `session_id`, D-67 `strategy`/`source` từ dòng cha; `parent_ticket_id = parent_id`; KHÔNG dòng
        `turns` (lượt đầu do `ChildOps.start` mở). CHỈ gọi qua `effects.once("child_create", sub=child_id)` (D-18). Trả
        `domain.children.child_ref(child_id, intents, intent_type)` = `result_ref` (Q-T20b-12)."""
        ...

    async def mark_parent_once(self, ticket_id: str) -> bool:
        """`tickets.is_parent = true` chỉ khi đang false (idempotent) — True khi vừa đổi (D-30: chỉ số lọc `is_parent = false`)."""
        ...

    async def children_view(
        self, parent_id: str, children: Sequence[str], *, delivered_round: int | None = None
    ) -> list[ChildView]:
        """Theo thứ tự `children`: `final_state` (None khi con còn lượt `turns` mở — B20 của con chưa xong) + notice CHƯA gửi
        (`delivered_at IS NULL`, cũ → mới) — chỉ DB (D-17).
        `delivered_round=n`: thay vào đó CHỈ notice đã gửi ở vòng `n` — `parent_wait` chạy lại cùng lượt sau khi tin vòng `n` đã gửi
        (`deliver_round` đã commit, checkpoint chưa có) dựng lại ĐÚNG tin đó, không gom notice mới tới sau (soát S10 B-iii)."""
        ...

    async def deliver_round(self, parent_id: str, round_no: int, notice_ids: Sequence[int], at: datetime) -> str:
        """`delivered_round = round_no`, `delivered_at = at` cho đúng `notice_ids` (của `parent_id`, còn chưa gửi) — trong transaction
        của `effects.once("notify_user", sub=f"round:{n}")` (P7). Trả ref của tin tổng hợp."""
        ...

    async def started_children(self, parent_id: str) -> frozenset[str]:
        """Con đã có dòng `child_submit` của cha ở BẤT KỲ lượt nào (`result_ref = started:<con>`) — Q-T20b-11. Chỉ đọc."""
        ...

    async def children_status(self, parent_id: str) -> list[ChildHandoffRow]:
        """Trạng thái từng con cho ghi chú bàn giao của ticket lỗi (Q-T20b-9 (i)) — chỉ DB: MỌI dòng `tickets` có `parent_ticket_id =
        parent_id` (kể cả con đã `child_create` mà checkpoint cha chưa có `children` — soát lượt 4 mục 4), theo `index`; không con → []."""
        ...


class EscalationStore(Protocol):
    """`db/escalations.SqlEscalationStore.create` — chỉ gọi qua `effects.once("escalation_create")`."""

    async def create(
        self,
        *,
        ticket_id: str,
        exit_code: str,
        reason_detail: str | None,
        handoff_note: Mapping[str, Any],
        is_deny_case: bool,
        created_at: datetime,
    ) -> str: ...


class SecurityEvents(Protocol):
    """`audit/security_events.SecurityEventWriter.record` (cùng chữ ký, phase3 mục 8.2). Node CHỈ gọi qua
    `effects.once("security_event", …)` (test AST `SIDE_EFFECT_FUNCS`); writer ghi bằng `current_tx()` nên dòng sự kiện
    và dòng `side_effects` cùng commit. `detail` không chứa văn bản người dùng (`check_event` chặn khoá nhạy cảm)."""

    async def record(
        self, event_type: str, *, ticket_id: str | None = None, detail: Mapping[str, Any] | None = None
    ) -> None: ...


class TicketRepo(TicketStore, Protocol):
    """Thêm phần API dùng (2b-3): tạo ticket + lượt `submit` đầu tiên trong MỘT transaction."""

    async def create(
        self, ticket: NewTicket, *, turn_id: str, security_events: NewEvents = ()
    ) -> None:
        """`security_events` (event_type, detail) INSERT cùng transaction (3e, phase3 mục 8.3)."""
        ...

    async def list_own(self, requester_id: str, limit: int) -> list[TicketRow]:
        """P3 "Gần đây" (`GET /api/tickets`): ticket GỐC của ĐÚNG `requester_id`, `created_at DESC, ticket_id DESC`, tối đa `limit`,
        trừ ticket người đó đã ẩn (lọc trước `LIMIT`). Chỉ DB."""
        ...

    async def hide(self, user_id: str, ticket_id: str, at: datetime) -> None:
        """P3 menu ⋯ "Xóa": ẩn ticket khỏi "Gần đây" của `user_id` — idempotent, không đổi dữ liệu nghiệp vụ."""
        ...

    async def children_progress_rows(self, parent_id: str, children: Sequence[str]) -> list[ChildProgressRow]:
        """Phase 5 T20b P11 (DỪNG 2): mỗi con (theo thứ tự `children`) — `final_state`, có phiếu `approvals.status='pending'`, có notice
        chưa gửi `needs ≠ none` của `parent_id`. Chỉ DB."""
        ...


class ApprovalRepo(Protocol):
    """Phần `approval/store.SqlApprovals` mà route duyệt dùng (2b-Q3). 4d (Q-4d-2 = A): cả route ghi đè (`api/tickets.py`) — `Desk`
    dựng ở `main.py` (M9, không sửa) chỉ có `tickets`/`approvals`, và `SqlApprovals` đã đọc `audit_logs` từ 4c (hộp thư)."""

    def lock_row(self, approval_id: str) -> AbstractAsyncContextManager[ApprovalRow | None]:
        """Transaction ngắn, khoá hàng (`FOR UPDATE`) suốt khối `async with`."""
        ...

    async def get(self, approval_id: str) -> ApprovalRow | None: ...

    async def inbox(self, user_id: str, status: str | None, limit: int) -> list[InboxRow]:
        """4c P5: phiếu `user_id` được giao HOẶC là dự phòng đã qua nhắc 2 (lọc vai trò ở SQL), [+ `status`], mới nhất trước, ≤ `limit`."""
        ...

    async def mark_viewed(self, approval_id: str, now: datetime) -> bool:
        """4c P6: `first_viewed_at = now` NẾU đang NULL và phiếu `pending` — True khi ghi được (lần xem đầu)."""
        ...

    async def procedure_title(self, doc_id: str) -> str | None:
        """4c P6: tiêu đề tài liệu `doc_id` ở bản KB hiện hành; không có → None (không chặn)."""
        ...

    async def policy_matches(self, ticket_id: str, before: datetime) -> PolicyMatchRow | None:
        """P3 tuần 8 (`ApprovalView.matched_rules`): `detail.all_matched` + `matched_rule_id` của dòng B13/B14 MỚI NHẤT (`log_id`) có
        `created_at <= before` (lúc tạo phiếu); không có → None."""
        ...

    async def decision_trail(self, ticket_id: str) -> DecisionTrail:
        """4d P3 (Q-4d-2 = A): dòng `B13/B14 risk_decided` MỚI NHẤT của ticket (`detail.route`, cột `policy_decision`) + có dòng
        `B10 deflected_info_only` hay không — để route ghi đè suy `original_decision`."""
        ...

    async def record_override(self, rec: OverrideRecord) -> bool:
        """4d P4: ghi MỘT dòng `audit_logs` `step="OVERRIDE"` (qua `AuditWriter.record_new`) — True = dòng mới; người này đã ghi đè
        ticket này (trùng `idempotency_key`) → False. KHÔNG đụng `tickets`, checkpoint, lượt."""
        ...

    async def open_deadline(self, ticket_id: str, kind: OpenWaitKind) -> datetime | None:
        """R3 (`TicketView.deadline`, chỉ đọc): `approval` → `approvals.deadline` của phiếu `pending` mới nhất của ticket;
        `clarify`/`confirm` → dòng `wait_deadlines` cùng loại chưa bắn (`fired_at IS NULL`, hạn muộn nhất) — đúng dòng worker bắn
        timeout. Không có → None. Nằm ở đây vì `Desk` (`main.py`) chỉ có `tickets`/`approvals` (như `inbox`, `procedure_title`)."""
        ...

    async def parent_deadline(self, parent_id: str) -> datetime | None:
        """`TicketView.deadline` của ticket CHA chưa kết thúc, theo thứ tự: (1) dòng `wait_deadlines` chưa bắn của CHÍNH cha
        (`parent_wait` đặt khi gửi tin tổng hợp — `db/runtime.py:SqlDeadlineStore._set`; mỗi lúc chỉ một dòng chưa bắn); (2) không có →
        `min(approvals.deadline)` các phiếu `pending` của ticket CON; (3) không có → None. Chỉ đọc."""
        ...
