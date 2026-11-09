"""Báo cáo M8 (`app.eval.report`) — dữ liệu tổng hợp, số tính tay (khớp 1e-9), golden file đầu ra.

10 kịch bản, 5 họ (gold: A = AUTO, H = HITL, L = ESCALATE_L2; "-" = route None):
    sid  họ  gold  intent    tình huống   Chỉ-luật  Chỉ-LLM  Hybrid  (Hybrid decided_by)
    01   F1  A     vpn       SIT-F1       A         A        A       rule
    02   F1  A     vpn       SIT-F1       A         H        A       rule
    03   F2  H     vpn       SIT-F2       H         H        H       rule
    04   F2  H     vpn       SIT-F2       H         H        A       llm   (bỏ sót)
    05   F3  L     account   SIT-F3       L         L        L       rule
    06   F3  L     account   SIT-F3       L         L        H       llm
    07   F4  A     access    SIT-F4a      A         H        A       rule
    08   F4  H     access    SIT-F4b      H         H        H       llm   (họ F4 chứa HAI tình huống)
    09   F5  H     software  SIT-F5       L         -        A       llm   (hidden_factor = true; Chỉ-LLM không tới M5)
    10   F5  chưa nhãn software SIT-F5    H         -        A       llm
Phần giao (đã nhãn, có route ở cả ba phương án) = 01–08 (n = 8). Ma trận chi phí mặc định cost[gold][pred]:
AUTO:{A 0, H 1, L 3}  HITL:{A 10, H 1, L 3}  L2:{A 20, H 6, L 3}.
    Chi phí/ticket trên phần giao: Chỉ-luật (0+0+1+1+3+3+0+1)/8 = 9/8; Chỉ-LLM (0+1+1+1+3+3+1+1)/8 = 11/8;
    Hybrid (0+0+1+10+3+6+0+1)/8 = 21/8; Thủ công (mọi lá HITL: 1+1+1+1+6+6+1+1)/8 = 18/8; Full-auto (3·0+3·10+2·20)/8 = 70/8.
    FNR theo tình huống (tình huống cần người: SIT-F2, SIT-F3, SIT-F4b → n = 3): Hybrid 1 (SIT-F2), các phương án khác 0, Full-auto 3.
    FNR theo HỌ (F2, F3, F4 → n = 3): Chỉ-luật 1 (F4 có câu 07 pred AUTO), Hybrid 2 (F2, F4) — khác FNR theo tình huống.
"""

import csv
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from app.eval.metrics import manual_baseline
from app.eval.predictions import PredictionRecord
from app.eval.report import (
    FAIL,
    NO_DIFF,
    PASS,
    UNKNOWN,
    Arm,
    Report,
    SituationFnr,
    Table,
    abort_as_l2,
    build_report,
    check_arms,
    full_auto_baseline,
    load_arm,
    load_manifest,
    load_situations,
    main,
    render_csv,
    report_files,
    rq1_verdict,
    situation_fnr,
    write_report,
)
from app.eval.stats import PairedDiffCI
from tests.unit.eval.contract_v11 import V11

TOL = 1e-9
GOLDEN_DIR: Final = Path(__file__).parent / "golden" / "report"
SHA: Final = "e" * 64
COMMIT: Final = "f" * 40
RUN: Final = {"rule_only": "a" * 12, "llm_only": "b" * 12, "hybrid": "c" * 12, "hybrid_no_tool": "d" * 12}
FULL: Final = {"A": "AUTO", "H": "HITL", "L": "ESCALATE_L2", "-": None}
# (họ, gold, intent, tình huống, hidden_factor)
SCN: Final = (
    ("F1", "A", "vpn", "SIT-F1", False), ("F1", "A", "vpn", "SIT-F1", False),
    ("F2", "H", "vpn", "SIT-F2", False), ("F2", "H", "vpn", "SIT-F2", False),
    ("F3", "L", "account", "SIT-F3", False), ("F3", "L", "account", "SIT-F3", False),
    ("F4", "A", "access", "SIT-F4a", False), ("F4", "H", "access", "SIT-F4b", False),
    ("F5", "H", "software", "SIT-F5", True), ("F5", "?", "software", "SIT-F5", False),
)  # fmt: skip
ROUTES: Final = {
    "rule_only": "AAHHLLAHLH", "llm_only": "AHHHLLHH--", "hybrid": "AAHALHAHAA", "hybrid_no_tool": "AAHALHAHAA",
}  # fmt: skip
DECIDED: Final = {
    "rule_only": ["rule"] * 10, "llm_only": ["llm"] * 10,
    "hybrid": ["rule", "rule", "rule", "llm", "rule", "llm", "rule", "llm", "llm", "llm"],
}  # fmt: skip
DECIDED["hybrid_no_tool"] = DECIDED["hybrid"]
RAW: Final = {4: 0.2, 6: 0.8, 8: 0.6, 9: 0.5, 10: 0.5}  # raw_prob của ca llm của Hybrid
CLARIFY: Final = {"hybrid": [0, 0, 1, 1, 0, 0, 0, 1, 2, 0], "hybrid_no_tool": [1, 1, 2, 2, 1, 1, 1, 2, 3, 1]}
STRATEGY: Final = {"rule_only": "rule_only", "llm_only": "llm_only", "hybrid": "hybrid", "hybrid_no_tool": "hybrid"}
INTENT_OF: Final = {"vpn": "vpn", "account": "account", "access": "access", "software": "software"}


