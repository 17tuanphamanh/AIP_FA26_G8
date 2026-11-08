"""Entrypoint worker: `python -m app.worker`. Cùng image với backend (01 mục 1.3, T01 mục 5).

Job (P1 mục 7): quét hạn chờ mỗi 15 giây, quét lượt dở dang mỗi 60 giây (và một lần lúc khởi động).
Heartbeat (`app/heartbeat.py`) ghi file mỗi 10 giây bằng CHÍNH scheduler đó — healthcheck compose đọc
file, quá 60 giây = unhealthy.
Worker KHÔNG có SVC_EXECUTOR_TOKEN (D-03): runner dựng với `can_execute=False` — recover không bao giờ
chạy B17, chuyển E7 "thực thi bị gián đoạn".
A2 (bn-a): worker KHÔNG nhận `JWT_SIGNING_KEY` (ký được token mọi vai trò) và `MFA_ENC_KEY` (giải mã secret MFA) — thấy một trong hai →
từ chối khởi động; chỉ nhận `USERNAME_HMAC_KEY` (khoá HMAC username ma cho B15 khi phục hồi lượt) — thiếu → từ chối. Kiểm ở
`require_worker_keys` TRƯỚC khi đụng DB; thông báo chỉ nêu tên biến.
M9 (B1): job `monitor_rules_minute` 60 giây chạy luật cảnh báo theo sự kiện; (B2) `monitor_rules_hourly` mỗi 3600
giây và `monitor_rules_daily` 19:00 UTC (02:00 giờ VN); (B3) `monitor_rules_weekly` Chủ nhật 19:00 UTC (02:00 thứ Hai
giờ VN) — ba job này chạy bù một lượt lúc khởi động — khối `# ---- M9` cuối file.
Notify-email: chỉ khi `Settings.email_active` (EMAIL_ENABLED=true, không EVAL_MODE) — job `send_emails` mỗi
`EMAIL_SEND_INTERVAL_SECONDS` (mặc định 15 s) gửi `email_outbox` qua SMTP, và nhắc duyệt 50 %/80 % ghi thêm dòng outbox
(`notify.notifier.ApproverEmailNotice`) — khối `# ---- Email` cuối file. Tắt → không đăng ký job, nhắc duyệt như cũ.
"""

import asyncio
import logging
import signal
from datetime import datetime, timedelta
from typing import Any, Protocol

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import heartbeat
from app.approval.store import log_approver_notice
from app.audit.alerts import AlertWriter  # M9: ghi alerts qua M7, không qua app.monitor
from app.auth.username_hash import resolve_key
from app.core.clock import Clock, SystemClock
from app.core.logging import configure_logging
from app.db.session import Engines, create_engines
from app.domain.alerts import AlertDraft
from app.graph.wiring import open_runtime
from app.graph.worker_jobs import ApproverNotice, WorkerJobs
from app.guard.privacy import guard_from_settings
from app.llm.config import load_llm_config
from app.monitor.db import MonitorUnavailable, monitor_engine
from app.monitor.evaluator import evaluate
from app.monitor.queries import rules_data as _rules_data  # noqa: F401
from app.monitor.rules import Every, RuleContext
from app.monitor.window import VN_TZ
from app.notify.notifier import ApproverEmailNotice, email_outbox_from_settings
from app.notify.outbox import SqlEmailOutbox
from app.notify.smtp import EmailSendJob, SmtpSender
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


WORKER_FORBIDDEN_KEYS = ("jwt_signing_key", "mfa_enc_key")


def require_worker_keys(settings: Settings) -> bytes:
    """A2: fail-closed lúc khởi động worker — có khoá thừa (JWT/MFA) hoặc thiếu `USERNAME_HMAC_KEY` → RuntimeError (chỉ tên biến)."""
    if extra := [name.upper() for name in WORKER_FORBIDDEN_KEYS if getattr(settings, name) is not None]:
        raise RuntimeError(f"worker không được nhận {', '.join(extra)} (chỉ backend giữ) — gỡ khỏi env của worker; từ chối khởi động")
    key = resolve_key(None, settings.username_hmac_key)
    if key is None:
        raise RuntimeError(
            "USERNAME_HMAC_KEY chưa cấu hình — worker cần khoá HMAC username ma (dẫn xuất từ JWT_SIGNING_KEY bằng "
            "scripts/ops/derive_username_key.py); từ chối khởi động"
        )
    return key


