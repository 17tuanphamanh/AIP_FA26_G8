"""N18 — `app.eval.offline`: route offline của Hybrid, Chỉ-LLM, Hybrid-guarded (P8 v1.4 §5.3, §5.4) trên dữ liệu tổng hợp.

Dữ liệu: 66 kịch bản, 10 họ F01..F10 (họ Fk → phần (k−1) % 5 + 1), lượt S1 (hybrid) và S2 (llm_only) dựng đúng hợp đồng
predictions v1.1 (nạp bằng `load_predictions` thật), `probs.jsonl` như G10 ghi. Kịch bản đặc biệt (P8 §5.4 [Chốt 22/10], trường `m5_aborted`):
  S60 chưa nhãn · S61 nhãn, route null, E1, m5_aborted false (ngoài mẫu) · S62 nhãn, route null, E2 hết hạn lượt tại B12/B14,
  m5_aborted true (→ ESCALATE_L2) · S63 S1 luật CHO PHÉP nhưng S2 route null, E2 tại B12, m5_aborted true ·
  S64 nhãn, route null, E9 tại B3, m5_aborted false (ngoài mẫu số) · S65 nhãn, route null, `final_state` null do kẹt B11, m5_aborted false.
Kỳ vọng chép từ P8 §5.4 và 7 điểm duyệt 22–23/10, không suy từ code.
"""

import dataclasses
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from app.eval import offline
from app.eval.offline import ArmRow, StopError
from app.eval.predictions import PredictionRecord, load_predictions
from app.eval.report import build_report, check_arms, load_arm
from app.risk.calibrator import load_calibrator
from app.settings import parse_policy
from tests.unit.eval.contract_v11 import V11

REPO = Path(__file__).resolve().parents[4]
GOLD = ("AUTO", "HITL", "ESCALATE_L2", "AUTO", "HITL", "AUTO")
N = 60
SPECIAL = 66
SHA = "e" * 64
STARTED = "2026-10-22T03:00:00+00:00"
Dict = dict[str, Any]


def p_of(i: int) -> float:
    base = {"AUTO": 0.12, "HITL": 0.5, "ESCALATE_L2": 0.85}[GOLD[i % 6]]
    return round(min(0.98, max(0.02, base + ((i * 7) % 9 - 4) * 0.03)), 4)


def no_ev(p: float) -> float:
    return round(min(0.98, p * 0.9 + 0.04), 4)