def rec(name: str, i: int, *, routes: str | None = None, split: str = "test", run: str | None = None) -> PredictionRecord:
    """Lá thứ `i` (1..10) của phương án `name`."""
    fam, gold, intent, _, hidden = SCN[i - 1]
    route = FULL[(routes or ROUTES[name])[i - 1]]
    llm = route is not None and DECIDED[name][i - 1] == "llm"
    clar = CLARIFY.get(name, [0] * 10)[i - 1]
    data: dict[str, Any] = {
        "run_id": run or RUN[name], "strategy": STRATEGY[name], "split": split,
        "scenario_id": f"S{i:02d}", "family": fam, "ticket_id": f"T-{name}-{i:02d}", "parent_ticket_id": None,
        "expected_route": None if gold == "?" else FULL[gold],
        "route": route, "decided_by": None if route is None else DECIDED[name][i - 1],
        "raw_prob": RAW.get(i) if name == "hybrid" and llm else None, "calibrated_prob": None,
        "p_method": "self_report" if name == "hybrid" and llm else None,
        "final_state": None if route is None else "S_RESOLVED", "exit_code": "E1" if name == "llm_only" and i == 9 else None,
        "close_reason": "resolved_user_confirmed" if name in CLARIFY else None, "resolution_path": None,
        "has_approval": False, "clarification_turns": clar, "intent": INTENT_OF[intent], "gold_intent": intent,
        "doc_ids": None, "gold_doc_ids": (), **V11, "hidden_factor": hidden,
        "m5_aborted": None if gold == "?" else False,  # lá đã nhãn không route (S09 llm_only, E1): M5 không bị ngắt → ngoài mẫu số
    }  # fmt: skip
    return PredictionRecord.model_validate(data)


def records(name: str, **kw: Any) -> list[PredictionRecord]:
    return [rec(name, i, **kw) for i in range(1, 11)]


