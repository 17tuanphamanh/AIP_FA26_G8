"""D-70 — `scripts/eval/b2_offline.py`: tính lại E1 `injection_suspected` ở τ' < τ_run từ audit B2 của lượt đã chạy.

Dữ liệu giả (kịch bản tổng hợp `fake_stack.real_scenario`, thư mục lượt giả, `sql` giả trả dòng `tickets` / audit B2); không stack, không
PG, không LLM. Phán quyết đối chiếu `app.guard.b2_review.after_judge` (biên p = τ → E1; `too_many_windows` → E1; LLM nói tấn công hoặc
`category ≠ none` → E0). Câu người dùng giả mang chuỗi canh `SENTINEL_TXT` — không được xuất hiện ở file kết quả hay log.
"""

import csv
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.eval import offline
from app.eval.dataset import load_scenarios
from tests.unit.eval.contract_v11 import V11
from tests.unit.eval.eval_scripts import load_script
from tests.unit.eval.fake_stack import SEED_USERS, real_scenario, write_seed

bo = load_script("b2_offline")

TAU_RUN = "0.9999"
RUN_ID = "3f1f1724a798"
TEXT = "SENTINEL_TXT"
_IN = re.compile(r"IN \(([^)]*)\)")


def scr(p: float | None, *, attack: bool = False, category: str = "none", ml_error: str | None = None) -> dict[str, Any]:
    """`detail.screening` của nhánh đã qua L4 (`b02_screen.py:95-98`)."""
    return {"layer_decided": "llm", "p_mal": p, "clf_mode": "review", "ml_error": ml_error, "masks_replaced": 0,
            "llm_is_attack": attack, "llm_category": category, "llm_role": "fast", "llm_model": "SENTINEL_MODEL"}  # fmt: skip


def b2(tid: str, event: str, screening: Mapping[str, Any] | None, log_id: int = 1) -> dict[str, Any]:
    return {"ticket_id": tid, "log_id": log_id, "event": event, "screening": screening}


def tk(tid: str, exit_code: str | None = None, final_state: str | None = "resolved", parent: str | None = None) -> dict[str, Any]:
    return {"ticket_id": tid, "parent_ticket_id": parent, "exit_code": exit_code, "final_state": final_state}


def pred(tid: str, sid: str, family: str, *, route: str | None, decided_by: str | None = None, raw_prob: float | None = None,
         expected: str | None = "HITL", m5_aborted: bool | None = False) -> dict[str, Any]:
    """Một dòng `predictions.jsonl` đủ hợp đồng v1.1 (khuôn `test_offline.record`)."""
    llm = decided_by == "llm"
    return {
        "run_id": RUN_ID, "strategy": "hybrid", "split": "test", "scenario_id": sid, "family": family, "ticket_id": tid,
        "parent_ticket_id": None, "expected_route": expected, "route": route, "decided_by": decided_by, "raw_prob": raw_prob,
        "calibrated_prob": None, "p_method": "self_report" if llm else None,
        "final_state": "S_RESOLVED" if route else "S_ESCALATED", "exit_code": None, "close_reason": None,
        "resolution_path": None, "has_approval": False, "clarification_turns": 0, "intent": "vpn", "gold_intent": "vpn",
        "doc_ids": None, "gold_doc_ids": [], **V11, "kb_gap": False if llm else None, "m5_aborted": m5_aborted,
    }  # fmt: skip


def full_manifest() -> dict[str, Any]:
    """Khoá `report.load_manifest` / `offline.load_run` cần (ngoài các khoá script này đọc)."""
    return {"git_commit": "f" * 40, "git_dirty": False, "strategy": "hybrid", "split": "test", "schema_version": "1.1",
            "enable_proactive_diagnosis": True, "predictions_unavailable": ["fold"], "started_at": "2026-10-30T03:00:00+00:00"}  # fmt: skip


