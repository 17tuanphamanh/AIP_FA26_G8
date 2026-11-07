"""Bản giả in-memory cho runtime graph (P1) — cùng hợp đồng với store SQL (`app/db/runtime.py`,
`app/audit/writer.py`) để test graph không cần Postgres. Bản SQL chạy lại các luồng chính trong
`tests/integration/test_graph_pg.py`.

`GraphHarness.restart()` dựng graph + runner MỚI trên cùng checkpointer và cùng "DB" giả — mô phỏng
khởi động lại backend (cổng 2).

Phase 4 4b (TQ-6): bảng `users` giả (`GraphHarness.auth_store`, `InMemoryAuthStore`) dùng chung cho FK của phiếu duyệt
(`MemoryApprovals` — `approver_id`/`backup_approver_id` phải có dòng, như Postgres) và `approver_users` (`AuthApproverUsers` THẬT
bọc `AdUserSync` THẬT trên store đó, khoá HMAC `HARNESS_USERNAME_KEY`). Người duyệt GIẢ (`approver_id`, B15 giả) được gieo sẵn một
dòng `users` (như `graph_pg` gieo `l1-fake`); người trong roster thì KHÔNG — B15 thật phải `ensure`.
AD giả (`FakeAd`, khi test không truyền `directory`): harness GỘP thêm người trong roster + chuỗi quản lý của họ từ
`mock_services/seed.json` (`ad_seed.ROSTER_CHAIN`, chuỗi P14 `l1_01 → l1_lead → it_mgr01`) — `FakeAd.add` không đè người test đã
dựng. `roster_in_ad=False` → không gộp (ca "AD không có roster" → B15 E5 `no_valid_approver`). Test đổi trạng thái/lỗi của người
trong roster thì làm TƯỜNG MINH: `h.ad.set_status(...)`, `h.ad.fail_ids`.
"""

import asyncio
import importlib.util
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.approval.store import (
    ApprovalRow,
    InboxRow,
    NoticeKind,
    OpenWaitKind,
    PolicyMatchRow,
)
from app.audit.writer import check_audit_row
from app.auth.models import UserRecord
from app.auth.service import auth_config, lock_policy
from app.auth.user_sync import AdUserSync, AuthApproverUsers
from app.auth.username_hash import username_key
from app.core.clock import Clock, FakeClock
from app.db.escalations import (
    ClosedEscalation,
    CloseRequest,
    EscalationHead,
    QueueItem,
    QueueKey,
    QueueStatus,
    ReopenHook,
    close_audit_row,
)
from app.db.lineage import LINEAGE_KEY, check_lineage_row
from app.db.models import CONFLICT_TYPES, NOTICE_KINDS, NOTICE_NEEDS
from app.db.runtime import (
    CHILD_SKIP,
    DueReminder,
    DueWait,
    OpenTurn,
    OrphanChild,
    ReminderTarget,
    as_ref,
)
from app.db.security_events import check_event
from app.db.tickets import NewEvents, NewTicket, TicketRow
from app.domain.action import Action
from app.domain.approval import REMINDER_FRACTIONS, ReminderN, Roster
from app.domain.children import (
    ChildHandoffRow,
    ChildProgressRow,
    ChildView,
    Notice,
    child_index,
    child_ref,
)
from app.domain.final import FinalSummary
from app.domain.override import DecisionTrail, OverrideRecord
from app.domain.states import S_ESCALATED
from app.domain.ticket_state import ExecutionResult
from app.graph.builder import build_graph, fake_nodes, real_nodes
from app.graph.checkpoint import make_serde
from app.graph.fakes import ApproverUsers, FakeScenario, NodeDeps
from app.graph.ports import SpanRecord, TicketBusy, ToolCaller
from app.graph.runner import Runner
from app.llm import LlmPort
from app.notify.child import ChildAwareNotifier
from app.settings import Settings, get_escalation_templates, get_policy, open_approvers
from langgraph.checkpoint.memory import InMemorySaver
from tests.fakes.ad_seed import ROSTER_CHAIN, seed_ad_records
from tests.fakes.auth import InMemoryAuthStore, RecordingSink
from tests.fakes.executor import MemoryTxLog
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.identity import (
    REQUESTER,
    SESSION,
    FakeAd,
    MemoryAlerts,
    MemoryIdentity,
    ad_user,
    fake_directory,
)
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fakes.vpn import SeedVpn

LOCKOUT = timedelta(minutes=15)
# Khoá HMAC username ma của `approver_users` trong harness (4b, 4.10 #11) — test mang khoá trượt ghi lần sai bằng CÙNG khoá này.
HARNESS_USERNAME_KEY = username_key(b"harness-jwt-signing-key-4b-000000")


class MemoryAudit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.lineage: list[dict[str, Any]] = []  # bảng `lineage` giả — ghi cùng "transaction" với dòng audit (3g)
        self.drop = False  # True → mô phỏng INSERT không để lại dòng (kiểm cấm 4)
        self.crash_once: set[str] = set()  # event → process "chết" ngay TRƯỚC khi ghi dòng đó

    async def record(self, row: Mapping[str, Any], *, lineage: Mapping[str, Any] | None = None) -> bool:
        check_audit_row(row)
        if lineage is not None:
            check_lineage_row(lineage)
        if row["event"] in self.crash_once:
            self.crash_once.discard(row["event"])
            raise Crash(f"process chết trước khi ghi audit {row['event']}")
        key = row.get("idempotency_key")
        if self.drop:
            return False
        if lineage is not None and not any(
            all(r.get(k) == lineage.get(k) for k in LINEAGE_KEY) for r in self.lineage
        ):  # như `db/lineage.insert_once`: NOT EXISTS (ticket, lượt, bước, prompt)
            self.lineage.append(dict(lineage))
        if key is None or all(r.get("idempotency_key") != key for r in self.rows):
            self.rows.append(dict(row))
        return True

    async def record_new(self, row: Mapping[str, Any]) -> bool:
        """Như `AuditWriter.record_new` (4d P4): True CHỈ khi vừa ghi dòng mới; khoá đã có → False; thiếu khoá → ValueError."""
        check_audit_row(row)
        key = row.get("idempotency_key")
        if key is None:
            raise ValueError("audit_logs.record_new: thiếu idempotency_key")
        if any(r.get("idempotency_key") == key for r in self.rows):
            return False
        self.rows.append(dict(row))
        return True

    def events(self, ticket_id: str) -> list[tuple[str, str]]:
        return [(r["step"], r["event"]) for r in self.rows if r["ticket_id"] == ticket_id]

    def of(self, ticket_id: str, event: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["ticket_id"] == ticket_id and r["event"] == event]


