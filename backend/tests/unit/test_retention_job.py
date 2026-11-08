"""M2 (bn-a, 08/11) — job dọn theo hạn giữ: phần điều phối + cấu hình + lịch (test viết trước, DỪNG 1). SQL thật:
`integration/test_retention_pg.py` (TA chạy bằng `make test`).

Hợp đồng (PLAN bn-a mục M2; P7 mục 4 [Chốt 17.2]):
- `settings.RetentionConfig` nạp từ `config/retention.yaml` (`load_retention`/`open_retention`): `retention_days` (mặc định 90, ≥ 1),
  `session_grace_days` (30 — P7 mục 4 "sessions: 30 ngày sau khi hết hạn"), `wait_grace_days` (7 — ĐP chốt Q3), `dry_run` (mặc định TRUE,
  bool chặt), `batch` (≥ 1). Khoá lạ / giá trị sai → không khởi động. Bật xoá thật = sửa file config (commit), KHÔNG qua `.env` máy đo.
- `graph.retention.RetentionJob(store, saver, clock, config).run() -> RetentionReport`:
  - mốc ticket `cutoff = clock.now() − retention_days`; mốc phiên `clock.now() − session_grace_days` — đồng hồ TIÊM (FakeClock).
  - `store.expired_threads(cutoff, limit=batch)` → danh sách ticket hết hạn còn checkpoint (điều kiện "đã kết thúc", `<` mốc… nằm ở SQL —
    test PG).
  - dry-run: chỉ đếm (`count_expired_sessions`, `count_fired_waits`), KHÔNG gọi `saver.adelete_thread`, `purge_ticket_rows`, hàm xoá nào.
  - xoá thật: mỗi ticket `store.purge_ticket_rows(ticket_id)` rồi `saver.adelete_thread(ticket_id)` (API của saver, không DELETE tay) — thread
    còn thì lượt sau chọn lại; lỗi một ticket → bỏ qua, đếm `errors`, đi tiếp; rồi `delete_expired_sessions`, `delete_fired_waits`.
  - ĐÚNG MỘT `store.record_run(detail, at=now)` mỗi lượt; `detail` = {dry_run, threads, sessions, waits, errors, retention_days} — chỉ
    int/bool, không chữ tự do, không ticket_id.
- `worker.setup_retention_job(scheduler, job)`: job `retention_purge` cron 20:00 UTC (03:00 giờ VN, sau job M9 ngày 19:00), `timezone="UTC"`
  tường minh, `max_instances=1`, `coalesce`, `misfire_grace_time=None`; KHÔNG nằm trong `schedule_jobs` (tập job lõi đã ghim).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)


@dataclass
class FakeStore:
    threads: list[str] = field(default_factory=lambda: ["tk-a", "tk-b"])
    sessions: int = 3
    waits: int = 4
    calls: list[tuple[str, Any]] = field(default_factory=list)
    runs: list[tuple[dict[str, Any], datetime]] = field(default_factory=list)
    fail_rows: frozenset[str] = frozenset()

    async def expired_threads(self, cutoff: datetime, limit: int) -> list[str]:
        self.calls.append(("expired_threads", (cutoff, limit)))
        return list(self.threads)

    async def purge_ticket_rows(self, ticket_id: str) -> None:
        self.calls.append(("purge_ticket_rows", ticket_id))
        if ticket_id in self.fail_rows:
            raise RuntimeError("db down")

    async def count_expired_sessions(self, cutoff: datetime) -> int:
        self.calls.append(("count_expired_sessions", cutoff))
        return self.sessions

    async def delete_expired_sessions(self, cutoff: datetime) -> int:
        self.calls.append(("delete_expired_sessions", cutoff))
        return self.sessions

    async def count_fired_waits(self, cutoff: datetime) -> int:
        self.calls.append(("count_fired_waits", cutoff))
        return self.waits

    async def delete_fired_waits(self, cutoff: datetime) -> int:
        self.calls.append(("delete_fired_waits", cutoff))
        return self.waits

    async def record_run(self, detail: Mapping[str, Any], *, at: datetime) -> None:
        self.runs.append((dict(detail), at))

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


@dataclass
class FakeSaver:
    deleted: list[str] = field(default_factory=list)
    fail: frozenset[str] = frozenset()

    async def adelete_thread(self, thread_id: str) -> None:
        if thread_id in self.fail:
            raise RuntimeError("pool timeout")
        self.deleted.append(thread_id)


def _config(**over: Any) -> Any:
    from app.settings import RetentionConfig

    return RetentionConfig(**{"retention_days": 90, "session_grace_days": 30, "wait_grace_days": 7, "dry_run": True, "batch": 500,
                              **over})  # fmt: skip


def _job(store: FakeStore, saver: FakeSaver, clock: Any, **over: Any) -> Any:
    from app.graph.retention import RetentionJob

    return RetentionJob(store, saver, clock, _config(**over))


# ---- dry-run / xoá thật -------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m2_dry_run_counts_only_and_writes_one_event() -> None:
    from app.core.clock import FakeClock

    store, saver = FakeStore(), FakeSaver()
    report = await _job(store, saver, FakeClock(NOW)).run()
    assert saver.deleted == []
    assert not {"purge_ticket_rows", "delete_expired_sessions", "delete_fired_waits"} & set(store.names())
    assert ("expired_threads", (NOW - timedelta(days=90), 500)) in store.calls
    assert ("count_expired_sessions", NOW - timedelta(days=30)) in store.calls
    assert ("count_fired_waits", NOW - timedelta(days=7)) in store.calls
    assert store.runs == [({"dry_run": True, "threads": 2, "sessions": 3, "waits": 4, "errors": 0, "retention_days": 90}, NOW)]
    assert (report.dry_run, report.threads, report.sessions, report.waits, report.errors) == (True, 2, 3, 4, 0)


@pytest.mark.asyncio
async def test_m2_real_run_deletes_rows_then_thread_via_saver_api_then_sessions_waits() -> None:
    from app.core.clock import FakeClock

    store, saver = FakeStore(), FakeSaver()
    report = await _job(store, saver, FakeClock(NOW), dry_run=False).run()
    assert saver.deleted == ["tk-a", "tk-b"]
    assert [a for n, a in store.calls if n == "purge_ticket_rows"] == ["tk-a", "tk-b"]
    assert ("delete_expired_sessions", NOW - timedelta(days=30)) in store.calls
    assert ("delete_fired_waits", NOW - timedelta(days=7)) in store.calls
    assert store.runs == [({"dry_run": False, "threads": 2, "sessions": 3, "waits": 4, "errors": 0, "retention_days": 90}, NOW)]
    assert (report.dry_run, report.threads) == (False, 2)


@pytest.mark.asyncio
async def test_m2_one_ticket_error_skips_it_counts_error_and_continues() -> None:
    from app.core.clock import FakeClock

    store, saver = FakeStore(threads=["tk-a", "tk-b", "tk-c"]), FakeSaver(fail=frozenset({"tk-b"}))
    report = await _job(store, saver, FakeClock(NOW), dry_run=False).run()
    assert saver.deleted == ["tk-a", "tk-c"]  # tk-b: thread còn → lượt sau chọn lại
    assert [a for n, a in store.calls if n == "purge_ticket_rows"] == ["tk-a", "tk-b", "tk-c"]  # dòng phụ trước, xoá lặp vô hại
    [(detail, _)] = store.runs
    assert (detail["threads"], detail["errors"]) == (2, 1)
    assert (report.threads, report.errors) == (2, 1)


@pytest.mark.asyncio
async def test_m2_cutoff_follows_injected_clock() -> None:
    from app.core.clock import FakeClock

    clock = FakeClock(NOW)
    store = FakeStore()
    job = _job(store, FakeSaver(), clock, retention_days=7)
    await job.run()
    clock.advance(timedelta(days=1))
    await job.run()
    cutoffs = [a[0] for n, a in store.calls if n == "expired_threads"]
    assert cutoffs == [NOW - timedelta(days=7), NOW - timedelta(days=6)]
    assert [at for _, at in store.runs] == [NOW, NOW + timedelta(days=1)]


@pytest.mark.asyncio
async def test_m2_event_detail_has_no_free_text() -> None:
    from app.core.clock import FakeClock

    store = FakeStore(threads=["tk-bi-mat-1"])
    await _job(store, FakeSaver(), FakeClock(NOW), dry_run=False).run()
    [(detail, _)] = store.runs
    assert set(detail) == {"dry_run", "threads", "sessions", "waits", "errors", "retention_days"}
    assert all(type(v) in (int, bool) for v in detail.values())
    assert "tk-bi-mat-1" not in repr(detail)


# ---- cấu hình -------------------------------------------------------------------------------------------------------------------


def test_m2_repo_config_defaults_dry_run_true_90_days() -> None:
    from app.settings import load_retention

    cfg = load_retention(REPO / "config" / "retention.yaml")
    assert (cfg.retention_days, cfg.session_grace_days, cfg.wait_grace_days, cfg.dry_run) == (90, 30, 7, True)


@pytest.mark.parametrize("bad", [
    {"retention_days": 0}, {"retention_days": -1}, {"dry_run": "false"}, {"dry_run": 0}, {"batch": 0},
    {"session_grace_days": 0}, {"wait_grace_days": 0}, {"khoa_la": 1},
])  # fmt: skip
def test_m2_config_rejects_bad_values(tmp_path: Path, bad: dict[str, Any]) -> None:
    from app.settings import load_retention

    path = tmp_path / "retention.yaml"
    path.write_text(yaml.safe_dump({"retention_days": 90, "session_grace_days": 30, "wait_grace_days": 7, "dry_run": True, "batch": 500,
                                    **bad}),
                    encoding="utf-8")  # fmt: skip
    with pytest.raises(ValueError):  # ValidationError là ValueError
        load_retention(path)


def test_m2_settings_has_no_retention_env_switch() -> None:
    """Công tắc xoá thật KHÔNG đi qua env/`.env` (chốt "không .env máy đo"): Settings không có trường retention/dry_run."""
    from app.settings import Settings

    assert not [f for f in Settings.model_fields if "retention" in f or "dry_run" in f]


# ---- lịch worker ----------------------------------------------------------------------------------------------------------------


def test_m2_worker_schedules_nightly_retention_job_outside_core_jobs() -> None:
    from app.core.clock import FakeClock
    from app.worker import setup_retention_job
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="UTC")
    job = _job(FakeStore(), FakeSaver(), FakeClock(NOW))
    setup_retention_job(scheduler, job)
    [j] = scheduler.get_jobs()
    assert j.id == "retention_purge"
    assert (j.max_instances, j.coalesce, j.misfire_grace_time) == (1, True, None)
    fields = {f.name: str(f) for f in j.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("20", "0")
    assert str(j.trigger.timezone) == "UTC"


def test_m2_core_schedule_jobs_unchanged() -> None:
    """`schedule_jobs` (tập job lõi đã ghim) không thêm job retention."""
    import inspect

    from app import worker

    assert "retention" not in inspect.getsource(worker.schedule_jobs)


@pytest.mark.asyncio
async def test_m2_rows_error_skips_thread_delete_and_counts() -> None:
    """Xoá dòng phụ lỗi → KHÔNG xoá thread của ticket đó (còn checkpoint → lượt sau làm lại cả hai)."""
    from app.core.clock import FakeClock

    store, saver = FakeStore(threads=["tk-a", "tk-b"], fail_rows=frozenset({"tk-a"})), FakeSaver()
    report = await _job(store, saver, FakeClock(NOW), dry_run=False).run()
    assert saver.deleted == ["tk-b"] and (report.threads, report.errors) == (1, 1)


@pytest.mark.asyncio
async def test_m2_tick_swallows_whole_run_failure() -> None:
    """Lỗi cả lượt (DB mất) không ném ra scheduler — job khác của worker chạy tiếp; không ghi sự kiện nửa vời."""
    from app.core.clock import FakeClock

    class Down(FakeStore):
        async def expired_threads(self, cutoff: datetime, limit: int) -> list[str]:
            raise ConnectionError("db down")

    store = Down()
    await _job(store, FakeSaver(), FakeClock(NOW)).tick()
    assert store.runs == []


def test_m2_open_retention_refuses_bad_or_missing_file(tmp_path: Path) -> None:
    from app.settings import Settings, open_retention

    with pytest.raises(RuntimeError, match="retention.yaml"):
        open_retention(Settings(_env_file=None, config_dir=tmp_path))  # type: ignore[call-arg]
    (tmp_path / "retention.yaml").write_text("dry_run: 'false'\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="retention.yaml"):
        open_retention(Settings(_env_file=None, config_dir=tmp_path))  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_m2_failure_after_purging_still_records_one_event() -> None:
    """Soát M2 5b: đã xoá thread rồi bước xoá phiên lỗi (DB mất) → vẫn đúng 1 `record_run` mang số thread đã xoá + errors; lỗi ném lại."""
    from app.core.clock import FakeClock

    class SessionsDown(FakeStore):
        async def delete_expired_sessions(self, cutoff: datetime) -> int:
            raise ConnectionError("db down")

    store, saver = SessionsDown(), FakeSaver()
    with pytest.raises(ConnectionError):
        await _job(store, saver, FakeClock(NOW), dry_run=False).run()
    [(detail, _)] = store.runs
    assert (detail["threads"], detail["sessions"], detail["errors"]) == (2, 0, 1)
    assert saver.deleted == ["tk-a", "tk-b"]