class FakeDb:
    """`sql` giả: lọc theo các danh sách `IN (…)` của câu hỏi. Dòng `tickets` có thêm `redacted_request` (canh) — script không được
    chép nó ra đâu cả."""

    def __init__(self, tickets: Sequence[Mapping[str, Any]], b2_rows: Sequence[Mapping[str, Any]]) -> None:
        self.tickets, self.b2_rows = list(tickets), list(b2_rows)
        self.queries: list[str] = []

    def __call__(self, query: str) -> Any:
        self.queries.append(query)
        ids = {x.strip().strip("'") for m in _IN.findall(query) for x in m.split(",")}
        if "FROM audit_logs" in query:
            assert "step = 'B2'" in query
            return [r for r in self.b2_rows if r["ticket_id"] in ids]
        by_parent = "parent_ticket_id IN" in query
        return [{**t, "redacted_request": f"{TEXT}_db"} for t in self.tickets
                if t["ticket_id"] in ids or (by_parent and t["parent_ticket_id"] in ids)]  # fmt: skip


class World:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.scen = tmp / "scen"
        self.scen.mkdir()
        self.seed = write_seed(tmp / "seed.json")
        self.out = tmp / ".verify" / "b2off"
        self.runs: list[Path] = []

    def scenario(self, sid: str, *intents: str) -> None:
        data = real_scenario(sid, intents=intents or ("vpn",), turns=[f"{TEXT}_cau dau {sid}"])
        (self.scen / f"{sid}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    def sha(self) -> str:
        return load_scenarios(self.scen, users=SEED_USERS).sha256

    def run_dir(self, name: str, rows: Sequence[tuple[str, str | None, str, str]], *, run_id: str = RUN_ID,
                clf_mode: str = "review", sha: str | None = None, preds: Sequence[Mapping[str, Any]] = (),
                pred_lines: Sequence[str] | None = None, manifest_extra: Mapping[str, Any] | None = None) -> Path:  # fmt: skip
        """Thư mục lượt `name` (nhãn lượt). `rows`: (scenario_id, ticket_id, hours_class, outcome). Mặc định MỌI lượt cùng run_id
        (run_id sinh từ cấu hình — không duy nhất). `preds`: dòng `predictions.jsonl`; `pred_lines`: dòng ĐÃ dựng sẵn (giữ byte)."""
        d = self.tmp / name
        d.mkdir()
        manifest = {"run_id": run_id, "clf_mode": clf_mode, "dataset_sha256": sha or self.sha(),
                    "ignored_fields": {"allowed": False, "count": 0, "paths": []}, **(manifest_extra or {})}  # fmt: skip
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (d / "outcomes.jsonl").write_text("".join(json.dumps({
            "scenario_id": sid, "ticket_id": tid, "outcome": outcome, "hours_class": hours,
        }) + "\n" for sid, tid, hours, outcome in rows), encoding="utf-8")  # fmt: skip
        lines = pred_lines if pred_lines is not None else [json.dumps(p) + "\n" for p in preds]
        (d / "predictions.jsonl").write_text("".join(lines), encoding="utf-8")
        self.runs.append(d)
        return d

    def main(self, db: FakeDb, *extra: str, tau_run: str = TAU_RUN) -> tuple[int, list[str]]:
        argv = [x for d in self.runs for x in ("--run", str(d))]
        argv += ["--scenarios", str(self.scen), "--seed", str(self.seed), "--tau-run", tau_run, "--out", str(self.out), *extra]
        log: list[str] = []
        return bo.main(argv, sql=db, echo=log.append), log

    def csv(self, tau: str) -> dict[str, dict[str, str]]:
        with (self.out / f"ca-{tau}.csv").open(encoding="utf-8", newline="") as f:
            return {r["ticket_id"]: r for r in csv.DictReader(f)}

    def ids(self, tau: str) -> list[str]:
        return (self.out / f"e1-moi-{tau}.txt").read_text(encoding="utf-8").splitlines()

    def summary(self) -> dict[str, Any]:
        return dict(json.loads((self.out / "tom-tat.json").read_text(encoding="utf-8")))


@pytest.fixture
def w(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setattr(bo, "VERIFY_DIR", tmp_path / ".verify")
    return World(tmp_path)


def _one_each(w: World, n: int) -> None:
    for i in range(1, n + 1):
        w.scenario(f"S{i}")


# ---- biên, giữ nguyên ------------------------------------------------------------------------------------------------


def test_bien_p_bang_tau_thanh_e1_o_cau_dau(w: World) -> None:
    _one_each(w, 2)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done")])
    db = FakeDb([tk("T1"), tk("T2")], [b2("T1", "screened", scr(0.5)), b2("T2", "screened", scr(0.4999))])
    code, log = w.main(db, "--tau", "0.5")
    assert code == 0, log
    rows = w.csv("0.5")
    assert (rows["T1"]["ket_qua_tau"], rows["T1"]["luot_b2_vuot"], rows["T1"]["e1_moi"]) == ("E1", "0", "1")
    assert rows["T1"]["ket_qua_goc"] == "resolved"
    assert (rows["T2"]["ket_qua_tau"], rows["T2"]["luot_b2_vuot"], rows["T2"]["e1_moi"]) == ("resolved", "", "0")
    assert w.ids("0.5") == ["T1"]


@pytest.mark.parametrize(
    ("ticket", "row", "e1_goc"),
    [
        (tk("T1"), b2("T1", "screened", scr(None, ml_error="model_missing")), False),  # ml_error khác → qua như gốc
        (tk("T1", "E1", "escalated"), b2("T1", "injection_suspected", scr(None, ml_error="too_many_windows")), True),
        (tk("T1", "E0", "blocked"), b2("T1", "injection_detected", scr(0.99, attack=True)), False),  # LLM nói tấn công
        (tk("T1", "E0", "blocked"), b2("T1", "injection_detected", scr(0.99, category="other")), False),  # category ≠ none
        (tk("T1", "E0", "blocked"), b2("T1", "injection_detected", {"layer_decided": "regex", "pattern_id": "x"}), False),
        (tk("T1", "E2", "escalated"), b2("T1", "guard_unavailable", None), False),
        (tk("T1", "E2", "escalated"), b2("T1", "turn_budget_exceeded", None), False),
        (tk("T1", "E9", "escalated"), None, False),  # không có dòng B2
    ],
    ids=["ml_error", "too_many_windows", "llm_tan_cong", "category", "regex", "e2", "turn_budget", "khong_b2"],
)
def test_giu_nguyen_ket_qua_goc(w: World, ticket: dict[str, Any], row: dict[str, Any] | None, e1_goc: bool) -> None:
    _one_each(w, 2)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done")])  # T2: mốc p cho kiểm biên τ_run
    code, log = w.main(FakeDb([ticket, tk("T2")], [*([row] if row else []), b2("T2", "screened", scr(0.1))]), "--tau", "0.5")
    assert code == 0, log
    r = w.csv("0.5")["T1"]
    assert r["ket_qua_tau"] == r["ket_qua_goc"] == (ticket["exit_code"] or ticket["final_state"])
    assert r["e1_moi"] == "0"
    assert r["luot_b2_vuot"] == ("0" if e1_goc else "")
    assert w.ids("0.5") == []
    cong = w.summary()["theo_tau"]["0.5"]["cong"]
    assert (cong["ca_e1"], cong["ca_e1_moi"], cong["ca_khong_b2"]) == (int(e1_goc), 0, int(row is None))


# ---- τ ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("tau_run", "tau", "want"), [("0.999", "0.9999", "> τ_run"), (TAU_RUN, "0.4", "ngoài"),
                                                       ("1.0", "0.5", "τ_run")])  # fmt: skip