class MemoryEffects:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def run_once(
        self, *, key: str, ticket_id: str, kind: str, step: str, turn_id: str,
        call: Callable[[], Awaitable[Any]],
    ) -> str | None:  # fmt: skip
        async with self._lock:  # giống transaction: lời gọi thứ hai chờ lời gọi đầu xong
            if key in self.rows:
                return self.rows[key]["result_ref"]
            ref = as_ref(await call())
            self.rows[key] = {"ticket_id": ticket_id, "kind": kind, "step": step,
                              "turn_id": turn_id, "result_ref": ref}  # fmt: skip
            return ref

    async def peek(self, key: str) -> str | None:
        row = self.rows.get(key)
        return None if row is None else row["result_ref"]

    def count(self, ticket_id: str, kind: str) -> int:
        return sum(1 for r in self.rows.values() if r["ticket_id"] == ticket_id and r["kind"] == kind)


class MemorySpans:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []
        self.crash_once: set[str] = set()  # tên span → process "chết" khi node đã xong, trước checkpoint

    async def write(self, span: SpanRecord) -> None:
        if span.name in self.crash_once:
            self.crash_once.discard(span.name)
            raise Crash(f"process chết sau {span.name}, trước checkpoint")
        self.spans.append(span)


class MemoryTurns:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def start(
        self, *, turn_id: str, ticket_id: str, session_id: str | None, event_type: str, at: datetime
    ) -> None:
        assert turn_id not in self.rows, "turn_id là khoá chính"
        self.rows[turn_id] = {"ticket_id": ticket_id, "event_type": event_type,
                              "started_at": at, "ended_at": None}  # fmt: skip

    async def end(self, turn_id: str, at: datetime) -> None:
        if self.rows[turn_id]["ended_at"] is None:
            self.rows[turn_id]["ended_at"] = at

    async def is_open(self, turn_id: str) -> bool:
        return turn_id in self.rows and self.rows[turn_id]["ended_at"] is None

    async def bump_recover_attempts(self, turn_id: str) -> int | None:
        row = self.rows.get(turn_id)
        if row is None or row["ended_at"] is not None:
            return None
        row["recover_attempts"] = row.get("recover_attempts", 0) + 1
        return int(row["recover_attempts"])

    async def stale(self, before: datetime, limit: int) -> list[OpenTurn]:
        rows = sorted(
            (r["started_at"], t, r["ticket_id"]) for t, r in self.rows.items()
            if r["ended_at"] is None and r["started_at"] < before
        )  # fmt: skip
        return [OpenTurn(tid, t, at) for at, t, tid in rows[:limit]]

    def of(self, ticket_id: str) -> list[dict[str, Any]]:
        return [{"turn_id": t, **r} for t, r in self.rows.items() if r["ticket_id"] == ticket_id]


class MemoryDeadlines:
    """`wait_deadlines` + phần `approvals` worker đọc (hạn duyệt) + 2 truy vấn nhắc 4c P3 (cùng ngữ nghĩa câu SQL của
    `SqlDeadlineStore`: lọc thô ở `due_reminders`, đánh dấu có điều kiện ở `mark_reminder_once`)."""

    def __init__(self) -> None:
        self.waits: list[dict[str, Any]] = []
        self.approvals: dict[str, dict[str, Any]] = {}
        self.tickets: MemoryTickets | None = None  # harness nối — Phase 5 T20b: con/cha theo dòng `tickets` giả
        self.effects: MemoryEffects | None = None  # harness nối — P12 (a) đếm `child_submit` của cha

    async def set(self, ticket_id: str, kind: str, deadline: datetime, created_turn: str) -> str:
        """Như `SqlDeadlineStore.set`. Phase 5 T20b: ticket CON → không ghi, trả `CHILD_SKIP` (P5 — hạn do cha giữ); ticket CHA → thay
        mọi hạn chưa bắn của cả hai loại (Q-T20b-3 = A); ticket thường → thay hạn chưa bắn CÙNG loại (như cũ)."""
        row = self.tickets.rows.get(ticket_id, {}) if self.tickets is not None else {}
        if row.get("parent_ticket_id"):
            return CHILD_SKIP
        is_parent = bool(row.get("is_parent"))
        for w in self.waits:
            if w["ticket_id"] == ticket_id and (is_parent or w["kind"] == kind) and w["fired_at"] is None:
                w["fired_at"] = deadline  # bị thay (giá trị giả, chỉ cần khác None)
        self.waits.append({"ticket_id": ticket_id, "kind": kind, "deadline": deadline,
                           "created_turn": created_turn, "fired_at": None, "is_parent": is_parent})  # fmt: skip
        return created_turn

    async def due(self, now: datetime, limit: int) -> list[DueWait]:
        out = [DueWait(w["ticket_id"], w["kind"], w["created_turn"], w["is_parent"])
               for w in sorted(self.waits, key=lambda w: w["deadline"])
               if w["fired_at"] is None and w["deadline"] < now]  # fmt: skip
        out += [DueWait(a["ticket_id"], "approval", aid) for aid, a in self.approvals.items()
                if a["status"] == "pending" and a["deadline"] < now]  # fmt: skip
        return out[:limit]

    async def due_reminders(self, now: datetime, limit: int) -> list[DueReminder]:
        out = []
        for aid, a in sorted(self.approvals.items(), key=lambda kv: kv[1]["deadline"]):
            created, deadline = a.get("created_at", a["deadline"]), a["deadline"]
            r1, r2 = a.get("reminder_1_at"), a.get("reminder_2_at")
            if (a["status"] == "pending" and deadline > now and (r1 is None or r2 is None)
                    and created + (deadline - created) * REMINDER_FRACTIONS[1] <= now):  # fmt: skip
                out.append(DueReminder(aid, a["ticket_id"], created, deadline, r1, r2))
        return out[:limit]

    def _children(self, parent_id: str) -> list[str]:
        assert self.tickets is not None
        return [t for t, r in self.tickets.rows.items() if r["parent_ticket_id"] == parent_id]

    def _pending_needs(self, child_id: str) -> list[str]:
        assert self.tickets is not None
        return [n["needs"] for n in self.tickets.notices
                if n["child_ticket_id"] == child_id and n["delivered_at"] is None and n["needs"] != "none"]  # fmt: skip

    async def parents_to_wake(self, limit: int) -> list[str]:
        """Như SQL (P12 a, 2 vế): cha chưa kết thúc mà (1) số `child_submit` (khác `result_ref`) < số con, HOẶC (2) mọi con đã dừng theo
        điều kiện `children_view` (`final` VÀ không lượt mở, hoặc notice chưa gửi `needs≠none`)."""
        assert self.tickets is not None and self.effects is not None
        out = []
        for tid, r in self.tickets.rows.items():
            kids = self._children(tid)
            if not r["is_parent"] or r["final"] is not None or not kids:
                continue
            submitted = {e["result_ref"] for e in self.effects.rows.values() if e["ticket_id"] == tid and e["kind"] == "child_submit"}

            def ended(c: str) -> bool:
                assert self.tickets is not None
                return self.tickets.rows[c]["final"] is not None and all(
                    t["ended_at"] is not None for t in self.tickets._turns.of(c))  # fmt: skip

            if len(submitted) < len(kids) or all(ended(c) or self._pending_needs(c) for c in kids):
                out.append(tid)
        return out[:limit]

    async def orphan_children(
        self, now: datetime, limit: int, *, clarify_hours: int, confirm_hours: int
    ) -> list[OrphanChild]:
        """Như SQL (P12 b, mở rộng Q-T20b-5 (iii)): con chưa kết thúc, cha đã có `final_state`, có notice `needs≠none` (ĐÃ gửi hay chưa)
        — `needs` của notice đó MỚI NHẤT; con đang có phiếu duyệt `pending` (đang chờ L1, không chờ người dùng) → bỏ. Q-T20b-9 (ii): chỉ
        khi `delivered_at` (chưa gửi → `created_at`) của notice đó + hạn thường (`answer` 24 h / `confirm` 48 h) ≤ `now`."""
        assert self.tickets is not None
        out = []
        for tid, r in self.tickets.rows.items():
            parent = r["parent_ticket_id"]
            asking = sorted((n for n in self.tickets.notices if n["child_ticket_id"] == tid and n["needs"] != "none"),
                            key=lambda n: (n["created_at"], n["notice_id"]))  # fmt: skip
            waiting_l1 = any(a["ticket_id"] == tid and a["status"] == "pending" for a in self.approvals.values())
            if not (parent and r["final"] is None and asking and not waiting_l1 and self.tickets.rows[parent]["final"] is not None):
                continue
            last = asking[-1]
            hours = clarify_hours if last["needs"] == "answer" else confirm_hours
            if (last["delivered_at"] or last["created_at"]) <= now - timedelta(hours=hours):
                out.append(OrphanChild(tid, last["needs"]))
        return out[:limit]

    async def mark_reminder_once(self, approval_id: str, n: ReminderN, now: datetime) -> ReminderTarget | None:
        a = self.approvals.get(approval_id)
        col = f"reminder_{n}_at"
        if a is None or a["status"] != "pending" or a.get(col) is not None or not a["deadline"] > now:
            return None
        a[col] = now
        return ReminderTarget(a["approver_id"], a.get("backup_approver_id"))

    async def mark_fired(self, due: DueWait, at: datetime) -> None:
        if due.kind == "approval":
            if self.approvals[due.ref]["status"] == "pending":
                self.approvals[due.ref].update(status="timeout", decided_at=at)  # như SQL (4c A11)
            return
        for w in self.waits:
            if (w["ticket_id"], w["kind"], w["created_turn"]) == (due.ticket_id, due.kind, due.ref):
                w["fired_at"] = w["fired_at"] or at


