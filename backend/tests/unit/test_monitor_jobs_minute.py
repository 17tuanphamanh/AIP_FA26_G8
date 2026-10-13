"""M9-B1 GĐ2 — job `monitor_rules_minute` (worker.py khối M9) và kiểm tĩnh loader `queries/rules_data.py`. Không DB.

Nguồn: file chia việc M9 mục 6 (B1); chốt Q-M9-B1-6, 12, 13, 15, 19 + 3 điều kiện duyệt GĐ2 ở #13. Job trên Postgres thật:
`tests/integration/test_monitor_jobs_minute_pg.py`.
"""

import ast
import asyncio
import inspect
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from app import worker
from app.core.clock import FakeClock
from app.db.models import INTENTS, SECURITY_EVENT_TYPES, SPAN_STATUSES, SPAN_TYPES
from app.db.session import Engines
from app.domain.alerts import AlertDraft
from app.domain.override import OVERRIDE_EVENT, OVERRIDE_STEP
from app.graph.runner import FINALIZE_FAILED
from app.llm.config import load_llm_config
from app.monitor.evaluator import LOADERS, EvalResult, Pending
from app.monitor.queries import rules_data
from app.monitor.queries.business import WeightedRate
from app.monitor.rules import LOOKBACK, REGISTRY, RuleContext
from app.monitor.window import VN_TZ
from app.settings import Settings
from app.tools.registry import CIRCUIT_OPEN
from app.worker import (
    MONITOR_RULES_MINUTE,
    MONITOR_RULES_SECONDS,
    MONITOR_RUN_TIMEOUT_SECONDS,
    IncidentLog,
    MonitorRulesJob,
    schedule_jobs,
    schedule_monitor_jobs,
    setup_monitor_jobs,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.elements import TextClause

REPO = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
SECRET = "giá-trị-nhạy-cảm-xyz"  # nằm trong detail của draft — không được lọt vào log

B1_RULES = {
    "injection_detected", "password_bruteforce", "refresh_reuse", "permission_denied_burst", "policy_saved",
    "finalize_failed", "execution_failed",
}  # fmt: skip
B2_MINUTE_RULES = {"e9_spike", "e6_spike", "breaker_open"}  # B2 GĐ2 cụm 1 (Q-M9-B2-2, 10)
MINUTE_RULES = B1_RULES | B2_MINUTE_RULES


# ---- đồ giả -----------------------------------------------------------------------------------------------------


class FakeEngine:
    """`connect()` trả context async; `fail` = exception ném khi mở connection (mô phỏng mất kết nối)."""

    def __init__(self, name: str = "monitor") -> None:
        self.name = name
        self.fail: BaseException | None = None
        self.connects = 0

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[object]:
        self.connects += 1
        if self.fail is not None:
            raise self.fail
        yield self


class FakeWriter:
    """Như `AlertWriter.raise_once`: True = dòng mới, False = khoá `(rule_id, subject, window_start)` đã có."""

    def __init__(self, fail_on: Callable[[AlertDraft], BaseException | None] = lambda d: None) -> None:
        self.written: list[AlertDraft] = []
        self._keys: set[tuple[str, str, datetime]] = set()
        self._fail_on = fail_on

    async def raise_once(self, draft: AlertDraft) -> bool:
        exc = self._fail_on(draft)
        if exc is not None:
            raise exc
        key = (draft.rule_id, draft.subject, draft.window_start)
        if key in self._keys:
            return False
        self._keys.add(key)
        self.written.append(draft)
        return True


class IdleJobs:
    async def scan_deadlines(self) -> None: ...
    async def scan_stale_turns(self) -> None: ...


def engines(monitor: FakeEngine | None, main: FakeEngine | None = None) -> Engines:
    main = main or FakeEngine("main")
    return Engines(main=cast(Any, main), lock=cast(Any, main), monitor=cast(Any, monitor))


def make_job(monitor: FakeEngine | None, clock: FakeClock, writer: FakeWriter | None = None,
             main: FakeEngine | None = None) -> MonitorRulesJob:  # fmt: skip
    return MonitorRulesJob(engines(monitor, main), writer or FakeWriter(), clock, cap_usd=38.0, warn_ratio=0.8)


def draft(rule_id: str, subject: str) -> AlertDraft:
    return AlertDraft(rule_id=rule_id, subject=subject, window_start=T0, severity="critical", detail={"x": SECRET})


def fake_evaluate(monkeypatch: pytest.MonkeyPatch, result: EvalResult | BaseException) -> list[RuleContext]:
    """Thay `evaluate` trong worker; trả danh sách ctx đã nhận."""
    seen: list[RuleContext] = []

    async def run(every: str, conn: object, ctx: RuleContext) -> EvalResult:
        assert every == "minute"
        seen.append(ctx)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(worker, "evaluate", run)
    return seen


def m9_records(caplog: pytest.LogCaptureFixture, level: int | None = None) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name == "app.worker" and (level is None or r.levelno == level)
    ]  # fmt: skip


def settings_with(config_dir: Path, tmp_path: Path) -> Settings:
    return Settings(worker_heartbeat_path=tmp_path / "hb", config_dir=config_dir)


def llm_yaml(tmp_path: Path, cap: float, warn: float) -> Path:
    cfg = yaml.safe_load((REPO / "config" / "llm.yaml").read_text(encoding="utf-8"))
    cfg["spend"].update(cap_usd=cap, warn_ratio=warn)
    out = tmp_path / "cfg"
    out.mkdir()
    (out / "llm.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return out


# ---- lịch job ---------------------------------------------------------------------------------------------------


class RecordingScheduler:
    """Ghi lại đúng tham số mỗi lần `add_job` — so bộ tham số job M9 với job gốc, không qua giá trị mặc định."""

    def __init__(self) -> None:
        self.calls: dict[str, dict[str, Any]] = {}

    def add_job(self, func: object, **kwargs: Any) -> None:
        self.calls[kwargs["id"]] = kwargs


def test_schedule_monitor_job_uses_same_options_as_core_jobs(tmp_path: Path) -> None:
    """Điều kiện duyệt 3: cùng bộ `common` của `schedule_jobs` (interval, max_instances=1, coalesce=True), KHÔNG thêm
    tham số — so trực tiếp với job gốc (chỉ khác id và chu kỳ); `schedule_jobs` vẫn đúng 3 job."""
    rec = RecordingScheduler()
    schedule_jobs(cast(Any, rec), IdleJobs(), settings_with(REPO / "config", tmp_path), FakeClock(T0))
    assert set(rec.calls) == {"heartbeat", "scan_deadlines", "scan_stale_turns"}
    schedule_monitor_jobs(cast(Any, rec), make_job(FakeEngine(), FakeClock(T0)))
    m9 = {k: v for k, v in rec.calls[MONITOR_RULES_MINUTE].items() if k not in ("id", "seconds")}
    for core_id in ("heartbeat", "scan_deadlines", "scan_stale_turns"):
        assert m9 == {k: v for k, v in rec.calls[core_id].items() if k not in ("id", "seconds")}, core_id
    assert m9 == {"trigger": "interval", "max_instances": 1, "coalesce": True}
    assert rec.calls[MONITOR_RULES_MINUTE]["seconds"] == 60


def test_schedule_monitor_job_on_real_scheduler(tmp_path: Path) -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    schedule_jobs(scheduler, IdleJobs(), settings_with(REPO / "config", tmp_path), FakeClock(T0))
    schedule_monitor_jobs(scheduler, make_job(FakeEngine(), FakeClock(T0)))
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"heartbeat", "scan_deadlines", "scan_stale_turns", MONITOR_RULES_MINUTE}
    assert jobs[MONITOR_RULES_MINUTE].trigger.interval == timedelta(seconds=60)