def test_tau_sai_loi_ro_khong_ghi_file(w: World, tau_run: str, tau: str, want: str) -> None:
    w.runs.append(w.tmp / "khong_co")  # τ kiểm TRƯỚC khi đọc lượt
    code, log = w.main(FakeDb([], []), "--tau", tau, tau_run=tau_run)
    assert code == 2
    assert log[-1].startswith("DỪNG: ") and want in log[-1]
    assert not w.out.exists()


# ---- kiểm tái lập ----------------------------------------------------------------------------------------------------


def test_tai_lap_khop_tau_run_ra_dung_tap_e1_goc(w: World) -> None:
    _one_each(w, 3)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done"), ("S3", "T3", "trong", "done")])
    db = FakeDb([tk("T1", "E1", "escalated"), tk("T2"), tk("T3", "E0", "blocked")], [
        b2("T1", "injection_suspected", scr(0.9999)),  # biên p = τ_run → E1
        b2("T2", "screened", scr(0.99989)),
        b2("T3", "injection_detected", scr(0.2, attack=True)),
    ])  # fmt: skip
    code, log = w.main(db, "--tau", TAU_RUN)
    assert code == 0, log
    assert w.ids(TAU_RUN) == []
    cong = w.summary()["theo_tau"][TAU_RUN]["cong"]
    assert (cong["ca_e1"], cong["ca_e1_moi"]) == (1, 0)