async def run() -> None:
    settings = get_settings()
    require_worker_keys(settings)  # A2: trước khi đụng DB
    clock = SystemClock()
    engines = create_engines(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with open_runtime(settings, engines, clock, can_execute=False) as rt:
            outbox = email_outbox_from_settings(settings, engines.main, guard_from_settings(settings), clock)
            # Email tắt → hàm nhắc mặc định của WorkerJobs (`log_approver_notice`) như cũ.
            notice: ApproverNotice = log_approver_notice if outbox is None else ApproverEmailNotice(outbox)
            jobs = WorkerJobs(
                rt.runner, rt.deadlines, rt.turns,
                stale_after=timedelta(seconds=settings.worker_stale_turn_seconds),
                batch=settings.worker_batch, notify_approver=notice,
            )  # fmt: skip
            scheduler = AsyncIOScheduler(timezone="UTC")
            schedule_jobs(scheduler, jobs, settings, clock)
            setup_monitor_jobs(scheduler, settings, engines, clock)  # M9 — lỗi dựng không làm chết worker
            if outbox is not None:
                setup_email_jobs(scheduler, settings, outbox, clock)
            scheduler.start()
            heartbeat.write(settings.worker_heartbeat_path, clock.now())
            log.info("worker khởi động")
            await jobs.scan_stale_turns()  # phục hồi ngay lượt dở dang từ lần chết trước
            await stop.wait()
            scheduler.shutdown(wait=False)
    finally:
        await engines.dispose()
    log.info("worker dừng")


# ---- M9 (B1, #13; B2, #14; B3, #15): job luật cảnh báo phút / giờ / ngày / tuần ------------------------------------
#
# Job phút mỗi 60 giây: `evaluate("minute")` trên MỘT connection của engine `app_monitor` (chỉ đọc) → mỗi draft ghi bằng
# `AlertWriter.raise_once` (engine chính, app_rw) — ghi chỉ ở đây, không bao giờ trong `app.monitor` [Chốt 17.9.2].
# Import `rules_data` (đầu file, noqa F401) để đăng ký loader; `spend` đọc ở worker vì `app.monitor` không import
# `app.llm`.
# Không bỏ sót nhờ lookback 24 giờ của từng luật, không trùng nhờ khoá `(rule_id, subject, window_start)`.
# Nhịp log (review #24, Q-M9-B1-20): dòng tổng `nháp= ghi= trùng= lỗi= luật_lỗi=` — WARNING khi có lỗi ghi, hoặc khi
# IncidentLog báo luật lỗi ở lượt này (lần đầu / tập luật lỗi đổi / mỗi giờ); INFO ở lượt chạy được đầu tiên và khi có
# cảnh báo mới (kể cả khi luật lỗi mà IncidentLog không báo — Q-M9-B2-8); còn lại DEBUG (`core/logging.py` đã tắt INFO
# APScheduler vì quá dày). Q-M9-B1-24: dòng "luật bỏ qua (nguồn chưa có)" INFO khi tập luật bỏ qua đổi, còn lại DEBUG;
# WARNING từng draft ghi lỗi qua IncidentLog theo (rule_id, tên lớp) — dòng tổng `lỗi=` vẫn WARNING mỗi lượt.
#
# B2 (#14): cùng class `MonitorRulesJob`, một instance cho mỗi chu kỳ (`every`) — IncidentLog, nhịp log riêng; bốn job
# dùng chung MỘT `AlertWriter`. Job giờ `evaluate("hourly")` (luật 14) interval 3600 s; job ngày `evaluate("daily")`
# (luật 1, 7, 12, 13) cron 19:00 với `timezone="UTC"` TƯỜNG MINH (không theo múi giờ scheduler/máy) = 02:00 giờ VN.
# Chốt Q-M9-B2-4 (#14 comment 5959974287): "chạy bù lúc khởi động. Job giờ `misfire_grace_time = 3600`. Job ngày để
# `None` … Khoá theo `d0` nên chạy muộn không sinh trùng." Chạy bù = `next_run_time = clock.now()` lúc dựng: jobstore
# trong bộ nhớ không biết lượt nào đã lỡ nên MỖI lần khởi động chạy ngay một lượt; trùng ngày/giờ với lượt đã có →
# khoá `(rule_id, subject, window_start)` (luật 14 `day_start`, luật 1 `d0`, luật 7/12/13 mốc `r`) → `trùng`.
# Job phút KHÔNG chạy bù (giữ nguyên B1: lượt đầu sau 60 s, quét lại 24 giờ). Bốn job là bốn task riêng (`max_instances`
# tính theo từng job), mỗi lượt một connection monitor → job này chạy lâu không làm job khác lỡ lượt.
# Hạn chế đã biết (Q-M9-B2-26, chốt PR #31: giữ 19:00 UTC và ghi chú này; thử lại 02:00–06:00 để sau, khi gặp thật):
# lượt ngày lỗi cả khối (mất kết nối, hết giờ) khi worker vẫn sống thì không có lượt bù tới 19:00 hôm sau — luật
# 7/12/13 được đánh giá lại nhờ 7 mốc, luật 1 (chỉ `d0`) mất mốc ngày đó (cửa sổ 7 ngày của mốc sau chồng 6/7); ERROR
# `monitor_rules_daily lỗi:` theo IncidentLog báo người trực.
# Áp dụng CẢ cho lượt chạy bù lúc khởi động: APScheduler tính lượt kế ngay lúc nộp job, từ `next_run_time` của lượt bù,
# không xét kết quả (`run()` nuốt lỗi) → lượt bù của job ngày lỗi cả khối (vd worker khởi động khi DB chưa sẵn sàng)
# thì lượt kế là 19:00 UTC kế tiếp, không thử lại sớm hơn; job giờ thử lại sau 3600 giây. Hệ quả như trên.
#
# B3 (#15): job tuần `evaluate("weekly")` (luật 8 `drift`) cron Chủ nhật 19:00 UTC, `timezone="UTC"` tường minh = 02:00
# thứ Hai giờ VN. Chốt Q-M9-B3-10 (#15 comment 6127685951 đồng ý mặc định ở comment 6110081162): "job tuần cron
# `day_of_week="sun", hour=19, timezone="UTC"`, `misfire_grace_time=None`, chạy bù lúc khởi động, giống job ngày."
# `day_of_week` là chuỗi `"sun"`, không dùng số (APScheduler 3.x: 0 = thứ Hai). Chạy bù như job ngày; trùng mốc với lượt
# đã có → khoá `(drift, phân bố, mốc)` → `trùng`. Q-M9-B3-7: mỗi lượt đánh giá 2 mốc `W − 7 ngày`, `W`.
# Hạn chế đã biết (như Q-M9-B2-26; Q-M9-B3-17 [Đề xuất]: không thử lại trong tuần): lượt tuần lỗi cả khối khi worker
# vẫn sống → lượt kế là Chủ nhật 19:00 UTC tuần sau; nhờ 2 mốc, mốc của lượt lỗi vẫn được đánh giá ở lượt đó (trễ tới 7
# ngày, không mất); lỗi HAI lượt liền thì mốc đầu rơi khỏi 2 mốc → mất. Lượt bù lúc khởi động lỗi cũng chờ tới Chủ nhật
# tuần sau (trừ khi worker khởi động lại). ERROR `monitor_rules_weekly lỗi:` mỗi lượt lỗi (cách nhau > 1 giờ).

MONITOR_RULES_MINUTE = "monitor_rules_minute"
MONITOR_RULES_HOURLY = "monitor_rules_hourly"
MONITOR_RULES_DAILY = "monitor_rules_daily"
MONITOR_RULES_WEEKLY = "monitor_rules_weekly"
MONITOR_JOB_IDS: dict[Every, str] = {
    "minute": MONITOR_RULES_MINUTE, "hourly": MONITOR_RULES_HOURLY, "daily": MONITOR_RULES_DAILY,
    "weekly": MONITOR_RULES_WEEKLY,
}  # fmt: skip
MONITOR_RULES_SECONDS = 60
MONITOR_HOURLY_SECONDS = 3600
MONITOR_HOURLY_MISFIRE_SECONDS = 3600  # Q-M9-B2-4
MONITOR_DAILY_HOUR_UTC = 19  # 02:00 giờ VN (Q-M9-2, thẻ B2)
MONITOR_WEEKLY_DAY = "sun"  # chuỗi, không phải số (APScheduler 3.x: 0 = thứ Hai)
MONITOR_WEEKLY_HOUR_UTC = 19  # Chủ nhật 19:00 UTC = 02:00 thứ Hai giờ VN (Q-M9-B3-10)
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
        timeout_s: float = MONITOR_RUN_TIMEOUT_SECONDS, every: Every = "minute",
    ) -> None:  # fmt: skip
        self._every = every
        self._name = MONITOR_JOB_IDS[every]  # tên job trong mọi dòng log
        self._engines = engines
        self._writer = writer
        self._clock = clock
        self._cap_usd = cap_usd
        self._warn_ratio = warn_ratio
        self._timeout_s = timeout_s
        self._incident = IncidentLog(clock)
        self._announced = False  # đã in dòng tổng lần nào chưa — lượt chạy được đầu tiên in INFO (D5 thấy job chạy)
        # Q-M9-B1-24. Luật bỏ qua: tập ở lượt trước (nguồn chưa có là trạng thái đã biết, không phải sự cố → không nhắc
        # mỗi giờ). Draft ghi lỗi: một IncidentLog cho mỗi (rule_id, tên lớp) còn lỗi ở lượt trước.
        self._skipped: frozenset[str] = frozenset()
        self._draft_errors: dict[tuple[str, str], IncidentLog] = {}

    async def run(self) -> None:
        """Một lượt job M9 (phút / giờ / ngày theo `every`). Không ném lỗi (trừ `CancelledError` — hủy job phải lan ra).
        Log chỉ tên job, tên luật, tên lớp exception và SQLSTATE — không traceback, không dữ liệu (luật cứng 8;
        `IntegrityError` in cả tham số INSERT)."""
        try:
            engine = monitor_engine(self._engines)  # hợp đồng A0: thiếu DSN → MonitorUnavailable, KHÔNG rơi về main
        except MonitorUnavailable:
            if self._incident.failed(("MonitorUnavailable", None)):
                log.warning("%s: thiếu MONITOR_DATABASE_URL — luật cảnh báo M9 KHÔNG chạy", self._name)
            return
        ctx = RuleContext(now=self._clock.now(), tz=VN_TZ, cap_usd=self._cap_usd, warn_ratio=self._warn_ratio)
        try:
            # Hết giờ: hủy bằng CancelledError (except Exception bên trong không bắt) → ra khỏi khối thành TimeoutError.
            async with asyncio.timeout(self._timeout_s):  # đọc + ghi của một lượt (review #24 mục 2)
                async with engine.connect() as conn:  # một connection mỗi lượt; đóng = rollback (chỉ đọc)
                    result = await evaluate(self._every, conn, ctx)
                written, duplicate, errors = await self._write(result.drafts)
        # Job lỗi không làm sập worker; log tên lớp + SQLSTATE, không traceback (Q19). CancelledError lan ra.
        except Exception as exc:  # noqa: BLE001 — job lỗi (Q19)
            key = (type(exc).__name__, getattr(getattr(exc, "orig", None), "sqlstate", None))
            if self._incident.failed(key):
                log.error("%s lỗi: %s sqlstate=%s", self._name, *key)
            return
        reported = False  # IncidentLog có báo luật lỗi ở lượt này không — quyết mức dòng tổng bên dưới
        if result.failed_rules:  # luật lỗi KHÔNG phải lượt thành công — không phục hồi (review #24 mục 1)
            reported = self._incident.failed(("luật_lỗi", frozenset(result.failed_rules)))
            if reported:
                log.warning("%s: luật lỗi: %s", self._name, ", ".join(result.failed_rules))
        elif failures := self._incident.recovered():
            log.info("%s phục hồi sau %d lượt lỗi", self._name, failures)
        skipped = frozenset(result.skipped_rules)  # tập, không phải thứ tự: đổi thứ tự không phải đổi tập
        if skipped:
            log.log(logging.INFO if skipped != self._skipped else logging.DEBUG, "%s: luật bỏ qua (nguồn chưa có): %s",
                    self._name, ", ".join(result.skipped_rules))  # fmt: skip
        self._skipped = skipped  # gán cả tập rỗng: luật bỏ qua xuất hiện lại sau lượt rỗng → INFO ngay
        if errors or reported:
            level = logging.WARNING
        elif written or not self._announced:
            level = logging.INFO
        else:
            level = logging.DEBUG
        self._announced = True
        log.log(level, "%s: nháp=%d ghi=%d trùng=%d lỗi=%d luật_lỗi=%d", self._name, len(result.drafts),
                written, duplicate, errors, len(result.failed_rules))  # fmt: skip

    minute = run  # tên cũ: job phút đăng ký `job.minute` (schedule_monitor_jobs), test B1/B2 gọi `.minute()`

    async def _write(self, drafts: list[AlertDraft]) -> tuple[int, int, int]:
        """Ghi từng draft → (ghi, trùng, lỗi). ghi = cảnh báo MỚI (raise_once True); trùng = khoá đã có (False) — luật
        quét lại cửa sổ cũ (24 giờ / cùng ngày / 7 mốc) nên lượt sau gặp lại draft cũ.

        Nhịp WARNING từng draft lỗi (Q-M9-B1-24): theo (rule_id, tên lớp) — lần đầu, khi lớp đổi, rồi mỗi giờ; còn lại
        DEBUG. Khoá không lỗi ở lượt này bị bỏ → lỗi quay lại sau một lượt sạch báo ngay (nghiêng về báo thừa)."""
        written = duplicate = errors = 0
        seen: dict[tuple[str, str], IncidentLog] = {}
        for draft in drafts:  # một draft lỗi không chặn draft khác (Q-M9-B1-15)
            try:
                created = await self._writer.raise_once(draft)
            # Một draft lỗi không chặn draft khác (Q15); IntegrityError in cả tham số INSERT → chỉ log tên lớp.
            except Exception as exc:  # noqa: BLE001 — một draft (Q15)
                errors += 1
                key = (draft.rule_id, type(exc).__name__)
                incident = seen.setdefault(key, self._draft_errors.get(key) or IncidentLog(self._clock))
                level = logging.WARNING if incident.failed(key) else logging.DEBUG
                log.log(level, "%s: ghi cảnh báo luật %s lỗi: %s", self._name, draft.rule_id,
                        type(exc).__name__)  # fmt: skip
            else:
                if created:
                    written += 1
                else:
                    duplicate += 1
        self._draft_errors = seen  # hết giờ giữa chừng → không tới đây, giữ trạng thái cũ
        return written, duplicate, errors


