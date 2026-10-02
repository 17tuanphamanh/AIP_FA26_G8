"""Entrypoint worker: `python -m app.worker`. Cùng image với backend (01 mục 1.3, T01 mục 5).

Job (P1 mục 7): quét hạn chờ mỗi 15 giây, quét lượt dở dang mỗi 60 giây (và một lần lúc khởi động).
Heartbeat (`app/heartbeat.py`) ghi file mỗi 10 giây bằng CHÍNH scheduler đó — healthcheck compose đọc
file, quá 60 giây = unhealthy.
Worker KHÔNG có SVC_EXECUTOR_TOKEN (D-03): runner dựng với `can_execute=False` — recover không bao giờ
chạy B17, chuyển E7 "thực thi bị gián đoạn".
M9 (B1): job `monitor_rules_minute` 60 giây chạy luật cảnh báo theo sự kiện — khối `# ---- M9` cuối file.
"""

import asyncio
import logging
import signal
from datetime import datetime, timedelta
from typing import Any, Protocol

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import heartbeat
from app.audit.alerts import AlertWriter  # M9: ghi alerts qua M7, không qua app.monitor
from app.core.clock import Clock, SystemClock
from app.core.logging import configure_logging
from app.db.session import Engines, create_engines
from app.domain.alerts import AlertDraft
from app.graph.wiring import open_runtime
from app.graph.worker_jobs import WorkerJobs
from app.llm.config import load_llm_config
from app.monitor.db import MonitorUnavailable, monitor_engine
from app.monitor.evaluator import evaluate
from app.monitor.queries import rules_data as _rules_data  # noqa: F401
from app.monitor.rules import RuleContext
from app.monitor.window import VN_TZ
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
            setup_monitor_jobs(scheduler, settings, engines, clock)  # M9 — lỗi dựng không làm chết worker
            scheduler.start()
            heartbeat.write(settings.worker_heartbeat_path, clock.now())
            log.info("worker khởi động")
            await jobs.scan_stale_turns()  # phục hồi ngay lượt dở dang từ lần chết trước
            await stop.wait()
            scheduler.shutdown(wait=False)
    finally:
        await engines.dispose()
    log.info("worker dừng")


# ---- M9 (B1, #13): job luật cảnh báo theo sự kiện ----------------------------------------------------------------
#
# Mỗi 60 giây: `evaluate("minute")` trên MỘT connection của engine `app_monitor` (chỉ đọc) → mỗi draft ghi bằng
# `AlertWriter.raise_once` (engine chính, app_rw) — ghi chỉ ở đây, không bao giờ trong `app.monitor` [Chốt 17.9.2].
# Import `rules_data` (đầu file, noqa F401) để đăng ký loader; `spend` đọc ở worker vì `app.monitor` không import
# `app.llm`.
# Không bỏ sót nhờ lookback 24 giờ của từng luật, không trùng nhờ khoá `(rule_id, subject, window_start)`.
# Nhịp log (review #24): dòng tổng `nháp= ghi= trùng= lỗi= luật_lỗi=` — WARNING khi có lỗi ghi hoặc luật lỗi; INFO ở
# lượt chạy được đầu tiên và khi có cảnh báo mới; còn lại DEBUG (`core/logging.py` đã tắt INFO APScheduler vì quá dày).

MONITOR_RULES_MINUTE = "monitor_rules_minute"
MONITOR_RULES_SECONDS = 60
# Trần thời gian MỘT lượt (đọc + ghi), dưới chu kỳ 60 s: truy vấn treo + `max_instances=1` → mọi lượt sau bị bỏ, tầng
# cảnh báo chết im lặng (review #24 mục 2). Hết giờ → `TimeoutError` vào nhánh ERROR như lỗi job khác.
MONITOR_RUN_TIMEOUT_SECONDS = 50.0
# Cùng giá trị với `common` của `schedule_jobs` (biến cục bộ — không sửa hàm đó; test so tham số job M9 với job gốc).
# `misfire_grace_time` để mặc định của APScheduler (nhỏ): lượt bị trễ quá hạn có thể bị bỏ — chấp nhận, lượt sau quét
# lại 24 giờ nên không mất cảnh báo.
MONITOR_JOB_OPTIONS: dict[str, Any] = {"trigger": "interval", "max_instances": 1, "coalesce": True}
MONITOR_REMIND_EVERY = timedelta(hours=1)