@pytest.mark.parametrize(
    "rows",
    [
        [b2("T1", "screened", scr(0.99995)), b2("T2", "screened", scr(0.1))],  # p ≥ τ_run mà gốc qua
        [b2("T1", "injection_suspected", scr(0.5)), b2("T2", "screened", scr(0.1))],  # gốc E1 mà p < τ_run
        [b2("T1", "injection_suspected", None), b2("T2", "screened", scr(0.1))],  # gốc E1 mà không có phán quyết
    ],
    ids=["qua_ma_vuot", "e1_ma_duoi", "e1_khong_screening"],
)
def test_tai_lap_lech_dung_in_ticket_lech(w: World, rows: list[dict[str, Any]]) -> None:
    _one_each(w, 2)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done")])
    code, log = w.main(FakeDb([tk("T1"), tk("T2")], rows), "--tau", "0.5")
    assert code == 2
    assert "TÁI LẬP" in log[-1] and "T1" in log[-1] and "T2" not in log[-1]
    assert not list(w.out.glob("*"))


def test_bien_tau_run_nam_giua_qua_va_in_hai_so(w: World) -> None:
    _one_each(w, 3)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done"), ("S3", "T3", "trong", "done")])
    db = FakeDb([tk("T1", "E1", "escalated"), tk("T2"), tk("T3", "E1", "escalated")], [
        b2("T1", "injection_suspected", scr(0.99995)), b2("T2", "screened", scr(0.9998)),
        b2("T3", "injection_suspected", scr(None, ml_error="too_many_windows")),  # E1 không có p: đếm, không vào min
    ])  # fmt: skip
    code, log = w.main(db, "--tau", "0.5")
    assert code == 0, log
    line = next(x for x in log if x.startswith("E1 thật"))
    assert "E1 thật 2 ca" in line and "min p_mal E1 thật = 0.99995" in line
    assert "max p_mal LLM nói không mà không E1 = 0.9998" in line


