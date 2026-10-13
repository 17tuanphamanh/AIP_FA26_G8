"""M9-B2 GĐ2 cụm 3 — job giờ `monitor_rules_hourly`, job ngày `monitor_rules_daily`; M9-B3 cụm 4 — job tuần
`monitor_rules_weekly` (worker.py khối M9). Không DB.

Nguồn: thẻ B2 (file chia việc mục 6: "job `monitor_rules_hourly`, `monitor_rules_daily` (02:00 giờ VN = 19:00 UTC)"),
kế hoạch chung M9 mục 3.3; chốt #14 comment 5959974287 — Q-M9-B2-4: "chạy bù lúc khởi động. Job giờ
`misfire_grace_time = 3600`. Job ngày để `None`". Thẻ B3: "job tuần (thứ Hai 02:00 giờ VN)"; chốt #15 comment 6127685951
đồng ý mặc định ở comment 6110081162 — Q-M9-B3-10: "job tuần cron `day_of_week="sun", hour=19, timezone="UTC"`,
`misfire_grace_time=None`, chạy bù lúc khởi động, giống job ngày." Job phút giữ nguyên hành vi (test ở
`test_monitor_jobs_minute.py`). Bản Postgres: `tests/integration/test_monitor_jobs_hourly_pg.py`,
`test_monitor_jobs_daily_pg.py`, `test_monitor_jobs_weekly_pg.py`.

Kỳ vọng là hằng viết tay (id job, chu kỳ, giờ chạy, tập luật), không lấy từ hằng của worker. Ngày trong tuần của các mốc
lịch đã kiểm độc lập: 11/10/2026, 18/10/2026, 08/03/2026, 01/11/2026 là Chủ nhật; 17/10/2026 là thứ Bảy; 12/10/2026 là
thứ Hai; New York đổi giờ 08/03/2026 và 01/11/2026.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
import yaml
from app import worker
from app.core.clock import FakeClock
from app.db.session import Engines
from app.domain.alerts import AlertDraft
from app.monitor.evaluator import (
    LOADERS,
    EvalResult,
    Pending,
    reset_log_pacing,
)
from app.monitor.rules import REGISTRY, RuleContext
from app.monitor.window import VN_TZ
from app.settings import Settings
from app.worker import MonitorRulesJob, schedule_jobs, setup_monitor_jobs
from apscheduler.schedulers.asyncio import AsyncIOScheduler

REPO = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
SECRET = "giá-trị-nhạy-cảm-xyz"  # nằm trong thông điệp exception — không được lọt vào log

MINUTE_ID, HOURLY_ID, DAILY_ID = "monitor_rules_minute", "monitor_rules_hourly", "monitor_rules_daily"
WEEKLY_ID = "monitor_rules_weekly"
CORE_IDS = {"heartbeat", "scan_deadlines", "scan_stale_turns"}
HOURLY_RULES = {"llm_budget"}
DAILY_RULES = {"escalation_rate_high", "b2_degraded", "b3_degraded", "reflex_approval"}
WEEKLY_RULES = {"drift"}  # luật 8 (B3 cụm 3), job tuần (B3 cụm 4)
MINUTE_RULES = {
    "injection_detected", "password_bruteforce", "refresh_reuse", "permission_denied_burst", "policy_saved",
    "finalize_failed", "execution_failed", "e9_spike", "e6_spike", "breaker_open",
}  # fmt: skip


@pytest.fixture(autouse=True)
def _pacing() -> Iterator[None]:
    reset_log_pacing()  # nhịp log của evaluator là trạng thái cấp module
    yield
    reset_log_pacing()


# ---- đồ giả -----------------------------------------------------------------------------------------------------


class FakeEngine:
    """`connect()` trả chính nó; có `begin_nested()` để `evaluate` thật chạy được trên nó (U5)."""

    def __init__(self, name: str = "monitor") -> None:
        self.name = name

    @asynccontextmanager
    async def connect(self) -> AsyncIterator["FakeEngine"]:
        yield self

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield


class SpyWriter:
    """Thay `worker.AlertWriter`: như `raise_once` (True = khoá mới, False = khoá đã có); ghi lại engine được trao."""

    built: ClassVar[list["SpyWriter"]] = []  # mỗi test đặt lại trước khi dựng job

    def __init__(self, engine: object, clock: object) -> None:
        self.engine = engine
        self.written: list[AlertDraft] = []
        self._keys: set[tuple[str, str, datetime]] = set()
        SpyWriter.built.append(self)

    async def raise_once(self, draft: AlertDraft) -> bool:
        key = (draft.rule_id, draft.subject, draft.window_start)
        if key in self._keys:
            return False
        self._keys.add(key)
        self.written.append(draft)
        return True


class IdleJobs:
    async def scan_deadlines(self) -> None: ...
    async def scan_stale_turns(self) -> None: ...


class RecordingScheduler:
    """Ghi lại đúng hàm + tham số mỗi lần `add_job` (không qua giá trị mặc định của APScheduler)."""

    def __init__(self) -> None:
        self.calls: dict[str, tuple[object, dict[str, Any]]] = {}

    def add_job(self, func: object, **kwargs: Any) -> None:
        self.calls[kwargs["id"]] = (func, {k: v for k, v in kwargs.items() if k != "id"})


def engines(monitor: FakeEngine | None) -> Engines:
    main = FakeEngine("main")
    return Engines(main=cast(Any, main), lock=cast(Any, main), monitor=cast(Any, monitor))


def settings_with(config_dir: Path, tmp_path: Path) -> Settings:
    return Settings(worker_heartbeat_path=tmp_path / "hb", config_dir=config_dir)


def llm_yaml(tmp_path: Path, cap: float, warn: float) -> Path:
    cfg = yaml.safe_load((REPO / "config" / "llm.yaml").read_text(encoding="utf-8"))
    cfg["spend"].update(cap_usd=cap, warn_ratio=warn)
    out = tmp_path / "cfg"
    out.mkdir()
    (out / "llm.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return out


def build(
    scheduler: Any, tmp_path: Path, clock: FakeClock, monitor: FakeEngine | None = None
) -> dict[str, MonitorRulesJob]:  # fmt: skip
    jobs = setup_monitor_jobs(scheduler, settings_with(llm_yaml(tmp_path, 12.0, 0.5), tmp_path),
                              engines(monitor if monitor is not None else FakeEngine()), clock)  # fmt: skip
    assert jobs is not None
    return cast(dict[str, MonitorRulesJob], jobs)


def draft(rule_id: str, subject: str) -> AlertDraft:
    return AlertDraft(rule_id=rule_id, subject=subject, window_start=T0, severity="warning", detail={"n": 1})


def record_evaluate(
    monkeypatch: pytest.MonkeyPatch, plan: dict[str, EvalResult | BaseException] | None = None
) -> list[tuple[str, RuleContext]]:  # fmt: skip
    """Thay `evaluate` trong worker; ghi (every, ctx). `plan[every]` = kết quả hoặc exception (thiếu → 0 draft)."""
    seen: list[tuple[str, RuleContext]] = []

    async def run(every: str, conn: object, ctx: RuleContext) -> EvalResult:
        seen.append((every, ctx))
        out = (plan or {}).get(every, EvalResult(drafts=[], failed_rules=[], skipped_rules=[]))
        if isinstance(out, BaseException):
            raise out
        return out

    monkeypatch.setattr(worker, "evaluate", run)
    return seen


def m9_records(caplog: pytest.LogCaptureFixture, level: int | None = None) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.worker" and (level is None or r.levelno == level)]


def summaries(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in m9_records(caplog) if "nháp=" in r.getMessage()]


# ---- U1–U3: đăng ký, giờ chạy, chạy bù -------------------------------------------------------------------------------


def test_periodic_jobs_registered_exact_options(tmp_path: Path) -> None:
    """U1. Bộ tham số so NGUYÊN dict: job phút như B1 (không chạy bù, misfire mặc định); job giờ interval 3600 s, misfire
    3600; job ngày cron 19:00 `timezone="UTC"`, misfire `None` (khoá PHẢI có mặt — thiếu thì APScheduler điền 1 giây);
    job tuần cron Chủ nhật (`"sun"`) 19:00 `timezone="UTC"`, misfire `None` (Q-M9-B3-10); giờ/ngày/tuần `next_run_time` =
    giờ dựng (chạy bù, Q-M9-B2-4, Q-M9-B3-10). Dict của phút/giờ/ngày giữ nguyên chữ B2 (job cũ không đổi hành vi). Mỗi
    id gắn đúng job của chu kỳ đó."""
    rec = RecordingScheduler()
    jobs = build(rec, tmp_path, FakeClock(T0))
    assert set(rec.calls) == {MINUTE_ID, HOURLY_ID, DAILY_ID, WEEKLY_ID}
    common = {"max_instances": 1, "coalesce": True}
    assert rec.calls[MINUTE_ID][1] == {"trigger": "interval", "seconds": 60, **common}
    assert rec.calls[HOURLY_ID][1] == {
        "trigger": "interval", "seconds": 3600, **common, "misfire_grace_time": 3600, "next_run_time": T0,
    }  # fmt: skip
    assert rec.calls[DAILY_ID][1] == {
        "trigger": "cron", "hour": 19, "minute": 0, "timezone": "UTC", **common, "misfire_grace_time": None,
        "next_run_time": T0,
    }  # fmt: skip
    assert rec.calls[WEEKLY_ID][1] == {
        "trigger": "cron", "day_of_week": "sun", "hour": 19, "minute": 0, "timezone": "UTC", **common,
        "misfire_grace_time": None, "next_run_time": T0,
    }  # fmt: skip
    for job_id, every in ((MINUTE_ID, "minute"), (HOURLY_ID, "hourly"), (DAILY_ID, "daily"), (WEEKLY_ID, "weekly")):
        func = rec.calls[job_id][0]
        assert getattr(func, "__self__", None) is jobs[every], job_id
        assert getattr(func, "__func__", None) is MonitorRulesJob.run, job_id


@pytest.mark.parametrize("scheduler_tz", ["UTC", "Asia/Ho_Chi_Minh", "America/New_York"])
def test_daily_fires_19_utc_any_scheduler_tz(scheduler_tz: str, tmp_path: Path) -> None:
    """U2. Job ngày 19:00 UTC = 02:00 giờ VN, KHÔNG theo múi giờ của scheduler (hay của máy): scheduler VN/New York vẫn
    ra 19:00Z, kể cả ngày New York đổi giờ (08/03/2026). Job giờ: chu kỳ 1 giờ."""
    scheduler = AsyncIOScheduler(timezone=scheduler_tz)
    build(scheduler, tmp_path, FakeClock(T0))
    daily, hourly = scheduler.get_job(DAILY_ID), scheduler.get_job(HOURLY_ID)
    assert daily is not None and hourly is not None
    fire = daily.trigger.get_next_fire_time
    assert fire(None, datetime(2026, 10, 2, 18, 59, tzinfo=UTC)) == datetime(2026, 10, 2, 19, 0, tzinfo=UTC)
    assert fire(None, datetime(2026, 10, 2, 19, 0, 0, 1, tzinfo=UTC)) == datetime(2026, 10, 3, 19, 0, tzinfo=UTC)
    assert fire(None, datetime(2026, 3, 8, 18, 59, tzinfo=UTC)) == datetime(2026, 3, 8, 19, 0, tzinfo=UTC)
    assert hourly.trigger.interval == timedelta(hours=1)


@pytest.mark.parametrize("scheduler_tz", ["UTC", "Asia/Ho_Chi_Minh", "America/New_York"])
def test_weekly_fires_sunday_19_utc_any_scheduler_tz(scheduler_tz: str, tmp_path: Path) -> None:
    """U2b. Job tuần Chủ nhật 19:00 UTC = 02:00 thứ Hai giờ VN (Q-M9-B3-10), KHÔNG theo múi giờ của scheduler: từ CN
    18:59Z ra CN 19:00Z cùng ngày; vừa qua 19:00Z ra CN tuần sau; từ thứ Bảy (bắt `"sat"`) và thứ Hai (bắt `"mon"` / số 0
    — APScheduler 3.x đánh 0 = thứ Hai) đều ra CN kế tiếp; hai CN New York đổi giờ (08/03, 01/11/2026) vẫn 19:00Z."""
    scheduler = AsyncIOScheduler(timezone=scheduler_tz)
    build(scheduler, tmp_path, FakeClock(T0))
    weekly = scheduler.get_job(WEEKLY_ID)
    assert weekly is not None
    fire = weekly.trigger.get_next_fire_time
    sun_19 = datetime(2026, 10, 18, 19, 0, tzinfo=UTC)
    assert fire(None, datetime(2026, 10, 11, 18, 59, tzinfo=UTC)) == datetime(2026, 10, 11, 19, 0, tzinfo=UTC)
    assert fire(None, datetime(2026, 10, 11, 19, 0, 0, 1, tzinfo=UTC)) == sun_19
    assert fire(None, datetime(2026, 10, 17, 18, 59, tzinfo=UTC)) == sun_19
    assert fire(None, datetime(2026, 10, 12, 0, 0, tzinfo=UTC)) == sun_19
    assert fire(None, datetime(2026, 3, 8, 18, 59, tzinfo=UTC)) == datetime(2026, 3, 8, 19, 0, tzinfo=UTC)
    assert fire(None, datetime(2026, 11, 1, 18, 59, tzinfo=UTC)) == datetime(2026, 11, 1, 19, 0, tzinfo=UTC)
    assert sun_19 == datetime(2026, 10, 19, 2, 0, tzinfo=VN_TZ)  # 02:00 thứ Hai 19/10/2026 giờ VN


@pytest.mark.asyncio
async def test_startup_catchup_once_per_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """U3. APScheduler thật: start xong → job giờ, ngày, tuần chạy NGAY đúng một lượt mỗi job (chạy bù, Q-M9-B2-4,
    Q-M9-B3-10); job phút KHÔNG chạy bù (lượt đầu sau 60 s như B1). Sau lượt bù: giờ hẹn `start + 1 giờ`, ngày hẹn 19:00
    UTC kế tiếp, tuần hẹn Chủ nhật 19:00 UTC kế tiếp. misfire sau khi APScheduler điền mặc định: phút 1 (không đổi), giờ
    3600, ngày None, tuần None."""
    start = datetime.now(UTC).replace(microsecond=0)  # giây tròn: timestamp float cộng 3600 không lệch micro giây
    seen = record_evaluate(monkeypatch)
    scheduler = AsyncIOScheduler(timezone="UTC")
    build(scheduler, tmp_path, FakeClock(start))
    scheduler.start()
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            if len(seen) >= 3:
                break
        await asyncio.sleep(0.2)  # không có lượt thứ tư
        jobs = {job_id: scheduler.get_job(job_id) for job_id in (MINUTE_ID, HOURLY_ID, DAILY_ID, WEEKLY_ID)}
    finally:
        scheduler.shutdown(wait=False)
    assert sorted(every for every, _ in seen) == ["daily", "hourly", "weekly"]
    minute, hourly, daily, weekly = jobs[MINUTE_ID], jobs[HOURLY_ID], jobs[DAILY_ID], jobs[WEEKLY_ID]
    assert minute is not None and hourly is not None and daily is not None and weekly is not None
    assert (minute.misfire_grace_time, hourly.misfire_grace_time, daily.misfire_grace_time,
            weekly.misfire_grace_time) == (1, 3600, None, None)  # fmt: skip
    assert hourly.next_run_time == start + timedelta(hours=1)
    next_19 = start.replace(hour=19, minute=0, second=0)
    if next_19 <= start:
        next_19 += timedelta(days=1)
    assert daily.next_run_time == next_19
    next_sun_19 = start.replace(hour=19, minute=0, second=0) + timedelta(days=(6 - start.weekday()) % 7)
    if next_sun_19 <= start:
        next_sun_19 += timedelta(days=7)
    assert weekly.next_run_time == next_sun_19


# ---- U4–U5: mỗi job đúng chu kỳ, đúng tập luật -------------------------------------------------------------------------


@pytest.mark.parametrize(("every", "job_id"), [("hourly", HOURLY_ID), ("daily", DAILY_ID), ("weekly", WEEKLY_ID)])
def test_periodic_job_evaluates_own_every(
    every: str, job_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U4. Job dựng bởi setup gọi `evaluate(every)` của CHÍNH nó, ctx như job phút (Clock của app, VN_TZ, `cap_usd`/
    `warn_ratio` của `llm.yaml`); hàm mà scheduler gọi theo id cũng vậy (đổi chéo khi `add_job` thì đỏ)."""
    seen = record_evaluate(monkeypatch)
    scheduler = AsyncIOScheduler(timezone="UTC")
    jobs = build(scheduler, tmp_path, FakeClock(T0))
    asyncio.run(jobs[every].run())
    scheduled = scheduler.get_job(job_id)
    assert scheduled is not None
    asyncio.run(scheduled.func())
    assert seen == [(every, RuleContext(now=T0, tz=VN_TZ, cap_usd=12.0, warn_ratio=0.5))] * 2


