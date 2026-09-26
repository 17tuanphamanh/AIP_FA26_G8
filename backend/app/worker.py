"""Entrypoint worker: `python -m app.worker`. Cùng image với backend (01 mục 1.3, T01 mục 5).

Job (P1 mục 7): quét hạn chờ mỗi 15 giây, quét lượt dở dang mỗi 60 giây (và một lần lúc khởi động).
Heartbeat (`app/heartbeat.py`) ghi file mỗi 10 giây bằng CHÍNH scheduler đó — healthcheck compose đọc
file, quá 60 giây = unhealthy.
Worker KHÔNG có SVC_EXECUTOR_TOKEN (D-03): runner dựng với `can_execute=False` — recover không bao giờ
chạy B17, chuyển E7 "thực thi bị gián đoạn".
"""

import asyncio
import logging
import signal
from datetime import timedelta
from typing import Any, Protocol

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import heartbeat
from app.core.clock import Clock, SystemClock
from app.core.logging import configure_logging
from app.db.session import create_engines
from app.graph.wiring import open_runtime
from app.graph.worker_jobs import WorkerJobs
from app.settings import Settings, get_settings

log = logging.getLogger("app.worker")

HEARTBEAT_JOB = "heartbeat"


class Jobs(Protocol):
    async def scan_deadlines(self) -> Any: ...
    async def scan_stale_turns(self) -> Any: ...


def schedule_jobs(scheduler: AsyncIOScheduler, jobs: Jobs, settings: Settings, clock: Clock) -> None:
    async def beat() -> None:
        heartbeat.write(settings.worker_heartbeat_path, clock.now())

    common: dict[str, Any] = {"trigger": "interval", "max_instances": 1, "coalesce": True}
    scheduler.add_job(beat, id=HEARTBEAT_JOB, seconds=settings.worker_heartbeat_seconds, **common)
    scheduler.add_job(
        jobs.scan_deadlines, id="scan_deadlines", seconds=settings.worker_deadline_scan_seconds,
        **common,
    )  # fmt: skip
    scheduler.add_job(
        jobs.scan_stale_turns, id="scan_stale_turns",
        seconds=settings.worker_recover_scan_seconds, **common,
    )  # fmt: skip


async def run() -> None:
    settings = get_settings()
    clock = SystemClock()
    engines = create_engines(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with open_runtime(settings, engines, clock, can_execute=False) as rt:
            jobs = WorkerJobs(
                rt.runner, rt.deadlines, rt.turns,
                stale_after=timedelta(seconds=settings.worker_stale_turn_seconds),
                batch=settings.worker_batch,
            )  # fmt: skip
            scheduler = AsyncIOScheduler(timezone="UTC")
            schedule_jobs(scheduler, jobs, settings, clock)
            scheduler.start()
            heartbeat.write(settings.worker_heartbeat_path, clock.now())
            log.info("worker khởi động")
            await jobs.scan_stale_turns()  # phục hồi ngay lượt dở dang từ lần chết trước
            await stop.wait()
            scheduler.shutdown(wait=False)
    finally:
        await engines.dispose()
    log.info("worker dừng")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run())