class MemoryApprovals:
    """Port approvals giả, ghi vào cùng bảng `approvals` giả mà worker đọc hạn. `lock_row` khoá
    theo phiếu như `SELECT … FOR UPDATE` (giữ suốt khối `async with`). Phase 4 4b (TQ-6): `users` (bảng `users` giả) có thì
    `approver_id`/`backup_approver_id` chưa có dòng → `ValueError` như FK Postgres (M-4b-12 chết ở unit)."""

    def __init__(
        self, deadlines: MemoryDeadlines, *, clock: Clock, users: Mapping[str, Any] | None = None,
        audit: "MemoryAudit | None" = None, tickets: "MemoryTickets | None" = None,
    ) -> None:  # fmt: skip
        self._table = deadlines.approvals
        self._waits = deadlines.waits  # R3: `open_deadline` đọc `wait_deadlines` giả (cùng list worker đọc)
        self._clock = clock
        self._users = users
        self._audit = audit  # 4c P5: `inbox` lấy `intended_action` từ dòng audit B15 `queued` (như SQL)
        self._tickets = tickets  # 4c P5: `inbox` lấy người gửi (như JOIN tickets)
        self.titles: dict[str, str] = {}  # 4c P6: tiêu đề tài liệu quy trình theo doc_id (bảng kb_documents giả)
        self.notified: list[tuple[str, str]] = []  # B15 (`kind="new"`) — giữ 2-tuple như 4b
        self.reminded: list[tuple[str, str, str]] = []  # 4c P3: (approval_id, người nhận, reminder_1|reminder_2)
        self._row_locks: dict[str, asyncio.Lock] = {}
        self.crash_on_create = False  # process "chết" ở lần tạo phiếu kế tiếp (chưa ghi gì)

    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str, *,
        backup_approver_id: str | None, conflict_detected: bool, conflict_type: str | None,
    ) -> str:  # fmt: skip
        if self.crash_on_create:
            self.crash_on_create = False
            raise Crash(f"process chết khi tạo phiếu cho {ticket_id}")
        if self._users is not None:
            for uid in (approver_id, backup_approver_id):
                if uid is not None and uid not in self._users:
                    raise ValueError(f"FK approvals → users: {uid} chưa có dòng users")  # như Postgres
        if conflict_type is not None and conflict_type not in CONFLICT_TYPES:
            raise ValueError(f"CHECK approvals.conflict_type: {conflict_type!r}")  # như Postgres
        approval_id = str(len(self._table) + 1)
        self._table[approval_id] = {"ticket_id": ticket_id, "approver_id": approver_id,
                                    "deadline": deadline, "status": "pending",
                                    "action_plan_hash": action_plan_hash, "backup_approver_id": backup_approver_id,
                                    "conflict_detected": conflict_detected, "conflict_type": conflict_type,
                                    "created_at": self._clock.now()}  # fmt: skip
        return approval_id

    async def notify_approver(self, approval_id: str, approver_id: str, kind: NoticeKind = "new") -> str:
        if kind != "new":
            self.reminded.append((approval_id, approver_id, kind))
            return f"r{len(self.reminded)}"
        self.notified.append((approval_id, approver_id))
        return f"n{len(self.notified)}"

    async def close(
        self, approval_id: str, result: str, at: datetime, *, decided_by: str | None = None,
        note: str | None = None,
    ) -> int:  # fmt: skip
        row = self._table[approval_id]
        if row["status"] != "pending":
            return 0
        if result == "rejected" and note is None:
            raise ValueError("CHECK rejected_needs_note")  # như Postgres
        row.update(status=result, decided_at=at, decided_by=decided_by, note=note)
        return 1

    def _row(self, approval_id: str) -> ApprovalRow | None:
        a = self._table.get(approval_id)
        if a is None:
            return None
        return ApprovalRow(
            approval_id=approval_id, ticket_id=a["ticket_id"], approver_id=a["approver_id"],
            status=a["status"], deadline=a["deadline"], decided_by=a.get("decided_by"),
            note=a.get("note"), first_viewed_at=a.get("first_viewed_at"),
            backup_approver_id=a.get("backup_approver_id"), conflict_detected=bool(a.get("conflict_detected", False)),
            conflict_type=a.get("conflict_type"), created_at=a.get("created_at", a["deadline"]),
            reminder_1_at=a.get("reminder_1_at"), reminder_2_at=a.get("reminder_2_at"), decided_at=a.get("decided_at"),
            action_plan_hash=str(a.get("action_plan_hash", "")),
        )  # fmt: skip

    async def get(self, approval_id: str) -> ApprovalRow | None:
        return self._row(approval_id)

    async def get_status(self, approval_id: str) -> str | None:
        row = self._row(approval_id)
        return None if row is None else row.status

    async def inbox(self, user_id: str, status: str | None, limit: int) -> list[InboxRow]:
        """Như SQL: vai trò lọc ở nguồn (được giao | dự phòng đã nhắc 2), [+ status], mới nhất trước."""
        rows = []
        for aid, a in self._table.items():
            mine = a["approver_id"] == user_id or (a.get("backup_approver_id") == user_id and a.get("reminder_2_at") is not None)
            if not mine or (status is not None and a["status"] != status):
                continue
            queued = [r for r in (self._audit.rows if self._audit else [])
                      if (r["ticket_id"], r["step"], r["event"]) == (a["ticket_id"], "B15", "queued")
                      and r.get("action_plan_hash") == a.get("action_plan_hash")]  # fmt: skip
            ticket = self._tickets.rows.get(a["ticket_id"], {}) if self._tickets else {}
            rows.append(InboxRow(
                approval_id=aid, ticket_id=a["ticket_id"], status=a["status"], created_at=a.get("created_at", a["deadline"]),
                deadline=a["deadline"], reminder_1_at=a.get("reminder_1_at"), reminder_2_at=a.get("reminder_2_at"),
                approver_id=a["approver_id"], backup_approver_id=a.get("backup_approver_id"),
                requester_id=str(ticket.get("requester_id", "")),
                intended_action=queued[-1].get("intended_action") if queued else None,
            ))  # fmt: skip
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]

    async def mark_viewed(self, approval_id: str, now: datetime) -> bool:
        a = self._table.get(approval_id)
        if a is None or a["status"] != "pending" or a.get("first_viewed_at") is not None:
            return False
        a["first_viewed_at"] = now
        return True

    async def procedure_title(self, doc_id: str) -> str | None:
        return self.titles.get(doc_id)

    async def parent_deadline(self, parent_id: str) -> datetime | None:
        """Như SQL: hạn chờ riêng chưa bắn của cha (hạn muộn nhất); không có → min hạn phiếu `pending` của các con; không có → None."""
        own = [w["deadline"] for w in self._waits if w["ticket_id"] == parent_id and w["fired_at"] is None]
        if own:
            return max(own)
        rows = self._tickets.rows if self._tickets is not None else {}
        children = {t for t, r in rows.items() if r["parent_ticket_id"] == parent_id}
        pending = [a["deadline"] for a in self._table.values() if a["ticket_id"] in children and a["status"] == "pending"]
        return min(pending) if pending else None

    async def open_deadline(self, ticket_id: str, kind: OpenWaitKind) -> datetime | None:
        """Như SQL (R3): `approval` → phiếu `pending` mới nhất của ticket; `clarify`/`confirm` → dòng chưa bắn cùng loại, hạn muộn nhất."""
        if kind == "approval":
            pending = [a for a in self._table.values() if a["ticket_id"] == ticket_id and a["status"] == "pending"]
            return max(pending, key=lambda a: a.get("created_at", a["deadline"]))["deadline"] if pending else None
        waits = [w["deadline"] for w in self._waits if (w["ticket_id"], w["kind"]) == (ticket_id, kind) and w["fired_at"] is None]
        return max(waits) if waits else None

    async def policy_matches(self, ticket_id: str, before: datetime) -> PolicyMatchRow | None:
        """Như SQL (P3 tuần 8): dòng B13/B14 ghi SAU CÙNG (thứ tự ghi = `log_id`) có `created_at <= before`."""
        rows = [r for r in (self._audit.rows if self._audit else [])
                if (r["ticket_id"], r["step"]) == (ticket_id, "B13/B14") and r.get("created_at", before) <= before]  # fmt: skip
        if not rows:
            return None
        last = rows[-1]
        return PolicyMatchRow(all_matched=(last.get("detail") or {}).get("all_matched"), matched_rule_id=last.get("matched_rule_id"))

    async def decision_trail(self, ticket_id: str) -> DecisionTrail:
        """Như SQL (4d P3): dòng `B13/B14 risk_decided` ghi SAU CÙNG (thứ tự ghi = `log_id`) + có `B10 deflected_info_only`."""
        rows = [r for r in (self._audit.rows if self._audit else []) if r["ticket_id"] == ticket_id]
        risk = [r for r in rows if (r["step"], r["event"]) == ("B13/B14", "risk_decided")]
        last = risk[-1] if risk else {}
        return DecisionTrail(
            risk_route=(last.get("detail") or {}).get("route"), risk_policy_decision=last.get("policy_decision"),
            has_risk_decided=bool(risk), deflected=any((r["step"], r["event"]) == ("B10", "deflected_info_only") for r in rows),
        )  # fmt: skip

    async def record_override(self, rec: OverrideRecord) -> bool:
        """Như SQL (4d P4): một dòng `step="OVERRIDE"` vào CHÍNH `MemoryAudit` của harness — không đụng `tickets`."""
        assert self._audit is not None, "MemoryApprovals cần audit (harness nối sẵn)"
        return await self._audit.record_new(rec.audit_row())

    @asynccontextmanager
    async def lock_row(self, approval_id: str) -> AsyncIterator[ApprovalRow | None]:
        lock = self._row_locks.setdefault(approval_id, asyncio.Lock())
        async with lock:
            yield self._row(approval_id)

    def status(self, approval_id: str) -> str:
        return str(self._table[approval_id]["status"])

    def count(self, ticket_id: str) -> int:
        return sum(1 for a in self._table.values() if a["ticket_id"] == ticket_id)


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.crash_once: set[str] = set()  # ticket → process "chết" giữa lúc gửi (chưa gửi được)

    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
        if ticket_id in self.crash_once:
            self.crash_once.discard(ticket_id)
            raise Crash(f"process chết khi gửi tin cho {ticket_id}")
        self.sent.append((ticket_id, text, needs))
        return f"m{len(self.sent)}"

    def count(self, ticket_id: str) -> int:
        return sum(1 for t, _, _ in self.sent if t == ticket_id)