def test_job_rule_sets_match_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # fmt: skip
    """U5. `evaluate` THẬT, mọi loader thay bằng bản giả ghi tên + trả `Pending`: tập luật mỗi job (phút, giờ, ngày, tuần
    — gọi qua `jobs[every].run()`) chạy BẰNG tập luật `REGISTRY` theo `every` và bằng hằng viết tay; bốn job phủ đúng
    `REGISTRY`. Luật giờ/ngày/tuần đều có loader thật. Job tuần báo luật 8 bỏ qua dưới tên của nó."""
    assert HOURLY_RULES | DAILY_RULES | WEEKLY_RULES <= set(LOADERS)
    called: list[str] = []

    def probe(rule_id: str) -> Any:
        async def load(conn: object, ctx: RuleContext) -> Pending:
            called.append(rule_id)
            return Pending("probe")

        return load

    for rule_id in REGISTRY:
        monkeypatch.setitem(LOADERS, rule_id, probe(rule_id))
    jobs = build(AsyncIOScheduler(timezone="UTC"), tmp_path, FakeClock(T0))
    ran: dict[str, set[str]] = {}
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for every in ("minute", "hourly", "daily", "weekly"):
            called.clear()
            asyncio.run(jobs[every].run())
            ran[every] = set(called)
            assert ran[every] == {r for r, spec in REGISTRY.items() if spec.every == every}, every
    assert f"{WEEKLY_ID}: luật bỏ qua (nguồn chưa có): drift" in [r.getMessage() for r in m9_records(caplog)]
    assert (ran["minute"], ran["hourly"], ran["daily"], ran["weekly"]) == (
        MINUTE_RULES, HOURLY_RULES, DAILY_RULES, WEEKLY_RULES,
    )  # fmt: skip
    assert ran["minute"] | ran["hourly"] | ran["daily"] | ran["weekly"] == set(REGISTRY)