def test_bien_tau_run_mot_phia_khong_co_ca_in_ro(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")])
    code, log = w.main(FakeDb([tk("T1")], [b2("T1", "screened", scr(0.3))]), "--tau", "0.5")
    assert code == 0, log
    line = next(x for x in log if x.startswith("E1 thật"))
    assert "E1 thật 0 ca" in line and "min p_mal E1 thật = không có ca" in line and "= 0.3" in line


def test_bien_tau_run_ca_hai_phia_khong_co_ca_dung(w: World) -> None:
    _one_each(w, 2)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done")])
    db = FakeDb([tk("T1", "E1", "escalated"), tk("T2")], [
        b2("T1", "injection_suspected", scr(None, ml_error="too_many_windows")),
        b2("T2", "screened", scr(None, ml_error="model_missing")),
    ])  # fmt: skip
    code, log = w.main(db, "--tau", "0.5")
    assert code == 2 and "cả hai phía" in log[-1]
    assert not list(w.out.glob("*"))


@pytest.mark.parametrize(
    ("min_e1", "max_pass", "ok"),
    [
        (0.9999, 0.99989, True),  # biên: min_E1 = τ_run vẫn qua (p ≥ τ)
        (None, 0.5, True),
        (0.99995, None, True),
        (0.99989, None, False),  # min_E1 < τ_run
        (None, 0.9999, False),  # max_khong_E1 = τ_run → phải là E1
        (0.99995, 0.99996, False),
        (None, None, False),
    ],
)
def test_check_bounds_doc_lap_after_judge(min_e1: float | None, max_pass: float | None, ok: bool) -> None:
    if ok:
        bo.check_bounds(min_e1, max_pass, 0.9999)
    else:
        with pytest.raises(bo.Stop):
            bo.check_bounds(min_e1, max_pass, 0.9999)


def test_hai_dong_b2_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")])
    db = FakeDb([tk("T1")], [b2("T1", "screened", scr(0.1), 1), b2("T1", "screened", scr(0.1), 2)])
    code, log = w.main(db, "--tau", "0.5")
    assert code == 2
    assert "≥ 2 dòng B2" in log[-1] and "T1" in log[-1]
    assert not list(w.out.glob("*"))


# ---- cha nhiều ý -----------------------------------------------------------------------------------------------------


def test_cha_hai_y_thanh_e1_keo_theo_moi_la(w: World) -> None:
    w.scenario("SP", "account", "vpn")
    w.scenario("SQ", "account", "vpn")
    # P: outcomes có cả dòng cha lẫn dòng lá; Q: chỉ dòng cha (như runner — lá tìm qua parent_ticket_id)
    w.run_dir("R1", [("SP", "P", "trong", "multi_leaf"), ("SP", "P-1", "trong", "done"), ("SP", "P-2", "trong", "done"),
                     ("SQ", "Q", "ngoai", "multi_leaf")])  # fmt: skip
    tickets = [tk("P", None, None), tk("P-1", parent="P"), tk("P-2", "E4", "escalated", parent="P"),
               tk("Q", None, None), tk("Q-1", parent="Q"), tk("Q-2", parent="Q")]  # fmt: skip
    db = FakeDb(tickets, [b2("P", "screened", scr(0.7)), b2("Q", "screened", scr(0.6))])
    code, log = w.main(db, "--tau", "0.5")
    assert code == 0, log
    rows = w.csv("0.5")
    assert {t: (r["ket_qua_tau"], r["e1_moi"], r["intent_the"]) for t, r in rows.items()} == {
        t: ("E1", "1", "account+vpn") for t in ("P", "P-1", "P-2", "Q")
    }
    assert rows["P-2"]["ket_qua_goc"] == "E4"
    assert w.ids("0.5") == ["P", "P-1", "P-2", "Q", "Q-1", "Q-2"]
    cong = w.summary()["theo_tau"]["0.5"]["cong"]
    assert (cong["ca"], cong["the"], cong["ca_e1_moi"], cong["the_e1_moi"]) == (4, 2, 4, 2)
    assert cong["theo_intent"]["account+vpn"]["the_e1_moi"] == 2
    assert (cong["cha_nhieu_y_e1"], cong["la_cua_cha_e1"]) == (2, 4)  # ĐP 31/10: cha đếm một lần dù có dòng lá
    assert any("cha nhiều ý E1 2 (4 lá)" in line for line in log)
    assert all("IN ('P', 'Q')" in q for q in db.queries[1:])  # B2 tra theo cha, không theo lá


# ---- nhiều lượt, tóm tắt ---------------------------------------------------------------------------------------------


def test_nhieu_luot_tom_tat_theo_run_cong_intent_khung_gio(w: World) -> None:
    w.scenario("S1", "account")
    w.scenario("S2", "vpn")
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "ngoai", "done"), ("S2", None, "bien_gio", "skipped_hours")])
    w.run_dir("R2", [("S1", "T3", "ngoai", "done")])
    db = FakeDb([tk("T1"), tk("T2"), tk("T3")],
                [b2("T1", "screened", scr(0.7)), b2("T2", "screened", scr(0.9995)), b2("T3", "screened", scr(0.4))])  # fmt: skip
    code, log = w.main(db)  # mặc định 0,5 / 0,999 / 0,9999
    assert code == 0, log
    s = w.summary()
    assert s["luot"] == {"R1": "3f1f1724a798", "R2": "3f1f1724a798"} and set(s["theo_tau"]) == {"0.5", "0.999", "0.9999"}
    half = s["theo_tau"]["0.5"]
    assert {k: half["theo_luot"]["R1"][k] for k in ("run_id", "ca", "the", "ca_e1_moi", "the_e1_moi")} == {
        "run_id": "3f1f1724a798", "ca": 2, "the": 2, "ca_e1_moi": 2, "the_e1_moi": 2}  # fmt: skip
    assert half["theo_luot"]["R2"]["ca_e1_moi"] == 0
    assert {k: half["cong"][k] for k in ("ca", "the", "ca_e1_moi", "the_e1_moi")} == {
        "ca": 3, "the": 2, "ca_e1_moi": 2, "the_e1_moi": 2}  # fmt: skip
    assert half["cong"]["theo_khung_gio"]["ngoai"]["ca"] == 2 and half["cong"]["theo_khung_gio"]["ngoai"]["ca_e1_moi"] == 1
    assert half["cong"]["theo_intent"]["account"]["ca_e1_moi"] == 1
    assert (half["cong"]["cha_nhieu_y_e1"], half["cong"]["la_cua_cha_e1"]) == (0, 0)  # một intent → 0, vẫn in
    assert sum("cha nhiều ý E1 0 (0 lá)" in line for line in log) == 3
    assert w.ids("0.5") == ["T1", "T2"]
    assert w.ids("0.999") == ["T2"]
    assert w.ids("0.9999") == []


