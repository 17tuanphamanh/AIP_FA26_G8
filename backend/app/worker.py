"""Entrypoint worker: `python -m app.worker`. Cùng image với backend (01 mục 1.3, T01 mục 5).

Phase 1 chỉ khởi động và chờ tín hiệu dừng. Job quét hạn chờ, nhắc duyệt, recover làm ở
Phase 2 (P1 mục 7).
"""

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import configure_logging

log = logging.getLogger("app.worker")


async def run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker khởi động (chưa có job — Phase 2)")
    await stop.wait()
    scheduler.shutdown(wait=False)
    log.info("worker dừng")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run())
