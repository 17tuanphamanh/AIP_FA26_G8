"""G7 — runner chỉ chạy ca khi giờ thật cùng loại giờ với `at`; `skipped_hours`; `--resume` (stack giả `SimStack`, không Docker).

"Policy" của container giả = `FAKE_HOURS` (thứ 2–6, 08:00–17:00 giờ Việt Nam — TỰ DỰNG cho test, không phải số thật). Giờ mặc định
của `Run`: thứ Hai 19/10/2026 03:00 UTC = 10:00 VN (trong giờ); `at` mặc định thứ Ba 09:00 VN (trong giờ).
"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.eval.predictions import load_predictions
from app.eval.runner import main
from app.eval.stack import StackError
from tests.unit.eval.test_harness_runner import ENV, SUMMARY, Run, scn

AT_OUT = "2026-09-15T21:10:00+07:00"  # thứ Ba 21:10 VN — ngoài giờ
MON_10 = datetime(2026, 10, 19, 3, 0, tzinfo=UTC)  # 10:00 VN
MON_21 = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)  # 21:00 VN
MON_0755 = datetime(2026, 10, 19, 0, 55, tzinfo=UTC)  # 07:55 VN — vùng đệm biên đầu
FILES = ("predictions.jsonl", "outcomes.jsonl", "manifest.json")


def mixed(tmp: Path) -> Run:
    return Run(tmp, scn(1, "direct"), scn(2, "direct", at=AT_OUT), scn(3, "clarify", "SENTINEL_TXT_a"))


def resume(r: Run, *extra: str, timeout: str = "30") -> int:
    argv = ["--scenarios", str(r.scen), "--resume", str(r.outdir), "--seed", str(r.seed), "--strategy", "hybrid",
            "--split", "test", "--timeout-s", timeout, *extra]  # fmt: skip
    r.out.clear()
    r.err.clear()
    return main(argv, env=ENV, make_deps=r.make_deps, out=r.out.append, err=r.err.append)


def creates(r: Run) -> int:
    return r.paths().count("/api/tickets")


def md5s(r: Run) -> list[str]:
    return [hashlib.md5((r.outdir / f).read_bytes()).hexdigest() for f in FILES]


def summary_ok(r: Run) -> bool:
    return len(r.out) == 7 and all(re.fullmatch(p, x) for p, x in zip(SUMMARY, r.out, strict=True))


# ---- một lượt -----------------------------------------------------------------------------------------------------------


def test_runner_mixed(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    assert r() == 0
    assert creates(r) == 2
    rows = r.outcomes()
    assert [o["outcome"] for o in rows] == ["done", "skipped_hours", "done"]
    assert rows[1] | {"run_started_at": None} == {
        "scenario_id": "SENTINEL_ID_2", "ticket_id": None, "outcome": "skipped_hours", "error_type": None, "elapsed_s": 0.0,
        "run_started_at": None, "in_business_hours": True, "hours_class": "trong", "skip_reason": "lech_loai_gio", "pass": 1,
    }  # fmt: skip
    assert [(o["in_business_hours"], o["hours_class"], o["skip_reason"], o["pass"]) for o in (rows[0], rows[2])] == \
        [(True, "trong", None, 1)] * 2  # fmt: skip
    assert [x.scenario_id for x in load_predictions(r.outdir / "predictions.jsonl")] == ["SENTINEL_ID_1", "SENTINEL_ID_3"]
    m = r.manifest()
    assert (m["counts"]["skipped_hours"], m["counts"]["done"], m["counts"]["written"]) == (1, 2, 2)
    assert m["passes"] == [{"pass": 1, "started_at": MON_10.isoformat(), "finished_at": MON_10.isoformat(), "ran": 2,
                            "skipped_hours": 1, "lech_loai_gio": 1, "bien_gio": 0,
                            "hours_class": {"trong": 3, "ngoai": 0, "bien_gio": 0}}]  # fmt: skip
    assert summary_ok(r)
    assert r.out[3].endswith(" skipped_hours=1")


def test_runner_out_hours_runs_out_scenarios(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    r.now = lambda: MON_21
    assert r() == 0
    assert [o["outcome"] for o in r.outcomes()] == ["skipped_hours", "done", "skipped_hours"]
    assert {o["hours_class"] for o in r.outcomes()} == {"ngoai"}
    assert {o["in_business_hours"] for o in r.outcomes()} == {False}


def test_runner_boundary_no_ticket(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    r.now = lambda: MON_0755
    assert r() == 0
    assert creates(r) == 0
    assert {(o["outcome"], o["skip_reason"], o["hours_class"]) for o in r.outcomes()} == {("skipped_hours", "bien_gio", "bien_gio")}
    assert (r.outdir / "predictions.jsonl").read_text(encoding="utf-8") == ""
    assert r.manifest()["passes"][0]["bien_gio"] == 3
    assert summary_ok(r) and r.out[3].endswith(" skipped_hours=3")


def test_probe_asks_at_and_now_buffer(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r() == 0
    at = datetime.fromisoformat("2026-10-20T09:00:00+07:00")
    ten = timedelta(minutes=10)
    assert r.sim.hours_probes == [(at, MON_10 - ten, MON_10, MON_10 + ten)]


def test_probe_failure_stops(tmp_path: Path) -> None:
    r = mixed(tmp_path)

    def broken(times: Any) -> list[bool]:
        raise StackError("SENTINEL_ERR")

    r.sim.in_hours = broken  # type: ignore[method-assign]
    assert r() == 2
    assert r.no_files() and creates(r) == 0
    assert r.out[-1].startswith("DỪNG:") and "SENTINEL" not in r.text


def test_per_case_skip_reason(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    assert r("--per-case") == 0
    assert "SENTINEL_ID_2 skipped_hours 0.0 lech_loai_gio" in r.out
    assert all(re.fullmatch(p, x) for p, x in zip(SUMMARY, r.out[-7:], strict=True))


def test_bad_at_stops_before_stack(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), scn(2, "direct", at="2026-10-20T09:00:00"))
    assert r() == 2
    assert r.deps_made == 0 and r.no_files()
    assert "2026-10-20T09:00:00" not in r.text


def test_check_only_counts_bad_at(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), scn(2, "direct", at="SENTINEL_AT"), scn(3, "direct", at="2026-10-20T09:00:00"))
    assert r("--check-only", env={}, timeout=None) == 2
    assert r.out == ["scenarios: loaded=3 errors=0", "at: errors=2 (cần ISO-8601 có múi giờ)"]
    assert r.deps_made == 0 and "SENTINEL" not in r.text


def test_long_timeout_warns(tmp_path: Path) -> None:
    a, b = Run(tmp_path / "a", scn(1, "direct")), Run(tmp_path / "b", scn(1, "direct"))
    assert a(timeout="601") == 0 and b(timeout="600") == 0
    assert any("biên giờ hành chính" in e for e in a.err)
    assert not any("biên giờ hành chính" in e for e in b.err)


def test_no_config_values_leak(tmp_path: Path) -> None:
    """Không giá trị cấu hình giờ (giờ bắt đầu / kết thúc, tz, thứ) ở stdout/stderr/manifest/outcomes."""
    r = mixed(tmp_path)
    assert r("--per-case") == 0
    r.now = lambda: MON_21
    assert resume(r, "--per-case") == 0
    blob = r.text + (r.outdir / "manifest.json").read_text(encoding="utf-8") + (r.outdir / "outcomes.jsonl").read_text(encoding="utf-8")
    assert not any(s in blob for s in ("08:00", "17:00", "Asia", "Ho_Chi_Minh", "weekdays", '"tz"'))


# ---- --resume -----------------------------------------------------------------------------------------------------------


def test_resume_runs_only_skipped(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    assert r() == 0
    pred0 = (r.outdir / "predictions.jsonl").read_text(encoding="utf-8")
    out0 = (r.outdir / "outcomes.jsonl").read_text(encoding="utf-8")
    before = creates(r)
    r.now = lambda: MON_21
    assert resume(r) == 0
    assert creates(r) - before == 1
    pred = (r.outdir / "predictions.jsonl").read_text(encoding="utf-8")
    outs = (r.outdir / "outcomes.jsonl").read_text(encoding="utf-8")
    assert pred.startswith(pred0) and len(pred.splitlines()) == 3  # dòng cũ giữ nguyên từng byte
    assert outs.startswith(out0) and len(outs.splitlines()) == 4
    last = r.outcomes()[-1]
    assert (last["scenario_id"], last["outcome"], last["pass"], last["in_business_hours"], last["hours_class"]) == \
        ("SENTINEL_ID_2", "done", 2, False, "ngoai")  # fmt: skip
    assert last["run_started_at"] == MON_21.isoformat()
    assert [x.scenario_id for x in load_predictions(r.outdir / "predictions.jsonl")] == \
        ["SENTINEL_ID_1", "SENTINEL_ID_3", "SENTINEL_ID_2"]  # fmt: skip
    assert summary_ok(r) and r.out[3].endswith(" skipped_hours=0")


def test_resume_keeps_run_id(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    assert r() == 0
    run_id = r.manifest()["run_id"]
    r.now = lambda: MON_21
    assert resume(r) == 0
    assert r.manifest()["run_id"] == run_id
    assert {x.run_id for x in load_predictions(r.outdir / "predictions.jsonl")} == {run_id}
    assert r.out[0].startswith(f"eval run {run_id} ")


def test_resume_run_id_changed_stops(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    assert r() == 0
    sums, before = md5s(r), creates(r)
    r.now = lambda: MON_21
    assert resume(r, timeout="31") == 2
    assert md5s(r) == sums and creates(r) == before
    assert "run_id" in r.out[-1]


def test_resume_passes_manifest(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    assert r() == 0
    r.now = lambda: MON_21
    assert resume(r) == 0
    m = r.manifest()
    assert [(p["pass"], p["started_at"], p["finished_at"], p["ran"], p["skipped_hours"]) for p in m["passes"]] == \
        [(1, MON_10.isoformat(), MON_10.isoformat(), 2, 1), (2, MON_21.isoformat(), MON_21.isoformat(), 1, 0)]  # fmt: skip
    assert m["passes"][1]["hours_class"] == {"trong": 0, "ngoai": 1, "bien_gio": 0}
    assert (m["started_at"], m["finished_at"]) == (MON_10.isoformat(), MON_21.isoformat())
    c = m["counts"]
    assert (c["loaded"], c["done"], c["skipped_hours"], c["written"], c["timeout"], c["error"]) == (3, 3, 0, 3, 0, 0)


def test_resume_still_skipped_then_again(tmp_path: Path) -> None:
    """Resume lúc vẫn lệch giờ: ca vẫn skipped (pass 2), resume tiếp lúc khớp giờ thì chạy (pass 3)."""
    r = mixed(tmp_path)
    assert r() == 0
    assert resume(r) == 0
    assert r.manifest()["counts"]["skipped_hours"] == 1 and len(r.manifest()["passes"]) == 2
    r.now = lambda: MON_21
    assert resume(r) == 0
    assert [o["pass"] for o in r.outcomes()] == [1, 1, 1, 2, 3]
    assert r.manifest()["counts"]["skipped_hours"] == 0


def _tamper_outcome(r: Run) -> None:
    with (r.outdir / "outcomes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"scenario_id": "SENTINEL_ID_2", "outcome": "done"}) + "\n")
        f.write(json.dumps({"scenario_id": "SENTINEL_ID_2", "outcome": "skipped_hours"}) + "\n")


def _tamper_prediction(r: Run) -> None:
    path = r.outdir / "predictions.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    row.update(scenario_id="SENTINEL_ID_2", ticket_id="SENTINEL_TID-x")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def test_resume_no_duplicate(tmp_path: Path) -> None:
    for name, tamper in (("o", _tamper_outcome), ("p", _tamper_prediction)):
        r = mixed(tmp_path / name)
        assert r() == 0
        tamper(r)
        sums, before = md5s(r), creates(r)
        r.now = lambda: MON_21
        assert resume(r) == 2, name
        assert md5s(r) == sums and creates(r) == before
        assert "lần 2" in r.out[-1] and "SENTINEL" not in r.text


def test_resume_nothing_pending(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r() == 0
    sums, made = md5s(r), r.deps_made
    assert resume(r) == 0
    assert r.out == ["resume: không còn ca skipped_hours — không chạy, không ghi"]
    assert md5s(r) == sums and r.deps_made == made


def test_resume_with_out_rejected(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    assert r() == 0
    sums = md5s(r)
    assert resume(r, "--out", str(tmp_path / "other")) == 2
    assert md5s(r) == sums and not (tmp_path / "other").exists()


def test_resume_missing_files(tmp_path: Path) -> None:
    r = mixed(tmp_path)
    r.outdir.mkdir()
    assert resume(r) == 2
    assert r.deps_made == 0 and r.out[-1].startswith("DỪNG: --resume")
