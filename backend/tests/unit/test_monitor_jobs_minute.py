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
from typing import Any, cast

import pytest
import yaml
from app import worker
from app.core.clock import FakeClock
from app.db.models import SECURITY_EVENT_TYPES
from app.db.session import Engines
from app.domain.alerts import AlertDraft
from app.graph.runner import FINALIZE_FAILED
from app.monitor.evaluator import LOADERS, EvalResult
from app.monitor.queries import rules_data
from app.monitor.rules import LOOKBACK, REGISTRY, RuleContext
from app.monitor.window import VN_TZ
from app.settings import Settings
from app.worker import (
    MONITOR_RULES_MINUTE,
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
    job = setup_monitor_jobs(scheduler, settings_with(llm_yaml(tmp_path, 12.0, 0.5), tmp_path), engines(FakeEngine()),
                             clock)  # fmt: skip
    assert job is not None and [j.id for j in scheduler.get_jobs()] == [MONITOR_RULES_MINUTE]
    seen = fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=[], skipped_rules=[]))
    asyncio.run(job.minute())
    assert seen == [RuleContext(now=T0, tz=VN_TZ, cap_usd=12.0, warn_ratio=0.5)]


def test_monitor_setup_error_keeps_three_jobs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Điều kiện duyệt 1: dựng M9 lỗi (không có `llm.yaml`) → worker vẫn đủ 3 job gốc, đúng 1 ERROR (tên lớp)."""
    settings = settings_with(tmp_path, tmp_path)  # thư mục trống
    scheduler = AsyncIOScheduler(timezone="UTC")
    schedule_jobs(scheduler, IdleJobs(), settings, FakeClock(T0))
    with caplog.at_level(logging.INFO, logger="app.worker"):
        assert setup_monitor_jobs(scheduler, settings, engines(FakeEngine()), FakeClock(T0)) is None
    assert {j.id for j in scheduler.get_jobs()} == {"heartbeat", "scan_deadlines", "scan_stale_turns"}
    errors = m9_records(caplog, logging.ERROR)
    assert len(errors) == 1 and "FileNotFoundError" in errors[0].getMessage()
    assert errors[0].exc_info is None


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
    không giá trị `detail`; cuối lượt 1 dòng tổng `ghi=<n> lỗi=<m>` (WARNING khi m > 0)."""
    drafts = [draft("refresh_reuse", "u-1"), draft("injection_detected", "t-2"), draft("finalize_failed", "t-3")]
    writer = FakeWriter(lambda d: ValueError(f"hỏng {d.detail}") if d.subject == "t-2" else None)
    fake_evaluate(monkeypatch, EvalResult(drafts=drafts, failed_rules=[], skipped_rules=[]))
    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(make_job(FakeEngine(), FakeClock(T0), writer).minute())
    assert [d.subject for d in writer.written] == ["u-1", "t-3"]
    warnings = [r.getMessage() for r in m9_records(caplog, logging.WARNING)]
    assert warnings == [
        f"{MONITOR_RULES_MINUTE}: ghi cảnh báo luật injection_detected lỗi: ValueError",
        f"{MONITOR_RULES_MINUTE}: ghi=2 lỗi=1",
    ]
    assert all(r.exc_info is None and SECRET not in r.getMessage() for r in caplog.records)