# ---- không câu người dùng, chốt đầu vào ------------------------------------------------------------------------------


def test_khong_co_cau_nguoi_dung_o_dau_ra(w: World) -> None:
    _one_each(w, 2)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "ngoai", "done")])
    db = FakeDb([tk("T1"), tk("T2")], [b2("T1", "screened", scr(0.8)), b2("T2", "screened", scr(0.1))])
    code, log = w.main(db, "--tau", "0.5")
    assert code == 0, log
    with (w.out / "ca-0.5.csv").open(encoding="utf-8", newline="") as f:
        assert tuple(next(csv.reader(f))) == bo.CSV_COLUMNS
    for p in w.out.iterdir():
        assert TEXT not in p.read_text(encoding="utf-8"), p.name
    assert not any(TEXT in line for line in log)
    assert not any("redacted_request" in q for q in db.queries)


def test_clf_mode_khac_review_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")], clf_mode="shadow")
    code, log = w.main(FakeDb([tk("T1")], []), "--tau", "0.5")
    assert code == 2 and "clf_mode" in log[-1]


def test_sha_kich_ban_lech_manifest_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")], sha="0" * 64)
    code, log = w.main(FakeDb([tk("T1")], []), "--tau", "0.5")
    assert code == 2 and "dataset_sha256" in log[-1]


