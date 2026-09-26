"""Heartbeat worker (người yêu cầu khi duyệt 2a, 26/09/2026): worker ghi file định kỳ bằng chính
scheduler chạy job; healthcheck compose đọc nó, quá 60 giây = unhealthy; `make up` chờ worker healthy."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from app import heartbeat
from app.core.clock import FakeClock, SystemClock
from app.core.logging import configure_logging
from app.settings import Settings
from app.worker import HEARTBEAT_JOB, schedule_jobs
from apscheduler.schedulers.asyncio import AsyncIOScheduler

REPO = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 9, 26, 7, 0, tzinfo=UTC)


def settings(path: Path, **kw: Any) -> Settings:
    return Settings(worker_heartbeat_path=path, **kw)


# ---- file heartbeat + lệnh kiểm -------------------------------------------------------------


def test_fresh_heartbeat_is_healthy_and_stale_is_not(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    heartbeat.write(path, T0)
    s = settings(path)
    assert heartbeat.main(s, T0 + timedelta(seconds=60)) == 0
    assert heartbeat.main(s, T0 + timedelta(seconds=61)) == 1  # quá 60 giây = unhealthy


@pytest.mark.parametrize("content", [None, "", "không phải thời gian", "2026-09-26T07:00:00"])
def test_missing_or_broken_heartbeat_is_unhealthy(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "hb"
    if content is not None:
        path.write_text(content, encoding="utf-8")  # dòng cuối: thiếu múi giờ
    assert heartbeat.main(settings(path), T0) == 1


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    heartbeat.write(path, T0)
    heartbeat.write(path, T0 + timedelta(seconds=10))
    assert heartbeat.age_seconds(path, T0 + timedelta(seconds=15)) == 5
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hb"]


def test_interval_must_leave_margin_under_max_age(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="WORKER_HEARTBEAT_SECONDS"):
        settings(tmp_path / "hb", worker_heartbeat_seconds=30, worker_heartbeat_max_age=60)


# ---- worker thật sự ghi heartbeat qua scheduler ---------------------------------------------


class IdleJobs:
    async def scan_deadlines(self) -> None: ...
    async def scan_stale_turns(self) -> None: ...


def test_worker_schedules_heartbeat_with_margin(tmp_path: Path) -> None:
    s = settings(tmp_path / "hb")
    scheduler = AsyncIOScheduler(timezone="UTC")
    schedule_jobs(scheduler, IdleJobs(), s, FakeClock(T0))
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {HEARTBEAT_JOB, "scan_deadlines", "scan_stale_turns"}
    interval = jobs[HEARTBEAT_JOB].trigger.interval.total_seconds()
    assert interval * 3 <= s.worker_heartbeat_max_age


@pytest.mark.asyncio
async def test_running_scheduler_keeps_heartbeat_fresh(tmp_path: Path) -> None:
    """Chạy APScheduler thật với nhịp 0,05 giây: file phải xuất hiện và được làm mới liên tục."""
    path = tmp_path / "hb"
    s = settings(path, worker_heartbeat_seconds=0.05)
    scheduler = AsyncIOScheduler(timezone="UTC")
    schedule_jobs(scheduler, IdleJobs(), s, SystemClock())
    scheduler.start()
    try:
        seen: set[str] = set()
        for _ in range(40):
            await asyncio.sleep(0.05)
            if path.exists():
                seen.add(path.read_text(encoding="utf-8"))
            if len(seen) >= 3:
                break
    finally:
        scheduler.shutdown(wait=False)
    assert len(seen) >= 3, "scheduler không ghi heartbeat định kỳ"
    assert heartbeat.main(s) == 0


# ---- compose healthcheck + Makefile `up` ----------------------------------------------------


def _seconds(value: str) -> float:
    m = re.fullmatch(r"(\d+)s", value)
    assert m, value
    return float(m.group(1))


def test_compose_worker_healthcheck_reads_heartbeat() -> None:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    hc = compose["services"]["worker"]["healthcheck"]
    assert hc["test"] == ["CMD", "python", "-m", "app.heartbeat"]
    assert hc["retries"] == 1  # ngưỡng 60 giây nằm trong lệnh kiểm, không cộng dồn thêm
    assert _seconds(hc["interval"]) + _seconds(hc["timeout"]) <= 60


def test_make_up_waits_for_worker_healthy_then_dumps_logs() -> None:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    up = makefile.split("\nup:", 1)[1].split("\n\n", 1)[0]
    assert "{{.State.Health.Status}}" in up and "ps -q worker" in up
    assert "seq 1 60" in up and '"healthy"' in up
    assert "logs --tail 30 worker" in up and "exit 1" in up


# ---- logger APScheduler ---------------------------------------------------------------------


def test_apscheduler_logger_quiet_but_app_logs_info() -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level, logging.getLogger("apscheduler").level
    try:
        configure_logging()
        assert logging.getLogger("apscheduler.executors.default").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("app.worker").getEffectiveLevel() == logging.INFO
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        logging.getLogger("apscheduler").setLevel(saved[2])
