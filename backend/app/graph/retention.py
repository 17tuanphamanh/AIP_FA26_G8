"""Job hạn giữ của worker (M2 bn-a; P7 mục 4 [Chốt 17.2]; huong-dan 17.2 "hội thoại và checkpoint giữ 90 ngày").

Một lượt (`RetentionJob.run`):
1. Mốc từ đồng hồ TIÊM: ticket `now − retention_days`, phiên `now − session_grace_days`, hạn chờ `now − wait_grace_days`.
2. `store.expired_threads(mốc, batch)` — điều kiện "đã kết thúc, quá hạn" nằm ở SQL (`db/retention.py`).
3. `dry_run` (mặc định, `config/retention.yaml`): CHỈ đếm — không gọi hàm xoá nào.
   Xoá thật, từng ticket: `store.purge_ticket_rows` (side_effects, child_notices) TRƯỚC, rồi `saver.adelete_thread` (API của
   `AsyncPostgresSaver` — không DELETE tay bảng checkpoint). Thứ tự này để lỗi giữa chừng không bỏ sót: thread còn → lượt sau chọn lại
   ticket và làm lại (xoá dòng phụ lặp lại vô hại). Lỗi một ticket → bỏ qua, `errors` + 1, đi tiếp (log tên lớp, không ticket_id).
   Rồi xoá phiên hết hạn và hạn chờ đã bắn.
4. ĐÚNG MỘT `store.record_run(detail, at=now)` — kể cả khi lỗi giữa chừng sau bước chọn (`finally`, `errors` + 1, rồi ném lại); lỗi ngay ở
   bước chọn thì chưa làm gì → không ghi. `detail` = {dry_run, threads, sessions, waits, errors, retention_days} — chỉ bool/int.
Không đụng `audit_logs` (append-only; role `app_rw` không có quyền — rào ở DB). Lỗi ngoài từng ticket (DB mất) → log tên lớp, không ném ra
scheduler (job khác của worker chạy tiếp); lượt sau làm lại.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.core.clock import Clock
from app.settings import RetentionConfig

log = logging.getLogger(__name__)


class RetentionStore(Protocol):
    async def expired_threads(self, cutoff: datetime, limit: int) -> list[str]: ...
    async def purge_ticket_rows(self, ticket_id: str) -> None: ...
    async def count_expired_sessions(self, cutoff: datetime) -> int: ...
    async def delete_expired_sessions(self, cutoff: datetime) -> int: ...
    async def count_fired_waits(self, cutoff: datetime) -> int: ...
    async def delete_fired_waits(self, cutoff: datetime) -> int: ...
    async def record_run(self, detail: Mapping[str, Any], *, at: datetime) -> None: ...


class ThreadDeleter(Protocol):
    async def adelete_thread(self, thread_id: str) -> None: ...


@dataclass(frozen=True)
class RetentionReport:
    dry_run: bool
    threads: int
    sessions: int
    waits: int
    errors: int


class RetentionJob:
    def __init__(self, store: RetentionStore, saver: ThreadDeleter, clock: Clock, config: RetentionConfig) -> None:
        self._store = store
        self._saver = saver
        self._clock = clock
        self._config = config

    async def run(self) -> RetentionReport:
        cfg = self._config
        now = self._clock.now()
        ticket_cutoff = now - timedelta(days=cfg.retention_days)
        session_cutoff = now - timedelta(days=cfg.session_grace_days)
        wait_cutoff = now - timedelta(days=cfg.wait_grace_days)
        threads = await self._store.expired_threads(ticket_cutoff, cfg.batch)  # lỗi ở đây: chưa làm gì → không ghi sự kiện
        purged = sessions = waits = errors = 0
        try:
            if cfg.dry_run:
                purged = len(threads)
                sessions = await self._store.count_expired_sessions(session_cutoff)
                waits = await self._store.count_fired_waits(wait_cutoff)
            else:
                for ticket_id in threads:
                    try:
                        await self._store.purge_ticket_rows(ticket_id)
                        await self._saver.adelete_thread(ticket_id)
                    except Exception as exc:  # noqa: BLE001 — một ticket lỗi không chặn ticket khác; lượt sau chọn lại
                        errors += 1
                        log.warning("retention: dọn một ticket lỗi (%s) — lượt sau làm lại", type(exc).__name__)
                    else:
                        purged += 1
                sessions = await self._store.delete_expired_sessions(session_cutoff)
                waits = await self._store.delete_fired_waits(wait_cutoff)
        except Exception:
            errors += 1  # soát M2 5b: lỗi giữa chừng (sau khi đã xoá N thread) vẫn để lại dòng sự kiện với số đã làm
            raise
        finally:
            detail = {"dry_run": cfg.dry_run, "threads": purged, "sessions": sessions, "waits": waits, "errors": errors,
                      "retention_days": cfg.retention_days}  # fmt: skip
            await self._store.record_run(detail, at=now)
            log.info("retention: dry_run=%s threads=%d sessions=%d waits=%d errors=%d", cfg.dry_run, purged, sessions, waits,
                     errors)  # fmt: skip
        return RetentionReport(cfg.dry_run, purged, sessions, waits, errors)

    async def tick(self) -> None:
        """Điểm đăng ký với scheduler: lỗi cả lượt (DB mất…) → log tên lớp, không ném (job khác của worker chạy tiếp)."""
        try:
            await self.run()
        except Exception as exc:  # noqa: BLE001 — job nền
            log.error("retention lỗi: %s", type(exc).__name__)