def test_setup_monitor_jobs_reads_llm_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`cap_usd`, `warn_ratio` đọc từ `<config_dir>/llm.yaml` ở WORKER; `now` từ Clock của app; tz = VN_TZ."""
    clock = FakeClock(T0)
    scheduler = AsyncIOScheduler(timezone="UTC")
    jobs = setup_monitor_jobs(scheduler, settings_with(llm_yaml(tmp_path, 12.0, 0.5), tmp_path), engines(FakeEngine()),
                              clock)  # fmt: skip
    # B3 cụm 4: setup đăng ký 4 job M9 theo thứ tự phút → giờ → ngày → tuần (giờ/ngày/tuần: test_monitor_jobs_periodic.py)
    assert jobs is not None
    assert [j.id for j in scheduler.get_jobs()] == [
        MONITOR_RULES_MINUTE, "monitor_rules_hourly", "monitor_rules_daily", "monitor_rules_weekly",
    ]  # fmt: skip
    seen = fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=[], skipped_rules=[]))
    asyncio.run(jobs["minute"].minute())
    assert seen == [RuleContext(now=T0, tz=VN_TZ, cap_usd=12.0, warn_ratio=0.5)]


@pytest.mark.parametrize("fault", ["missing", "schema", "add_job"])
def test_monitor_setup_error_keeps_three_jobs(
    fault: str, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Điều kiện duyệt 1: dựng M9 lỗi → worker vẫn đủ 3 job gốc, đúng 1 ERROR chỉ tên lớp. Ba nguồn lỗi (review #24 mục
    3): không có `llm.yaml` (OSError), `llm.yaml` sai schema (ValidationError — không phải OSError), `add_job` ném — bắt
    đột biến `except OSError` và `add_job` ra ngoài try. Thông điệp exception (có thể chứa giá trị cấu hình) không lọt log."""
    if fault == "missing":
        config_dir = tmp_path  # thư mục trống
    else:
        config_dir = llm_yaml(tmp_path, 38.0, 0.8)
        if fault == "schema":
            cfg = yaml.safe_load((config_dir / "llm.yaml").read_text(encoding="utf-8"))
            cfg["spend"]["cap_usd"] = SECRET
            (config_dir / "llm.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    settings = settings_with(config_dir, tmp_path)
    scheduler = AsyncIOScheduler(timezone="UTC")
    schedule_jobs(scheduler, IdleJobs(), settings, FakeClock(T0))
    if fault == "add_job":
        exc: Exception = RuntimeError(f"add_job hỏng {SECRET}")

        def broken_add_job(*args: object, **kwargs: object) -> None:
            raise exc

        monkeypatch.setattr(scheduler, "add_job", broken_add_job)
    else:
        try:
            load_llm_config(config_dir / "llm.yaml")
        except Exception as raised:  # noqa: BLE001 — lấy đúng exception mà worker gặp để so thông điệp
            exc = raised
        else:
            pytest.fail("cấu hình hỏng phải ném lỗi")
    expected_class = {"missing": "FileNotFoundError", "schema": "ValidationError", "add_job": "RuntimeError"}[fault]
    assert type(exc).__name__ == expected_class
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        assert setup_monitor_jobs(scheduler, settings, engines(FakeEngine()), FakeClock(T0)) is None
    assert {j.id for j in scheduler.get_jobs()} == {"heartbeat", "scan_deadlines", "scan_stale_turns"}
    errors = m9_records(caplog, logging.ERROR)
    assert len(errors) == 1 and expected_class in errors[0].getMessage()
    assert errors[0].exc_info is None
    assert all(str(exc) not in r.getMessage() and SECRET not in r.getMessage() for r in caplog.records)


def test_run_calls_setup_monitor_jobs_after_schedule_jobs() -> None:
    """Review #24 mục 3: xoá lời gọi `setup_monitor_jobs` trong `run()` thì worker chạy mà không có cảnh báo M9 — không
    test nào khác đỏ. Kiểm tĩnh: đúng 1 lời gọi mỗi hàm, M9 dựng SAU 3 job gốc, cùng scheduler/settings/engines/clock."""
    tree = ast.parse(inspect.getsource(worker.run))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    core = [c for c in calls if cast(ast.Name, c.func).id == "schedule_jobs"]
    m9 = [c for c in calls if cast(ast.Name, c.func).id == "setup_monitor_jobs"]
    assert len(core) == 1 and len(m9) == 1
    assert m9[0].lineno > core[0].lineno
    assert [ast.unparse(a) for a in m9[0].args] == ["scheduler", "settings", "engines", "clock"]


def test_setup_monitor_job_writes_via_main_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review #24 mục 3: job do `setup_monitor_jobs` dựng ghi `alerts` bằng `engines.main` (app_rw) — `app_monitor` chỉ
    đọc, ghi bằng nó thì mọi INSERT lỗi quyền. Test PG tự dựng writer nên không bắt được đột biến này."""

    class SpyWriter(FakeWriter):
        def __init__(self, engine: object, clock: object) -> None:
            super().__init__()
            self.engine = engine
            built.append(self)

    built: list[SpyWriter] = []
    main, lock, mon = FakeEngine("main"), FakeEngine("lock"), FakeEngine("monitor")
    monkeypatch.setattr(worker, "AlertWriter", SpyWriter)
    jobs = setup_monitor_jobs(AsyncIOScheduler(timezone="UTC"), settings_with(REPO / "config", tmp_path),
                              Engines(main=cast(Any, main), lock=cast(Any, lock), monitor=cast(Any, mon)),
                              FakeClock(T0))  # fmt: skip
    assert jobs is not None
    fake_evaluate(monkeypatch, EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=[], skipped_rules=[]))
    asyncio.run(jobs["minute"].minute())
    (writer,) = built  # MỘT writer dùng chung cho 4 job M9 (B2 GĐ2 cụm 3, B3 cụm 4)
    assert {id(j._writer) for j in jobs.values()} == {id(writer)}
    assert writer.engine is main
    assert [d.subject for d in writer.written] == ["u-1"]


# ---- thiếu engine monitor / job lỗi: nhịp log chung ----------------------------------------------------------------


def test_missing_monitor_engine_warns_first_then_hourly(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q-M9-B1-6: WARNING lần đầu, rồi mỗi 1 giờ (không mỗi 60 s); không ném, không đọc/ghi gì, KHÔNG rơi về main."""
    clock = FakeClock(T0)
    main = FakeEngine("main")
    writer = FakeWriter()
    job = make_job(None, clock, writer, main=main)
    seen = fake_evaluate(monkeypatch, AssertionError("evaluate không được chạy"))
    warnings: list[int] = []
    with caplog.at_level(logging.INFO, logger="app.worker"):
        for at in (0, 1, 59, 60, 61, 119, 120):
            clock.set(T0 + at * MIN)
            asyncio.run(job.minute())
            warnings.append(len(m9_records(caplog, logging.WARNING)))
    assert warnings == [1, 1, 1, 2, 2, 2, 3]
    assert "MONITOR_DATABASE_URL" in m9_records(caplog, logging.WARNING)[0].getMessage()
    assert seen == [] and writer.written == [] and main.connects == 0


def test_job_error_log_cadence(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q-M9-B1-19: ERROR ngay lần đầu và mỗi khi (tên lớp, SQLSTATE) đổi; cùng lỗi → nhắc mỗi giờ; lượt thành công đầu
    sau chuỗi lỗi → INFO "phục hồi sau N lượt lỗi". Chỉ tên lớp + SQLSTATE, không traceback, không thông điệp driver."""

    class Orig(Exception):
        def __init__(self, sqlstate: str) -> None:
            super().__init__(f"host=db-monitor port=5432 user=app_monitor {SECRET}")
            self.sqlstate = sqlstate

    clock = FakeClock(T0)
    mon = FakeEngine()
    job = make_job(mon, clock)
    fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=[], skipped_rules=[]))
    plan = [  # (phút, sqlstate hoặc None = kết nối được)
        (0, "08006"), (1, "08006"), (2, "28P01"), (3, "28P01"), (61, "28P01"), (62, "28P01"), (63, None), (64, None),
    ]  # fmt: skip
    errors: list[int] = []
    with caplog.at_level(logging.INFO, logger="app.worker"):
        for at, state in plan:
            clock.set(T0 + at * MIN)
            mon.fail = None if state is None else OperationalError("SELECT 1", {}, Orig(state))
            asyncio.run(job.minute())
            errors.append(len(m9_records(caplog, logging.ERROR)))
    assert errors == [1, 1, 2, 2, 2, 3, 3, 3]
    messages = [r.getMessage() for r in m9_records(caplog, logging.ERROR)]
    assert [m.split("sqlstate=")[1] for m in messages] == ["08006", "28P01", "28P01"]
    assert all("OperationalError" in m and SECRET not in m and "host=" not in m for m in messages)
    assert all(r.exc_info is None for r in m9_records(caplog, logging.ERROR))
    recovered = [r.getMessage() for r in m9_records(caplog, logging.INFO) if "phục hồi" in r.getMessage()]
    assert recovered == [f"{MONITOR_RULES_MINUTE} phục hồi sau 6 lượt lỗi"]  # đúng 1 lần, ở phút 63


def test_incident_log_without_sqlstate_key_change() -> None:
    """Exception không có `.orig` (không phải lỗi DB) → sqlstate None; đổi lớp exception cũng tính là sự cố mới."""
    clock = FakeClock(T0)
    inc = IncidentLog(clock)
    assert inc.failed(("TimeoutError", None)) is True
    assert inc.failed(("TimeoutError", None)) is False
    assert inc.failed(("OSError", None)) is True
    assert inc.recovered() == 3 and inc.recovered() == 0
    assert inc.failed(("OSError", None)) is True  # sau phục hồi: sự cố mới báo ngay


# ---- ghi từng draft --------------------------------------------------------------------------------------------------


def test_draft_write_error_does_not_block_others(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q-M9-B1-15: try/except TỪNG draft — draft 2 lỗi, draft 1 và 3 vẫn ghi. Log: rule_id + tên lớp, không traceback,
    không giá trị `detail`; cuối lượt 1 dòng tổng `nháp= ghi= trùng= lỗi= luật_lỗi=` (WARNING khi lỗi > 0)."""
    drafts = [draft("refresh_reuse", "u-1"), draft("injection_detected", "t-2"), draft("finalize_failed", "t-3")]
    writer = FakeWriter(lambda d: ValueError(f"hỏng {d.detail}") if d.subject == "t-2" else None)
    fake_evaluate(monkeypatch, EvalResult(drafts=drafts, failed_rules=[], skipped_rules=[]))
    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(make_job(FakeEngine(), FakeClock(T0), writer).minute())
    assert [d.subject for d in writer.written] == ["u-1", "t-3"]
    warnings = [r.getMessage() for r in m9_records(caplog, logging.WARNING)]
    assert warnings == [
        f"{MONITOR_RULES_MINUTE}: ghi cảnh báo luật injection_detected lỗi: ValueError",
        f"{MONITOR_RULES_MINUTE}: nháp=3 ghi=2 trùng=0 lỗi=1 luật_lỗi=0",
    ]
    assert all(r.exc_info is None and SECRET not in r.getMessage() for r in caplog.records)


def draft_lines(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    """Dòng "ghi cảnh báo luật … lỗi" ở đúng mức `level`, theo thứ tự."""
    return [r.getMessage() for r in m9_records(caplog, level) if "ghi cảnh báo luật" in r.getMessage()]


def write_error(rule_id: str, exc: str) -> str:
    return f"{MONITOR_RULES_MINUTE}: ghi cảnh báo luật {rule_id} lỗi: {exc}"


def test_draft_write_warning_paced(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q-M9-B1-24: một draft hỏng không còn in WARNING mỗi phút suốt 24 giờ. Theo (rule_id, tên lớp): WARNING lần đầu,
    khi lớp đổi, qua 1 giờ, và ngay sau một lượt ghi được; còn lại DEBUG. Dòng tổng `lỗi=` vẫn đếm mọi lượt."""
    clock = FakeClock(T0)
    fail: list[BaseException | None] = [None]
    writer = FakeWriter(lambda d: fail[0])
    job = make_job(FakeEngine(), clock, writer)
    fake_evaluate(monkeypatch, EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=[], skipped_rules=[]))
    plan: list[tuple[int, type[Exception] | None]] = [  # (phút, lỗi ghi; None = ghi được)
        (0, ValueError), (1, ValueError), (59, ValueError), (60, ValueError), (61, ValueError), (62, None),
        (63, ValueError), (64, OSError), (65, OSError),
    ]  # fmt: skip
    warned: list[int] = []
    debugged: list[int] = []
    counted: list[str] = []
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for at, exc in plan:
            clock.set(T0 + at * MIN)
            caplog.clear()
            fail[0] = None if exc is None else exc(f"hỏng {SECRET}")
            asyncio.run(job.minute())
            warned.append(len(draft_lines(caplog, logging.WARNING)))
            debugged.append(len(draft_lines(caplog, logging.DEBUG)))
            ((_, message),) = summaries(caplog)
            counted.append(message.split(" lỗi=")[1].split()[0])
            assert all(r.exc_info is None and SECRET not in r.getMessage() for r in caplog.records)
    assert warned == [1, 0, 0, 1, 0, 0, 1, 1, 0]
    assert debugged == [0, 1, 1, 0, 1, 0, 0, 0, 1]
    assert counted == ["1", "1", "1", "1", "1", "0", "1", "1", "1"]


def test_draft_write_warning_paced_per_rule_in_run(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q-M9-B1-24: hai luật cùng lớp lỗi → hai WARNING (khoá có rule_id); hai draft cùng luật cùng lớp trong một lượt →
    dòng log y hệt nên 1 WARNING + 1 DEBUG; `lỗi=` vẫn đếm đủ 3. Lượt sau cùng lỗi → chỉ DEBUG."""
    drafts = [draft("refresh_reuse", "u-1"), draft("refresh_reuse", "u-2"), draft("injection_detected", "t-3"),
              draft("finalize_failed", "t-4")]  # fmt: skip
    writer = FakeWriter(lambda d: None if d.subject == "t-4" else ValueError(f"hỏng {d.detail}"))
    clock = FakeClock(T0)
    job = make_job(FakeEngine(), clock, writer)
    fake_evaluate(monkeypatch, EvalResult(drafts=drafts, failed_rules=[], skipped_rules=[]))
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        asyncio.run(job.minute())
        assert draft_lines(caplog, logging.WARNING) == [
            write_error("refresh_reuse", "ValueError"), write_error("injection_detected", "ValueError"),
        ]  # fmt: skip
        assert draft_lines(caplog, logging.DEBUG) == [write_error("refresh_reuse", "ValueError")]
        assert summaries(caplog) == [(logging.WARNING, summary(4, 1, 0, 3, 0))]
        assert all(r.exc_info is None and SECRET not in r.getMessage() for r in caplog.records)
        caplog.clear()
        clock.set(T0 + MIN)
        asyncio.run(job.minute())
        assert draft_lines(caplog, logging.WARNING) == []
        assert draft_lines(caplog, logging.DEBUG) == [
            write_error("refresh_reuse", "ValueError"), write_error("refresh_reuse", "ValueError"),
            write_error("injection_detected", "ValueError"),
        ]  # fmt: skip
        assert summaries(caplog) == [(logging.WARNING, summary(4, 0, 1, 3, 0))]
    assert all(r.exc_info is None and SECRET not in r.getMessage() for r in caplog.records)


def test_summary_info_when_no_error(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_evaluate(monkeypatch, EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=[], skipped_rules=[]))
    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(make_job(FakeEngine(), FakeClock(T0)).minute())
    assert [r.getMessage() for r in m9_records(caplog, logging.INFO)] == [
        f"{MONITOR_RULES_MINUTE}: nháp=1 ghi=1 trùng=0 lỗi=0 luật_lỗi=0"
    ]
    assert m9_records(caplog, logging.WARNING) == []


def summaries(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    """(mức, nội dung) các dòng tổng của job, theo thứ tự."""
    return [(r.levelno, r.getMessage()) for r in m9_records(caplog) if "nháp=" in r.getMessage()]


def summary(n: int, written: int, duplicate: int, errors: int, failed: int) -> str:
    return f"{MONITOR_RULES_MINUTE}: nháp={n} ghi={written} trùng={duplicate} lỗi={errors} luật_lỗi={failed}"


def test_summary_counts_only_new_alerts(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """`ghi` = số cảnh báo MỚI (`raise_once` trả True), `trùng` = khoá đã có (False). Job quét lại 24 giờ mỗi phút →
    lượt sau gặp lại đúng các draft cũ → `ghi=0 trùng=2` ở DEBUG, không phải `ghi=2` mỗi phút."""
    old = [draft("refresh_reuse", "u-1"), draft("injection_detected", "t-2")]
    writer = FakeWriter()
    job = make_job(FakeEngine(), FakeClock(T0), writer)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        fake_evaluate(monkeypatch, EvalResult(drafts=old, failed_rules=[], skipped_rules=[]))
        asyncio.run(job.minute())
        asyncio.run(job.minute())
        fake_evaluate(monkeypatch, EvalResult(drafts=[*old, draft("finalize_failed", "t-3")], failed_rules=[],
                                              skipped_rules=[]))  # fmt: skip
        asyncio.run(job.minute())
    assert summaries(caplog) == [
        (logging.INFO, summary(2, 2, 0, 0, 0)),
        (logging.DEBUG, summary(2, 0, 2, 0, 0)),
        (logging.INFO, summary(3, 1, 2, 0, 0)),
    ]
    assert len(writer.written) == 3


def test_summary_three_cases_distinct(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review #24 mục 1: 0 draft / 37 draft đều đã có / 7/7 luật lỗi trước đây cùng in `ghi=0 lỗi=0` ở INFO. Sau lượt
    khởi động, ba tình huống phải ra ba dòng tổng KHÁC nhau: hai lượt "không có gì mới" ở DEBUG, luật lỗi ở WARNING."""
    old = [draft("refresh_reuse", f"u-{i}") for i in range(37)]
    writer = FakeWriter()
    job = make_job(FakeEngine(), FakeClock(T0), writer)
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        fake_evaluate(monkeypatch, EvalResult(drafts=old, failed_rules=[], skipped_rules=[]))
        asyncio.run(job.minute())  # khởi động: 37 cảnh báo mới
        caplog.clear()
        cases: list[EvalResult] = [
            EvalResult(drafts=[], failed_rules=[], skipped_rules=[]),
            EvalResult(drafts=old, failed_rules=[], skipped_rules=[]),
            EvalResult(drafts=[], failed_rules=sorted(B1_RULES), skipped_rules=[]),
        ]
        for result in cases:
            fake_evaluate(monkeypatch, result)
            asyncio.run(job.minute())
    assert summaries(caplog) == [
        (logging.DEBUG, summary(0, 0, 0, 0, 0)),
        (logging.DEBUG, summary(37, 0, 37, 0, 0)),
        (logging.WARNING, summary(0, 0, 0, 0, 7)),
    ]
    assert len(writer.written) == 37


def test_first_run_info_then_debug(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nhịp log (review #24 mục 1): lượt chạy được đầu tiên sau khi worker lên → INFO (D5 thấy job chạy, dù 0 draft);
    lượt không có gì mới → DEBUG; lượt có cảnh báo mới → INFO."""
    empty = EvalResult(drafts=[], failed_rules=[], skipped_rules=[])
    job = make_job(FakeEngine(), FakeClock(T0))
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for result in (empty, empty, EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=[],
                                                skipped_rules=[]), empty):  # fmt: skip
            fake_evaluate(monkeypatch, result)
            asyncio.run(job.minute())
    assert [level for level, _ in summaries(caplog)] == [logging.INFO, logging.DEBUG, logging.INFO, logging.DEBUG]


def test_failed_rules_not_recovery_and_cadence(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review #24 mục 1: lượt có luật lỗi KHÔNG phải lượt thành công — không "phục hồi". `failed_rules` đi qua
    IncidentLog, key = TẬP tên luật: báo lần đầu, khi tập đổi (thứ tự khác không tính), rồi mỗi giờ. Hết luật lỗi →
    phục hồi, đếm cả lượt lỗi kết nối lẫn lượt luật lỗi."""

    class Orig(Exception):
        sqlstate = "08006"

    clock = FakeClock(T0)
    mon = FakeEngine()
    job = make_job(mon, clock)
    rules = sorted(B1_RULES)
    plan: list[tuple[int, list[str] | None]] = [  # (phút, luật lỗi; None = mất kết nối)
        (0, None), (1, rules), (2, rules[::-1]), (3, rules[:1]), (63, rules[:1]), (64, []),
    ]  # fmt: skip
    rule_warnings: list[int] = []
    errors: list[int] = []
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for at, failed in plan:
            clock.set(T0 + at * MIN)
            mon.fail = OperationalError("SELECT 1", {}, Orig()) if failed is None else None
            fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=failed or [], skipped_rules=[]))
            asyncio.run(job.minute())
            rule_warnings.append(len([r for r in m9_records(caplog, logging.WARNING) if "luật lỗi:" in r.getMessage()]))
            errors.append(len(m9_records(caplog, logging.ERROR)))
    assert rule_warnings == [0, 1, 1, 2, 3, 3]
    assert errors == [1, 1, 1, 1, 1, 1]
    recovered = [r.getMessage() for r in m9_records(caplog) if "phục hồi" in r.getMessage()]
    assert recovered == [f"{MONITOR_RULES_MINUTE} phục hồi sau 5 lượt lỗi"]  # đúng 1 lần, ở phút 64
    assert [r.levelno for r in m9_records(caplog) if "phục hồi" in r.getMessage()] == [logging.INFO]


def test_summary_level_cadence_failed_rules(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q-M9-B1-20: luật lỗi không còn nâng dòng tổng lên WARNING mỗi lượt — chỉ ở lượt IncidentLog báo (lần đầu, tập luật
    lỗi đổi, qua 1 giờ), trùng đúng với dòng "luật lỗi:". Các lượt còn lại (0 draft) → DEBUG. Thứ tự tên luật khác nhau
    không phải tập đổi."""
    clock = FakeClock(T0)
    job = make_job(FakeEngine(), clock)
    a = sorted(B1_RULES)
    plan: list[tuple[int, list[str]]] = [  # (phút, tập luật lỗi)
        (0, a), (1, a), (2, a[::-1]), (3, a), (4, a[:1]), (5, a[:1]), (64, a[:1]), (65, a[:1]),
    ]  # fmt: skip
    levels: list[int] = []
    rule_lines: list[int] = []
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for at, failed in plan:
            clock.set(T0 + at * MIN)
            caplog.clear()
            fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=failed, skipped_rules=[]))
            asyncio.run(job.minute())
            ((level, message),) = summaries(caplog)
            assert message == summary(0, 0, 0, 0, len(failed))
            levels.append(level)
            rule_lines.append(len([r for r in m9_records(caplog, logging.WARNING) if "luật lỗi:" in r.getMessage()]))
    W, D = logging.WARNING, logging.DEBUG  # viết tắt cho bảng mức
    assert levels == [W, D, D, D, W, D, W, D]
    assert rule_lines == [1, 0, 0, 0, 1, 0, 1, 0]  # dòng tổng WARNING đúng ở lượt có dòng "luật lỗi:"


@pytest.mark.parametrize("with_failed_rules", [False, True])
def test_summary_warning_every_run_when_write_errors(
    with_failed_rules: bool, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`lỗi > 0` → dòng tổng WARNING MỌI lượt, không phụ thuộc IncidentLog. Ca có luật lỗi: lượt 2, 3 IncidentLog không
    báo nhưng lỗi ghi vẫn giữ WARNING."""
    clock = FakeClock(T0)
    writer = FakeWriter(lambda d: ValueError("hỏng"))
    job = make_job(FakeEngine(), clock, writer)
    failed = ["refresh_reuse"] if with_failed_rules else []
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for at in (0, 1, 2):
            clock.set(T0 + at * MIN)
            fake_evaluate(monkeypatch, EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=failed,
                                                  skipped_rules=[]))  # fmt: skip
            asyncio.run(job.minute())
    assert summaries(caplog) == [(logging.WARNING, summary(1, 0, 0, 1, len(failed)))] * 3
    assert len([r for r in m9_records(caplog, logging.WARNING) if "luật lỗi:" in r.getMessage()]) == len(failed)


def test_summary_info_when_failed_rules_unreported_but_written(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q-M9-B2-8 (mặc định, chờ anh Tuấn Anh xác nhận): luật lỗi mà IncidentLog KHÔNG báo + có cảnh báo mới → INFO (cảnh
    báo mới phải thấy, WARNING sẽ phá nhịp đã giãn); lượt sau chỉ còn trùng → DEBUG. Lượt đầu (IncidentLog báo) → WARNING."""
    clock = FakeClock(T0)
    job = make_job(FakeEngine(), clock)
    failed = ["policy_saved"]
    new = [draft("refresh_reuse", "u-1")]
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for at, drafts in ((0, []), (1, new), (2, new)):
            clock.set(T0 + at * MIN)
            fake_evaluate(monkeypatch, EvalResult(drafts=drafts, failed_rules=failed, skipped_rules=[]))
            asyncio.run(job.minute())
    assert summaries(caplog) == [
        (logging.WARNING, summary(0, 0, 0, 0, 1)),
        (logging.INFO, summary(1, 1, 0, 0, 1)),
        (logging.DEBUG, summary(1, 0, 1, 0, 1)),
    ]
    assert [r.getMessage() for r in m9_records(caplog) if "luật lỗi:" in r.getMessage()] == [
        f"{MONITOR_RULES_MINUTE}: luật lỗi: policy_saved"
    ]  # chỉ ở lượt 0


# ---- timeout một lượt ------------------------------------------------------------------------------------------------


def test_run_timeout_constant() -> None:
    assert 0 < MONITOR_RUN_TIMEOUT_SECONDS < MONITOR_RULES_SECONDS


@pytest.mark.parametrize("hang", ["evaluate", "writer"])
def test_run_timeout_then_next_run_ok(
    hang: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review #24 mục 2: truy vấn treo + `max_instances=1` → mọi lượt sau bị bỏ, tầng cảnh báo chết im lặng. Một lượt
    bị chặn bởi timeout bọc CẢ đọc (`evaluate`) lẫn ghi (`raise_once`) → ERROR `TimeoutError`, lượt sau chạy bình
    thường. `wait_for` 2 s là lưới an toàn: bỏ timeout thì test đỏ chứ không treo."""
    runs = 0

    async def forever() -> None:
        await asyncio.Event().wait()

    async def run_evaluate(every: str, conn: object, ctx: RuleContext) -> EvalResult:
        if hang == "evaluate" and runs == 1:
            await forever()
        return EvalResult(drafts=[draft("refresh_reuse", f"u-{runs}")], failed_rules=[], skipped_rules=[])

    class HangingWriter(FakeWriter):
        async def raise_once(self, d: AlertDraft) -> bool:
            if hang == "writer" and runs == 1:
                await forever()
            return await super().raise_once(d)

    monkeypatch.setattr(worker, "evaluate", run_evaluate)
    writer = HangingWriter()
    job = MonitorRulesJob(engines(FakeEngine()), writer, FakeClock(T0), cap_usd=38.0, warn_ratio=0.8, timeout_s=0.05)

    async def one_run() -> None:
        nonlocal runs
        runs += 1
        await asyncio.wait_for(job.minute(), 2)

    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        asyncio.run(one_run())
        assert [r.getMessage() for r in m9_records(caplog, logging.ERROR)] == [
            f"{MONITOR_RULES_MINUTE} lỗi: TimeoutError sqlstate=None"
        ]
        assert summaries(caplog) == [] and writer.written == []
        asyncio.run(one_run())
    assert len(m9_records(caplog, logging.ERROR)) == 1
    assert [d.subject for d in writer.written] == ["u-2"]
    assert f"{MONITOR_RULES_MINUTE} phục hồi sau 1 lượt lỗi" in [r.getMessage() for r in m9_records(caplog)]
    assert summaries(caplog) == [(logging.INFO, summary(1, 1, 0, 0, 0))]


def test_failed_and_skipped_rules_logged_by_name(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=["refresh_reuse", "policy_saved"],
                                          skipped_rules=["b3_degraded"]))  # fmt: skip
    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(make_job(FakeEngine(), FakeClock(T0)).minute())
    messages = [r.getMessage() for r in m9_records(caplog)]
    assert f"{MONITOR_RULES_MINUTE}: luật lỗi: refresh_reuse, policy_saved" in messages
    assert f"{MONITOR_RULES_MINUTE}: luật bỏ qua (nguồn chưa có): b3_degraded" in messages


def test_skipped_rules_line_cadence(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q-M9-B1-24 + luật cứng 7: dòng "luật bỏ qua (nguồn chưa có)" INFO khi TẬP luật bỏ qua đổi (kể cả xuất hiện lại
    sau một lượt rỗng); cùng tập (thứ tự khác không tính) → DEBUG, qua 1 giờ cũng không nhắc (nguồn chưa có là trạng
    thái đã biết). Luật bỏ qua không nâng mức dòng tổng."""
    clock = FakeClock(T0)
    job = make_job(FakeEngine(), clock)
    b2, b3 = "b2_degraded", "b3_degraded"
    plan: list[tuple[int, list[str]]] = [  # (phút, luật bỏ qua)
        (0, [b3]), (1, [b3]), (2, [b3]), (3, [b2, b3]), (4, [b3, b2]), (65, [b3, b2]), (66, []), (67, [b3, b2]),
    ]  # fmt: skip
    lines: list[list[tuple[int, str]]] = []
    levels: list[int] = []
    with caplog.at_level(logging.DEBUG, logger="app.worker"):
        for at, skipped in plan:
            clock.set(T0 + at * MIN)
            caplog.clear()
            fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=[], skipped_rules=skipped))
            asyncio.run(job.minute())
            lines.append([(r.levelno, r.getMessage()) for r in m9_records(caplog) if "luật bỏ qua" in r.getMessage()])
            ((level, _),) = summaries(caplog)
            levels.append(level)
    I, D = logging.INFO, logging.DEBUG  # viết tắt cho bảng mức
    line = f"{MONITOR_RULES_MINUTE}: luật bỏ qua (nguồn chưa có): "
    assert lines == [
        [(I, line + "b3_degraded")],
        [(D, line + "b3_degraded")],
        [(D, line + "b3_degraded")],
        [(I, line + "b2_degraded, b3_degraded")],
        [(D, line + "b3_degraded, b2_degraded")],
        [(D, line + "b3_degraded, b2_degraded")],
        [],
        [(I, line + "b3_degraded, b2_degraded")],
    ]
    assert levels == [I, D, D, D, D, D, D, D]  # lượt 1 INFO vì là lượt chạy được đầu tiên


@pytest.mark.parametrize("where", ["connect", "evaluate", "writer"])
def test_cancelled_error_propagates(where: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hủy job (tắt worker) phải lan ra — không bị `except Exception` nuốt ở bất kỳ lớp nào."""
    mon = FakeEngine()
    writer = FakeWriter(lambda d: asyncio.CancelledError() if where == "writer" else None)
    if where == "connect":
        mon.fail = asyncio.CancelledError()
    fake_evaluate(monkeypatch, asyncio.CancelledError() if where == "evaluate" else
                  EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=[], skipped_rules=[]))  # fmt: skip
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(make_job(mon, FakeClock(T0), writer).minute())


def test_job_reads_via_monitor_engine_not_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đọc qua `monitor_engine(engines)` (role app_monitor), không bao giờ engine chính. Bản Postgres (kiểm
    `current_user`): `test_monitor_jobs_minute_pg.py::test_job_reads_via_app_monitor`."""
    main, mon = FakeEngine("main"), FakeEngine("monitor")
    fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=[], skipped_rules=[]))
    asyncio.run(make_job(mon, FakeClock(T0), main=main).minute())
    assert (mon.connects, main.connects) == (1, 0)


# ---- loader rules_data: đăng ký + kiểm tĩnh + tham số bind -------------------------------------------------------------


def test_every_minute_rule_has_loader() -> None:
    """Worker import `rules_data` → mọi luật `minute` có loader (thiếu → MissingLoaderError → failed_rules mỗi phút).
    B2 GĐ2 cụm 1: luật 4, 5, 6 đăng ký `minute` CÙNG commit với loader (Q-M9-B2-10)."""
    minute = {r for r, spec in REGISTRY.items() if spec.every == "minute"}
    assert minute == MINUTE_RULES
    assert minute <= set(LOADERS)
    assert {LOADERS[r].__module__ for r in B2_MINUTE_RULES} == {rules_data.__name__}
    assert "from app.monitor.queries import rules_data" in inspect.getsource(worker)


def _sql() -> dict[str, str]:
    found = {name: clause.text for name, clause in vars(rules_data).items() if isinstance(clause, TextClause)}
    # quét không rỗng; luật 4/6 dùng lại TICKET_EXIT_SQL, luật 5 thêm TOOL_SPAN_SQL; luật 14 LLM_SPEND_SQL, luật 7
    # REFLEX_SQL (luật 1, 12, 13 gọi hàm của luồng A, không có SQL riêng); B3 luật 8: 5 câu đếm bin DRIFT_* (escalation
    # gọi hàm A1, không có SQL riêng)
    assert len(found) == 13
    return found


_UNWRITTEN_COLUMNS = ("confidence", "query", "success", "action_plan_hash_matched")  # kế hoạch chung 1.4
_JSON_KEY = re.compile(r"->>?\s*'[^']*'")  # truy cập khoá JSON `->'k'` / `->>'k'` — khoá JSON không phải cột
# Q-M9-B3-15 [Đề xuất] — miễn trừ ĐÍCH DANH kiểm `<`: Q-M9-B1-12 cấm chặn trên THEO `now` ở luật sự kiện (sự kiện có thời
# điểm sau `now` do lệch đồng hồ vẫn phải được đọc). Cửa sổ drift là tuần ĐÃ KHÉP `[frm, to)`, `to` là mốc tuần cố định
# tính từ `week_start`, không phải `now`; biểu thức bin top_score cần `< 0`. Kiểm không có `:now` vẫn áp cho TẤT CẢ.
DRIFT_SQL = {"DRIFT_INTENT_SQL", "DRIFT_CONFIDENCE_SQL", "DRIFT_TOP_SCORE_SQL", "DRIFT_DONE_SQL", "DRIFT_OVERRIDE_SQL"}
# Q-M9-B3-16 [Đề xuất] — miễn trừ ĐÍCH DANH kiểm `::`: `::numeric` chỉ trong nhánh THEN sau `jsonb_typeof(...) = 'number'`
# (số JSONB luôn ép được → không có lỗi ép kiểu in giá trị). `cast(` vẫn cấm cho tất cả.
DRIFT_CAST_SQL = {"DRIFT_CONFIDENCE_SQL": "confidence", "DRIFT_TOP_SCORE_SQL": "top_score"}


def test_rules_data_only_select() -> None:
    """Chỉ SELECT; không đụng bảng `tickets` trực tiếp (đếm qua `v_leaf`); không đọc 4 cột chưa ghi; KHÔNG chặn trên
    theo `now` (Q-M9-B1-12 — không có `<`, không có tham số `now`); luật 2/16 (và 4/6, cùng SQL) qua `v_leaf`, luật 15
    thì không. Luật 5 đọc `spans`, không lọc lá (Q-M9-B2-22: breaker là sự cố hệ thống, không phải đếm ticket).
    Luật 14: tổng toàn bảng `llm_calls` — không cửa sổ, không nối, không `v_leaf` (Q-M9-6, như `spend_total`). Luật 7: gốc
    `approvals`, không lọc lá (Q-M9-B2-24, chốt PR #31: luật đếm phiếu, không đếm ticket).
    B3 luật 8: miễn trừ đích danh `DRIFT_SQL` khỏi kiểm `<` (Q-M9-B3-15) và `DRIFT_CAST_SQL` khỏi kiểm `::` (Q-M9-B3-16),
    kèm kiểm dương; kiểm cột chưa ghi bỏ qua truy cập khoá JSON (`detail->'confidence'` không phải cột `confidence`)."""
    sql = _sql()
    assert DRIFT_SQL <= set(sql) and set(DRIFT_CAST_SQL) <= DRIFT_SQL  # gõ sai tên miễn trừ → đỏ
    for name, body in sql.items():
        words = body.lower()
        columns = _JSON_KEY.sub("", words)
        assert words.strip().startswith("select"), name
        assert not re.search(r"\b(insert|update|delete|truncate|create|alter|drop|grant)\b", words), name
        assert not re.search(r"\btickets\b", words), name
        assert not [c for c in _UNWRITTEN_COLUMNS if re.search(rf"\b{c}\b", columns)], name
        assert "a.confidence" not in words, name
        assert ":now" not in body, name
        if name not in DRIFT_SQL:
            assert "<" not in body, name
        assert "cast(" not in words, name
        if name not in DRIFT_CAST_SQL:
            assert "::" not in body, name  # không ép kiểu dữ liệu JSON
    for name in DRIFT_SQL:  # chặn trên chỉ là mốc tuần `:to`; `<` khác chỉ là so bin `< 0`
        assert "t.created_at < :to" in sql[name], name
        assert set(re.findall(r"<\s*[^\s)]+", sql[name].replace("t.created_at < :to", ""))) <= {"< 0"}, name
    for name, key in DRIFT_CAST_SQL.items():
        body, guard = sql[name], f"jsonb_typeof(a.detail->'{key}') = 'number' THEN"
        assert body.count(guard) == 1 and body.count("jsonb_typeof") == 1, name
        assert body.count("::") == body.count("::numeric") >= 1, name
        assert body.index(guard) < body.index("::numeric"), name
    assert "detail->'confidence'" in sql["DRIFT_CONFIDENCE_SQL"]
    assert "v_leaf" in sql["TICKET_EXIT_SQL"]
    assert "v_leaf" not in sql["FINALIZE_FAILED_SQL"]
    assert "from spans" in sql["TOOL_SPAN_SQL"].lower() and "v_leaf" not in sql["TOOL_SPAN_SQL"]
    spend = sql["LLM_SPEND_SQL"].lower()
    assert "from llm_calls" in spend and not re.search(r"\b(where|join|v_leaf)\b", spend)
    assert "from approvals" in sql["REFLEX_SQL"].lower() and "v_leaf" not in sql["REFLEX_SQL"]


class RecordingConn:
    """Ghi lại (câu SQL, tham số bind) của loader; trả 0 dòng."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, clause: TextClause, params: dict[str, Any]) -> list[Any]:
        self.calls.append((clause.text, params))
        return []


_ALLOWED_BINDS = {
    "since", "code", "step", "event", "event_type", "reason", "rule_id", "span_type", "status", "error", "decisions",
}  # fmt: skip


@pytest.mark.parametrize("rule_id", sorted(B1_RULES))
def test_loader_binds_only_time_and_constants(rule_id: str) -> None:
    """Tham số bind chỉ là mốc thời gian + hằng code (lỗi SQL in `[parameters]` → không lộ dữ liệu); mọi mốc tính từ
    `ctx.now`: lookback 24 giờ, luật 10 lùi thêm 5 phút, luật 3 đọc `alerts` lùi thêm 60 s; event type có thật."""
    conn = RecordingConn()
    ctx = RuleContext(now=T0, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)
    asyncio.run(LOADERS[rule_id](cast(Any, conn), ctx))
    assert conn.calls
    since = T0 - LOOKBACK
    expected = {
        "permission_denied_burst": [since - timedelta(minutes=5)],
        "password_bruteforce": [since, since - timedelta(seconds=60)],
    }.get(rule_id, [since])
    assert [params["since"] for _, params in conn.calls] == expected
    for _, params in conn.calls:
        assert set(params) <= _ALLOWED_BINDS
        assert all(isinstance(v, str | datetime) for v in params.values())
        if "event_type" in params:
            assert params["event_type"] in SECURITY_EVENT_TYPES


def test_bruteforce_loader_filters_threshold_and_rule_id() -> None:
    """Luật 3: chỉ `account_locked` có reason `threshold` (`still_locked` không đối soát); alerts lọc rule_id ở SQL
    (Q-M9-B1-13) — luật vẫn tự kiểm."""
    conn = RecordingConn()
    asyncio.run(LOADERS["password_bruteforce"](cast(Any, conn), RuleContext(T0, VN_TZ, 38.0, 0.8)))
    (_, locks), (_, alerts) = conn.calls
    assert (locks["event_type"], locks["reason"]) == ("account_locked", "threshold")
    assert alerts["rule_id"] == "password_bruteforce"


def test_alerts_sql_filters_rule_id() -> None:
    """Review #24: test trên chỉ thấy tham số bind — bỏ `rule_id = :rule_id` khỏi WHERE (bind thừa vẫn truyền) thì vẫn
    xanh. Ghim mệnh đề trong SQL; luật 3 vẫn tự kiểm rule_id (lưới thứ hai, `test_monitor_rules_event.py`)."""
    assert re.search(r"WHERE\s+rule_id = :rule_id AND", rules_data.ALERTS_SQL.text)


def test_finalize_event_constant_matches_runner() -> None:
    """`monitor` không import `graph` → hằng sao chép; lệch tên event là luật 15 câm lặng (FN)."""
    assert rules_data.FINALIZE_FAILED_EVENT == FINALIZE_FAILED
    assert rules_data.FINALIZE_FAILED_STEP == "B20"


def test_policy_saved_loader_does_not_call_is_pending() -> None:
    """Chốt 02/10 (#13): `is_pending("policy_saved")` ném KeyError → luật 11 vào failed_rules mỗi phút. Loader chạy
    truy vấn thật; chưa có nơi ghi → 0 sự kiện. B2: module nay import `is_pending` (luật 5) → chỉ quét hàm loader 11;
    toàn module xem `test_only_pending_source_loaders_call_is_pending`."""
    tree = ast.parse(inspect.getsource(rules_data.load_policy_saved))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert {"_events", "LOOKBACK"} <= names  # quét không rỗng
    assert "is_pending" not in names
    conn = RecordingConn()
    out = asyncio.run(LOADERS["policy_saved"](cast(Any, conn), RuleContext(T0, VN_TZ, 38.0, 0.8)))
    assert out == [] and conn.calls[0][1]["event_type"] == "policy_saved"


# ---- loader B2 luật 60 s: 4 e9_spike, 6 e6_spike, 5 breaker_open (Q-M9-B2-2, 5, 10, 12; Q-M9-4) ---------------------

# T0 = 2026-10-02T08:00Z → giờ cũ nhất được đánh giá 2026-10-01T08:00Z (24 giờ trước) → trừ 168 giờ (tính tay).
SPIKE_SINCE_T0 = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(("rule_id", "code"), [("e9_spike", "E9"), ("e6_spike", "E6")])
def test_spike_loader_binds_own_code(rule_id: str, code: str) -> None:
    """Q-M9-B2-5: loader 4/6 dùng lại `TICKET_EXIT_SQL` (`first_at` qua `v_leaf`) với ĐÚNG mã của luật; mốc dưới =
    `spike_since(ctx)` (đủ trung vị 168 giờ cho giờ cũ nhất), không phải `now − 24 giờ`."""
    conn = RecordingConn()
    out = asyncio.run(LOADERS[rule_id](cast(Any, conn), RuleContext(T0, VN_TZ, 38.0, 0.8)))
    assert out == []
    [(sql, params)] = conn.calls
    assert sql == rules_data.TICKET_EXIT_SQL.text
    assert params == {"code": code, "since": SPIKE_SINCE_T0}


def test_breaker_loader_pending_no_sql() -> None:
    """Luật 5: nguồn `tool_spans` pending (span tool chưa ghi DB, Q-M9-4) → `Pending`, KHÔNG chạy SQL (luật vào
    `skipped_rules`, không báo, không đoán)."""
    conn = RecordingConn()
    out = asyncio.run(LOADERS["breaker_open"](cast(Any, conn), RuleContext(T0, VN_TZ, 38.0, 0.8)))
    assert out == Pending("tool_spans_not_recorded")
    assert conn.calls == []


def test_breaker_loader_ready_binds_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nhánh khi nguồn ready (vá riêng khoá `tool_spans`): đúng hợp đồng dự kiến Q-M9-4 — `span_type='tool'`,
    `status='error'`, `attributes.error='circuit_open'`; đọc từ `now − 24 giờ` (Q-M9-B2-12). Giá trị là hằng có thật."""
    real = rules_data.is_pending
    monkeypatch.setattr(rules_data, "is_pending", lambda key: False if key == "tool_spans" else real(key))
    conn = RecordingConn()
    out = asyncio.run(LOADERS["breaker_open"](cast(Any, conn), RuleContext(T0, VN_TZ, 38.0, 0.8)))
    assert out == []
    [(sql, params)] = conn.calls
    assert sql == rules_data.TOOL_SPAN_SQL.text
    assert params == {
        "span_type": "tool", "status": "error", "error": "circuit_open", "since": datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
    }  # fmt: skip
    assert params["span_type"] in SPAN_TYPES and params["status"] in SPAN_STATUSES
    assert set(params) <= _ALLOWED_BINDS


def test_breaker_error_constant_matches_registry() -> None:
    """`monitor` không import `tools` → hằng sao chép; lệch là luật 5 câm lặng khi nguồn ready (FN)."""
    assert rules_data.BREAKER_ERROR == CIRCUIT_OPEN


def test_only_pending_source_loaders_call_is_pending() -> None:
    """Chỉ luật có nguồn TỪNG pending mới gọi `is_pending` (hợp đồng mục 3, file chia việc :111, :113), mỗi loader một lời
    gọi với khoá HẰNG (gõ sai → KeyError → failed_rules): luật 5 `tool_spans`, luật 7 `approval_view` (pending tới 4c), luật
    12 `b2_classifier`, luật 13 `b3_cascade`. Luật 11 không gọi (chốt 02/10 ở #13); luật 1, 14 không có nguồn pending.
    B3 luật 8: `drift_counts` gọi `override_count` (pending tới 4d) — chỉ bỏ phân bố override, không bỏ cả luật (Q-M9-B3-3);
    `load_drift` không gọi lại (đọc `DriftCounts.pending`)."""
    tree = ast.parse(inspect.getsource(rules_data))
    calls = [
        (fn.name, [a.value for a in call.args if isinstance(a, ast.Constant)])
        for fn in ast.walk(tree) if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef)
        for call in ast.walk(fn)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "is_pending"
    ]  # fmt: skip
    assert calls == [
        ("load_breaker_open", ["tool_spans"]),
        ("load_reflex_approval", ["approval_view"]),
        ("load_b2_degraded", ["b2_classifier"]),
        ("load_b3_degraded", ["b3_cascade"]),
        ("drift_counts", ["override_count"]),
    ]


# ---- B3 luật 8 drift: tham số bind ------------------------------------------------------------------------------------

# T0 = 2026-10-02T08:00Z = 15:00 thứ Sáu 02/10 giờ VN → W = 00:00 thứ Hai 28/09 VN = 2026-09-27T17:00Z (tính tay). Ba cửa
# sổ: [09-06T17, 09-13T17), [09-13T17, 09-20T17), [09-20T17, 09-27T17).
DRIFT_WINDOWS_T0 = [
    (datetime(2026, 9, d, 17, 0, tzinfo=UTC), datetime(2026, 9, d + 7, 17, 0, tzinfo=UTC)) for d in (6, 13, 20)
]
_DRIFT_BINDS = {"frm", "to", "intents", "steps", "e3", "step", "event"}


class _DriftResult:
    def all(self) -> list[Any]:
        return []

    def one(self) -> Any:
        return SimpleNamespace(n=0, hit=0)


class DriftRecordingConn:
    """Như RecordingConn nhưng kết quả có `all()`/`one()` (câu đếm của luật 8)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, clause: TextClause, params: dict[str, Any]) -> _DriftResult:
        self.calls.append((clause.text, params))
        return _DriftResult()


def test_drift_loader_binds_only_windows_and_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tham số bind của luật 8 chỉ là mốc tuần (3 cửa sổ tay) + hằng code; KHÔNG có `now`/`since` (không đọc theo `now`).
    Không nới `_ALLOWED_BINDS` của luật sự kiện — bộ khoá riêng của drift."""

    async def no_rate(conn: object, frm: datetime, to: datetime) -> WeightedRate:
        return WeightedRate(raw=None, weighted=None, by_group={}, sensitivity={})

    monkeypatch.setattr(rules_data, "escalation_rate_weighted", no_rate)
    conn = DriftRecordingConn()
    asyncio.run(LOADERS["drift"](cast(Any, conn), RuleContext(T0, VN_TZ, 38.0, 0.8)))
    assert len(conn.calls) == 3 * 5
    assert sorted({(p["frm"], p["to"]) for _, p in conn.calls}) == DRIFT_WINDOWS_T0
    for sql, params in conn.calls:
        assert set(params) <= _DRIFT_BINDS and {"frm", "to"} <= set(params), sql
        assert all(isinstance(v, str | datetime | list) for v in params.values())
    by_sql = {sql: {k: v for k, v in params.items() if k not in ("frm", "to")} for sql, params in conn.calls}
    assert by_sql == {
        rules_data.DRIFT_INTENT_SQL.text: {"intents": list(INTENTS)},
        rules_data.DRIFT_CONFIDENCE_SQL.text: {"steps": ["B3", "B4"]},
        rules_data.DRIFT_TOP_SCORE_SQL.text: {"steps": ["B8"]},
        rules_data.DRIFT_DONE_SQL.text: {"e3": "E3"},
        rules_data.DRIFT_OVERRIDE_SQL.text: {"step": OVERRIDE_STEP, "event": OVERRIDE_EVENT},
    }