def write_files(tmp: Path, name: str, *, routes: str | None = None, split: str = "test", manifest: Mapping[str, Any] | None = None,
                sha: str = SHA) -> tuple[Path, Path]:  # fmt: skip
    d = tmp / name
    d.mkdir(exist_ok=True)
    recs = records(name, routes=routes, split=split)
    (d / "predictions.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in recs), encoding="utf-8")
    mf: dict[str, Any] = {
        "run_id": RUN[name], "git_commit": COMMIT, "git_dirty": False, "dataset_sha256": sha, "strategy": STRATEGY[name],
        "split": "test", "schema_version": "1.1", "enable_proactive_diagnosis": name != "hybrid_no_tool", "policy_sha256": "9" * 64,
        "clf_mode": "review", "predictions_unavailable": ["fold", "kb_gap", "in_business_hours"],
    }  # fmt: skip
    if manifest is not None:
        mf = {**mf, **manifest}
    (d / "manifest.json").write_text(json.dumps(mf), encoding="utf-8")
    return d / "predictions.jsonl", d / "manifest.json"


def all_arms(tmp: Path, names: Sequence[str] = ("rule_only", "llm_only", "hybrid", "hybrid_no_tool"), **kw: Any) -> list[Arm]:
    return [load_arm(*write_files(tmp, n, **kw)) for n in names]


def situations_csv(tmp: Path) -> Path:
    path = tmp / "situations.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["scenario_id", "situation_id"])
        for i, (_, _, _, sit, _) in enumerate(SCN, start=1):
            w.writerow([f"S{i:02d}", sit])
    return path


def table(report: Report, key: str) -> Table:
    return next(t for t in report.tables if t.key == key)


def rows(report: Report, key: str) -> list[dict[str, Any]]:
    t = table(report, key)
    return [dict(zip(t.columns, r, strict=True)) for r in t.rows]


def row(report: Report, key: str, **where: Any) -> dict[str, Any]:
    hits = [r for r in rows(report, key) if all(r[k] == v for k, v in where.items())]
    assert len(hits) == 1, (key, where, len(hits))
    return hits[0]


def close(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) <= TOL


@pytest.fixture
def rep(tmp_path: Path) -> Report:
    return build_report(all_arms(tmp_path), load_situations(situations_csv(tmp_path)), n_boot=200)


# ---- FNR theo tình huống ---------------------------------------------------------------------------------------------------


def common_sample(name: str) -> list[PredictionRecord]:
    return [r for r in records(name) if r.scenario_id <= "S08"]


def test_situation_fnr_unit_changes_the_number() -> None:
    sit = {f"S{i:02d}": s[3] for i, s in enumerate(SCN, start=1)}
    by_sit = situation_fnr(common_sample("rule_only"), lambda r: sit[r.scenario_id])
    by_fam = situation_fnr(common_sample("rule_only"))
    assert (by_sit.k, by_sit.n) == (0, 3)
    assert (by_fam.k, by_fam.n) == (1, 3)  # họ F4 chứa câu 07 (gold AUTO, pred AUTO) → "ít nhất một câu AUTO"
    assert by_fam.n_mixed == 1 and by_sit.n_mixed == 0  # F4 lẫn gold AUTO / HITL
    hy_sit = situation_fnr(common_sample("hybrid"), lambda r: sit[r.scenario_id])
    hy_fam = situation_fnr(common_sample("hybrid"))
    assert (hy_sit.k, hy_sit.n, hy_fam.k, hy_fam.n) == (1, 3, 2, 3)
    assert close(hy_sit.value, 1 / 3)


def test_situation_fnr_clopper_pearson() -> None:
    f = situation_fnr(common_sample("rule_only"), lambda r: r.scenario_id)  # đơn vị = lá: 5 lá cần người (03–06, 08), không lá nào AUTO
    assert (f.k, f.n) == (0, 5)
    assert f.upper95 is not None and f.hi95 is not None and f.lo95 is not None
    assert close(f.upper95, 1 - 0.05 ** (1 / 5))  # k = 0: 1 − α^(1/n)
    assert close(f.hi95, 1 - 0.025 ** (1 / 5)) and f.lo95 == 0.0
    one = situation_fnr(common_sample("hybrid"), lambda r: r.scenario_id)  # lá 04 pred AUTO → k = 1 trên n = 5 lá cần người
    assert (one.k, one.n) == (1, 5)
    p = one.upper95
    assert p is not None
    # P(X ≤ k) = α với X ~ Binomial(n, p) — đường độc lập với beta.ppf
    assert abs(((1 - p) ** 5 + 5 * p * (1 - p) ** 4) - 0.05) < TOL
    lo = one.lo95
    assert lo is not None and abs((1 - (1 - lo) ** 5) - 0.025) < TOL  # P(X ≥ 1) = 0.025 tại cận dưới


def test_situation_fnr_llm_layer_and_hidden() -> None:
    sit = {f"S{i:02d}": s[3] for i, s in enumerate(SCN, start=1)}
    full = records("hybrid")  # toàn bộ ca tới M5 của Hybrid (lá 10 chưa nhãn bị bỏ)
    llm = situation_fnr(full, lambda r: sit[r.scenario_id], only_llm=True)
    assert (llm.k, llm.n, llm.n_leaves) == (2, 4, 4)  # 04 (SIT-F2) và 09 (SIT-F5) bị bỏ sót; 06, 08 đúng
    p = llm.upper95
    assert p is not None and p >= 0.10
    assert abs(sum(_binom(4, j, p) for j in range(3)) - 0.05) < TOL
    only = situation_fnr(full, lambda r: sit[r.scenario_id], hidden="only")
    rest = situation_fnr(full, lambda r: sit[r.scenario_id], hidden="except")
    assert (only.k, only.n) == (1, 1) and (rest.k, rest.n) == (1, 3)


def _binom(n: int, j: int, p: float) -> float:
    from math import comb

    return comb(n, j) * p**j * (1 - p) ** (n - j)


def test_situation_fnr_ignores_unlabeled_and_route_none_and_empty() -> None:
    f = situation_fnr(records("llm_only"))  # lá 09, 10 route None; lá 10 chưa nhãn
    assert (f.k, f.n) == (0, 3)
    empty = situation_fnr([r for r in records("hybrid") if r.expected_route == "AUTO"])  # không có tình huống cần người
    assert (empty.k, empty.n, empty.value, empty.upper95, empty.lo95, empty.hi95) == (0, 0, None, None, None, None)


# ---- giải tích ----------------------------------------------------------------------------------------------------------


def test_full_auto_baseline() -> None:
    src = records("llm_only")
    out = full_auto_baseline(src)
    assert [r.route for r in out] == ["AUTO"] * 8 + [None, None]
    assert {r.strategy for r in out} == {"full_auto"}
    assert [r.scenario_id for r in out] == [r.scenario_id for r in src]
    assert [r.route for r in src][:2] == ["AUTO", "HITL"]  # đầu vào không đổi


# ---- nạp và kiểm đầu vào ---------------------------------------------------------------------------------------------------


def test_load_arm_names(tmp_path: Path) -> None:
    arms = all_arms(tmp_path)
    assert [a.name for a in arms] == ["rule_only", "llm_only", "hybrid", "hybrid_no_tool"]
    assert all(len(a.records) == 10 for a in arms)


def test_load_arm_refuses_calibration_split(tmp_path: Path) -> None:
    pred, mf = write_files(tmp_path, "hybrid", split="calibration")
    with pytest.raises(ValueError, match="split"):
        load_arm(pred, mf)
    pred, mf = write_files(tmp_path, "hybrid", manifest={"split": "calibration"})
    with pytest.raises(ValueError, match="split"):
        load_arm(pred, mf)


def test_load_arm_requires_manifest(tmp_path: Path) -> None:
    pred, mf = write_files(tmp_path, "hybrid")
    mf.unlink()
    with pytest.raises(ValueError, match="manifest"):
        load_arm(pred, mf)


@pytest.mark.parametrize("key", ["run_id", "git_commit", "dataset_sha256", "enable_proactive_diagnosis", "schema_version"])
def test_manifest_missing_key(tmp_path: Path, key: str) -> None:
    _, mf = write_files(tmp_path, "hybrid")
    data = json.loads(mf.read_text(encoding="utf-8"))
    del data[key]
    mf.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=key):
        load_manifest(mf)


def test_load_arm_mismatch_and_bad_strategy(tmp_path: Path) -> None:
    pred, mf = write_files(tmp_path, "hybrid", manifest={"run_id": "0" * 12})
    with pytest.raises(ValueError, match="lệch"):
        load_arm(pred, mf)
    pred, mf = write_files(tmp_path, "hybrid", manifest={"schema_version": "1.0"})
    with pytest.raises(ValueError, match="schema_version"):
        load_arm(pred, mf)
    pred, mf = write_files(tmp_path, "rule_only", manifest={"enable_proactive_diagnosis": False})
    with pytest.raises(ValueError, match="S3"):
        load_arm(pred, mf)


