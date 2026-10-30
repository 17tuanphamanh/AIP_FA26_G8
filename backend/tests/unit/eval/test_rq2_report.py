"""RQ2 — báo cáo offline trên bản thu thập GIẢ: tệp đầu ra, PNG hợp lệ, bảng, manifest (n_boot 1000, ghi chú P8), B5, script."""

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
from app.eval.rq2.metrics import Point
from app.eval.rq2.report import (
    BOOT_NOTE,
    describe_b5,
    reliability_bins,
    reliability_png,
    write_report,
)
from tests.unit.eval.eval_scripts import load_script


def _rows(with_c: bool) -> list[dict[str, Any]]:
    rows = []
    for i in range(60):
        fam = f"HB{i % 15:02d}"
        y = (i * 7) % 10 < 4
        row: dict[str, Any] = {"ticket_id": f"tk-{i:03d}", "scenario_id": f"S-{i}", "family": fam, "fold": (i % 15) % 5 + 1, "y": y,
                               "p_a": round(((i * 13) % 20) / 20 * 0.9 + (0.1 if y else 0.0), 6), "p_b": min(5, i % 4 + (2 if y else 0)) / 5,
                               "p_b_source": "votes", "reasons": {"a": None, "b": None}}  # fmt: skip
        if with_c:
            row["p_c"] = min(0.999, ((i * 11) % 17) / 17 + (0.05 if y else 0.0))
        rows.append(row)
    rows[5]["p_a"] = None  # lá không có p_a (vd rerender_mismatch)
    return rows


@pytest.mark.parametrize("with_c", [True, False])
def test_write_report_outputs(tmp_path: Path, with_c: bool) -> None:
    from datetime import UTC, datetime

    rows = _rows(with_c)
    manifest = write_report(tmp_path, rows, {"model": "deepseek-flash", "rq2_run_id": "abc"}, now=datetime(2026, 11, 1, tzinfo=UTC),
                            n_boot=30)  # fmt: skip
    methods = ["a", "b", "c"] if with_c else ["a", "b"]
    assert manifest["report"]["methods"] == methods
    header = (tmp_path / "per_ticket.csv").read_text().splitlines()[0].split(",")
    assert header == ["ticket_id", "scenario_id", "family", "fold", "y"] + [f"p_{m}_{s}" for m in methods for s in ("raw", "cal")]
    assert len((tmp_path / "per_ticket.csv").read_text().splitlines()) == 61
    metrics = json.loads((tmp_path / "metrics.json").read_text())
    assert {(e["method"], e["stage"], e["scope"]) for e in metrics} == {(m, s, sc) for m in methods for s in ("raw", "cal")
                                                                         for sc in ("common", "own")}  # fmt: skip
    common = [e for e in metrics if e["scope"] == "common"]
    assert len({e["n"] for e in common}) == 1 and common[0]["n"] == 59  # cùng một tập lá cho mọi cách
    b_raw = next(e for e in metrics if (e["method"], e["stage"], e["scope"]) == ("b", "raw", "own"))
    assert b_raw["n_levels"] == 6 and set(b_raw) >= {"ece10", "ece5_mass", "brier", "top2_share"}
    md = (tmp_path / "tables.md").read_text()
    assert md.count("\n") == 2 + len(metrics)
    for m in methods:
        for s in ("raw", "cal"):
            png = (tmp_path / f"reliability_{m}_{s}.png").read_bytes()
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
            assert (tmp_path / f"reliability_{m}_{s}.svg").read_text().startswith("<svg")
    rep = json.loads((tmp_path / "manifest.json").read_text())["report"]
    assert rep["bootstrap_note"] == BOOT_NOTE and "2000" in BOOT_NOTE and rep["seed"] == 20260925
    assert rep["c_feasibility_note"].startswith("(c) khả thi")
    assert len(rep["folds"]["a"]) == 5


def test_png_decodes_to_expected_size() -> None:
    png = reliability_png(reliability_bins([Point("a", "H", 0.3, True), Point("b", "H", 0.8, False)]))
    w, h = struct.unpack(">II", png[16:24])
    idat = png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    assert (w, h) == (400, 400) and len(raw) == h * (1 + 3 * w)


def test_describe_b5(tmp_path: Path) -> None:
    a = tmp_path / "gia-tri-a.csv"
    a.write_text("id,ghi_chu,self_report\n" + "".join(f"S{i},x,{v}\n" for i, v in enumerate([0.3, 0.3, 0.7, 0.3, 0.85])))
    got = describe_b5([a])
    assert got[0]["file"] == "gia-tri-a.csv" and got[0]["column"] == "self_report"
    assert got[0]["n"] == 5 and got[0]["n_levels"] == 3 and got[0]["top2_share"] == pytest.approx(0.8)
    two = tmp_path / "hai-cot.csv"
    two.write_text("p,q\n0.1,0.2\n0.3,0.4\n")
    with pytest.raises(ValueError, match="--b5-col"):
        describe_b5([two])
    assert describe_b5([two], "q")[0]["n_levels"] == 2


def test_report_script_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("EVAL_MODE", "true")
    rows = _rows(False)
    (tmp_path / "collected.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "manifest_collect.json").write_text(json.dumps({"model": "deepseek-v4-pro"}))
    b5 = tmp_path / "b5.csv"
    b5.write_text("gia_tri\n0.2\n0.4\n")
    code = load_script("rq2_report").main([str(tmp_path), "--b5-csv", str(b5), "--now", "2026-11-01T00:00:00+07:00"])
    out = capsys.readouterr().out
    assert code == 0 and "rows=60" in out and "n_boot=1000" in out and "tk-" not in out
    rep = json.loads((tmp_path / "manifest.json").read_text())["report"]
    assert rep["n_boot"] == 1000 and rep["b5"][0]["n"] == 2
    assert "CHƯA kiểm trên model B14 (deepseek-v4-pro)" in rep["c_feasibility_note"]
