"""G7 — `app.eval.schedule`: loại giờ của giờ thật vs `at`, vùng đệm 10 phút quanh hai biên, chọn ca cho `--resume`.

"Trong giờ" luôn lấy từ hàm backend `within_business_hours` với policy giả TỰ DỰNG `FAKE_HOURS` (thứ 2–6, 08:00–17:00 giờ Việt Nam —
chỉ trong test, không phải số thật). Ngày: 19/10/2026 thứ Hai · 22/10 thứ Năm · 23/10 thứ Sáu · 24/10 thứ Bảy · 26/10 thứ Hai.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.domain.policy import within_business_hours
from app.eval import schedule
from app.eval.schedule import DuplicateRun, HoursCheck, decide, probe_times
from tests.unit.eval.fake_stack import FAKE_HOURS

VN = ZoneInfo("Asia/Ho_Chi_Minh")
AT_IN = datetime(2026, 10, 20, 9, 0, tzinfo=VN)  # thứ Ba 09:00 — trong giờ
AT_OUT = datetime(2026, 9, 15, 21, 10, tzinfo=VN)  # thứ Ba 21:10 — ngoài giờ


def vn(day: int, h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 10, day, h, m, s, tzinfo=VN)


def check(now: datetime, at: datetime = AT_IN) -> HoursCheck:
    """Như runner: hỏi "policy" bốn thời điểm bằng đúng hàm backend rồi `decide`."""
    return decide(*[within_business_hours(t, FAKE_HOURS) for t in probe_times(at, now)])


# ---- trong / ngoài giờ / cuối tuần ------------------------------------------------------------------------------------


def test_in_hours_run() -> None:
    assert check(vn(22, 10)) == HoursCheck(at_in=True, now_in=True, hours_class="trong", skip=None)


def test_out_hours_run() -> None:
    assert check(vn(22, 21), AT_OUT) == HoursCheck(at_in=False, now_in=False, hours_class="ngoai", skip=None)


@pytest.mark.parametrize(("now", "at", "now_in"), [(vn(22, 10), AT_OUT, True), (vn(22, 21), AT_IN, False)])
def test_mismatch_skipped(now: datetime, at: datetime, now_in: bool) -> None:
    c = check(now, at)
    assert (c.skip, c.now_in, c.at_in) == ("lech_loai_gio", now_in, not now_in)
    assert c.hours_class == ("trong" if now_in else "ngoai")


def test_weekend_is_out() -> None:
    """Thứ Bảy 10:00: theo hàm backend là NGOÀI giờ → `at` ngoài giờ chạy, `at` trong giờ bỏ qua."""
    assert check(vn(24, 10), AT_OUT).skip is None
    assert check(vn(24, 10), AT_OUT).hours_class == "ngoai"
    assert check(vn(24, 10), AT_IN).skip == "lech_loai_gio"


def test_at_weekend_counts_as_out() -> None:
    sat = datetime(2026, 10, 24, 10, 0, tzinfo=VN)
    assert check(vn(22, 21), sat).skip is None
    assert check(vn(22, 10), sat).skip == "lech_loai_gio"


# ---- hai biên ±10 phút: ngay trước / ngay trong / ngay sau vùng đệm (nửa mở [biên − 10′, biên + 10′)) ------------------


@pytest.mark.parametrize(("now", "cls"), [
    (vn(22, 7, 49, 59), "ngoai"),  # ngay trước vùng đệm
    (vn(22, 7, 50), "bien_gio"),  # ngay trong (mép trước)
    (vn(22, 8, 0), "bien_gio"),
    (vn(22, 8, 9, 59), "bien_gio"),  # ngay trong (mép sau)
    (vn(22, 8, 10), "trong"),  # ngay sau vùng đệm
])  # fmt: skip
def test_start_boundary(now: datetime, cls: str) -> None:
    c = check(now)
    assert c.hours_class == cls
    assert c.skip == ("bien_gio" if cls == "bien_gio" else None if cls == "trong" else "lech_loai_gio")


@pytest.mark.parametrize(("now", "cls"), [
    (vn(22, 16, 49, 59), "trong"),
    (vn(22, 16, 50), "bien_gio"),
    (vn(22, 17, 0), "bien_gio"),
    (vn(22, 17, 9, 59), "bien_gio"),
    (vn(22, 17, 10), "ngoai"),
])  # fmt: skip
def test_end_boundary(now: datetime, cls: str) -> None:
    c = check(now, AT_OUT)
    assert c.hours_class == cls
    assert c.skip == ("bien_gio" if cls == "bien_gio" else None if cls == "ngoai" else "lech_loai_gio")


@pytest.mark.parametrize("now", [vn(23, 17, 5), vn(26, 7, 55)])
def test_friday_end_monday_start(now: datetime) -> None:
    assert check(now, AT_IN).skip == check(now, AT_OUT).skip == "bien_gio"


def test_midnight_is_not_boundary() -> None:
    assert check(vn(26, 0, 5), AT_OUT) == HoursCheck(at_in=False, now_in=False, hours_class="ngoai", skip=None)


def test_now_utc_vs_at_offset() -> None:
    """`now` UTC (như `datetime.now(UTC)` của runner) và `at` +07: hàm backend quy về cùng múi giờ policy."""
    assert check(datetime(2026, 10, 22, 3, 0, tzinfo=UTC)).hours_class == "trong"  # 10:00 VN
    assert check(datetime(2026, 10, 22, 0, 55, tzinfo=UTC)).hours_class == "bien_gio"  # 07:55 VN
    assert check(datetime(2026, 10, 22, 14, 0, tzinfo=UTC), AT_OUT).skip is None  # 21:00 VN


def test_probe_times_buffer() -> None:
    now = vn(22, 10)
    assert probe_times(AT_IN, now) == (AT_IN, now - timedelta(minutes=10), now, now + timedelta(minutes=10))


# ---- `at` ---------------------------------------------------------------------------------------------------------------


def test_parse_at_ok() -> None:
    assert schedule.parse_at("2026-09-15T21:10:00+07:00") == AT_OUT


@pytest.mark.parametrize("bad", ["2026-10-20T09:00:00", "SENTINEL_AT", "", "2026-13-40T09:00:00+07:00"])
def test_parse_at_rejects(bad: str) -> None:
    with pytest.raises(ValueError) as e:
        schedule.parse_at(bad)
    assert "SENTINEL" not in str(e.value) and (not bad or bad not in str(e.value))


def test_bad_at_counts() -> None:
    assert schedule.bad_at(["2026-10-20T09:00:00+07:00", "2026-10-20T09:00:00", "x"]) == 2


# ---- script trong container -------------------------------------------------------------------------------------------


def _no_file() -> bytes:
    raise AssertionError("test không được đọc file policy nào")


def test_hours_script_uses_backend_function_and_policy(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """`HOURS_SCRIPT` = `within_business_hours` + `get_policy().business_hours` (policy giả thay vào; không mở file), chỉ in bool."""
    from app import settings

    monkeypatch.setattr(settings, "_policy_bytes", _no_file)
    monkeypatch.setattr(settings, "get_policy", lambda: SimpleNamespace(business_hours=FAKE_HOURS))
    times = [vn(22, 10), vn(22, 7, 59), vn(22, 17, 0), vn(24, 10), datetime(2026, 10, 22, 1, 0, tzinfo=UTC)]
    monkeypatch.setattr(sys, "argv", ["-c", *(t.isoformat() for t in times)])
    exec(compile(schedule.HOURS_SCRIPT, "<hours>", "exec"), {"__name__": "__hours__"})  # noqa: S102 — hằng của module
    line = capsys.readouterr().out.strip()
    assert json.loads(line) == {"in_hours": [True, False, False, False, True]}
    assert not any(s in line for s in ("08", "17", "Asia", "Ho_Chi_Minh", "weekdays", "start", "end"))


@pytest.mark.parametrize("data", [{}, {"in_hours": [True]}, {"in_hours": [True, 1, False]}, {"in_hours": "TTT"},
                                  {"in_hours": [True, False, True, False]}])  # fmt: skip
def test_parse_probe_bad(data: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        schedule.parse_probe(data, 3)


def test_parse_probe_ok() -> None:
    assert schedule.parse_probe({"in_hours": [True, False, True]}, 3) == [True, False, True]


# ---- resume -----------------------------------------------------------------------------------------------------------


def row(sid: str, outcome: str) -> dict[str, Any]:
    return {"scenario_id": sid, "outcome": outcome}


def test_pending_latest_outcome() -> None:
    rows = [row("a", "done"), row("b", "skipped_hours"), row("c", "skipped_hours"), row("c", "done"), row("d", "timeout"),
            row("e", "skipped_hours"), row("e", "skipped_hours")]  # fmt: skip
    assert schedule.pending(rows) == ["b", "e"]


def test_check_no_rerun() -> None:
    rows = [row("a", "done"), row("b", "skipped_hours")]
    schedule.check_no_rerun(["b"], rows, {"a"})
    with pytest.raises(DuplicateRun):
        schedule.check_no_rerun(["b"], [*rows, row("b", "error")], {"a"})
    with pytest.raises(DuplicateRun):
        schedule.check_no_rerun(["b"], rows, {"a", "b"})


def test_pass_entry_counts() -> None:
    checks = [check(vn(22, 10)), check(vn(22, 10), AT_OUT), check(vn(22, 7, 55)), check(vn(22, 10))]
    assert schedule.pass_entry(2, "s", "f", checks) == {
        "pass": 2, "started_at": "s", "finished_at": "f", "ran": 2, "skipped_hours": 2, "lech_loai_gio": 1, "bien_gio": 1,
        "hours_class": {"trong": 3, "ngoai": 0, "bien_gio": 1},
    }  # fmt: skip


def test_merge_counts() -> None:
    prior = {"loaded": 3, "done": 2, "skipped_hours": 1, "written": 2, "confirm_default": 1}
    now = {"loaded": 3, "done": 1, "skipped_hours": 0, "written": 1, "confirm_default": 0}
    assert schedule.merge_counts(prior, now) == {"loaded": 3, "done": 3, "skipped_hours": 0, "written": 3, "confirm_default": 1}