def schedule_monitor_jobs(scheduler: AsyncIOScheduler, job: MonitorRulesJob) -> None:
    scheduler.add_job(job.minute, id=MONITOR_RULES_MINUTE, seconds=MONITOR_RULES_SECONDS, **MONITOR_JOB_OPTIONS)


def schedule_periodic_jobs(
    scheduler: AsyncIOScheduler, hourly: MonitorRulesJob, daily: MonitorRulesJob, weekly: MonitorRulesJob,
    now: datetime,
) -> None:  # fmt: skip
    """Job giờ + job ngày (Q-M9-B2-4) + job tuần (Q-M9-B3-10), đăng ký theo thứ tự đó. `next_run_time=now` = chạy bù một
    lượt ngay khi scheduler start. Job ngày và job tuần truyền `misfire_grace_time=None` TƯỜNG MINH (thiếu khoá thì
    APScheduler điền mặc định 1 giây → máy ngủ qua 02:00 là mất lượt) và `timezone="UTC"` tường minh (không thì trigger
    lấy múi giờ của scheduler)."""
    scheduler.add_job(
        hourly.run, id=MONITOR_RULES_HOURLY, seconds=MONITOR_HOURLY_SECONDS, **MONITOR_JOB_OPTIONS,
        misfire_grace_time=MONITOR_HOURLY_MISFIRE_SECONDS, next_run_time=now,
    )  # fmt: skip
    scheduler.add_job(
        daily.run, id=MONITOR_RULES_DAILY, trigger="cron", hour=MONITOR_DAILY_HOUR_UTC, minute=0, timezone="UTC",
        max_instances=1, coalesce=True, misfire_grace_time=None, next_run_time=now,
    )  # fmt: skip
    scheduler.add_job(
        weekly.run, id=MONITOR_RULES_WEEKLY, trigger="cron", day_of_week=MONITOR_WEEKLY_DAY,
        hour=MONITOR_WEEKLY_HOUR_UTC, minute=0, timezone="UTC", max_instances=1, coalesce=True,
        misfire_grace_time=None, next_run_time=now,
    )  # fmt: skip