class AlertSink(Protocol):
    async def raise_once(self, draft: AlertDraft) -> bool: ...


class IncidentLog:
    """Nhịp log cho sự cố kéo dài của tầng cảnh báo — dùng chung cho thiếu engine monitor (Q-M9-B1-6), job lỗi
    (Q-M9-B1-19) và luật lỗi (review #24, key = tập tên luật lỗi): báo NGAY lần đầu và mỗi khi loại sự cố (`key`) đổi;
    cùng sự cố lặp lại → nhắc mỗi `every`; lượt chạy thành công đầu tiên sau chuỗi lỗi (không luật nào lỗi) → báo phục
    hồi. Log một lần rồi im thì worker chạy lâu không ai thấy cảnh báo đã ngừng (FN cả tầng); log mỗi 60 s thì thành
    nhiễu."""

    def __init__(self, clock: Clock, every: timedelta = MONITOR_REMIND_EVERY) -> None:
        self._clock = clock
        self._every = every
        self._key: object = None
        self._last: datetime | None = None
        self._failures = 0

    def failed(self, key: object) -> bool:
        """Ghi nhận một lượt lỗi; True = lượt này phải log."""
        now = self._clock.now()
        self._failures += 1
        if self._last is None or key != self._key or now - self._last >= self._every:
            self._key, self._last = key, now
            return True
        return False

    def recovered(self) -> int:
        """Ghi nhận một lượt thành công; trả số lượt lỗi liên tiếp vừa chấm dứt (0 = trước đó không lỗi)."""
        failures, self._failures, self._key, self._last = self._failures, 0, None, None
        return failures