class MemorySecurityEvents:
    """`security_events` giả cho node (3e) — cùng kiểm `check_event` như writer thật; ghi vào transaction của
    `effects.once` giả (MemoryEffects gọi hàm đúng một lần theo khoá)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def record(
        self, event_type: str, *, ticket_id: str | None = None, detail: Mapping[str, Any] | None = None
    ) -> None:
        payload = dict(detail or {})
        check_event(event_type, payload)
        self.rows.append({"event_type": event_type, "ticket_id": ticket_id, "detail": payload})

    def of(self, ticket_id: str, event_type: str = "injection_detected") -> list[dict[str, Any]]:
        return [r for r in self.rows if r["ticket_id"] == ticket_id and r["event_type"] == event_type]


class Crash(BaseException):
    """Mô phỏng process chết giữa chừng: không phải Exception nên boundary E9 không bắt, LangGraph
    không kịp ghi checkpoint của node đang chạy."""


class CountingExecutor:
    """Executor giả cho graph node GIẢ (gate2-kiểu) và test runtime: luôn thành công, đếm lời gọi theo ticket."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.crash_once: set[str] = set()  # ticket sẽ "chết" giữa lần thực thi đầu

    async def execute(self, ticket_id: str, turn_id: str, action: Action) -> ExecutionResult:
        self.calls[ticket_id] += 1
        if ticket_id in self.crash_once:
            self.crash_once.discard(ticket_id)
            raise Crash(f"process chết khi đang thực thi {ticket_id}")
        return ExecutionResult(
            success=True, steps_done=[action.type], failed_step=None, rollback_status="none_needed",
            rollback_details=[], action_plan_hash_matched=None, handoff_note=None,
        )  # fmt: skip