def setup_monitor_jobs(
    scheduler: AsyncIOScheduler, settings: Settings, engines: Engines, clock: Clock
) -> dict[Every, MonitorRulesJob] | None:  # fmt: skip
    """Dựng + đăng ký 4 job M9 (phút, giờ, ngày, tuần — chung một writer). Lỗi (đọc `llm.yaml`, dựng writer, đăng ký
    job) → ERROR tên lớp, trả None; worker vẫn chạy 3 job gốc — hết hạn duyệt (E6) và phục hồi lượt dở quan trọng hơn
    cảnh báo (điều kiện duyệt #13). Đăng ký theo thứ tự phút → giờ → ngày → tuần; lỗi giữa chừng thì job đã đăng ký vẫn
    chạy (gỡ ra là bỏ sót). `cap_usd`, `warn_ratio` đọc ở worker (`app.monitor` không import `app.llm`)."""
    try:
        spend = load_llm_config(settings.config_dir / "llm.yaml").spend
        writer = AlertWriter(engines.main, clock)
        jobs: dict[Every, MonitorRulesJob] = {
            every: MonitorRulesJob(
                engines, writer, clock, cap_usd=spend.cap_usd, warn_ratio=spend.warn_ratio, every=every
            )
            for every in ("minute", "hourly", "daily", "weekly")  # tường minh: thêm chu kỳ phải sửa có chủ đích
        }
        schedule_monitor_jobs(scheduler, jobs["minute"])
        schedule_periodic_jobs(scheduler, jobs["hourly"], jobs["daily"], jobs["weekly"], clock.now())
    # Dựng M9 lỗi không làm chết worker (điều kiện duyệt 1); lỗi cấu hình có thể in giá trị → chỉ log tên lớp.
    except Exception as exc:  # noqa: BLE001 — dựng job M9
        log.error("không dựng đủ job M9 (%s) — worker chạy tiếp, THIẾU cảnh báo M9", type(exc).__name__)
        return None
    return jobs


# ---- Email (notify-email) ---------------------------------------------------------------------------------------------
# Một job interval, cùng option với job lõi (`max_instances=1`, `coalesce`): một lượt gửi chậm (SMTP treo tới timeout) không chồng lượt
# sau. Không đăng ký trong `schedule_jobs` (tập job lõi được test ghim). Chỉ gọi khi `email_active`.

SEND_EMAILS_JOB = "send_emails"


def setup_email_jobs(scheduler: AsyncIOScheduler, settings: Settings, outbox: SqlEmailOutbox, clock: Clock) -> EmailSendJob:
    job = EmailSendJob(outbox, SmtpSender.from_settings(settings), clock)
    scheduler.add_job(
        job.run, id=SEND_EMAILS_JOB, seconds=settings.email_send_interval_seconds, trigger="interval", max_instances=1,
        coalesce=True,
    )  # fmt: skip
    log.info("email bật — job %s mỗi %g giây", SEND_EMAILS_JOB, settings.email_send_interval_seconds)
    return job


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run())