class MonitorRulesJob:
    def __init__(
        self, engines: Engines, writer: AlertSink, clock: Clock, *, cap_usd: float, warn_ratio: float,
        timeout_s: float = MONITOR_RUN_TIMEOUT_SECONDS,
    ) -> None:  # fmt: skip
        self._engines = engines
        self._writer = writer
        self._clock = clock
        self._cap_usd = cap_usd
        self._warn_ratio = warn_ratio
        self._timeout_s = timeout_s
        self._incident = IncidentLog(clock)
        self._announced = False  # đã in dòng tổng lần nào chưa — lượt chạy được đầu tiên in INFO (D5 thấy job chạy)

    async def minute(self) -> None:
        """Một lượt job 60 s. Không ném lỗi (trừ `CancelledError` — hủy job phải lan ra). Log chỉ tên luật, tên lớp
        exception và SQLSTATE — không traceback, không dữ liệu (luật cứng 8; `IntegrityError` in cả tham số INSERT)."""
        try:
            engine = monitor_engine(self._engines)  # hợp đồng A0: thiếu DSN → MonitorUnavailable, KHÔNG rơi về main
        except MonitorUnavailable:
            if self._incident.failed(("MonitorUnavailable", None)):
                log.warning("%s: thiếu MONITOR_DATABASE_URL — luật cảnh báo M9 KHÔNG chạy", MONITOR_RULES_MINUTE)
            return
        ctx = RuleContext(now=self._clock.now(), tz=VN_TZ, cap_usd=self._cap_usd, warn_ratio=self._warn_ratio)
        try:
            # Hết giờ: hủy bằng CancelledError (except Exception bên trong không bắt) → ra khỏi khối thành TimeoutError.
            async with asyncio.timeout(self._timeout_s):  # đọc + ghi của một lượt (review #24 mục 2)
                async with engine.connect() as conn:  # một connection mỗi lượt; đóng = rollback (chỉ đọc)
                    result = await evaluate("minute", conn, ctx)
                written, duplicate, errors = await self._write(result.drafts)
        # Job lỗi không làm sập worker; log tên lớp + SQLSTATE, không traceback (Q19). CancelledError lan ra.
        except Exception as exc:  # noqa: BLE001 — job lỗi (Q19)
            key = (type(exc).__name__, getattr(getattr(exc, "orig", None), "sqlstate", None))
            if self._incident.failed(key):
                log.error("%s lỗi: %s sqlstate=%s", MONITOR_RULES_MINUTE, *key)
            return
        if result.failed_rules:  # luật lỗi KHÔNG phải lượt thành công — không phục hồi (review #24 mục 1)
            if self._incident.failed(("luật_lỗi", frozenset(result.failed_rules))):
                log.warning("%s: luật lỗi: %s", MONITOR_RULES_MINUTE, ", ".join(result.failed_rules))
        elif failures := self._incident.recovered():
            log.info("%s phục hồi sau %d lượt lỗi", MONITOR_RULES_MINUTE, failures)
        if result.skipped_rules:
            log.info("%s: luật bỏ qua (nguồn pending): %s", MONITOR_RULES_MINUTE, ", ".join(result.skipped_rules))
        if errors or result.failed_rules:
            level = logging.WARNING
        elif written or not self._announced:
            level = logging.INFO
        else:
            level = logging.DEBUG
        self._announced = True
        log.log(level, "%s: nháp=%d ghi=%d trùng=%d lỗi=%d luật_lỗi=%d", MONITOR_RULES_MINUTE, len(result.drafts),
                written, duplicate, errors, len(result.failed_rules))  # fmt: skip

    async def _write(self, drafts: list[AlertDraft]) -> tuple[int, int, int]:
        """Ghi từng draft → (ghi, trùng, lỗi). ghi = cảnh báo MỚI (raise_once True); trùng = khoá đã có (False) — quét
        lại 24 giờ mỗi phút nên lượt sau gặp lại draft cũ."""
        written = duplicate = errors = 0
        for draft in drafts:  # một draft lỗi không chặn draft khác (Q-M9-B1-15)
            try:
                created = await self._writer.raise_once(draft)
            # Một draft lỗi không chặn draft khác (Q15); IntegrityError in cả tham số INSERT → chỉ log tên lớp.
            except Exception as exc:  # noqa: BLE001 — một draft (Q15)
                errors += 1
                log.warning("%s: ghi cảnh báo luật %s lỗi: %s", MONITOR_RULES_MINUTE, draft.rule_id, type(exc).__name__)
            else:
                if created:
                    written += 1
                else:
                    duplicate += 1
        return written, duplicate, errors


def schedule_monitor_jobs(scheduler: AsyncIOScheduler, job: MonitorRulesJob) -> None:
    scheduler.add_job(job.minute, id=MONITOR_RULES_MINUTE, seconds=MONITOR_RULES_SECONDS, **MONITOR_JOB_OPTIONS)


def setup_monitor_jobs(
    scheduler: AsyncIOScheduler, settings: Settings, engines: Engines, clock: Clock
) -> MonitorRulesJob | None:  # fmt: skip
    """Dựng + đăng ký job M9. Lỗi (đọc `llm.yaml`, dựng writer, đăng ký job) → ERROR tên lớp, trả None; worker vẫn chạy
    3 job gốc — hết hạn duyệt (E6) và phục hồi lượt dở quan trọng hơn cảnh báo (điều kiện duyệt #13). `cap_usd`,
    `warn_ratio` đọc ở worker (`app.monitor` không import `app.llm`)."""
    try:
        spend = load_llm_config(settings.config_dir / "llm.yaml").spend
        job = MonitorRulesJob(
            engines, AlertWriter(engines.main, clock), clock, cap_usd=spend.cap_usd, warn_ratio=spend.warn_ratio
        )
        schedule_monitor_jobs(scheduler, job)
    # Dựng M9 lỗi không làm chết worker (điều kiện duyệt 1); lỗi cấu hình có thể in giá trị → chỉ log tên lớp.
    except Exception as exc:  # noqa: BLE001 — dựng job M9
        log.error("không dựng được job M9 (%s) — worker chạy tiếp KHÔNG có cảnh báo M9", type(exc).__name__)
        return None
    return job


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run())