def test_summary_info_when_no_error(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_evaluate(monkeypatch, EvalResult(drafts=[draft("refresh_reuse", "u-1")], failed_rules=[], skipped_rules=[]))
    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(make_job(FakeEngine(), FakeClock(T0)).minute())
    assert [r.getMessage() for r in m9_records(caplog, logging.INFO)] == [f"{MONITOR_RULES_MINUTE}: ghi=1 lỗi=0"]
    assert m9_records(caplog, logging.WARNING) == []


def test_summary_counts_only_new_alerts(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """`ghi` = số cảnh báo MỚI (`raise_once` trả True). Job quét lại 24 giờ mỗi phút → lượt sau gặp lại đúng các draft
    cũ (trả False) → `ghi=0`, không phải `ghi=2` mỗi phút (dễ hiểu nhầm là đang sinh cảnh báo mới)."""
    old = [draft("refresh_reuse", "u-1"), draft("injection_detected", "t-2")]
    writer = FakeWriter()
    job = make_job(FakeEngine(), FakeClock(T0), writer)
    with caplog.at_level(logging.INFO, logger="app.worker"):
        fake_evaluate(monkeypatch, EvalResult(drafts=old, failed_rules=[], skipped_rules=[]))
        asyncio.run(job.minute())
        asyncio.run(job.minute())
        fake_evaluate(monkeypatch, EvalResult(drafts=[*old, draft("finalize_failed", "t-3")], failed_rules=[],
                                              skipped_rules=[]))  # fmt: skip
        asyncio.run(job.minute())
    summaries = [r.getMessage() for r in m9_records(caplog, logging.INFO) if "ghi=" in r.getMessage()]
    assert summaries == [f"{MONITOR_RULES_MINUTE}: ghi={n} lỗi=0" for n in (2, 0, 1)]
    assert len(writer.written) == 3


def test_failed_and_skipped_rules_logged_by_name(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_evaluate(monkeypatch, EvalResult(drafts=[], failed_rules=["refresh_reuse", "policy_saved"],
                                          skipped_rules=["b3_degraded"]))  # fmt: skip
    with caplog.at_level(logging.INFO, logger="app.worker"):
        asyncio.run(make_job(FakeEngine(), FakeClock(T0)).minute())
    messages = [r.getMessage() for r in m9_records(caplog)]
    assert f"{MONITOR_RULES_MINUTE}: luật lỗi: refresh_reuse, policy_saved" in messages
    assert f"{MONITOR_RULES_MINUTE}: luật bỏ qua (nguồn pending): b3_degraded" in messages


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
    """Worker import `rules_data` → mọi luật `minute` có loader (thiếu → MissingLoaderError → failed_rules mỗi phút)."""
    minute = {r for r, spec in REGISTRY.items() if spec.every == "minute"}
    assert minute == B1_RULES
    assert minute <= set(LOADERS)
    assert "from app.monitor.queries import rules_data" in inspect.getsource(worker)


def _sql() -> dict[str, str]:
    found = {name: clause.text for name, clause in vars(rules_data).items() if isinstance(clause, TextClause)}
    assert len(found) == 5  # quét không rỗng
    return found


_UNWRITTEN_COLUMNS = ("confidence", "query", "success", "action_plan_hash_matched")  # kế hoạch chung 1.4


def test_rules_data_only_select() -> None:
    """Chỉ SELECT; không đụng bảng `tickets` trực tiếp (đếm qua `v_leaf`); không đọc 4 cột chưa ghi; KHÔNG chặn trên
    theo `now` (Q-M9-B1-12 — không có `<`, không có tham số `now`); luật 2/16 qua `v_leaf`, luật 15 thì không."""
    sql = _sql()
    for name, body in sql.items():
        words = body.lower()
        assert words.strip().startswith("select"), name
        assert not re.search(r"\b(insert|update|delete|truncate|create|alter|drop|grant)\b", words), name
        assert not re.search(r"\btickets\b", words), name
        assert not [c for c in _UNWRITTEN_COLUMNS if re.search(rf"\b{c}\b", words)], name
        assert "<" not in body and ":now" not in body, name
        assert "cast(" not in words and "::" not in body, name  # không ép kiểu dữ liệu JSON
    assert "v_leaf" in sql["TICKET_EXIT_SQL"]
    assert "v_leaf" not in sql["FINALIZE_FAILED_SQL"]


class RecordingConn:
    """Ghi lại (câu SQL, tham số bind) của loader; trả 0 dòng."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, clause: TextClause, params: dict[str, Any]) -> list[Any]:
        self.calls.append((clause.text, params))
        return []


_ALLOWED_BINDS = {"since", "code", "step", "event", "event_type", "reason", "rule_id"}


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


def test_finalize_event_constant_matches_runner() -> None:
    """`monitor` không import `graph` → hằng sao chép; lệch tên event là luật 15 câm lặng (FN)."""
    assert rules_data.FINALIZE_FAILED_EVENT == FINALIZE_FAILED
    assert rules_data.FINALIZE_FAILED_STEP == "B20"


def test_policy_saved_loader_does_not_call_is_pending() -> None:
    """Chốt 02/10 (#13): `is_pending("policy_saved")` ném KeyError → luật 11 vào failed_rules mỗi phút. Loader chạy
    truy vấn thật; chưa có nơi ghi → 0 sự kiện."""
    tree = ast.parse(inspect.getsource(rules_data))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert len(names) > 10  # quét không rỗng
    assert "is_pending" not in names
    conn = RecordingConn()
    out = asyncio.run(LOADERS["policy_saved"](cast(Any, conn), RuleContext(T0, VN_TZ, 38.0, 0.8)))
    assert out == [] and conn.calls[0][1]["event_type"] == "policy_saved"