def test_check_arms_rejects(tmp_path: Path) -> None:
    ok = all_arms(tmp_path)
    check_arms(ok)
    other = load_arm(*write_files(tmp_path, "rule_only", sha="1" * 64))
    with pytest.raises(ValueError, match="dataset_sha256"):
        check_arms([ok[2], other])
    with pytest.raises(ValueError, match="cùng phương án"):
        check_arms([ok[0], ok[0]])
    with pytest.raises(ValueError, match="RQ1"):
        check_arms([ok[3]])
    fewer = Arm("llm_only", ok[1].records[:-1], ok[1].manifest, "x")
    with pytest.raises(ValueError, match="scenario_id"):
        check_arms([ok[0], fewer])
    shifted = Arm("llm_only", tuple(r.model_copy(update={"expected_route": "AUTO"}) for r in ok[1].records), ok[1].manifest, "x")
    with pytest.raises(ValueError, match="gold"):
        check_arms([ok[0], shifted])


def test_load_situations(tmp_path: Path) -> None:
    s = load_situations(situations_csv(tmp_path))
    assert s.mapping["S07"] == "SIT-F4a" and s.mapping["S08"] == "SIT-F4b" and len(s.sha256) == 64
    js = tmp_path / "s.json"
    js.write_text(json.dumps({"S01": "X"}), encoding="utf-8")
    assert load_situations(js).mapping == {"S01": "X"}
    js.write_text(json.dumps([{"scenario_id": "S01", "situation_id": "X"}]), encoding="utf-8")
    assert load_situations(js).mapping == {"S01": "X"}
    js.write_text(json.dumps([{"scenario_id": "S01", "situation_id": "X"}, {"scenario_id": "S01", "situation_id": "Y"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="trùng"):
        load_situations(js)
    bad = tmp_path / "bad.csv"
    bad.write_text("scenario_id,x\nS01,A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cột"):
        load_situations(bad)
    empty = tmp_path / "empty.csv"
    empty.write_text("scenario_id,situation_id\nS01,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="rỗng"):
        load_situations(empty)
    txt = tmp_path / "x.txt"
    txt.write_text("S01,A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="csv"):
        load_situations(txt)


def test_situations_must_cover_dataset(tmp_path: Path) -> None:
    js = tmp_path / "s.json"
    js.write_text(json.dumps({"S01": "X"}), encoding="utf-8")
    with pytest.raises(ValueError, match="thiếu ánh xạ"):
        build_report(all_arms(tmp_path), load_situations(js), n_boot=20)


# ---- số liệu tính tay ------------------------------------------------------------------------------------------------------


def test_t1_primary_cost_unweighted_on_common_set(rep: Report) -> None:
    want = {"Thủ công": 18 / 8, "Full-auto": 70 / 8, "Chỉ-luật": 9 / 8, "Chỉ-LLM": 11 / 8, "Hybrid": 21 / 8}
    for arm, cost in want.items():
        r = row(rep, "t1_rq1_cost", arm=arm)
        assert close(r["cost"], cost), arm
        assert r["n"] == 8  # cùng phần giao (G1-Q1: Thủ công trên đúng phần giao)
        assert r["ci95_lo"] is not None and r["ci95_hi"] is not None and r["n_boot"] == 200 and r["n_families"] == 4
    assert "SỐ CHÍNH RQ1" in table(rep, "t1_rq1_cost").title
    assert not close(row(rep, "t1_rq1_cost", arm="Hybrid")["cost"], 1.25)  # không phải bản có trọng số 70/20/10


def test_meta_columns(rep: Report) -> None:
    assert table(rep, "t1_rq1_cost").columns[:6] == ("run_id", "dataset_sha256", "git_commit", "n", "n_unlabeled", "n_excluded")
    h = row(rep, "t1_rq1_cost", arm="Hybrid")
    assert (h["run_id"], h["dataset_sha256"], h["git_commit"]) == (RUN["hybrid"], SHA, COMMIT)
    assert (h["n"], h["n_unlabeled"], h["n_excluded"]) == (8, 1, 1)  # 9 lá đã nhãn − 8 trong phần giao
    assert row(rep, "t1_rq1_cost", arm="Thủ công")["run_id"] == f"manual@{RUN['hybrid']}"
    for t in rep.tables:
        for r in t.rows:
            assert r[0] and r[1] == SHA and r[2]


def test_t2_cost_diff_points(rep: Report) -> None:
    assert close(row(rep, "t2_rq1_cost_diff", comparison="Hybrid − Chỉ-luật")["diff"], 21 / 8 - 9 / 8)
    assert close(row(rep, "t2_rq1_cost_diff", comparison="Hybrid − Chỉ-LLM")["diff"], 21 / 8 - 11 / 8)


def test_t3a_situation_fnr_rows(rep: Report) -> None:
    want = {"Thủ công": 0, "Full-auto": 3, "Chỉ-luật": 0, "Chỉ-LLM": 0, "Hybrid": 1}
    for arm, k in want.items():
        r = row(rep, "t3a_safety_situation", arm=arm, scope="tất cả")
        assert (r["k_missed"], r["n_situations"], r["n_mixed_gold"]) == (k, 3, 0), arm
        assert r["unit"] == "tình huống (situation_id)"
    h = row(rep, "t3a_safety_situation", arm="Hybrid", scope="lớp LLM (decided_by = llm)")
    assert (h["k_missed"], h["n_situations"]) == (1, 3)  # phần giao: lá 04, 06, 08
    own = next(r for r in rows(rep, "t3a_safety_situation") if str(r["scope"]).startswith("lớp LLM, toàn bộ"))
    assert (own["k_missed"], own["n_situations"]) == (2, 4)


def test_t3a_falls_back_to_family_with_warning(tmp_path: Path) -> None:
    rep = build_report(all_arms(tmp_path), None, n_boot=20)
    warning = "đơn vị = họ, chưa có ánh xạ tình huống"
    assert any(warning in w for w in rep.warnings)
    assert any(warning in n for n in table(rep, "t3a_safety_situation").notes)
    assert any(warning in n for n in table(rep, "t4_rq1_verdict").notes)
    assert row(rep, "t3a_safety_situation", arm="Chỉ-luật", scope="tất cả")["k_missed"] == 1  # theo họ: khác 0 theo tình huống
    assert row(rep, "t3a_safety_situation", arm="Hybrid", scope="tất cả")["k_missed"] == 2
    assert row(rep, "t3a_safety_situation", arm="Chỉ-luật", scope="tất cả")["unit"] == "họ (family)"
    assert any("lẫn AUTO" in w for w in rep.warnings)  # F4 lẫn gold


def test_with_situations_no_family_warning(rep: Report) -> None:
    assert not any("chưa có ánh xạ" in w for w in rep.warnings)
    assert not any("chưa có ánh xạ" in n for n in table(rep, "t4_rq1_verdict").notes)
    assert not any("lẫn AUTO" in w for w in rep.warnings)


def test_t4_verdict_rows(rep: Report) -> None:
    assert rep.verdict.safety == FAIL  # cận trên của 2/4 ≥ 10%
    assert rep.verdict.cost_vs_rule in (FAIL, NO_DIFF) and rep.verdict.cost_vs_llm in (FAIL, NO_DIFF)
    assert rep.verdict.overall.startswith("không đạt")
    assert [r["criterion"] for r in rows(rep, "t4_rq1_verdict")][-1] == "kết luận"


def test_t5_weighted_secondary(rep: Report) -> None:
    main = row(rep, "t5_operating_mix", arm="Hybrid", mix="70/20/10 (chính)")
    # nhóm gold: routine (01,02,07) 0; approval (03,04,08) (1+10+1)/3 = 4; sensitive (05,06) (3+6)/2 = 4,5
    assert close(main["cost_weighted"], 0.2 * 4 + 0.1 * 4.5)
    assert close(row(rep, "t5_operating_mix", arm="Hybrid", mix="60/30/10")["cost_weighted"], 0.3 * 4 + 0.1 * 4.5)
    assert close(row(rep, "t5_operating_mix", arm="Hybrid", mix="80/15/5")["cost_weighted"], 0.15 * 4 + 0.05 * 4.5)
    assert close(main["automation"], 0.7 * 1 + 0.2 / 3)  # routine 3/3 AUTO, approval 1/3, sensitive 0
    assert close(main["review"], 0.2 * 2 / 3 + 0.1 * 1 / 2) and close(main["l2"], 0.1 * 1 / 2)
    assert "SỐ PHỤ" in table(rep, "t5_operating_mix").title
    assert "SỐ PHỤ" in table(rep, "t5_operating_mix").notes[0]


def test_t6_ratio_sensitivity(rep: Report) -> None:
    # Hybrid chỉ có một ô HITL→AUTO (lá 04) phụ thuộc r: tổng = 11 + r → /8
    for ratio, t_low in ((5.0, 0.2), (10.0, 0.1), (20.0, 0.05)):
        r = row(rep, "t6_ratio_sensitivity", arm="Hybrid", ratio=ratio)
        assert close(r["cost"], (11 + ratio) / 8) and close(r["t_low_theoretical"], t_low)
    assert close(row(rep, "t6_ratio_sensitivity", arm="Chỉ-luật", ratio=20.0)["cost"], 9 / 8)  # không ô nào phụ thuộc r


def test_t7_breakeven(rep: Report) -> None:
    m = row(rep, "t7_breakeven", pair="Hybrid vs Thủ công", mix="không trọng số")
    # trên phần giao 01–08 (như T1): Hybrid fixed 11/8, miss 1/8 (chỉ lá 04); Thủ công fixed 18/8, miss 0 → r* = (7/8)/(1/8) = 7
    assert (m["n_pairs"], m["reason"], m["n_excluded_a"], m["n_excluded_b"]) == (8, "ok", 0, 0)
    assert close(m["fixed_a"], 11 / 8) and close(m["miss_a"], 1 / 8) and close(m["fixed_b"], 18 / 8) and close(m["miss_b"], 0.0)
    assert close(m["r_star"], 7.0)
    for r, want in ((5, 2 / 8), (10, -3 / 8), (20, -13 / 8)):  # cost_B − cost_A = (7 − r)/8; r > r* → Hybrid đắt hơn Thủ công
        assert close(m[f"saving_{r}"], want)
    d = row(rep, "t7_breakeven", pair="Hybrid vs Chỉ-luật", mix="không trọng số")
    # Chỉ-luật trên phần giao: fixed 9/8, miss 0 → r* = (9/8 − 11/8)/(1/8) = −2 ≤ 0 → dominated (Hybrid đắt hơn với mọi r, như T2)
    assert (d["reason"], d["n_pairs"], d["r_star"]) == ("dominated", 8, None)
    assert close(d["fixed_b"], 9 / 8) and close(d["miss_b"], 0.0)
    for r, want in ((5, -7 / 8), (10, -12 / 8), (20, -22 / 8)):  # (−2 − r)/8
        assert close(d[f"saving_{r}"], want)
    # 70/20/10: Hybrid approval (03,04,08) fixed 2/3, miss 1/3; sensitive fixed 4,5 → fixed_A = 0,2·2/3 + 0,1·4,5 = 7/12, miss_A = 1/15
    w = row(rep, "t7_breakeven", pair="Hybrid vs Thủ công", mix="70/20/10")  # Thủ công 0,7·1 + 0,2·1 + 0,1·6 = 1,5
    assert close(w["fixed_a"], 7 / 12) and close(w["miss_a"], 1 / 15) and close(w["fixed_b"], 1.5) and close(w["r_star"], 13.75)
    wr = row(rep, "t7_breakeven", pair="Hybrid vs Chỉ-luật", mix="70/20/10")  # fixed_B 0,2·1 + 0,1·3 = 0,5
    assert close(wr["fixed_b"], 0.5) and wr["reason"] == "dominated"
    assert {r["mix"] for r in rows(rep, "t7_breakeven")} == {"không trọng số", "70/20/10", "60/30/10", "80/15/5"}


def test_t7_same_sample_as_t1(rep: Report) -> None:
    """T7 trên CÙNG phần giao với T1: cột meta, n và chi phí ở r = 10 (ma trận mặc định) trùng T1/T2/T5."""
    t1 = {r["arm"]: r for r in rows(rep, "t1_rq1_cost")}
    meta = ("n", "n_unlabeled", "n_excluded")
    for arm in ("Chỉ-LLM", "Hybrid"):
        for other in ("Thủ công", "Chỉ-luật"):
            b = row(rep, "t7_breakeven", pair=f"{arm} vs {other}", mix="không trọng số")
            assert tuple(b[k] for k in meta) == tuple(t1[arm][k] for k in meta) == (8, 1, 1), (arm, other)
            assert b["n_pairs"] == t1[arm]["n"] and (b["n_excluded_a"], b["n_excluded_b"]) == (0, 0)
            assert close(b["fixed_a"] + 10 * b["miss_a"], t1[arm]["cost"]), (arm, other)
            assert close(b["fixed_b"] + 10 * b["miss_b"], t1[other]["cost"]), (arm, other)
    assert close(row(rep, "t7_breakeven", pair="Hybrid vs Thủ công", mix="không trọng số")["fixed_b"], 2.25)  # = T1 Thủ công
    d = row(rep, "t7_breakeven", pair="Hybrid vs Chỉ-luật", mix="không trọng số")
    assert close(d["saving_10"], -row(rep, "t2_rq1_cost_diff", comparison="Hybrid − Chỉ-luật")["diff"])
    w = row(rep, "t7_breakeven", pair="Hybrid vs Thủ công", mix="70/20/10")
    assert close(w["fixed_a"] + 10 * w["miss_a"], row(rep, "t5_operating_mix", arm="Hybrid", mix="70/20/10 (chính)")["cost_weighted"])


def test_t8_ablation(rep: Report) -> None:
    full = row(rep, "t8_ablation", ablation="Hybrid đầy đủ")
    assert close(full["cost"], 21 / 8) and close(full["clarification_mean"], 3 / 8)
    off = row(rep, "t8_ablation", ablation="bỏ tool (tắt chẩn đoán chủ động, S3)")
    assert close(off["clarification_mean"], 11 / 8) and close(off["cost"], 21 / 8)
    assert row(rep, "t8_ablation", ablation="bỏ RAG ở M5 (biến thể không trích đoạn)")["arm"] == "không có dữ liệu"


def test_t9_calibration(rep: Report) -> None:
    h = row(rep, "t9_decided_by_calibration", arm="Hybrid")
    assert close(h["llm_share"], 3 / 8) and close(h["rule_share"], 5 / 8) and h["n_cal_raw"] == 3
    assert close(h["brier_raw"], (0.8**2 + 0.2**2 + 0.4**2) / 3) and close(h["ece_raw"], (0.8 + 0.2 + 0.4) / 3)
    assert h["n_cal_calibrated"] == 0 and h["ece_calibrated"] is None and h["p_method"] == "self_report"
    assert row(rep, "t9_decided_by_calibration", arm="Chỉ-luật")["ece_raw"] is None


def test_t10_rq3_by_intent(rep: Report) -> None:
    allr = row(rep, "t10_rq3_by_intent", intent="(tất cả)")
    assert (allr["n"], allr["n_unlabeled"]) == (10, 1)
    assert close(allr["clarification_on"], 0.5) and close(allr["clarification_off"], 1.5) and close(allr["reduction"], 1.0)
    # mỗi lá tắt chẩn đoán hơn đúng 1 lượt → hiệu = 1 ở mọi lần rút → khoảng suy biến
    assert close(allr["ci95_lo"], 1.0) and close(allr["ci95_hi"], 1.0) and allr["contains_zero"] is False
    assert close(allr["one_turn_on"], 0.6) and close(allr["one_turn_off"], 0.0)
    assert close(allr["route_accuracy_on"], 6 / 9) and close(allr["route_accuracy_off"], 6 / 9)
    sw = row(rep, "t10_rq3_by_intent", intent="software")
    assert close(sw["clarification_on"], 1.0) and close(sw["clarification_off"], 2.0) and close(sw["route_accuracy_on"], 0.0)
    assert {r["intent"] for r in rows(rep, "t10_rq3_by_intent")} == {"(tất cả)", "vpn", "account", "access", "software"}


def test_t11_exclusions(rep: Report) -> None:
    l = row(rep, "t11_exclusions", arm="Chỉ-LLM")
    assert (l["n_leaves"], l["n_unlabeled"], l["n_route_none"], l["n_reached_labelled"], l["n_outside_common"]) == (10, 1, 2, 8, 0)
    assert l["n_e1_injection_suspected"] == 1
    h = row(rep, "t11_exclusions", arm="Hybrid")
    assert (h["n_route_none"], h["n_reached_labelled"], h["n_outside_common"], h["n_e1_injection_suspected"]) == (0, 9, 1, 0)


def test_t0_provenance(rep: Report) -> None:
    assert {r["run_id"] for r in rows(rep, "t0_provenance")} == set(RUN.values())
    h = row(rep, "t0_provenance", arm="Hybrid")
    assert h["policy_sha256"] == "9" * 64 and h["clf_mode"] == "review" and h["predictions_unavailable"] == "fold,kb_gap,in_business_hours"
    assert row(rep, "t0_provenance", arm="Chỉ-LLM")["n_excluded"] == 2  # route None


def test_unlabeled_reported(rep: Report) -> None:
    assert any("n_unlabeled = 1/10" in w for w in rep.warnings)
    assert any("fold = null" in w for w in rep.warnings)


def test_missing_arms_do_not_invent_numbers(tmp_path: Path) -> None:
    rep = build_report(all_arms(tmp_path, ("hybrid",)), None, n_boot=20)
    assert rep.verdict.cost_vs_rule == UNKNOWN and rep.verdict.cost_vs_llm == UNKNOWN
    assert rep.verdict.overall.startswith("không đạt") or "chưa kết luận" in rep.verdict.overall
    assert not rows(rep, "t10_rq3_by_intent") and any("S3" in w for w in rep.warnings)
    assert row(rep, "t2_rq1_cost_diff", comparison="Hybrid − Chỉ-luật")["diff"] is None


def test_empty_common_set(tmp_path: Path) -> None:
    arms = [load_arm(*write_files(tmp_path, "rule_only")), load_arm(*write_files(tmp_path, "llm_only", routes="----------")),
            load_arm(*write_files(tmp_path, "hybrid"))]  # fmt: skip
    rep = build_report(arms, None, n_boot=20)
    assert any("Phần giao rỗng" in w for w in rep.warnings)
    assert row(rep, "t1_rq1_cost", arm="Hybrid")["cost"] is None and row(rep, "t1_rq1_cost", arm="Hybrid")["n"] == 0
    assert not rows(rep, "t7_breakeven")  # phần giao rỗng → không bịa số hoà vốn


# ---- kết luận RQ1 -----------------------------------------------------------------------------------------------------------


def diff(lo: float, hi: float) -> PairedDiffCI:
    return PairedDiffCI(0.0, lo, hi, lo <= 0.0 <= hi, 2000, 2000, 0, 10, 1, 0.95)


def fnr(upper: float | None, n: int = 20) -> SituationFnr:
    return SituationFnr(0, n, n, 0, upper, 0.0, upper)


def test_verdict_pass() -> None:
    v = rq1_verdict(diff(-2.0, -0.1), diff(-1.0, -0.01), fnr(0.0999))
    assert (v.cost_vs_rule, v.cost_vs_llm, v.safety) == (PASS, PASS, PASS)
    assert v.overall == "Hybrid tốt hơn: cả hai vế đạt"


def test_verdict_cost_boundary_zero_is_not_pass() -> None:
    v = rq1_verdict(diff(-1.0, 0.0), diff(-2.0, -0.5), fnr(0.05))
    assert v.cost_vs_rule == NO_DIFF  # hi = 0 chưa "hẳn dưới 0"
    assert v.overall.startswith("không đạt") and "Chỉ-luật" in v.overall


def test_verdict_cost_worse_and_safety_limit() -> None:
    v = rq1_verdict(diff(0.2, 1.0), diff(-2.0, -0.5), fnr(0.10))
    assert v.cost_vs_rule == FAIL and v.cost_vs_llm == PASS
    assert v.safety == FAIL  # cận trên = 10% chưa "< 10%"


def test_verdict_unknown() -> None:
    v = rq1_verdict(None, diff(-2.0, -0.5), None)
    assert (v.cost_vs_rule, v.safety) == (UNKNOWN, UNKNOWN)
    assert "chưa kết luận được" in v.overall
    assert rq1_verdict(diff(-2.0, -0.5), diff(-2.0, -0.5), fnr(None, 0)).safety == UNKNOWN


# ---- ghi file, golden, CLI -----------------------------------------------------------------------------------------------------


def test_write_report_refuses_overwrite(rep: Report, tmp_path: Path) -> None:
    out = tmp_path / "out"
    names = write_report(rep, out)
    assert names[0] == "report.md" and len(names) == 1 + len(rep.tables)
    assert all((out / n).is_file() for n in names)
    with pytest.raises(ValueError, match="--out"):
        write_report(rep, out)


def test_csv_has_meta_header_and_blank_for_none(rep: Report) -> None:
    text = render_csv(table(rep, "t3a_safety_situation"))
    lines = text.splitlines()
    assert lines[0].startswith("run_id,dataset_sha256,git_commit,n,n_unlabeled,n_excluded,arm,scope")
    assert SHA in lines[1]  # CSV ghi sha đầy đủ; markdown rút gọn
    assert SHA not in report_files(rep)["report.md"]


def run_cli(tmp: Path, *extra: str, with_situations: bool = True) -> tuple[int, list[str], Path]:
    out_dir = tmp / "out"
    args: list[str] = []
    for name in ("rule_only", "llm_only", "hybrid", "hybrid_no_tool"):
        pred, mf = write_files(tmp, name)
        args += ["--arm", str(pred), str(mf)]
    if with_situations:
        args += ["--situations", str(situations_csv(tmp))]
    lines: list[str] = []
    code = main([*args, "--out", str(out_dir), "--n-boot", "200", *extra], out=lines.append)
    return code, lines, out_dir


def test_cli_matches_golden(tmp_path: Path) -> None:
    code, lines, out_dir = run_cli(tmp_path)
    assert code == 0 and any(line.startswith("verdict:") for line in lines)
    produced = {p.name: p.read_text(encoding="utf-8") for p in sorted(out_dir.iterdir())}
    if os.environ.get("UPDATE_GOLDEN") == "1":  # chỉ khi cố ý đổi định dạng/số, rồi đọc lại diff
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        for name, text in produced.items():
            (GOLDEN_DIR / f"{name}.golden").write_text(text, encoding="utf-8")
    golden = {p.name.removesuffix(".golden"): p.read_text(encoding="utf-8") for p in sorted(GOLDEN_DIR.glob("*.golden"))}
    assert produced.keys() == golden.keys()
    for name, text in produced.items():
        assert text == golden[name], name


def test_cli_errors(tmp_path: Path) -> None:
    lines: list[str] = []
    assert main(["--out", str(tmp_path / "o")], out=lines.append) == 2 and "DỪNG" in lines[-1]
    pred, mf = write_files(tmp_path, "hybrid")
    mf.unlink()
    assert main(["--arm", str(pred), str(mf), "--out", str(tmp_path / "o")], out=lines.append) == 2
    assert "manifest" in lines[-1]
    assert not (tmp_path / "o").exists()  # lỗi đầu vào thì không tạo thư mục
    assert main(["--bogus"], out=lines.append) == 2


def test_cli_without_situations_prints_warning(tmp_path: Path) -> None:
    code, lines, _ = run_cli(tmp_path, with_situations=False)
    assert code == 0 and any("chưa có ánh xạ tình huống" in line for line in lines)


def test_manual_baseline_matches_report_manual(rep: Report) -> None:
    # Thủ công trong báo cáo = manual_baseline của chính Hybrid trên phần giao (mọi lá có route → HITL).
    sample = common_sample("hybrid")
    assert {r.route for r in manual_baseline(sample)} == {"HITL"}
    assert row(rep, "t3a_safety_situation", arm="Thủ công", scope="tất cả")["k_missed"] == 0


# ---- lá không tới điểm log 4: CÙNG quy tắc với offline.py cho mọi phương án (P8 §5.4 [Chốt 22/10]) ---------------------------


def patch_rows(path: Path, updates: Mapping[str, Mapping[str, Any]]) -> None:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        row.update(updates.get(row["scenario_id"], {}))
        out.append(json.dumps(row))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def no_route(r: PredictionRecord, flag: bool | None) -> PredictionRecord:
    return r.model_copy(update={"route": None, "decided_by": None, "raw_prob": None, "calibrated_prob": None, "p_method": None,
                                "kb_gap": None, "m5_aborted": flag})  # fmt: skip


def test_abort_as_l2_converts_only_aborted_route_none() -> None:
    base = records("rule_only")
    aborted, kept = no_route(base[2], True), no_route(base[3], False)  # S03 M5 bị ngắt; S04 không ngắt
    unlabeled = no_route(base[9], None)  # S10 chưa nhãn: không cần cờ
    out = abort_as_l2([aborted, kept, unlabeled, base[0]])
    assert [r.route for r in out] == ["ESCALATE_L2", None, None, base[0].route]
    assert out[0].decided_by is None and out[0].raw_prob is None  # chỉ đổi route, không bịa trường rủi ro
    assert abort_as_l2(out) == out  # lặp lại trên file của offline.py (route đã đổi) không đổi gì


def test_abort_as_l2_null_flag_on_labeled_route_none_raises() -> None:
    with pytest.raises(ValueError, match="m5_aborted"):
        abort_as_l2([no_route(records("rule_only")[2], None)])


def test_load_arm_reports_file_name_when_flag_is_null(tmp_path: Path) -> None:
    pred, mf = write_files(tmp_path, "rule_only", routes="AA-HLLAHLH")
    patch_rows(pred, {"S03": {"m5_aborted": None}})
    with pytest.raises(ValueError, match=r"predictions\.jsonl: m5_aborted"):
        load_arm(pred, mf)


def n_common(tmp: Path, *, rule_flag: bool, llm_flag: bool) -> int:
    """S09 (nhãn HITL) không route ở Chỉ-luật và Chỉ-LLM; Hybrid có route. Số lá của phần giao (T1.n)."""
    tmp.mkdir(parents=True, exist_ok=True)
    arms = []
    for name, routes, flag in (("rule_only", "AAHHLLAH-H", rule_flag), ("llm_only", "AHHHLLHH--", llm_flag), ("hybrid", "AAHALHAHAA", None)):
        pred, mf = write_files(tmp, name, routes=routes)
        if flag is not None:
            patch_rows(pred, {"S09": {"m5_aborted": flag}})
        arms.append(load_arm(pred, mf))
    return int(row(build_report(arms, None, n_boot=20), "t1_rq1_cost", arm="Hybrid")["n"])


def test_rule_only_uses_the_same_abort_rule_so_denominators_match(tmp_path: Path) -> None:
    """S09 vào phần giao chỉ khi CẢ Chỉ-luật lẫn Chỉ-LLM tính nó là ESCALATE_L2 (M5 bị ngắt); một bên ngoài mẫu số → ra khỏi phần giao."""
    assert n_common(tmp_path / "a", rule_flag=True, llm_flag=True) == 9
    assert n_common(tmp_path / "b", rule_flag=False, llm_flag=True) == 8  # Chỉ-luật không ngắt → ngoài mẫu số
    assert n_common(tmp_path / "c", rule_flag=True, llm_flag=False) == 8
    assert n_common(tmp_path / "d", rule_flag=False, llm_flag=False) == 8