def test_db_hai_luot_cung_run_id_chi_lay_ticket_cua_thu_muc(w: World) -> None:
    _one_each(w, 2)
    w.run_dir("s3-lan2", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done")])
    # T3, T4: lượt khác CÙNG run_id có trong DB nhưng thư mục của nó không được đưa vào
    db = FakeDb([tk("T1"), tk("T2"), tk("T3"), tk("T4")], [
        b2("T1", "screened", scr(0.1)), b2("T2", "screened", scr(0.2)),
        b2("T3", "screened", scr(0.9)), b2("T4", "screened", scr(0.8)),
    ])  # fmt: skip
    code, log = w.main(db, "--tau", "0.5")
    assert code == 0, log
    assert set(w.csv("0.5")) == {"T1", "T2"}
    assert w.ids("0.5") == []
    assert not any("T3" in q or "T4" in q or "run_id" in q for q in db.queries)


def test_hai_thu_muc_cung_run_id_khac_ticket_tach_hai_dong(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("s3-lan2", [("S1", "T1", "trong", "done")])
    w.run_dir("s3-lan3", [("S1", "T2", "ngoai", "done")])
    db = FakeDb([tk("T1"), tk("T2")], [b2("T1", "screened", scr(0.7)), b2("T2", "screened", scr(0.2))])
    code, log = w.main(db, "--tau", "0.5")
    assert code == 0, log
    half = w.summary()["theo_tau"]["0.5"]
    assert list(half["theo_luot"]) == ["s3-lan2", "s3-lan3"]
    assert [half["theo_luot"][k]["ca_e1_moi"] for k in ("s3-lan2", "s3-lan3")] == [1, 0]
    assert (half["cong"]["ca"], half["cong"]["the"], half["cong"]["ca_e1_moi"]) == (2, 1, 1)
    assert {t: r["luot"] for t, r in w.csv("0.5").items()} == {"T1": "s3-lan2", "T2": "s3-lan3"}


def test_cung_ticket_o_hai_thu_muc_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("s3-lan2", [("S1", "T1", "trong", "done")])
    w.run_dir("s3-lan3", [("S1", "T1", "trong", "done")])
    code, log = w.main(FakeDb([tk("T1")], [b2("T1", "screened", scr(0.1))]), "--tau", "0.5")
    assert code == 2 and "chồng" in log[-1] and "T1" in log[-1]


def test_hai_thu_muc_cung_ten_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")])
    w.runs.append(w.runs[0])
    code, log = w.main(FakeDb([tk("T1")], []), "--tau", "0.5")
    assert code == 2 and "cùng tên thư mục" in log[-1]


def test_predictions_co_ticket_ngoai_outcomes_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")], preds=[{"ticket_id": "T9", "route": "AUTO", "m5_aborted": False}])
    code, log = w.main(FakeDb([tk("T1")], []), "--tau", "0.5")
    assert code == 2 and "T9" in log[-1]


# ---- route / m5_aborted ở τ' -----------------------------------------------------------------------------------------


def test_ca_moi_e1_route_null_m5_false_ca_khac_giu_goc(w: World) -> None:
    _one_each(w, 3)
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done"), ("S3", "T3", "trong", "error")], preds=[
        pred("T1", "S1", "F1", route="AUTO", decided_by="rule"),
        pred("T2", "S2", "F2", route=None, m5_aborted=True),
    ])  # fmt: skip
    db = FakeDb([tk("T1"), tk("T2", "E2", "escalated"), tk("T3", "E9", "escalated")],
                [b2("T1", "screened", scr(0.6)), b2("T2", "screened", scr(0.3)), b2("T3", "screened", scr(0.2))])  # fmt: skip
    code, log = w.main(db, "--tau", "0.5", "--tau", TAU_RUN)
    assert code == 0, log
    half = w.csv("0.5")
    assert (half["T1"]["e1_moi"], half["T1"]["route_tau"], half["T1"]["m5_aborted_tau"]) == ("1", "", "false")
    assert (half["T2"]["route_tau"], half["T2"]["m5_aborted_tau"]) == ("", "true")  # không đổi → giữ gốc
    assert (half["T3"]["route_tau"], half["T3"]["m5_aborted_tau"]) == ("", "")  # không có bản ghi predictions
    run = w.csv(TAU_RUN)
    assert (run["T1"]["route_tau"], run["T1"]["m5_aborted_tau"]) == ("AUTO", "false")  # τ' = τ_run: đúng như gốc


def test_out_ngoai_verify_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")])
    w.out = w.tmp / "eval_out"
    code, log = w.main(FakeDb([tk("T1")], []), "--tau", "0.5")
    assert code == 2 and ".verify" in log[-1]
    assert not w.out.exists()


def test_ticket_outcomes_khong_co_trong_db_dung(w: World) -> None:
    _one_each(w, 1)
    w.run_dir("R1", [("S1", "T1", "trong", "done")])
    code, log = w.main(FakeDb([], []), "--tau", "0.5")
    assert code == 2 and "T1" in log[-1]