def seed_priority() -> dict[str, tuple[int, str]]:
    """Rank + nhãn E0–E9 đọc từ CHÍNH seed của migration 0001 (nguồn duy nhất, B20 5.1)."""
    path = Path(__file__).resolve().parents[2] / "app/db/alembic/versions/0001_init_22_bang_role_trigger.py"
    spec = importlib.util.spec_from_file_location("_mig_0001", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {r["exit_code"]: (r["rank"], r["label"]) for r in module.EXIT_CODE_PRIORITY}


class MemoryTickets:
    """`tickets` giả: ghi kết quả cuối MỘT lần (`WHERE final_state IS NULL`), trả dòng đang có.
    `fail` tiêm lỗi vào `finalize_once`: Exception (bug → boundary) hoặc `Crash` (process chết, không
    kịp ghi gì); `fail_times` None = mãi mãi."""

    def __init__(self, turns: MemoryTurns) -> None:
        self._turns = turns
        self.rows: dict[str, dict[str, Any]] = {}
        self.fail: BaseException | None = None
        self.fail_times: int | None = None
        self.finalize_calls: Counter[str] = Counter()
        self.security_events: list[dict[str, Any]] = []  # sự kiện ghi cùng `create` (3e)
        # Phase 5 T20b: bảng `child_notices` giả (cột như P7 2.9) — ghi qua `MemoryNoticeStore`, đánh dấu qua `deliver_round`
        self.notices: list[dict[str, Any]] = []
        self.created_children: list[str] = []  # thứ tự `create_child` (đếm "đúng 2 dòng con" — D-18)
        self.approvals_table: dict[str, dict[str, Any]] = {}  # = `MemoryDeadlines.approvals` (harness nối) — `children_progress_rows`
        self.effects: MemoryEffects | None = None  # harness nối — `started_children`, `children_status` đọc dòng `child_submit`
        self.txlog: MemoryTxLog | None = None  # harness nối — `children_status.executed`
        # D-67: chiến lược M5 chụp lúc tạo ticket (test đặt `strategies["t1"] = "rule_only"`); vắng = None → B12 coi là `hybrid`
        self.strategies: dict[str, str | None] = {}
        self.sources: dict[str, str] = {}

    def register(
        self, ticket_id: str, created_at: datetime, *, is_parent: bool = False,
        requester_id: str = REQUESTER, session_id: str | None = SESSION,
        redacted_request: str = "yêu cầu", parent_ticket_id: str | None = None,
        requester_role: str = "employee", requester_dept: str | None = None,
    ) -> None:  # fmt: skip
        self.rows.setdefault(ticket_id, {
            "created_at": created_at, "final": None, "is_parent": is_parent,
            "requester_id": requester_id, "session_id": session_id,
            "redacted_request": redacted_request, "parent_ticket_id": parent_ticket_id,
            "requester_role": requester_role, "requester_dept": requester_dept,
        })  # fmt: skip

    async def create(self, ticket: NewTicket, *, turn_id: str, security_events: NewEvents = ()) -> None:
        """Như SQL: dòng `tickets` + lượt `submit` + `security_events` trong MỘT transaction (lượt lỗi → không
        ticket, không sự kiện)."""
        for event_type, detail in security_events:
            check_event(event_type, detail)
        if ticket.ticket_id in self.rows:
            raise ValueError("PK tickets")
        if turn_id in self._turns.rows:
            raise ValueError("PK turns")
        self.security_events.extend(
            {"event_type": e, "ticket_id": ticket.ticket_id, "user_id": ticket.requester_id, "detail": dict(d)}
            for e, d in security_events
        )
        self.register(
            ticket.ticket_id, ticket.created_at, requester_id=ticket.requester_id,
            session_id=ticket.session_id, redacted_request=ticket.redacted_request,
            requester_role=ticket.requester_role, requester_dept=ticket.requester_dept,
        )  # fmt: skip
        self.strategies[ticket.ticket_id] = ticket.strategy
        self.sources[ticket.ticket_id] = ticket.source
        await self._turns.start(turn_id=turn_id, ticket_id=ticket.ticket_id,
                                session_id=ticket.session_id, event_type="submit",
                                at=ticket.created_at)  # fmt: skip

    async def get(self, ticket_id: str) -> TicketRow | None:
        r = self.rows.get(ticket_id)
        if r is None:
            return None
        final: FinalSummary | None = r["final"]
        return TicketRow(
            ticket_id=ticket_id, requester_id=r["requester_id"], session_id=r["session_id"],
            redacted_request=r["redacted_request"], parent_ticket_id=r["parent_ticket_id"],
            is_parent=r["is_parent"], final_state=final.final_state if final else None,
            exit_code=final.exit_code if final else None,
            close_reason=final.close_reason if final else None, created_at=r["created_at"],
            closed_at=final.closed_at if final else None,
        )  # fmt: skip

    async def list_own(self, requester_id: str, limit: int) -> list[TicketRow]:
        """Như SQL: gốc (`parent_ticket_id IS NULL`) của đúng người gửi, `created_at DESC, ticket_id DESC`, `LIMIT`."""
        own = [t for t, r in self.rows.items() if r["requester_id"] == requester_id and r["parent_ticket_id"] is None]
        own.sort(key=lambda t: (self.rows[t]["created_at"], t), reverse=True)
        return [row for t in own[:limit] if (row := await self.get(t)) is not None]

    async def strategy_of(self, ticket_id: str) -> str | None:
        return self.strategies.get(ticket_id)

    async def created_at(self, ticket_id: str) -> datetime:
        return self.rows[ticket_id]["created_at"]  # type: ignore[no-any-return]

    async def count_turns(self, ticket_id: str) -> int:
        return len(self._turns.of(ticket_id))

    async def finalize_once(self, ticket_id: str, summary: FinalSummary) -> FinalSummary:
        self.finalize_calls[ticket_id] += 1
        if self.fail is not None and (self.fail_times is None or self.fail_times > 0):
            if self.fail_times is not None:
                self.fail_times -= 1
            raise self.fail
        row = self.rows[ticket_id]
        if row["final"] is None:
            row["final"] = summary
        return row["final"]  # type: ignore[no-any-return]

    def final(self, ticket_id: str) -> FinalSummary | None:
        return self.rows[ticket_id]["final"]  # type: ignore[no-any-return]

    # ---- Phase 5 T20b (P3, P7) — cùng ngữ nghĩa `SqlTicketStore` ----------------------------------------------------------

    async def create_child(
        self, child_id: str, *, parent_id: str, redacted_request: str, created_at: datetime, intents: int, intent_type: str
    ) -> str:
        """Như SQL `INSERT … SELECT` từ dòng cha: chép người gửi/phiên; trùng khoá → `ValueError` (PK); KHÔNG dòng `turns`. Trả
        `child_ref` (Q-T20b-12)."""
        if child_id in self.rows:
            raise ValueError("PK tickets")
        parent = self.rows[parent_id]
        self.register(
            child_id, created_at, requester_id=parent["requester_id"], session_id=parent["session_id"],
            redacted_request=redacted_request, parent_ticket_id=parent_id, requester_role=parent["requester_role"],
            requester_dept=parent["requester_dept"],
        )  # fmt: skip
        self.strategies[child_id] = self.strategies.get(parent_id)  # D-67: con kế thừa từ cha
        self.sources[child_id] = self.sources.get(parent_id, "real")
        self.created_children.append(child_id)
        return child_ref(child_id, intents, intent_type)

    async def mark_parent_once(self, ticket_id: str) -> bool:
        row = self.rows[ticket_id]
        if row["is_parent"]:
            return False
        row["is_parent"] = True
        return True

    async def children_view(
        self, parent_id: str, children: Sequence[str], *, delivered_round: int | None = None
    ) -> list[ChildView]:
        """Như SQL: notice chưa gửi, cũ → mới; `delivered_round=n` → CHỈ notice đã gửi ở vòng `n`."""
        out = []
        for cid in children:
            final: FinalSummary | None = self.rows[cid]["final"] if cid in self.rows else None
            pending = tuple(
                Notice(n["notice_id"], cid, n["source_step"], n["kind"], n["needs"], n["body"], n["created_at"])
                for n in self.notices
                if n["child_ticket_id"] == cid and n["parent_ticket_id"] == parent_id
                and (n["delivered_at"] is None if delivered_round is None else n["delivered_round"] == delivered_round)
            )  # fmt: skip
            running = any(t["ended_at"] is None for t in self._turns.of(cid))  # như SQL: còn lượt mở → chưa kết thúc
            out.append(ChildView(cid, child_index(cid), final.final_state if final and not running else None, pending))
        return out

    async def deliver_round(self, parent_id: str, round_no: int, notice_ids: Sequence[int], at: datetime) -> str:
        wanted = set(notice_ids)
        for n in self.notices:
            if n["notice_id"] in wanted and n["parent_ticket_id"] == parent_id and n["delivered_at"] is None:
                n["delivered_round"], n["delivered_at"] = round_no, at
        return f"digest:{parent_id}:{round_no}"

    async def children_progress_rows(self, parent_id: str, children: Sequence[str]) -> list[ChildProgressRow]:
        """Như SQL (P11): phiếu `pending` đọc từ bảng `approvals` giả (`approvals_table`, harness nối)."""
        out = []
        for cid in children:
            final: FinalSummary | None = self.rows[cid]["final"]
            pending = any(a["ticket_id"] == cid and a["status"] == "pending" for a in self.approvals_table.values())
            ready = any(n["child_ticket_id"] == cid and n["parent_ticket_id"] == parent_id and n["delivered_at"] is None
                        and n["needs"] != "none" for n in self.notices)  # fmt: skip
            out.append(ChildProgressRow(cid, final.final_state if final else None, pending, ready))
        return out

    def notices_of(self, child_id: str) -> list[dict[str, Any]]:
        return [n for n in self.notices if n["child_ticket_id"] == child_id]

    async def started_children(self, parent_id: str) -> frozenset[str]:
        """Như SQL: `result_ref` `started:<con>` của các dòng `child_submit` của cha (mọi lượt)."""
        assert self.effects is not None
        return frozenset(e["result_ref"].removeprefix("started:") for e in self.effects.rows.values()
                         if e["ticket_id"] == parent_id and e["kind"] == "child_submit")  # fmt: skip

    async def children_status(self, parent_id: str) -> list[ChildHandoffRow]:
        """Như SQL `_HANDOFF_ROWS` (Q-T20b-9 (i)): mọi dòng có `parent_ticket_id = parent_id`, theo `index`."""
        assert self.txlog is not None
        started = await self.started_children(parent_id)
        out = []
        for cid in sorted((t for t, r in self.rows.items() if r["parent_ticket_id"] == parent_id), key=child_index):
            final: FinalSummary | None = self.rows[cid]["final"]
            asking = sorted((n for n in self.notices if n["child_ticket_id"] == cid and n["needs"] != "none"),
                            key=lambda n: (n["created_at"], n["notice_id"]))  # fmt: skip
            out.append(ChildHandoffRow(
                cid, cid in started, final.final_state if final else None, any(r["ticket_id"] == cid for r in self.txlog.rows),
                any(a["ticket_id"] == cid and a["status"] == "pending" for a in self.approvals_table.values()),
                asking[-1]["needs"] if asking else None,
            ))  # fmt: skip
        return out


class MemoryNoticeStore:
    """`child_notices` giả cho `ChildAwareNotifier` (cùng hợp đồng `db.notices.SqlNoticeStore`): `effect_key` UNIQUE (lần thứ hai trả
    id cũ, không thêm dòng); CHECK `kind`/`needs` như Postgres."""

    def __init__(self, tickets: MemoryTickets, clock: Clock) -> None:
        self._tickets = tickets
        self._clock = clock

    async def parent_of(self, ticket_id: str) -> str | None:
        row = self._tickets.rows.get(ticket_id)
        return None if row is None else row["parent_ticket_id"]

    async def insert(
        self, *, parent_id: str, child_id: str, source_step: str, kind: str, needs: str, body: str, effect_key: str
    ) -> int:
        if kind not in NOTICE_KINDS or needs not in NOTICE_NEEDS:
            raise ValueError(f"CHECK child_notices: kind={kind!r} needs={needs!r}")  # như Postgres
        for n in self._tickets.notices:
            if n["effect_key"] == effect_key:
                return int(n["notice_id"])
        notice_id = len(self._tickets.notices) + 1
        self._tickets.notices.append({
            "notice_id": notice_id, "parent_ticket_id": parent_id, "child_ticket_id": child_id, "source_step": source_step,
            "kind": kind, "needs": needs, "body": body, "effect_key": effect_key, "created_at": self._clock.now(),
            "delivered_round": None, "delivered_at": None,
        })  # fmt: skip
        return notice_id


class MemoryEscalations:
    def __init__(self, tickets: MemoryTickets, audit: "MemoryAudit | None" = None) -> None:
        self._tickets = tickets
        self._audit = audit
        self._priority = seed_priority()
        self.rows: list[dict[str, Any]] = []

    async def create(
        self, *, ticket_id: str, exit_code: str, reason_detail: str | None,
        handoff_note: Mapping[str, Any], is_deny_case: bool, created_at: datetime,
    ) -> str:  # fmt: skip
        rank, _ = self._priority[exit_code]
        self.rows.append({"escalation_id": len(self.rows) + 1, "ticket_id": ticket_id,
                          "exit_code": exit_code, "priority": rank, "reason_detail": reason_detail,
                          "handoff_note": dict(handoff_note), "is_deny_case": is_deny_case,
                          "created_at": created_at, "closed_at": None, "assigned_to": None})  # fmt: skip
        return str(len(self.rows))

    def of(self, ticket_id: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["ticket_id"] == ticket_id]

    def _leaf_or_failed_parent(self, ticket_id: str) -> bool:
        """Như SQL (T20b Q-T20b-5 (ii)): `is_parent = false OR tickets.exit_code IS NOT NULL`."""
        row = self._tickets.rows.get(ticket_id, {})
        final: FinalSummary | None = row.get("final")
        return not row.get("is_parent") or (final is not None and final.exit_code is not None)

    def _item(self, r: dict[str, Any]) -> QueueItem:
        return QueueItem(
            escalation_id=r["escalation_id"], ticket_id=r["ticket_id"], exit_code=r["exit_code"],
            priority=r["priority"], label=self._priority[r["exit_code"]][1],
            reason_detail=r["reason_detail"], is_deny_case=r["is_deny_case"],
            handoff_note=r["handoff_note"], assigned_to=None, created_at=r["created_at"],
            closed_at=r["closed_at"], close_result=r.get("close_result"), closed_by=r.get("closed_by"),
            close_note=r.get("close_note"),
        )  # fmt: skip

    @staticmethod
    def _order(r: dict[str, Any]) -> tuple[int, datetime, int]:
        return r["priority"], r["created_at"], r["escalation_id"]

    async def list_open(self, limit: int) -> list[QueueItem]:
        rows = [r for r in self.rows if r["closed_at"] is None and self._leaf_or_failed_parent(r["ticket_id"])]
        rows.sort(key=self._order)
        return [self._item(r) for r in rows[:limit]]

    async def list_page(self, status: QueueStatus, limit: int, after: QueueKey | None) -> list[QueueItem]:
        """Như SQL (P4 tuần 8): `open` | `closed`, thứ tự `priority, created_at, escalation_id`, keyset SAU `after`."""
        rows = [r for r in self.rows
                if (r["closed_at"] is None) == (status == "open") and self._leaf_or_failed_parent(r["ticket_id"])]  # fmt: skip
        rows.sort(key=self._order)
        if after is not None:
            rows = [r for r in rows if self._order(r) > (after.priority, after.created_at, after.escalation_id)]
        return [self._item(r) for r in rows[:limit]]

    async def get(self, escalation_id: int) -> EscalationHead | None:
        r = next((r for r in self.rows if r["escalation_id"] == escalation_id), None)
        return None if r is None else EscalationHead(
            escalation_id=r["escalation_id"], ticket_id=r["ticket_id"], exit_code=r["exit_code"],
            is_deny_case=r["is_deny_case"], closed_at=r["closed_at"],
        )  # fmt: skip

    async def close(self, req: CloseRequest, *, reopen: ReopenHook | None = None) -> ClosedEscalation | None:
        """Như SQL: đóng nếu còn mở (không `await` giữa kiểm và ghi → hai lần đóng: một thắng); `tickets.close_reason` chỉ khi
        `S_ESCALATED` và còn NULL; một dòng audit `B20`/`escalation_closed` vào `MemoryAudit` (nếu có). Móc `reopen` cần
        transaction SQL — bản giả không hỗ trợ."""
        assert reopen is None, "MemoryEscalations: móc reopen chỉ có ở SqlEscalationStore"
        r = next((r for r in self.rows if r["escalation_id"] == req.escalation_id), None)
        if r is None or r["closed_at"] is not None:
            return None
        r.update(closed_at=req.at, close_result=req.close_result, closed_by=req.closed_by, close_note=req.close_note)
        ticket = self._tickets.rows.get(r["ticket_id"], {})
        final: FinalSummary | None = ticket.get("final")
        if final is not None and final.close_reason is None and final.final_state == S_ESCALATED:
            final = ticket["final"] = replace(final, close_reason=req.close_reason)
        if self._audit is not None:
            await self._audit.record(close_audit_row(req, r["ticket_id"]))
        return ClosedEscalation(
            escalation_id=r["escalation_id"], ticket_id=r["ticket_id"], close_result=req.close_result,
            close_reason=final.close_reason if final is not None else None, closed_at=req.at, closed_by=req.closed_by,
            close_note=req.close_note, new_ticket_id=None,
        )  # fmt: skip


class MemoryTicketLock:
    def __init__(self, timeout: float = 5.0) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._timeout = timeout

    @asynccontextmanager
    async def hold(self, ticket_id: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(ticket_id, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), self._timeout)
        except TimeoutError as exc:
            raise TicketBusy(ticket_id) from exc
        try:
            yield
        finally:
            lock.release()


_DEFAULT_SETTINGS = Settings(_env_file=None)  # type: ignore[call-arg]


@dataclass
class GraphHarness:
    """Toàn bộ runtime trên bản giả. Trường `saver`, store… giữ nguyên qua `restart()`."""

    clock: FakeClock = field(default_factory=FakeClock)
    scenario: FakeScenario = field(default_factory=FakeScenario)
    can_execute: bool = True
    rediagnose_on_new_slot: bool = False
    recursion_limit: int = 60
    nodes: Literal["fake", "real"] = "fake"  # "real": node thật đã có (b02 — 3e, b08 — 3c) đè lên node giả
    concurrency: int = 8
    lock_timeout: float = 5.0
    saver: InMemorySaver = field(default_factory=lambda: InMemorySaver(serde=make_serde()))
    audit: MemoryAudit = field(default_factory=MemoryAudit)
    effects: MemoryEffects = field(default_factory=MemoryEffects)
    spans: MemorySpans = field(default_factory=MemorySpans)
    turns: MemoryTurns = field(default_factory=MemoryTurns)
    deadlines: MemoryDeadlines = field(default_factory=MemoryDeadlines)
    notifier: RecordingNotifier = field(default_factory=RecordingNotifier)
    executor: CountingExecutor = field(default_factory=CountingExecutor)
    txlog: MemoryTxLog = field(default_factory=MemoryTxLog)  # B17 bước 0 (NGHI-2) — test đặt `begun` qua đây
    # B1 thật: phiên `s1` của `nv-fake` còn sống, AD có `nv-fake` (employee)
    identity: MemoryIdentity = field(default_factory=MemoryIdentity)
    ad: FakeAd = field(default_factory=lambda: FakeAd(ad_user()))
    alerts: MemoryAlerts = field(default_factory=MemoryAlerts)
    directory: ToolCaller | None = None  # None = registry thật trên `FakeAd` + `vpn`; e2e gắn registry tới mock
    vpn: SeedVpn | None = None  # B6 thật (3f): VPN giả đọc mock_services/seed.json — None = dựng theo `clock`
    enable_proactive_diagnosis: bool = True  # ablation RQ3 (B6)
    grounding_gate_actions: bool = False  # Phase 4 S0-P11: ablation B9 cho nhánh hành động
    max_recover_attempts: int = 3
    # Hạn cho cả lượt (9.0): mặc định = Settings (100 s / 2 s) — test FakeClock tua quá hạn trong một lượt sẽ ra E2
    turn_budget_s: float = field(default_factory=lambda: _DEFAULT_SETTINGS.turn_budget_s)
    safety_margin_s: float = field(default_factory=lambda: _DEFAULT_SETTINGS.safety_margin_s)
    approver_id: str | None = "l1-fake"  # B15 giả (FAKE_APPROVER_ID)
    ml: FakeMlService = field(default_factory=FakeMlService)  # ml-service giả (3a), đếm ở nơi nhận
    rag: FakeRag = field(default_factory=FakeRag)  # RAG giả (3c) — b08 thật dùng khi `nodes="real"`
    # LLM gateway THẬT + ScriptedLLM rỗng (3d): node gọi LLM mà test chưa cấp kịch bản → ScriptExhausted → E9
    llm: LlmPort = field(default_factory=lambda: make_gateway().client)
    security_events: "MemorySecurityEvents" = field(default_factory=lambda: MemorySecurityEvents())
    # Phase 4 4b (TQ-6): bảng `users` giả — None = harness tự dựng. Roster = `config/approvers.yaml`. `approver_users` None =
    # `AuthApproverUsers(AdUserSync(auth_store))` THẬT; test Q-4b-5 truyền `AuthApproverUsers(None)`.
    auth_store: InMemoryAuthStore | None = None
    approvers: Mapping[str, Roster] = field(default_factory=lambda: open_approvers(_DEFAULT_SETTINGS).root)
    approver_users: ApproverUsers | None = None
    roster_in_ad: bool = True  # gộp `ROSTER_CHAIN` (seed.json) vào `ad` — chỉ khi `directory` None
    tickets: MemoryTickets = field(init=False)
    notices: "MemoryNoticeStore" = field(init=False)  # Phase 5 T20b: `child_notices` giả (ghi vào `tickets.notices`)
    escalations: MemoryEscalations = field(init=False)
    approvals: MemoryApprovals = field(init=False)
    lock: MemoryTicketLock = field(init=False)
    runner: Runner = field(init=False)

    def __post_init__(self) -> None:
        if self.vpn is None:
            self.vpn = SeedVpn(self.clock)
        if self.roster_in_ad and self.directory is None:
            self.ad.add(*seed_ad_records(self.clock.now(), ROSTER_CHAIN))
        if self.auth_store is None:
            self.auth_store = InMemoryAuthStore(RecordingSink(self.clock))
        if self.approver_id is not None and self.approver_id not in self.auth_store.users:
            self.auth_store.users[self.approver_id] = UserRecord(
                user_id=self.approver_id, username=self.approver_id, full_name=None, role="l1", department="it",
                manager_id=None, employment_status="active", hired_at=None, is_privileged_account=False,
            )  # người duyệt GIẢ của B15 giả (như `graph_pg` gieo `l1-fake`) — FK phiếu
        if self.approver_users is None:
            self.approver_users = AuthApproverUsers(AdUserSync(
                store=self.auth_store, sink=self.auth_store.sink, username_key=HARNESS_USERNAME_KEY,
                lock=lock_policy(auth_config(_DEFAULT_SETTINGS, get_policy().constants)),
            ))  # fmt: skip
        self.tickets = MemoryTickets(self.turns)
        self.deadlines.tickets = self.tickets  # Phase 5 T20b: con không đặt hạn, cha thay hạn mọi loại (Q-T20b-3)
        self.tickets.approvals_table = self.deadlines.approvals
        self.deadlines.effects = self.effects
        self.tickets.effects, self.tickets.txlog = self.effects, self.txlog
        self.notices = MemoryNoticeStore(self.tickets, self.clock)
        self.approvals = MemoryApprovals(self.deadlines, clock=self.clock, users=self.auth_store.users,
                                         audit=self.audit, tickets=self.tickets)  # fmt: skip
        self.escalations = MemoryEscalations(self.tickets)
        self.lock = MemoryTicketLock(self.lock_timeout)
        if isinstance(self.identity, MemoryIdentity):
            self.identity.add_session(
                SESSION, REQUESTER, expires_at=self.clock.now() + timedelta(days=365)
            )
        self.runner = self._make_runner()

    def deps(self) -> NodeDeps:
        """Mỗi lần gọi = một "process": registry (và breaker) mới, như khởi động lại backend."""
        assert self.approver_users is not None  # __post_init__ dựng
        return NodeDeps(
            # Phase 5 T20b (TQ-13): như wiring — con → `child_notices`; ticket thường/cha → `self.notifier` (RecordingNotifier) như cũ
            notifier=ChildAwareNotifier(self.notices, self.notifier), approvals=self.approvals, executor=self.executor,
            txlog=self.txlog,
            deadlines=self.deadlines, constants=get_policy().constants,
            identity=self.identity,
            directory=self.directory or fake_directory(self.ad, self.clock, self.vpn.handlers() if self.vpn else None),
            alerts=self.alerts, lockout=LOCKOUT, tickets=self.tickets,
            escalations=self.escalations, templates=get_escalation_templates(), ml=self.ml.client(self.clock),
            rag=self.rag, llm=self.llm, scenario=self.scenario, approver_id=self.approver_id,
            security_events=self.security_events, enable_proactive_diagnosis=self.enable_proactive_diagnosis,
            grounding_gate_actions=self.grounding_gate_actions, approvers=self.approvers,
            approver_users=self.approver_users,
        )  # fmt: skip

    def _make_runner(self) -> Runner:
        return Runner(
            build_graph((real_nodes if self.nodes == "real" else fake_nodes)(self.deps()), self.saver),
            lock=self.lock, turns=self.turns,
            audit=self.audit, effects=self.effects, spans=self.spans, clock=self.clock,
            turn_budget_s=self.turn_budget_s, safety_margin_s=self.safety_margin_s,
            concurrency=self.concurrency, can_execute=self.can_execute,
            rediagnose_on_new_slot=self.rediagnose_on_new_slot,
            recursion_limit=self.recursion_limit, max_recover_attempts=self.max_recover_attempts,
            tickets=self.tickets, txlog=self.txlog,
        )  # fmt: skip

    def restart(self, *, can_execute: bool | None = None) -> Runner:
        """Graph + runner mới (process mới) trên cùng checkpoint và cùng DB giả."""
        if can_execute is not None:
            self.can_execute = can_execute
        self.lock = MemoryTicketLock(self.lock_timeout)
        self.runner = self._make_runner()
        return self.runner

    async def submit(self, ticket_id: str, **plan: str | list[str]) -> Any:
        if plan:
            self.scenario.plan(ticket_id, **plan)
        return await self.submit_as(ticket_id, SESSION)

    async def submit_as(
        self, ticket_id: str, session_id: str | None, text: str = "yêu cầu",
        parent_ticket_id: str | None = None,
    ) -> Any:  # fmt: skip
        """Như API (2b-3): có dòng `tickets` trước, rồi mới submit graph."""
        self.tickets.register(ticket_id, self.clock.now())
        return await self.runner.submit(
            ticket_id, session_id=session_id, redacted_request=text,
            parent_ticket_id=parent_ticket_id,
        )  # fmt: skip

