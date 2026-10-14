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

- Vòng cha (Phase 5 T20b P12) cũng chạy Ở CUỐI `scan_deadlines` (tối đa mỗi `PARENT_RECONCILE_INTERVAL` giây). Q-T20b-10 = A: mỗi lượt
  tối đa `PARENT_SCAN_MAX` cha + `PARENT_SCAN_MAX` con mồ côi, ngân sách `PARENT_SCAN_BUDGET_S` cho MỖI bước (con mồ côi chạy TRƯỚC —
  cha chậm không bỏ đói bước giao timeout): truy vấn đọc bọc `asyncio.timeout`;
  lượt graph (đánh thức cha / giao timeout) KHÔNG bị huỷ giữa chừng (huỷ giữa lượt để lại lượt mở + effect dở) — hết ngân sách thì
  không bắt đầu mục mới (`deferred`), chu kỳ sau làm tiếp.

Mỗi mục bọc try/except riêng: một ticket lỗi không chặn ticket khác, worker không sập.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.approval.store import NoticeKind, log_approver_notice
from app.domain.approval import next_reminder
from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL
from app.graph.late_event import LateEvent, TicketNotFound, deliver_event
from app.graph.ports import (
    DeadlineStore,
    DueReminder,
    DueWait,
    OrphanChild,
    TicketBusy,
    TurnStore,
)
from app.graph.runner import Runner
from app.settings import get_policy

log = logging.getLogger(__name__)

_EXPECTED = {"clarify": S_CLARIFYING, "confirm": S_CONFIRMING, "approval": S_PENDING_APPROVAL}

type ApproverNotice = Callable[[str, str, NoticeKind], Awaitable[str]]  # (approval_id, user_id, kind) → result_ref


def expected_status(due: DueWait) -> str:
    # Ticket cha chờ người dùng ở parent_reply_wait (S_CONFIRMING) cho cả hạn 24 giờ lẫn 48 giờ (D-31).
    return S_CONFIRMING if due.is_parent else _EXPECTED[due.kind]


PARENT_RECONCILE_INTERVAL = 60  # giây — Phase 5 T20b P12: lưới an toàn của vòng cha (B03 §7, hằng code, không biến .env)
PARENT_SCAN_MAX = 20  # Q-T20b-10 = A: số cha (và số con mồ côi) tối đa mỗi lượt quét vòng cha
PARENT_SCAN_BUDGET_S = 5.0  # Q-T20b-10 = A: ngân sách MỖI BƯỚC của lượt quét vòng cha (2 bước ≈ 10 s < chu kỳ 15 s)


