"""Job của worker (P1 mục 7): quét hạn chờ, phục hồi lượt dở dang.

- `scan_deadlines` (15 giây): hạn `clarify`/`confirm` (`wait_deadlines`) và hạn duyệt
  (`approvals.deadline`) đã qua → `deliver_event(timeout, source="worker")` — đúng đường của thao tác
  người. Không giữ transaction suốt lượt (khác mã giả `FOR UPDATE SKIP LOCKED` của P1 mục 7 — giữ tx
  trong lúc chạy graph phá D-19; người duyệt 26/09/2026): đọc hạn không khoá → khoá ticket + guard
  chặn giao trùng giữa nhiều worker → đánh dấu `fired_at` trong tx ngắn. Ticket đang bận → để chu kỳ sau.
- `scan_stale_turns` (60 giây + lúc khởi động): `turns.ended_at IS NULL` quá 2 phút → `recover`.

Mỗi mục bọc try/except riêng: một ticket lỗi không chặn ticket khác, worker không sập.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from app.domain.states import S_CLARIFYING, S_CONFIRMING, S_PENDING_APPROVAL
from app.graph.late_event import LateEvent, TicketNotFound, deliver_event
from app.graph.ports import DeadlineStore, DueWait, TicketBusy, TurnStore
from app.graph.runner import Runner

log = logging.getLogger(__name__)

_EXPECTED = {"clarify": S_CLARIFYING, "confirm": S_CONFIRMING, "approval": S_PENDING_APPROVAL}


def expected_status(due: DueWait) -> str:
    # Ticket cha chờ người dùng ở parent_reply_wait (S_CONFIRMING) cho cả hạn 24 giờ lẫn 48 giờ (D-31).
    return S_CONFIRMING if due.is_parent else _EXPECTED[due.kind]


@dataclass
class ScanReport:
    delivered: int = 0
    late: int = 0
    busy: int = 0
    failed: int = 0


class WorkerJobs:
    def __init__(
        self,
        runner: Runner,
        deadlines: DeadlineStore,
        turns: TurnStore,
        *,
        stale_after: timedelta = timedelta(minutes=2),
        batch: int = 200,
    ) -> None:
        self._runner = runner
        self._deadlines = deadlines
        self._turns = turns
        self._stale_after = stale_after
        self._batch = batch

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
        return report

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