# ---- U6–U9: lỗi không lan, ghi qua writer, tên job trong log ---------------------------------------------------------


def test_one_job_error_does_not_spread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """U6. Job giờ lỗi → không ném, 1 ERROR tên job + tên lớp (không traceback, không thông điệp); job phút, ngày và tuần
    vẫn ghi cảnh báo của mình. IncidentLog RIÊNG từng job: job phút lỗi cùng lớp vẫn báo ERROR lần đầu; job giờ phục hồi
    không xoá sự cố đang mở của job phút."""
    SpyWriter.built = []
    monkeypatch.setattr(worker, "AlertWriter", SpyWriter)
    plan: dict[str, EvalResult | BaseException] = {
        "minute": EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=[], skipped_rules=[]),
        "hourly": RuntimeError(f"hỏng {SECRET}"),
        "daily": EvalResult(drafts=[draft("reflex_approval", "l1-1")], failed_rules=[], skipped_rules=[]),
        "weekly": EvalResult(drafts=[draft("drift", "e3_rate")], failed_rules=[], skipped_rules=[]),
    }
    record_evaluate(monkeypatch, plan)
    clock = FakeClock(T0)
    jobs = build(AsyncIOScheduler(timezone="UTC"), tmp_path, clock)
    (writer,) = SpyWriter.built

    async def round_(*everys: str) -> None:
        for every in everys:
            await jobs[every].run()

    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        asyncio.run(round_("minute", "hourly", "daily", "weekly"))
        assert [r.getMessage() for r in m9_records(caplog, logging.ERROR)] == [
            f"{HOURLY_ID} lỗi: RuntimeError sqlstate=None"
        ]
        assert [d.subject for d in writer.written] == ["u-1", "l1-1", "e3_rate"]
        assert summaries(caplog) == [
            (logging.INFO, f"{MINUTE_ID}: nháp=1 ghi=1 trùng=0 lỗi=0 luật_lỗi=0"),
            (logging.INFO, f"{DAILY_ID}: nháp=1 ghi=1 trùng=0 lỗi=0 luật_lỗi=0"),
            (logging.INFO, f"{WEEKLY_ID}: nháp=1 ghi=1 trùng=0 lỗi=0 luật_lỗi=0"),
        ]
        clock.advance(MIN)
        plan["minute"] = RuntimeError(f"hỏng {SECRET}")
        plan["hourly"] = EvalResult(drafts=[], failed_rules=[], skipped_rules=[])
        asyncio.run(round_("minute", "hourly", "minute"))
    assert [r.getMessage() for r in m9_records(caplog, logging.ERROR)] == [
        f"{HOURLY_ID} lỗi: RuntimeError sqlstate=None",
        f"{MINUTE_ID} lỗi: RuntimeError sqlstate=None",
    ]
    recovered = [r.getMessage() for r in m9_records(caplog, logging.INFO) if "phục hồi" in r.getMessage()]
    assert recovered == [f"{HOURLY_ID} phục hồi sau 1 lượt lỗi"]
    assert all(r.exc_info is None and SECRET not in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("every", "job_id", "rule_id"), [("hourly", HOURLY_ID, "llm_budget"),
                                                          ("daily", DAILY_ID, "escalation_rate_high"),
                                                          ("weekly", WEEKLY_ID, "drift")])  # fmt: skip