@dataclass
class ParentScanReport:
    """Phase 5 T20b P12: `woken` = lời gọi `wake_parent` đã chạy (kể cả no-op); `timeouts` = con mồ côi đã nhận `timeout`."""

    woken: int = 0
    timeouts: int = 0
    late: int = 0
    busy: int = 0
    failed: int = 0
    deferred: int = 0  # Q-T20b-10: mục chưa làm vì hết ngân sách lượt quét — chu kỳ sau


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
        wait_hours: tuple[int, int] | None = None,
        parent_scan_max: int = PARENT_SCAN_MAX,
        parent_scan_budget_s: float = PARENT_SCAN_BUDGET_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runner = runner
        self._deadlines = deadlines
        self._turns = turns
        self._stale_after = stale_after
        self._batch = batch
        self._notify_approver = notify_approver
        self._next_parent_scan: datetime | None = None  # T20b P12: lần quét vòng cha kế tiếp
        self._wait_hours = wait_hours  # (hỏi lại, xác nhận) — None: `policy.json` (CLARIFY/CONFIRM_TIMEOUT_HOURS), Q-T20b-9 (ii)
        self._parent_max = parent_scan_max
        self._parent_budget_s = parent_scan_budget_s
        self._monotonic = monotonic

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
        await self._maybe_scan_parents()
        return report

    async def _maybe_scan_parents(self) -> None:
        """T20b P12: lưới vòng cha chạy Ở CUỐI `scan_deadlines` (khuôn nhắc duyệt 4c — không đăng ký job mới: `worker.py` và test M9 ghim
        tập job lõi), tối đa mỗi `PARENT_RECONCILE_INTERVAL` giây theo đồng hồ của runner; lỗi bắt riêng (không làm hỏng phần quét hạn)."""
        now = self._runner.clock.now()
        if self._next_parent_scan is not None and now < self._next_parent_scan:
            return
        self._next_parent_scan = now + timedelta(seconds=PARENT_RECONCILE_INTERVAL)
        try:
            await self.scan_parents()
        except Exception:
            log.exception("quét vòng cha lỗi")

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

    async def scan_parents(self) -> ParentScanReport:
        """Phase 5 T20b P12 (mỗi `PARENT_RECONCILE_INTERVAL` giây), HAI bước, mỗi bước ngân sách RIÊNG `PARENT_SCAN_BUDGET_S` (một cha
        đánh thức chậm không bỏ đói bước kia — soát lượt 4 NGHI (b)): (b) TRƯỚC — `deadlines.orphan_children` (chỉ con đã quá hạn thường,
        Q-T20b-9 (ii)) → `deliver_event(con, S_CLARIFYING|S_CONFIRMING theo needs, {"kind": "timeout"}, source="worker")` — con không treo
        vì cha lỗi (P1 §8.2); (a) SAU — `deadlines.parents_to_wake` → `runner.wake_parent` (no-op nếu cha không ở `parent_wait`). Mỗi mục
        try/except riêng (một ticket lỗi không chặn ticket khác); truy vấn đọc quá ngân sách → bước đó bỏ (`failed`), bước kia vẫn chạy.
        Chỉ đọc DB (worker không đọc checkpoint)."""
        report = ParentScanReport()
        clarify_h, confirm_h = self._wait_hours or _policy_wait_hours()
        now = self._runner.clock.now()
        await self._budgeted(
            "con mồ côi", report,
            lambda: self._deadlines.orphan_children(now, self._parent_max, clarify_hours=clarify_h, confirm_hours=confirm_h),
            self._timeout_orphan,
        )  # fmt: skip
        await self._budgeted("cha cần đánh thức", report, lambda: self._deadlines.parents_to_wake(self._parent_max), self._wake)
        return report

    async def _budgeted[T](
        self, what: str, report: ParentScanReport, read: Callable[[], Awaitable[list[T]]],
        handle: Callable[[T, ParentScanReport], Awaitable[None]],
    ) -> None:  # fmt: skip
        """Một bước của `scan_parents` với ngân sách riêng: truy vấn đọc bọc `asyncio.timeout` (huỷ an toàn); lượt graph KHÔNG bị huỷ giữa
        chừng — hết ngân sách thì không bắt đầu mục mới (`deferred`), chu kỳ sau làm tiếp (Q-T20b-10 = A)."""
        stop_at = self._monotonic() + self._parent_budget_s
        try:
            async with asyncio.timeout(self._parent_budget_s):
                items = await read()
        except TimeoutError:
            log.warning("quét vòng cha: đọc %s quá %.0f s — bỏ bước này ở chu kỳ này", what, self._parent_budget_s)
            report.failed += 1
            return
        for n, item in enumerate(items):
            if self._monotonic() >= stop_at:
                report.deferred += len(items) - n
                return
            await handle(item, report)

    async def _timeout_orphan(self, orphan: OrphanChild, report: ParentScanReport) -> None:
        waiting = S_CLARIFYING if orphan.needs == "answer" else S_CONFIRMING
        try:
            await deliver_event(self._runner, orphan.ticket_id, waiting, {"kind": "timeout"}, source="worker")
            report.timeouts += 1
        except (LateEvent, TicketNotFound):
            report.late += 1
        except TicketBusy:
            report.busy += 1
        except Exception:
            log.exception("giao timeout cho ticket con %s lỗi", orphan.ticket_id)
            report.failed += 1

    async def _wake(self, parent_id: str, report: ParentScanReport) -> None:
        try:
            await self._runner.wake_parent(parent_id)
            report.woken += 1
        except TicketBusy:
            report.busy += 1
        except Exception:
            log.exception("đánh thức ticket cha %s lỗi", parent_id)
            report.failed += 1

def _policy_wait_hours() -> tuple[int, int]:
    c = get_policy().constants
    return c.CLARIFY_TIMEOUT_HOURS, c.CONFIRM_TIMEOUT_HOURS
