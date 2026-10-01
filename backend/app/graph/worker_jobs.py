"""Job của worker (P1 mục 7): quét hạn chờ, phục hồi lượt dở dang.

- `scan_deadlines` (15 giây): hạn `clarify`/`confirm` (`wait_deadlines`) và hạn duyệt
  (`approvals.deadline`) đã qua → `deliver_event(timeout, source="worker")` — đúng đường của thao tác
  người. Không giữ transaction suốt lượt (khác mã giả `FOR UPDATE SKIP LOCKED` của P1 mục 7 — giữ tx
  trong lúc chạy graph phá D-19; người duyệt 26/09/2026): đọc hạn không khoá → khoá ticket + guard
  chặn giao trùng giữa nhiều worker → đánh dấu `fired_at` trong tx ngắn. Ticket đang bận → để chu kỳ sau.
- `scan_stale_turns` (60 giây + lúc khởi động): `turns.ended_at IS NULL` quá 2 phút → `recover`.
- Nhắc duyệt 50 %/80 % (Phase 4 4c P3) chạy Ở CUỐI `scan_deadlines` (cùng chu kỳ 15 s — không đăng ký job mới, không sửa `worker.py`,
  phase4 mục 0.2), lỗi bắt riêng: không làm hỏng phần quét hạn. Đánh dấu nguyên tử `DeadlineStore.mark_reminder_once` (Q-4c-2 = A) TRƯỚC,
  gửi SAU qua `notify_approver` (mặc định `approval.store.log_approver_notice` — MỘT hàm với B15): hai worker cùng quét → một thông báo.
  Nhắc 1 → người duyệt; nhắc 2 → người duyệt + dự phòng. Qua mốc 2 mà chưa nhắc 1 → chỉ nhắc 2 (câu P3 n=2, rồi n=1 chỉ ghi sổ).

Mỗi mục bọc try/except riêng: một ticket lỗi không chặn ticket khác, worker không sập.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.approval.store import NoticeKind, log_approver_notice
from app.domain.approval import next_reminder
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL
from app.graph.late_event import LateEvent, TicketNotFound, deliver_event
from app.graph.ports import DeadlineStore, DueReminder, DueWait, TicketBusy, TurnStore
from app.graph.runner import Runner

log = logging.getLogger(__name__)

_EXPECTED = {"clarify": S_CLARIFYING, "confirm": S_CONFIRMING, "approval": S_PENDING_APPROVAL}

type ApproverNotice = Callable[[str, str, NoticeKind], Awaitable[str]]  # (approval_id, user_id, kind) → result_ref


def expected_status(due: DueWait) -> str:
    # Ticket cha chờ người dùng ở parent_reply_wait (S_CONFIRMING) cho cả hạn 24 giờ lẫn 48 giờ (D-31).
    return S_CONFIRMING if due.is_parent else _EXPECTED[due.kind]


@dataclass
class ScanReport:
    delivered: int = 0
    late: int = 0
    busy: int = 0
    failed: int = 0
    reminded: int = 0  # 4c P3: số thông báo nhắc đã gửi (mỗi người nhận một)
    reminder_failed: int = 0  # lỗi phần nhắc — KHÔNG cộng vào `failed` (phần quét hạn)


class WorkerJobs:
    def __init__(
        self,
        runner: Runner,
        deadlines: DeadlineStore,
        turns: TurnStore,
        *,
        stale_after: timedelta = timedelta(minutes=2),
        batch: int = 200,
        notify_approver: ApproverNotice = log_approver_notice,
    ) -> None:
        self._runner = runner
        self._deadlines = deadlines
        self._turns = turns
        self._stale_after = stale_after
        self._batch = batch
        self._notify_approver = notify_approver

    async def scan_deadlines(self) -> ScanReport:
        report = ScanReport()
        clock = self._runner.clock
        for due in await self._deadlines.due(clock.now(), self._batch):
            try:
                await deliver_event(
                    self._runner, due.ticket_id, expected_status(due), {"kind": "timeout"},
                    source="worker",
                )  # fmt: skip
                report.delivered += 1
            except (LateEvent, TicketNotFound):
                report.late += 1  # đã chuyển bước (hoặc hạn cũ) — đánh dấu để không bắn lại
            except TicketBusy:
                report.busy += 1
                continue
            except Exception:
                log.exception("giao timeout cho ticket %s lỗi", due.ticket_id)
                report.failed += 1
                continue
            try:
                await self._deadlines.mark_fired(due, clock.now())
            except Exception:
                log.exception("không đánh dấu được hạn đã bắn của ticket %s", due.ticket_id)
        try:
            await self._scan_approval_reminders(report)
        except Exception:
            log.exception("quét nhắc duyệt lỗi")
            report.reminder_failed += 1
        return report

    async def _scan_approval_reminders(self, report: ScanReport) -> None:
        now = self._runner.clock.now()
        for due in await self._deadlines.due_reminders(now, self._batch):
            try:
                report.reminded += await self._remind(due, now)
            except Exception:
                log.exception("nhắc duyệt phiếu %s lỗi", due.approval_id)
                report.reminder_failed += 1

    async def _remind(self, due: DueReminder, now: datetime) -> int:
        n = next_reminder(due.created_at, due.deadline, due.reminder_1_at, due.reminder_2_at, now)
        if n is None:
            return 0
        target = await self._deadlines.mark_reminder_once(due.approval_id, n, now)
        if target is None:  # worker khác đã đặt / phiếu vừa đóng / vừa tới hạn
            return 0
        if n == 2 and due.reminder_1_at is None:  # qua mốc 2 mà chưa nhắc 1: chỉ ghi sổ cột 1, KHÔNG gửi nhắc 1
            await self._deadlines.mark_reminder_once(due.approval_id, 1, now)
        kind: NoticeKind = "reminder_1" if n == 1 else "reminder_2"
        users = [target.approver_id]
        if n == 2 and target.backup_approver_id not in (None, target.approver_id):
            users.append(str(target.backup_approver_id))
        for user_id in users:
            await self._notify_approver(due.approval_id, user_id, kind)
        return len(users)

    async def scan_stale_turns(self) -> int:
        clock = self._runner.clock
        recovered = 0
        for turn in await self._turns.stale(clock.now() - self._stale_after, self._batch):
            try:
                if await self._runner.recover(turn.ticket_id, turn.turn_id) is not None:
                    recovered += 1
            except TicketBusy:
                continue
            except Exception:
                log.exception("recover ticket %s lỗi", turn.ticket_id)
        return recovered