def test_periodic_job_writes_via_writer_and_names_summary(
    every: str, job_id: str, rule_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    """U7. Draft của job giờ/ngày/tuần đi qua writer (`raise_once`); dòng tổng mang tên job của nó: lượt 1 `ghi=1` (INFO),
    lượt 2 cùng khoá → `trùng=1` (DEBUG)."""
    SpyWriter.built = []
    monkeypatch.setattr(worker, "AlertWriter", SpyWriter)
    d = draft(rule_id, "")
    record_evaluate(monkeypatch, {every: EvalResult(drafts=[d], failed_rules=[], skipped_rules=[])})
    jobs = build(AsyncIOScheduler(timezone="UTC"), tmp_path, FakeClock(T0))
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        asyncio.run(jobs[every].run())
        asyncio.run(jobs[every].run())
    assert SpyWriter.built[0].written == [d]
    assert summaries(caplog) == [
        (logging.INFO, f"{job_id}: nháp=1 ghi=1 trùng=0 lỗi=0 luật_lỗi=0"),
        (logging.DEBUG, f"{job_id}: nháp=1 ghi=0 trùng=1 lỗi=0 luật_lỗi=0"),
    ]


@pytest.mark.parametrize(("failing_id", "kept"), [
    (DAILY_ID, {MINUTE_ID, HOURLY_ID}),  # job tuần đăng ký SAU job ngày → không được đăng ký
    (WEEKLY_ID, {MINUTE_ID, HOURLY_ID, DAILY_ID}),
])  # fmt: skip
def test_setup_partial_failure_keeps_registered(
    failing_id: str, kept: set[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # fmt: skip
    """U8. Thứ tự đăng ký phút → giờ → ngày → tuần; đăng ký một job lỗi → các job đã đăng ký trước nó vẫn ở lại (gỡ ra
    là bỏ sót), cùng 3 job gốc; 1 ERROR chỉ tên lớp; trả None."""
    settings = settings_with(llm_yaml(tmp_path, 38.0, 0.8), tmp_path)
    scheduler = AsyncIOScheduler(timezone="UTC")
    schedule_jobs(scheduler, IdleJobs(), settings, FakeClock(T0))
    real_add_job = scheduler.add_job

    def add_job(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("id") == failing_id:
            raise RuntimeError(f"add_job hỏng {SECRET}")
        return real_add_job(*args, **kwargs)

    monkeypatch.setattr(scheduler, "add_job", add_job)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        assert setup_monitor_jobs(scheduler, settings, engines(FakeEngine()), FakeClock(T0)) is None
    assert {j.id for j in scheduler.get_jobs()} == CORE_IDS | kept
    errors = m9_records(caplog, logging.ERROR)
    assert len(errors) == 1 and "RuntimeError" in errors[0].getMessage()
    assert all(r.exc_info is None and SECRET not in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("every", "job_id"), [("hourly", HOURLY_ID), ("daily", DAILY_ID), ("weekly", WEEKLY_ID)])
def test_missing_monitor_engine_named_per_job(
    every: str, job_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """U9. Thiếu engine monitor → WARNING mang tên job giờ/ngày/tuần (không phải tên job phút), không chạy `evaluate`."""
    seen = record_evaluate(monkeypatch)
    jobs = setup_monitor_jobs(AsyncIOScheduler(timezone="UTC"), settings_with(REPO / "config", tmp_path),
                              engines(None), FakeClock(T0))  # fmt: skip
    assert jobs is not None
    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(jobs[cast(Any, every)].run())
    assert [r.getMessage() for r in m9_records(caplog, logging.WARNING)] == [
        f"{job_id}: thiếu MONITOR_DATABASE_URL — luật cảnh báo M9 KHÔNG chạy"
    ]
    assert seen == []