def rule_route(i: int) -> str:
    return ("AUTO", "HITL", "ESCALATE_L2")[(i // 5) % 3]


def is_rule(i: int) -> bool:
    return i % 5 == 0 and i < N


def kb_gap_of(i: int) -> bool:
    return i % 8 == 3


def sid(i: int) -> str:
    return f"S{i:02d}"


def family(i: int) -> str:
    return {60: "F01", 61: "F01", 62: "F02", 63: "F03", 64: "F04", 65: "F05"}.get(i, f"F{i // 6 + 1:02d}")


def expected(i: int) -> str | None:
    if i == 60:
        return None
    return {61: "HITL", 62: "HITL", 63: "AUTO", 64: "HITL", 65: "HITL"}.get(i, GOLD[i % 6])


def m5_aborted_of(strategy: str, i: int) -> bool | None:
    """Cờ của collector: M5 bị ngắt giữa chừng (event lớp bọc lỗi tại S_ASSESSING) — S62 mọi lượt; S63 chỉ ở S2; chưa nhãn → null."""
    if i == 60:
        return None
    return i == 62 or (i == 63 and strategy == "llm_only")


def record(run: str, strategy: str, i: int) -> Dict:
    """Một lá của lượt `strategy` ('hybrid' = S1, 'llm_only' = S2)."""
    s1 = strategy == "hybrid"
    route: str | None
    decided: str | None
    exit_code: str | None = None
    if i == 60:
        route = decided = None
    elif i in (61, 62, 64, 65):
        route, decided, exit_code = None, None, {61: "E1", 62: "E2", 64: "E9", 65: None}[i]
    elif i == 63:
        route, decided = ("AUTO", "rule") if s1 else (None, None)
        exit_code = None if s1 else "E2"
    elif s1 and is_rule(i):
        route, decided = rule_route(i), "rule"
    else:
        route, decided = "HITL", "llm"  # route của stack (chưa hiệu chỉnh); offline sẽ tính lại
    llm = decided == "llm"
    return {
        "run_id": run, "strategy": strategy, "split": "test", "scenario_id": sid(i), "family": family(i),
        "ticket_id": f"T-{strategy}-{i:02d}", "parent_ticket_id": None, "expected_route": expected(i), "route": route,
        "decided_by": decided, "raw_prob": p_of(i) if llm else None, "calibrated_prob": None,
        "p_method": "self_report" if llm else None, "final_state": None if i == 65 else ("S_RESOLVED" if route else "S_ESCALATED"),
        "exit_code": exit_code, "close_reason": None, "resolution_path": None, "has_approval": False,
        "clarification_turns": 0, "intent": "vpn", "gold_intent": "vpn", "doc_ids": None, "gold_doc_ids": [],
        **V11, "kb_gap": kb_gap_of(i) if llm else None, "m5_aborted": m5_aborted_of(strategy, i),
    }  # fmt: skip


def prob_lines(strategy: str) -> list[Dict]:
    out: list[Dict] = []
    for i in range(SPECIAL):
        r = record("x" * 12, strategy, i)
        if r["decided_by"] != "llm":
            continue
        p = p_of(i)
        out += [{"scenario_id": sid(i), "variant": "with_evidence", "raw_prob": p},
                {"scenario_id": sid(i), "variant": "no_evidence", "raw_prob": no_ev(p)},
                {"scenario_id": sid(i), "variant": "max", "raw_prob": max(p, no_ev(p))}]  # fmt: skip
    return out


def policy_bytes(high: float | None = None) -> bytes:
    data = json.loads((REPO / "config" / "policy.json").read_text(encoding="utf-8"))
    low = data["constants"]["THRESHOLD_LOW"]
    data["constants"]["THRESHOLD_HIGH"] = high if high is not None else round((low + 1) / 2, 3)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


class World:
    """Bộ file đầu vào trong `tmp_path` + cách chỉnh từng phần trước khi ghi."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.policy = policy_bytes()
        self.rec: dict[str, list[Dict]] = {s: [record(r, s, i) for i in range(SPECIAL)] for s, r in (("hybrid", "a" * 12), ("llm_only", "b" * 12))}
        self.probs: dict[str, list[Dict]] = {s: prob_lines(s) for s in ("hybrid", "llm_only")}
        self.manifest: dict[str, Dict] = {}
        for s, r in (("hybrid", "a" * 12), ("llm_only", "b" * 12)):
            self.manifest[s] = {
                "run_id": r, "git_commit": "f" * 40, "git_dirty": False, "dataset_sha256": SHA, "strategy": s, "split": "test",
                "schema_version": "1.1", "enable_proactive_diagnosis": True, "policy_sha256": hashlib.sha256(self.policy).hexdigest(),
                "clf_mode": "review", "predictions_unavailable": ["fold", "kb_gap", "in_business_hours"], "started_at": STARTED,
            }  # fmt: skip
        self.folds = [(f"F{k:02d}", (k - 1) % 5 + 1) for k in range(1, 11)]

    def row(self, strategy: str, i: int) -> Dict:
        return next(r for r in self.rec[strategy] if r["scenario_id"] == sid(i))

    def enable_s3(self) -> None:
        """S3 = Hybrid tắt chẩn đoán: cùng kịch bản/gold với S1, nhưng p khác (+0,04) và hỏi lại nhiều hơn (2 lượt)."""
        self.rec["s3"] = [{**record("c" * 12, "hybrid", i), "clarification_turns": 2} for i in range(SPECIAL)]
        self.probs["s3"] = prob_lines("hybrid")
        self.manifest["s3"] = {**self.manifest["hybrid"], "run_id": "c" * 12, "enable_proactive_diagnosis": False}
        for i in range(SPECIAL):
            if self.row("s3", i)["decided_by"] == "llm":
                p = round(min(0.98, p_of(i) + 0.04), 4)
                set_p(self, "s3", i, p, no_ev(p), max(p, no_ev(p)))

    def write(self) -> list[str]:
        d = self.tmp
        files: dict[str, bytes] = {}
        for tag, s in (("s1", "hybrid"), ("s2", "llm_only")):
            files[f"{tag}.jsonl"] = "".join(json.dumps(r) + "\n" for r in self.rec[s]).encode()
            files[f"{tag}-manifest.json"] = json.dumps(self.manifest[s]).encode()
            files[f"{tag}-probs.jsonl"] = "".join(json.dumps(r) + "\n" for r in self.probs[s]).encode()
        if "s3" in self.rec:
            files["s3.jsonl"] = "".join(json.dumps(r) + "\n" for r in self.rec["s3"]).encode()
            files["s3-manifest.json"] = json.dumps(self.manifest["s3"]).encode()
            files["s3-probs.jsonl"] = "".join(json.dumps(r) + "\n" for r in self.probs["s3"]).encode()
        files["folds.csv"] = ("family,fold\n" + "".join(f"{f},{k}\n" for f, k in self.folds)).encode()
        files["policy.json"] = self.policy
        for name, data in files.items():
            (d / name).write_bytes(data)
        s3 = ["--s3", str(d / "s3.jsonl"), str(d / "s3-manifest.json"), str(d / "s3-probs.jsonl")] if "s3" in self.rec else []
        return ["--s1", str(d / "s1.jsonl"), str(d / "s1-manifest.json"), str(d / "s1-probs.jsonl"),
                "--s2", str(d / "s2.jsonl"), str(d / "s2-manifest.json"), str(d / "s2-probs.jsonl"), *s3,
                "--folds", str(d / "folds.csv"), "--policy", str(d / "policy.json")]  # fmt: skip


def run_cli(w: World, out_name: str = "out", extra: list[str] | None = None) -> tuple[int, Path]:
    args = w.write()
    out = w.tmp / out_name
    return offline.main([*args, "--out", str(out), *(extra or [])]), out


def load_world_runs(w: World) -> tuple[offline.Run, offline.Run, dict[str, int]]:
    args = w.write()
    d = w.tmp
    s1 = offline.load_run(d / "s1.jsonl", d / "s1-manifest.json", d / "s1-probs.jsonl", strategy="hybrid")
    s2 = offline.load_run(d / "s2.jsonl", d / "s2-manifest.json", d / "s2-probs.jsonl", strategy="llm_only")
    folds, _ = offline.load_folds(d / "folds.csv")
    assert args
    return s1, s2, folds


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def set_p(w: World, strategy: str, i: int, with_ev: float, no_ev_p: float, mx: float) -> None:
    """Đổi p của ca `i` ở lượt `strategy` (predictions + probs.jsonl cùng lượt, để vẫn nhất quán)."""
    w.row(strategy, i)["raw_prob"] = with_ev
    new = {"with_evidence": with_ev, "no_evidence": no_ev_p, "max": mx}
    for line in w.probs[strategy]:
        if line["scenario_id"] == sid(i):
            line["raw_prob"] = new[line["variant"]]


def kinds(rows: list[ArmRow]) -> dict[str, str]:
    return {r.base.scenario_id: r.kind for r in rows}


# ---- điểm 1: tập ca đi lớp LLM của từng phương án ------------------------------------------------------------------------------


def test_p1_hybrid_only_llm_decided_cases_go_to_llm_rule_cases_keep_route(w: World) -> None:
    set_p(w, "hybrid", 1, 0.41, 0.40, 0.41)  # S1 khác S2 ở ca S01: Hybrid phải lấy p của S1
    s1, s2, folds = load_world_runs(w)
    rows = offline.classify("hybrid", s1, s2, folds)
    k = kinds(rows)
    for i in range(N):
        assert k[sid(i)] == ("fixed" if is_rule(i) else "llm"), i
    fixed = {r.base.scenario_id: r.fixed_route for r in rows if r.kind == "fixed"}
    assert fixed[sid(0)] == "AUTO" and fixed[sid(5)] == "HITL" and fixed[sid(10)] == "ESCALATE_L2"
    assert k[sid(60)] == "out" and k[sid(61)] == "out" and k[sid(62)] == "no_log4" and k[sid(63)] == "fixed"
    assert k[sid(64)] == "out" and k[sid(65)] == "out"  # E9 tại B3 và kẹt B11: M5 không bị ngắt → ngoài mẫu số
    llm = next(r for r in rows if r.base.scenario_id == sid(1))
    assert dict(llm.probs) == {"with_evidence": 0.41, "no_evidence": 0.40, "max": 0.41}
    other = next(r for r in rows if r.base.scenario_id == sid(2))
    assert dict(other.probs) == {"with_evidence": p_of(2), "no_evidence": no_ev(p_of(2)), "max": max(p_of(2), no_ev(p_of(2)))}


def test_p1_llm_only_includes_rule_matched_cases_with_s2_probabilities(w: World) -> None:
    s1, s2, folds = load_world_runs(w)
    rows = offline.classify("llm_only", s1, s2, folds)
    k = kinds(rows)
    assert all(k[sid(i)] == "llm" for i in range(N))  # kể cả ca S1 do luật quyết
    assert k[sid(63)] == "no_log4" and k[sid(62)] == "no_log4"
    assert k[sid(61)] == "out" and k[sid(60)] == "out" and k[sid(64)] == "out" and k[sid(65)] == "out"
    assert [r.base.strategy for r in rows] == ["llm_only"] * len(rows) and rows[0].base.run_id == "b" * 12


def test_p1_guarded_rule_allow_and_unmatched_go_to_llm_blocking_rules_keep_route(w: World) -> None:
    # S2 khác S1 ở ca S01 (llm trong S1) để chứng minh p của guarded lấy từ S2
    set_p(w, "hybrid", 1, 0.41, 0.40, 0.41)
    set_p(w, "llm_only", 1, 0.33, 0.31, 0.33)
    s1, s2, folds = load_world_runs(w)
    rows = offline.classify("hybrid_guarded", s1, s2, folds)
    k = kinds(rows)
    assert k[sid(0)] == "llm"  # luật CHO PHÉP (AUTO) → lớp LLM xét thêm
    assert k[sid(5)] == "fixed" and k[sid(10)] == "fixed"  # luật cần duyệt / chặn giữ route luật
    assert all(k[sid(i)] == "llm" for i in range(N) if not is_rule(i))
    by = {r.base.scenario_id: r for r in rows}
    assert by[sid(1)].probs["with_evidence"] == 0.33 and by[sid(1)].probs["no_evidence"] == 0.31  # p từ S2
    assert by[sid(0)].probs["with_evidence"] == p_of(0)  # ca luật cho phép: p từ S2 (S1 không có)
    src0 = by[sid(0)].src
    assert src0 is not None and src0.strategy == "llm_only"
    assert k[sid(63)] == "no_log4"  # S1 luật cho phép nhưng S2 không tới điểm log 4 → không có p lớp LLM → L2
    assert all(r.base.strategy == "hybrid" for r in rows)  # dòng nguồn S1; offline đổi nhãn khi ghi


def test_p1_probabilities_looked_up_per_scenario_and_variant(w: World) -> None:
    s1, s2, folds = load_world_runs(w)
    for arm in ("hybrid", "llm_only", "hybrid_guarded"):
        for r in offline.classify(arm, s1, s2, folds):
            if r.kind == "llm":
                i = int(r.base.scenario_id[1:])
                assert r.probs["no_evidence"] == no_ev(p_of(i)) and r.probs["with_evidence"] == p_of(i), (arm, i)
                assert r.probs["max"] == max(p_of(i), no_ev(p_of(i))), (arm, i)


def test_p1_probs_must_match_predictions_of_the_same_run(w: World) -> None:
    w.probs["hybrid"][0]["raw_prob"] = 0.0001  # with_evidence của S1 ≠ raw_prob trong predictions S1
    s1, s2, folds = load_world_runs(w)
    with pytest.raises(StopError, match="with_evidence khác raw_prob"):
        offline.classify("hybrid", s1, s2, folds)


def test_p1_probs_must_cover_with_evidence_of_every_llm_case(w: World) -> None:
    w.probs["hybrid"] = [p for p in w.probs["hybrid"] if not (p["scenario_id"] == sid(1) and p["variant"] == "with_evidence")]
    s1, s2, folds = load_world_runs(w)
    with pytest.raises(StopError, match="thiếu with_evidence"):
        offline.classify("hybrid", s1, s2, folds)


# ---- ca lớp LLM không có xác suất ghi lại: giữ route hệ thống, đếm llm_no_prob ----------------------------------------------------

NO_PROB_ARMS = [("hybrid", "hybrid"), ("llm_only", "llm_only"), ("hybrid_guarded", "llm_only"), (offline.NO_DIAG_ARM, "s3")]


def drop_p(w: World, strategy: str, i: int, route: str = "HITL") -> None:
    """Ca `i` ở lượt `strategy`: lớp LLM không ghi được xác suất — `raw_prob` null, route hệ thống `route`, KHÔNG có dòng probs nào."""
    row = w.row(strategy, i)
    row["raw_prob"], row["route"] = None, route
    w.probs[strategy] = [p for p in w.probs[strategy] if p["scenario_id"] != sid(i)]


def classify_arm(w: World, arm: str) -> list[ArmRow]:
    s1, s2, folds = load_world_runs(w)
    if arm == offline.NO_DIAG_ARM:
        d = w.tmp
        s3 = offline.load_run(d / "s3.jsonl", d / "s3-manifest.json", d / "s3-probs.jsonl", strategy="hybrid", diagnosis=False)
        return offline.classify("hybrid", s3, s2, folds)
    return offline.classify(arm, s1, s2, folds)


def signature(r: ArmRow) -> tuple[Any, ...]:
    return (r.kind, r.fixed_route, dict(r.probs), r.kb_gap, r.no_prob, r.fold)


@pytest.mark.parametrize(("arm", "strategy"), NO_PROB_ARMS)
def test_llm_case_without_probability_keeps_system_route_and_is_counted(w: World, arm: str, strategy: str) -> None:
    """(a) Ca S01 (đi lớp LLM, phần 1): `raw_prob` null, route hệ thống HITL, không có dòng probs → ra HITL, `llm_no_prob` = 1.
    Ca khác: phân loại (kind, route cố định, p, kb_gap) không đổi; ca cùng phần đo 1 ra y hệt (calibrator phần 1 fit trên phần 2–5,
    không chứa S01). Ca ở phần khác có thể đổi route vì S01 rời tập huấn luyện của chúng — đúng thiết kế, không kiểm."""
    if strategy == "s3":
        w.enable_s3()
    before = {r.base.scenario_id: signature(r) for r in classify_arm(w, arm)}
    assert run_cli(w, "base")[0] == 0
    drop_p(w, strategy, 1)
    rows = classify_arm(w, arm)
    after = {r.base.scenario_id: signature(r) for r in rows}
    assert after.pop(sid(1)) == ("fixed", "HITL", {}, None, True, 1)
    assert after == {k: v for k, v in before.items() if k != sid(1)}

    code, out = run_cli(w)
    assert code == 0
    got = {r.scenario_id: r for r in load_predictions(out / arm / "predictions.jsonl")}
    s01 = got[sid(1)]
    assert s01.route == "HITL" and s01.decided_by == "llm" and s01.calibrated_prob is None and s01.fold == 1
    # dòng ghi ra = dòng nguồn (base) giữ nguyên: Hybrid-guarded ghi dòng S1 (raw_prob của S1), các phương án khác base = src (null)
    assert s01.raw_prob == (w.row("hybrid", 1)["raw_prob"] if arm == "hybrid_guarded" else None)
    base = {r.scenario_id: r for r in load_predictions(w.tmp / "base" / arm / "predictions.jsonl")}
    same_fold = [k for k, r in base.items() if r.fold == 1 and k != sid(1)]
    assert same_fold and all(got[k] == base[k] for k in same_fold)
    counts = json.loads((out / arm / "manifest.json").read_text(encoding="utf-8"))["offline"]["counts"]
    base_counts = json.loads((w.tmp / "base" / arm / "manifest.json").read_text(encoding="utf-8"))["offline"]["counts"]
    assert counts["llm_no_prob"] == 1 and base_counts["llm_no_prob"] == 0
    assert counts["llm"] == base_counts["llm"] - 1 and counts["fixed"] == base_counts["fixed"] + 1
    if arm == "hybrid":  # S2 không đổi → Chỉ-LLM và Hybrid-guarded không có ca nào như vậy
        for other in ("llm_only", "hybrid_guarded"):
            assert json.loads((out / other / "manifest.json").read_text(encoding="utf-8"))["offline"]["counts"]["llm_no_prob"] == 0


@pytest.mark.parametrize(("arm", "strategy", "i", "route"), [("hybrid", "hybrid", 1, "AUTO"), ("llm_only", "llm_only", 1, "AUTO"),
                                                              (offline.NO_DIAG_ARM, "s3", 1, "AUTO"),
                                                              ("hybrid_guarded", "llm_only", 0, "HITL")])  # fmt: skip
def test_llm_case_without_probability_and_system_route_auto_stops(
    w: World, capsys: pytest.CaptureFixture[str], arm: str, strategy: str, i: int, route: str
) -> None:
    """(b) Như (a) nhưng route hệ thống (route của dòng nguồn ghi ra) là AUTO → DỪNG, không đoán. Hybrid-guarded: dòng nguồn là S1 — S00 luật
    CHO PHÉP (AUTO) ở S1 mà S2 không có p → dừng."""
    if strategy == "s3":
        w.enable_s3()
    drop_p(w, strategy, i, route)
    with pytest.raises(StopError, match="route hệ thống là AUTO"):
        classify_arm(w, arm)
    code, out = run_cli(w)
    assert code == 2 and not out.exists()
    assert "route hệ thống là AUTO" in capsys.readouterr().err


@pytest.mark.parametrize(("arm", "strategy"), NO_PROB_ARMS)
def test_llm_case_with_raw_prob_but_no_probs_lines_still_stops(w: World, arm: str, strategy: str) -> None:
    """(c) Ca CÓ `raw_prob` mà `probs.jsonl` không có dòng nào của ca → vẫn DỪNG như cũ (nhầm file / thu thiếu)."""
    if strategy == "s3":
        w.enable_s3()
    w.probs[strategy] = [p for p in w.probs[strategy] if p["scenario_id"] != sid(1)]
    assert w.row(strategy, 1)["raw_prob"] is not None
    with pytest.raises(StopError, match="thiếu with_evidence"):
        classify_arm(w, arm)


# ---- điểm 2 + Q3: kb_gap ------------------------------------------------------------------------------------------------------


def test_kb_gap_null_on_llm_case_stops_with_message_for_the_harness(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    w.row("hybrid", 1)["kb_gap"] = None
    code, out = run_cli(w)
    assert code == 2 and not out.exists()
    assert "harness phải điền kb_gap" in capsys.readouterr().err


def test_kb_gap_hybrid_rule_matched_cases_need_no_kb_gap(w: World) -> None:
    """(a) Hybrid: ca khớp luật ở S1 giữ route luật — dòng S1 của chúng không có `kb_gap` (null) và KHÔNG làm dừng."""
    assert all(w.row("hybrid", i)["kb_gap"] is None for i in range(N) if is_rule(i))  # đối chứng: dữ liệu đúng như stack
    s1, s2, folds = load_world_runs(w)
    rows = offline.classify("hybrid", s1, s2, folds)  # không ném StopError
    fixed = [r for r in rows if r.kind == "fixed"]
    assert fixed and all(r.kb_gap is None for r in fixed)
    assert run_cli(w)[0] == 0


def test_kb_gap_llm_only_and_guarded_take_the_s2_row_of_the_same_case(w: World) -> None:
    """(a) Chỉ-LLM và Hybrid-guarded lấy `kb_gap` từ dòng S2 của CHÍNH ca đó, không từ S1: S01 (LLM ở cả hai lượt) S1 nói true, S2 nói false;
    S00 (luật CHO PHÉP ở S1 → `kb_gap` null ở S1) S2 nói true."""
    w.row("hybrid", 1)["kb_gap"] = True
    w.row("llm_only", 1)["kb_gap"] = False
    w.row("llm_only", 0)["kb_gap"] = True
    s1, s2, folds = load_world_runs(w)
    by = {arm: {r.base.scenario_id: r for r in offline.classify(arm, s1, s2, folds)} for arm in offline.ARMS}
    assert by["hybrid"][sid(1)].kb_gap is True  # Hybrid: dòng S1
    assert by["llm_only"][sid(1)].kb_gap is False and by["llm_only"][sid(0)].kb_gap is True
    assert by["hybrid_guarded"][sid(1)].kb_gap is False and by["hybrid_guarded"][sid(0)].kb_gap is True


def test_kb_gap_written_to_output_comes_from_s2_for_guarded_and_llm_only(w: World) -> None:
    w.row("hybrid", 1)["kb_gap"] = True
    w.row("llm_only", 1)["kb_gap"] = False
    w.row("llm_only", 0)["kb_gap"] = True
    code, out = run_cli(w)
    assert code == 0
    got = {arm: {r.scenario_id: r for r in load_predictions(out / arm / "predictions.jsonl")} for arm in offline.ARMS}
    assert got["hybrid"][sid(1)].kb_gap is True
    assert got["llm_only"][sid(1)].kb_gap is False and got["llm_only"][sid(0)].kb_gap is True
    assert got["hybrid_guarded"][sid(1)].kb_gap is False and got["hybrid_guarded"][sid(0)].kb_gap is True
    assert got["hybrid"][sid(0)].kb_gap is None  # ca luật ở Hybrid: không có kb_gap


@pytest.mark.parametrize(("strategy", "i"), [("hybrid", 1), ("llm_only", 1), ("llm_only", 0)])
def test_kb_gap_null_on_llm_case_stops_even_when_the_other_run_has_a_value(
    w: World, capsys: pytest.CaptureFixture[str], strategy: str, i: int
) -> None:
    """(b) Ca đi lớp LLM mà `kb_gap` null → DỪNG (exit 2), không đoán, không rơi về lượt kia: dòng của lượt kia vẫn có giá trị."""
    w.row(strategy, i)["kb_gap"] = None
    other = "llm_only" if strategy == "hybrid" else "hybrid"
    assert i == 0 or w.row(other, i)["kb_gap"] is not None  # S01: lượt kia có giá trị thật
    code, out = run_cli(w)
    assert code == 2 and not out.exists()
    assert "harness phải điền kb_gap" in capsys.readouterr().err


@pytest.mark.parametrize("i", [0, 1])
def test_kb_gap_null_on_s2_row_stops_hybrid_guarded_even_if_s1_has_it(w: World, i: int) -> None:
    """(b) Riêng Hybrid-guarded: dòng S2 của ca (S00: luật cho phép; S01: LLM ở S1) null → dừng dù S1 có giá trị."""
    w.row("hybrid", 1)["kb_gap"] = True  # S1 có giá trị ở S01
    w.row("llm_only", i)["kb_gap"] = None
    s1, s2, folds = load_world_runs(w)
    with pytest.raises(StopError, match="kb_gap"):
        offline.classify("hybrid_guarded", s1, s2, folds)


def test_calibrated_output_never_auto_on_kb_gap_cases(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    for arm in ("hybrid", "llm_only", "hybrid_guarded"):
        for r in load_predictions(out / arm / "predictions.jsonl"):
            if r.decided_by == "llm" and r.kb_gap:
                assert r.route != "AUTO", (arm, r.scenario_id)


# ---- Q2: fold ----------------------------------------------------------------------------------------------------------------


def test_fold_csv_must_cover_every_family_and_match_predictions(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    w.folds = w.folds[:-1]  # bỏ F10
    assert run_cli(w)[0] == 2 and "họ không có phần" in capsys.readouterr().err


def test_fold_in_predictions_must_equal_csv(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    for s in ("hybrid", "llm_only"):
        for r in w.rec[s]:
            r["fold"] = (int(r["family"][1:]) - 1) % 5 + 1  # khớp CSV
    assert run_cli(w)[0] == 0
    for s in ("hybrid", "llm_only"):
        for r in w.rec[s]:
            r["fold"] = (int(r["family"][1:])) % 5 + 1  # nhất quán trong file nhưng lệch CSV một phần
    assert run_cli(w, "out2")[0] == 2 and "fold trong predictions khác CSV" in capsys.readouterr().err


def test_fold_csv_rejects_family_in_two_folds_and_bad_fold(w: World) -> None:
    w.folds = [*w.folds, ("F01", 2)]
    assert run_cli(w)[0] == 2
    w.folds = [("F01", 9)]
    assert run_cli(w, "out2")[0] == 2


# ---- Q4: ca không tới điểm log 4 ---------------------------------------------------------------------------------------------


def test_q4_no_log4_goes_to_l2_e1_and_unlabeled_stay_out_of_sample(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    for arm in ("hybrid", "llm_only", "hybrid_guarded"):
        by = {r.scenario_id: r for r in load_predictions(out / arm / "predictions.jsonl")}
        assert by[sid(62)].route == "ESCALATE_L2" and by[sid(62)].decided_by is None  # E2 hết hạn lượt tại B12/B14 → L2
        assert by[sid(61)].route is None  # E1: ngoài mẫu số
        assert by[sid(64)].route is None  # E9 tại B3 (M5 chưa chạy): ngoài mẫu số, KHÔNG bị L2 hoá
        assert by[sid(65)].route is None  # final_state null do kẹt B11: ngoài mẫu số
        assert by[sid(60)].route is None and by[sid(60)].expected_route is None  # chưa nhãn
        assert all(r.fold is not None for r in by.values())
    hy = {r.scenario_id: r for r in load_predictions(out / "hybrid" / "predictions.jsonl")}
    assert hy[sid(63)].route == "AUTO" and hy[sid(63)].decided_by == "rule"  # Hybrid: luật cho phép giữ nguyên
    gu = {r.scenario_id: r for r in load_predictions(out / "hybrid_guarded" / "predictions.jsonl")}
    assert gu[sid(63)].route == "ESCALATE_L2" and gu[sid(63)].decided_by is None and gu[sid(63)].raw_prob is None
    lo = {r.scenario_id: r for r in load_predictions(out / "llm_only" / "predictions.jsonl")}
    assert lo[sid(63)].route == "ESCALATE_L2"


def rec_of(i: int, strategy: str = "hybrid", **over: Any) -> PredictionRecord:
    return PredictionRecord.model_validate_json(json.dumps({**record("a" * 12, strategy, i), **over}))


@pytest.mark.parametrize(
    ("scenario", "over", "expected"),
    [
        (62, {}, "no_log4"),  # E2 hết hạn lượt tại B12/B14, m5_aborted true
        (64, {}, "out"),  # E9 tại B3: lỗi KHÔNG ở M5 → ngoài mẫu số dù exit_code = E9
        (65, {}, "out"),  # final_state null do kẹt B11 → ngoài mẫu số
        (61, {}, "out"),  # E1
        (61, {"final_state": None}, "out"),  # E1 + final_state null vẫn ngoài mẫu
        (64, {"exit_code": "E2", "final_state": None}, "out"),  # mã E2/final_state null KHÔNG quyết định — chỉ m5_aborted
        (65, {"m5_aborted": True}, "no_log4"),  # đảo cờ → đảo kết quả: cờ là điều kiện duy nhất
    ],
)
def test_q4_no_route_follows_m5_aborted_only(scenario: int, over: dict[str, Any], expected: str) -> None:
    assert offline._no_log4(rec_of(scenario, **over)) == expected


def test_q4_null_m5_aborted_on_labeled_no_route_case_stops() -> None:
    with pytest.raises(StopError, match="m5_aborted"):
        offline._no_log4(rec_of(64, m5_aborted=None))


def test_q4_null_m5_aborted_stops_the_cli_with_exit_2(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    w.row("hybrid", 64)["m5_aborted"] = None
    code, out = run_cli(w)
    assert code == 2 and not out.exists()
    assert "m5_aborted" in capsys.readouterr().err


# ---- điểm 7 + Q7/Q8: policy, chưa hiệu chỉnh, started_at -----------------------------------------------------------------------


def test_policy_sha_mismatch_or_missing_stops(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    w.manifest["hybrid"]["policy_sha256"] = "0" * 64
    assert run_cli(w)[0] == 2 and "policy_sha256" in capsys.readouterr().err
    w.manifest["hybrid"]["policy_sha256"] = None
    assert run_cli(w, "out2")[0] == 2 and "thiếu policy_sha256" in capsys.readouterr().err


def test_policy_threshold_is_read_from_the_policy_file(w: World) -> None:
    s1, s2, _ = load_world_runs(w)
    sha = hashlib.sha256(w.policy).hexdigest()
    got, got_sha = offline.read_policy_t_high(w.tmp / "policy.json", (s1, s2))
    assert got_sha == sha and got == parse_policy(w.policy).constants.THRESHOLD_HIGH
    w.policy = policy_bytes(0.97)
    for s in ("hybrid", "llm_only"):
        w.manifest[s]["policy_sha256"] = hashlib.sha256(w.policy).hexdigest()
    s1b, s2b, _ = load_world_runs(w)
    assert offline.read_policy_t_high(w.tmp / "policy.json", (s1b, s2b))[0] == 0.97


def test_started_at_missing_stops(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    del w.manifest["hybrid"]["started_at"]
    assert run_cli(w)[0] == 2 and "started_at" in capsys.readouterr().err


def uncalibrated_rows(w: World, arm: str = "hybrid") -> list[ArmRow]:
    s1, s2, folds = load_world_runs(w)
    rows = offline.classify(arm, s1, s2, folds)
    # chỉ giữ 3 ca đi lớp LLM mỗi phần → mọi phần huấn luyện < 10 mẫu → cả ba biến thể fit lỗi
    keep: list[ArmRow] = []
    seen: dict[int, int] = {}
    for r in rows:
        if r.kind == "llm":
            seen[r.fold] = seen.get(r.fold, 0) + 1
            if seen[r.fold] > 1:
                continue
        keep.append(r)
    return keep


def test_p7_uncalibrated_folds_route_by_policy_threshold_never_auto(w: World) -> None:
    rows = uncalibrated_rows(w)
    now = offline.started_at(load_world_runs(w)[0])
    res = offline.compute_arm("hybrid", rows, now=now, policy_t_high=0.3)
    assert res.counts["folds_uncalibrated"] == 5 and res.selection == {"uncalibrated": 5}
    for r in res.records:
        if r.decided_by == "llm":
            assert r.calibrated_prob is None and r.route in ("HITL", "ESCALATE_L2") and r.route != "AUTO"
            assert r.route == ("ESCALATE_L2" if r.raw_prob is not None and r.raw_prob > 0.3 else "HITL")
    other = offline.compute_arm("hybrid", rows, now=now, policy_t_high=0.95)
    routes = {r.scenario_id: r.route for r in res.records}
    assert routes != {r.scenario_id: r.route for r in other.records}  # đổi ngưỡng policy → đổi route


def test_p7_uncalibrated_fold_uses_with_evidence_probability(w: World) -> None:
    rows = uncalibrated_rows(w)
    now = offline.started_at(load_world_runs(w)[0])
    res = offline.compute_arm("hybrid", rows, now=now, policy_t_high=0.5)
    for r in res.records:
        if r.decided_by == "llm":
            assert r.raw_prob == p_of(int(r.scenario_id[1:]))


# ---- Q5: biến thể được chọn thiếu p ở ca đo ---------------------------------------------------------------------------------


def test_q5_chosen_variant_missing_on_test_case_goes_to_l2_and_is_counted(w: World) -> None:
    s1, s2, folds = load_world_runs(w)
    rows = offline.classify("hybrid", s1, s2, folds)
    row = next(r for r in rows if r.kind == "llm")
    gappy = dataclasses.replace(row, probs={"with_evidence": row.probs["with_evidence"]})
    fit = dataclasses.replace(offline_fit(rows, row.fold, s1), variant="max")
    counts: Counter[str] = Counter()
    up = offline._update(gappy, fit, 0.5, counts)
    assert up["route"] == "ESCALATE_L2" and up["raw_prob"] is None and counts["missing_p_to_l2"] == 1


def offline_fit(rows: list[ArmRow], fold: int, s1: offline.Run) -> Any:
    from app.eval.calibrate import fit_fold

    train = [r.case("calibration") for r in rows if r.kind != "out" and r.fold != fold]
    return fit_fold(train, now=offline.started_at(s1), policy_t_high=0.5)


# ---- LeakageError / G4: calibrator riêng từng phương án × phần, không nhìn phần đo -----------------------------------------------


def fold_versions(rows: list[ArmRow], now: Any) -> dict[int, str | None]:
    res = offline.compute_arm("hybrid", rows, now=now, policy_t_high=0.6)
    return {i: (f.calibrator.params.version if f is not None and f.calibrator is not None else None) for i, f in res.fits.items()}


def test_g4_calibrator_ignores_the_test_fold_labels_but_follows_train_labels(w: World) -> None:
    s1, s2, folds = load_world_runs(w)
    rows = offline.classify("hybrid", s1, s2, folds)
    now = offline.started_at(s1)
    base = fold_versions(rows, now)

    def flip(r: ArmRow) -> ArmRow:
        g = "AUTO" if r.base.expected_route != "AUTO" else "HITL"
        return dataclasses.replace(r, base=r.base.model_copy(update={"expected_route": g}))

    flipped_fold1 = [flip(r) if r.fold == 1 and r.kind != "out" else r for r in rows]
    after = fold_versions(flipped_fold1, now)
    assert after[1] == base[1]  # phần đo 1: calibrator fit trên phần 2–5, nhãn phần 1 không vào
    assert all(after[k] != base[k] for k in (2, 3, 4, 5))  # các phần khác dùng phần 1 làm huấn luyện
    assert len({v for v in base.values() if v}) == 5  # mỗi phần một calibrator riêng


def test_g4_each_arm_has_its_own_calibrators_saved_and_loadable(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    versions: dict[str, set[str]] = {}
    for arm in ("hybrid", "llm_only", "hybrid_guarded"):
        files = sorted((out / arm / "calibrators").glob("*.json"))
        assert len(files) >= 1
        versions[arm] = {f.stem for f in files}
        for f in files:
            assert load_calibrator(f.stem, f.parent).params.fitted_on.split == "calibration"
    assert versions["hybrid"].isdisjoint(versions["llm_only"]) and versions["llm_only"].isdisjoint(versions["hybrid_guarded"])


# ---- đầu ra: khớp report.py (G5), manifest, xác định -----------------------------------------------------------------------------


def test_outputs_load_in_report_and_build_report(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    arms = [load_arm(out / a / "predictions.jsonl", out / a / "manifest.json") for a in ("hybrid", "llm_only", "hybrid_guarded")]
    assert [a.name for a in arms] == ["hybrid", "llm_only", "hybrid_guarded"]
    check_arms(arms)
    report = build_report(arms, None, n_boot=20)
    assert report.tables


def test_manifest_of_derived_arms(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    m = {a: json.loads((out / a / "manifest.json").read_text(encoding="utf-8")) for a in ("hybrid", "llm_only", "hybrid_guarded")}
    assert m["hybrid"]["run_id"] == "a" * 12 and m["llm_only"]["run_id"] == "b" * 12
    g = m["hybrid_guarded"]
    assert g["strategy"] == "hybrid_guarded" and g["run_id"] not in ("a" * 12, "b" * 12) and len(g["run_id"]) == 12
    assert g["derived_from"]["hybrid_run_id"] == "a" * 12 and g["derived_from"]["llm_only_run_id"] == "b" * 12
    assert "fold" not in g["predictions_unavailable"]
    off = g["offline"]
    assert off["version"] == offline.OFFLINE_VERSION and off["policy_sha256"] == hashlib.sha256(w.policy).hexdigest()
    assert off["cost_matrix"].startswith("DEFAULT_COST") and off["limits"] and set(off["selection"]) <= {"with_evidence", "no_evidence", "max", "uncalibrated"}
    recs = load_predictions(out / "hybrid_guarded" / "predictions.jsonl")
    assert {r.run_id for r in recs} == {g["run_id"]} and {r.strategy for r in recs} == {"hybrid_guarded"}


def test_guarded_rule_allow_cases_become_llm_decided_with_s2_p_method(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    gu = {r.scenario_id: r for r in load_predictions(out / "hybrid_guarded" / "predictions.jsonl")}
    assert gu[sid(0)].decided_by == "llm" and gu[sid(0)].p_method == "self_report" and gu[sid(0)].raw_prob is not None
    assert gu[sid(5)].decided_by == "rule" and gu[sid(5)].route == "HITL"  # luật cần duyệt giữ nguyên
    assert gu[sid(10)].decided_by == "rule" and gu[sid(10)].route == "ESCALATE_L2"


def test_llm_rows_carry_calibrated_prob_and_chosen_variant_probability(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    for r in load_predictions(out / "hybrid" / "predictions.jsonl"):
        if r.decided_by == "llm":
            i = int(r.scenario_id[1:])
            assert r.raw_prob in (p_of(i), no_ev(p_of(i)), max(p_of(i), no_ev(p_of(i))))
            assert r.calibrated_prob is not None and 0.0 <= r.calibrated_prob <= 1.0


def test_fold_files_have_selection_thresholds_sensitivity_and_dropped_variants(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    for arm in ("hybrid", "llm_only", "hybrid_guarded"):
        for i in range(1, 6):
            rep = json.loads((out / arm / "folds" / f"{i}.json").read_text(encoding="utf-8"))
            assert rep["fold"] == i and rep["arm"] == arm and rep["mode"] in ("calibrated", "uncalibrated")
            assert {"thresholds", "t_low_star", "sensitivity", "trials", "log", "upper_disabled"} <= set(rep)
            assert rep["t_low_star"] == pytest.approx(0.1, abs=1e-12)
            if rep["mode"] == "calibrated":
                assert set(rep["sensitivity"]) == {"5", "10", "20"} and rep["calibrator_version"]


def test_two_runs_produce_identical_bytes(w: World) -> None:
    assert run_cli(w, "run1")[0] == 0
    assert run_cli(w, "run2")[0] == 0
    a, b = w.tmp / "run1", w.tmp / "run2"
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files and files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    for f in files:
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_out_directory_must_be_new(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    (w.tmp / "out").mkdir()
    assert run_cli(w)[0] == 2 and "--out đã tồn tại" in capsys.readouterr().err


def test_runs_must_be_consistent(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    w.manifest["llm_only"]["dataset_sha256"] = "d" * 64
    assert run_cli(w)[0] == 2 and "dataset_sha256" in capsys.readouterr().err
    w.manifest["llm_only"]["dataset_sha256"] = SHA
    w.manifest["hybrid"]["enable_proactive_diagnosis"] = False
    assert run_cli(w, "out2")[0] == 2


def test_probs_loader_rejects_bad_lines(tmp_path: Path) -> None:
    good = {"scenario_id": "s", "variant": "max", "raw_prob": 0.5}
    cases: list[tuple[str, Callable[[Dict], Dict]]] = [
        ("extra", lambda d: {**d, "kb_gap": False}), ("variant", lambda d: {**d, "variant": "self_report"}),
        ("range", lambda d: {**d, "raw_prob": 1.5}), ("bool", lambda d: {**d, "raw_prob": True}),
    ]  # fmt: skip
    for name, mutate in cases:
        p = tmp_path / f"{name}.jsonl"
        p.write_text(json.dumps(mutate(good)) + "\n", encoding="utf-8")
        with pytest.raises(StopError):
            offline.load_probs(p)
    dup = tmp_path / "dup.jsonl"
    dup.write_text((json.dumps(good) + "\n") * 2, encoding="utf-8")
    with pytest.raises(StopError):
        offline.load_probs(dup)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(StopError):
        offline.load_probs(empty)


def test_records_are_validated_through_prediction_record(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0
    recs = load_predictions(out / "hybrid" / "predictions.jsonl")  # v1.1 thật, từ chối trường lạ/sai kiểu
    assert all(isinstance(r, PredictionRecord) for r in recs) and len(recs) == SPECIAL
    assert [r.scenario_id for r in recs] == [sid(i) for i in range(SPECIAL)]  # giữ thứ tự dòng nguồn


# ---- S3: Hybrid tắt chẩn đoán → hybrid_no_diag ----------------------------------------------------------------------------------


def test_s3_absent_means_no_hybrid_no_diag_directory(w: World) -> None:
    code, out = run_cli(w)
    assert code == 0 and not (out / offline.NO_DIAG_ARM).exists()


def test_s3_writes_hybrid_no_diag_loadable_as_the_no_tool_arm(w: World) -> None:
    w.enable_s3()
    code, out = run_cli(w)
    assert code == 0
    arms = [load_arm(out / a / "predictions.jsonl", out / a / "manifest.json") for a in ("hybrid", "llm_only", "hybrid_no_diag")]
    assert [a.name for a in arms] == ["hybrid", "llm_only", "hybrid_no_tool"]  # manifest tắt chẩn đoán → ablation bỏ tool
    check_arms(arms)
    assert build_report(arms, None, n_boot=20).tables
    m = json.loads((out / "hybrid_no_diag" / "manifest.json").read_text(encoding="utf-8"))
    assert m["run_id"] == "c" * 12 and m["enable_proactive_diagnosis"] is False and m["strategy"] == "hybrid"
    assert m["offline"]["probs_sha256"]["s3"] and "fold" not in m["predictions_unavailable"]


def test_s3_is_computed_from_s3_own_data_with_its_own_calibrators(w: World) -> None:
    w.enable_s3()
    code, out = run_cli(w)
    assert code == 0
    s1 = {r.scenario_id: r for r in load_predictions(out / "hybrid" / "predictions.jsonl")}
    s3 = {r.scenario_id: r for r in load_predictions(out / "hybrid_no_diag" / "predictions.jsonl")}
    assert {r.run_id for r in s3.values()} == {"c" * 12} and s3[sid(1)].clarification_turns == 2  # dòng nguồn là S3, không phải S1
    assert s1[sid(1)].clarification_turns == 0
    for r in s3.values():
        if r.decided_by == "llm":
            i = int(r.scenario_id[1:])
            p3 = round(min(0.98, p_of(i) + 0.04), 4)
            assert r.raw_prob in (p3, no_ev(p3), max(p3, no_ev(p3)))  # p của S3 (không phải của S1)
    v1 = {f.stem for f in (out / "hybrid" / "calibrators").glob("*.json")}
    v3 = {f.stem for f in (out / "hybrid_no_diag" / "calibrators").glob("*.json")}
    assert v3 and v1.isdisjoint(v3)  # calibrator fit trên phần huấn luyện của CHÍNH S3
    for f in (out / "hybrid_no_diag" / "calibrators").glob("*.json"):
        assert load_calibrator(f.stem, f.parent).params.fitted_on.split == "calibration"


def test_s3_same_data_as_s1_gives_the_same_calibrators(w: World) -> None:
    """Đối chứng cho test trên: S3 trùng p với S1 → cùng calibrator (khác nhau ở test trên là do dữ liệu S3, không do tên thư mục)."""
    w.enable_s3()
    w.probs["s3"] = prob_lines("hybrid")
    for i in range(SPECIAL):
        row = w.row("s3", i)
        if row["decided_by"] == "llm":
            row["raw_prob"] = p_of(i)
    code, out = run_cli(w)
    assert code == 0
    v1 = {f.stem for f in (out / "hybrid" / "calibrators").glob("*.json")}
    v3 = {f.stem for f in (out / "hybrid_no_diag" / "calibrators").glob("*.json")}
    assert v1 == v3


def test_s3_must_have_diagnosis_off_and_match_dataset_and_policy(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    w.enable_s3()
    w.manifest["s3"]["enable_proactive_diagnosis"] = True
    assert run_cli(w)[0] == 2 and "tắt chẩn đoán" in capsys.readouterr().err
    w.manifest["s3"]["enable_proactive_diagnosis"] = False
    w.manifest["s3"]["dataset_sha256"] = "d" * 64
    assert run_cli(w, "out2")[0] == 2 and "dataset_sha256" in capsys.readouterr().err
    w.manifest["s3"]["dataset_sha256"] = SHA
    w.manifest["s3"]["policy_sha256"] = "0" * 64
    assert run_cli(w, "out3")[0] == 2 and "policy_sha256" in capsys.readouterr().err


def test_s3_kb_gap_null_stops_like_the_other_arms(w: World, capsys: pytest.CaptureFixture[str]) -> None:
    w.enable_s3()
    w.row("s3", 1)["kb_gap"] = None
    assert run_cli(w)[0] == 2 and "harness phải điền kb_gap" in capsys.readouterr().err


def test_module_scope_static() -> None:
    src = (REPO / "backend/app/eval/offline.py").read_text(encoding="utf-8")
    code = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
    assert not re.search(r"\.env['\"]", code) and not re.search(r"\b(httpx|requests|urllib|socket)\b", code)
    assert "THRESHOLD_HIGH" in code  # đọc từ file policy