def test_dan_xuat_offline_out_tang_dung_so_ca_moi_e1_ca_khac_giu_byte(w: World) -> None:
    _one_each(w, 4)
    recs = [pred("T1", "S1", "F1", route="HITL", decided_by="llm", raw_prob=0.3),  # mới E1 (ca LLM)
            pred("T2", "S2", "F2", route="AUTO", decided_by="rule", expected="AUTO"),  # mới E1 (ca luật)
            pred("T3", "S3", "F3", route="HITL", decided_by="llm", raw_prob=0.4),
            pred("T4", "S4", "F4", route="HITL", decided_by="rule")]  # fmt: skip
    # dòng giữ nguyên ghi KIỂU KHÁC json.dumps mặc định (gọn, không dấu cách) — dump lại sẽ lệch byte
    lines = [json.dumps(r, separators=(",", ":")) + "\n" for r in recs]
    run = w.run_dir("s1-hybrid", [(f"S{i}", f"T{i}", "trong", "done") for i in range(1, 5)], pred_lines=lines,
                    manifest_extra=full_manifest())  # fmt: skip
    probs = w.tmp / "probs.jsonl"
    probs.write_text("".join(json.dumps({"scenario_id": s, "variant": v, "raw_prob": p}) + "\n"
                             for s, p in (("S1", 0.3), ("S3", 0.4)) for v in ("with_evidence", "no_evidence", "max")),
                     encoding="utf-8")  # fmt: skip
    db = FakeDb([tk(f"T{i}") for i in range(1, 5)], [b2("T1", "screened", scr(0.7)), b2("T2", "screened", scr(0.6)),
                                                      b2("T3", "screened", scr(0.2)), b2("T4", "screened", scr(0.1))])  # fmt: skip
    code, log = w.main(db, "--tau", "0.5", "--tau", TAU_RUN)
    assert code == 0, log
    derived = w.out / "s1-hybrid" / "predictions-tau0.5.jsonl"
    folds = {"F1": 1, "F2": 2, "F3": 3, "F4": 4}

    def n_out(path: Path) -> int:
        r = offline.load_run(path, run / "manifest.json", probs, strategy="hybrid")  # manifest GỐC dùng được
        return sum(row.kind == "out" for row in offline.classify("hybrid", r, r, folds))

    n_new = sum(r["e1_moi"] == "1" for r in w.csv("0.5").values())
    assert n_new == 2
    assert n_out(derived) - n_out(run / "predictions.jsonl") == n_new
    got = derived.read_bytes().splitlines(keepends=True)
    src = (run / "predictions.jsonl").read_bytes().splitlines(keepends=True)
    assert got[2:] == src[2:]  # T3, T4: nguyên byte
    for line in got[:2]:
        rec = json.loads(line)
        assert rec["route"] is None and rec["m5_aborted"] is False
        assert all(rec[k] is None for k in ("decided_by", "raw_prob", "calibrated_prob", "p_method", "kb_gap"))
    assert (w.out / "s1-hybrid" / f"predictions-tau{TAU_RUN}.jsonl").read_bytes() == (run / "predictions.jsonl").read_bytes()
    assert any("s1-hybrid: predictions-tau0.5.jsonl đổi 2 dòng" in line for line in log)


def test_dan_xuat_khong_qua_load_predictions_xoa_file_dung(w: World) -> None:
    _one_each(w, 2)
    bad = {**pred("T1", "S1", "F1", route="AUTO", decided_by="rule"), "strategy": "khong_co"}  # hỏng sẵn ở lượt gốc
    w.run_dir("R1", [("S1", "T1", "trong", "done"), ("S2", "T2", "trong", "done")],
              preds=[bad, pred("T2", "S2", "F2", route="AUTO", decided_by="rule")])  # fmt: skip
    db = FakeDb([tk("T1"), tk("T2")], [b2("T1", "screened", scr(0.1)), b2("T2", "screened", scr(0.2))])
    code, log = w.main(db, "--tau", "0.5")
    assert code == 2 and "load_predictions" in log[-1]
    assert not (w.out / "R1" / "predictions-tau0.5.jsonl").exists()
