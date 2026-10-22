"""Mutation tay N18 / G4 — `backend/app/eval/calibrate.py` (fit_fold) và `backend/app/eval/offline.py` (route offline), P8 v1.4 §5.3–§5.4.
Mỗi đột biến áp lên file thật, chạy test của hai file, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3
(`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến. Mỗi đột biến PHẢI làm đúng các test dự đoán đỏ
(SỐNG hay khác dự đoán → mã thoát 1). Đánh số theo điểm duyệt: P1–P7 = 7 điểm chốt 22/10; LK = LeakageError; G4; Q = câu hỏi mẫu A.

  uv run python scripts/mutation/mutate_n18.py
  uv run python scripts/mutation/mutate_n18.py --only M-N18-P3a

Chỉ unit (hàm thuần, không DB/stack). Không đọc `.env`.
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import n3  # scripts/mutation/n3.py — cùng thư mục (sys.path[0] khi chạy script)

REPO = Path(__file__).resolve().parents[2]
CAL = "backend/app/eval/calibrate.py"
OFF = "backend/app/eval/offline.py"
DM = "backend/app/risk/decision_math.py"
CMD = ["uv", "run", "pytest", "backend/tests/unit/eval/test_calibrate.py", "backend/tests/unit/eval/test_offline.py", "-q",
       "-p", "no:cacheprovider"]  # fmt: skip

type Edit = tuple[str, str, str, int]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)


class Mutation(NamedTuple):
    name: str
    edits: list[Edit]
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ (tên hàm, hoặc `tên[tham số]`)


def _line(rel: str, frag: str) -> str:
    lines = [ln for ln in (REPO / rel).read_text(encoding="utf-8").splitlines(keepends=True) if frag in ln]
    if len(lines) != 1:
        raise SystemExit(f"{rel}: mảnh {frag!r} khớp {len(lines)} dòng (cần đúng 1)")
    return lines[0]


def sub(rel: str, frag: str, repl: str, tag: str) -> list[Edit]:
    """Thay `frag` bằng `repl` trong dòng duy nhất chứa nó; dấu MUTATION nằm CUỐI dòng (không bao giờ giữa biểu thức)."""
    old = _line(rel, frag)
    return [(rel, old, old.replace(frag, repl).rstrip("\n") + f"  # MUTATION {tag}\n", 1)]


def off(rel: str, frag: str, tag: str) -> list[Edit]:
    """`if <điều kiện>:` → `if False:` (giữ thụt lề)."""
    old = _line(rel, frag)
    indent = old[: len(old) - len(old.lstrip())]
    if not old.strip().startswith("if ") or not old.rstrip().endswith(":"):
        raise SystemExit(f"{rel}: dòng không phải `if …:` — {old!r}")
    return [(rel, old, f"{indent}if False:  # MUTATION {tag}\n", 1)]


def m(name: str, edits: list[Edit], *expect: str) -> Mutation:
    return Mutation(name, edits, CMD, list(expect))


ALL: list[Mutation] = [
    # ---- P1: tập ca đi lớp LLM ----
    m("M-N18-P1a guarded kéo cả luật chặn/cần duyệt vào lớp LLM",
      sub(OFF, 'and base.decided_by == "rule" and base.route == "AUTO"', 'and base.decided_by == "rule"', "M-N18-P1a"),
      "test_p1_guarded_rule_allow_and_unmatched_go_to_llm_blocking_rules_keep_route"),
    m("M-N18-P1b Hybrid lấy p của S2",
      sub(OFF, 'probs_run = s1 if arm == "hybrid" else s2', "probs_run = s2", "M-N18-P1b"),
      "test_p1_hybrid_only_llm_decided_cases_go_to_llm_rule_cases_keep_route"),
    m("M-N18-P1c Chỉ-LLM đọc ca từ S1 (bỏ ca khớp luật)",
      sub(OFF, 'base_run = s2 if arm == "llm_only" else s1', "base_run = s1", "M-N18-P1c"),
      "test_p1_llm_only_includes_rule_matched_cases_with_s2_probabilities"),
    m("M-N18-P1d Hybrid-guarded lấy p và p_method từ S1",
      sub(OFF, 'src = base if arm != "hybrid_guarded" else r2', "src = base", "M-N18-P1d"),
      "test_p1_guarded_rule_allow_and_unmatched_go_to_llm_blocking_rules_keep_route"),
    m("M-N18-P1e bỏ kiểm with_evidence khớp raw_prob cùng lượt",
      off(OFF, "if src.raw_prob is not None and src.raw_prob != probs", "M-N18-P1e"),
      "test_p1_probs_must_match_predictions_of_the_same_run"),
    # ---- P2: chi phí kỳ vọng, kb_gap ----
    m("M-N18-P2a expected_cost_on bỏ ca không đi lớp LLM",
      sub(CAL, "        if c.llm:", "        if not c.llm:\n            continue\n        if c.llm:", "M-N18-P2a"),
      "test_p2_expected_cost_counts_fixed_route_cases_hand_computed", "test_p2_fit_fold_scores_with_fixed_cases_included"),
    m("M-N18-P2b bỏ hạ AUTO → HITL khi kb_gap",
      off(CAL, 'if kb_gap and route == "AUTO":', "M-N18-P2b"),
      "test_p2_kb_gap_demotes_auto_to_hitl", "test_calibrated_output_never_auto_on_kb_gap_cases"),
    m("M-N18-P2c no_evidence bị coi là thiếu căn cứ vì trích đoạn rỗng",
      sub(CAL, "llm_route(c.probs[variant], cal, th, c.kb_gap, policy_t_high)",
          'llm_route(c.probs[variant], cal, th, c.kb_gap or variant == "no_evidence", policy_t_high)', "M-N18-P2c"),
      "test_p2_no_evidence_uses_original_kb_gap_not_empty_evidence"),
    m("M-N18-P2d offline không truyền kb_gap vào route",
      sub(OFF, "bool(row.kb_gap), policy_t_high", "False, policy_t_high", "M-N18-P2d"),
      "test_calibrated_output_never_auto_on_kb_gap_cases"),
    # ---- P3: hoà chi phí ----
    m("M-N18-P3a hoà chi phí → biến thể cuối",
      sub(CAL, "key = (round(score, 12), rank)", "key = (round(score, 12), -rank)", "M-N18-P3a"),
      "test_p3_tie_goes_to_with_evidence_then_no_evidence_then_max"),
    m("M-N18-P3b thứ tự hoà đổi",
      sub(CAL, 'VARIANT_ORDER: Final[tuple[Variant, ...]] = ("with_evidence", "no_evidence", "max")',
          'VARIANT_ORDER: Final[tuple[Variant, ...]] = ("max", "no_evidence", "with_evidence")', "M-N18-P3b"),
      "test_p3_variant_order_constant", "test_p3_tie_goes_to_with_evidence_then_no_evidence_then_max"),
    # ---- P4: ngưỡng trên 1,01 / không AUTO / chú thích ----
    m("M-N18-P4a ép ngưỡng trên bằng 1,0 thay vì 1,01",
      sub(CAL, "T_HIGH_MAX if reason is not None else th.t_high", "1.0 if reason is not None else th.t_high", "M-N18-P4a"),
      "test_p4_upper_1_01_means_llm_never_escalates_to_l2"),
    m("M-N18-P4b ngưỡng dưới chưa hiệu chỉnh khác 0",
      sub(CAL, "UNCALIBRATED_T_LOW: Final = 0.0", "UNCALIBRATED_T_LOW: Final = 0.2", "M-N18-P4b"),
      "test_p4_uncalibrated_never_auto_because_lower_threshold_is_zero"),
    m("M-N18-P4c chưa hiệu chỉnh bỏ qua ngưỡng trên của policy",
      sub(CAL, "return route_for(raw, UNCALIBRATED_T_LOW, policy_t_high)", "return route_for(raw, UNCALIBRATED_T_LOW, T_HIGH_MAX)", "M-N18-P4c"),
      "test_p4_uncalibrated_never_auto_because_lower_threshold_is_zero", "test_p7_uncalibrated_threshold_comes_from_argument_not_a_constant"),
    m("M-N18-P4d chú thích decision_math quay lại câu sai",
      sub(DM, "lớp LLM không bao giờ đưa ca sang L2 (p ≤ 1 < 1,01; P8 §5.3, B12-B14 §5.2 mục 5)",
          "bỏ đường LLM → mọi ca LLM đi L2 (P8 §5.3)", "M-N18-P4d"),
      "test_p4_decision_math_comments_fixed_behaviour_unchanged"),
    # ---- P5: AUC / thiếu L2 ----
    m("M-N18-P5a AUC đúng bằng ngưỡng bị coi là thấp",
      sub(CAL, "a < AUC_L2_MIN", "a <= AUC_L2_MIN", "M-N18-P5a"),
      "test_p5_auc_exactly_at_minimum_is_not_disabled"),
    m("M-N18-P5b AUC tính trên nhãn 'gold ≠ AUTO' thay vì L2",
      sub(CAL, 'auc(p_cal, [g == "ESCALATE_L2" for g in golds])', 'auc(p_cal, [g != "AUTO" for g in golds])', "M-N18-P5b"),
      "test_p5_low_auc_forces_upper"),
    m("M-N18-P5c AUC không tính được vẫn giữ ngưỡng trên chọn",
      sub(CAL, 'return "auc_undefined", None', "return None, None", "M-N18-P5c"),
      "test_p5_auc_undefined_forces_upper"),
    m("M-N18-P5d bỏ AUC: đủ ca L2 là giữ ngưỡng",
      sub(CAL, 'return ("auc_below_min" if a < AUC_L2_MIN else None), a', "return None, a", "M-N18-P5d"),
      "test_p5_low_auc_forces_upper"),
    # ---- P6: thiếu ca L2 ----
    m("M-N18-P6a đếm ca L2 trên cả phần huấn luyện (kể cả ca luật)",
      sub(CAL, 'n_l2 = sum(c.gold == "ESCALATE_L2" for c in llm)', 'n_l2 = sum(c.gold == "ESCALATE_L2" for c in train)', "M-N18-P6a"),
      "test_p6_fixed_route_l2_cases_do_not_count"),
    m("M-N18-P6b hằng MIN_L2_CASES = 9",
      sub(CAL, "MIN_L2_CASES: Final = 10", "MIN_L2_CASES: Final = 9", "M-N18-P6b"),
      "test_p6_boundary_nine_vs_ten_l2_cases_among_llm_cases", "test_p6_threshold_is_the_named_constant"),
    m("M-N18-P6c 'thiếu' tính cả đúng bằng ngưỡng",
      sub(CAL, "if n_l2 < MIN_L2_CASES:", "if n_l2 <= MIN_L2_CASES:", "M-N18-P6c"),
      "test_p6_boundary_nine_vs_ten_l2_cases_among_llm_cases"),
    m("M-N18-P6d ghi cứng số 10 thay vì đọc hằng",
      sub(CAL, "if n_l2 < MIN_L2_CASES:", "if n_l2 < 10:", "M-N18-P6d"),
      "test_p6_threshold_is_the_named_constant"),
    # ---- P7: biến thể lỗi, chưa hiệu chỉnh, policy ----
    m("M-N18-P7a fit lỗi không loại biến thể (lỗi thoát ra ngoài)",
      sub(CAL, "except ValueError as e:", "except KeyError as e:", "M-N18-P7a"),
      "test_p7_failed_variant_is_dropped_and_logged_others_compete", "test_p7_all_variants_failing_means_uncalibrated_with_policy_threshold"),
    m("M-N18-P7b không ghi log biến thể bị loại",
      sub(CAL, 'lines.append(f"biến thể {v} bị loại: {e}")', "pass", "M-N18-P7b"),
      "test_p7_failed_variant_is_dropped_and_logged_others_compete"),
    m("M-N18-P7c chưa hiệu chỉnh ghi cứng ngưỡng trên",
      sub(CAL, "(UNCALIBRATED_T_LOW, policy_t_high), None, tuple(trials),", "(UNCALIBRATED_T_LOW, 0.9), None, tuple(trials),", "M-N18-P7c"),
      "test_p7_uncalibrated_threshold_comes_from_argument_not_a_constant"),
    m("M-N18-P7d bỏ kiểm sha256 policy",
      off(OFF, "if r.manifest.policy_sha256 != sha:", "M-N18-P7d"),
      "test_policy_sha_mismatch_or_missing_stops"),
    m("M-N18-P7e ngưỡng trên ghi cứng thay vì đọc từ policy",
      sub(OFF, "return parse_policy(data).constants.THRESHOLD_HIGH, sha", "return 0.9, sha", "M-N18-P7e"),
      "test_policy_threshold_is_read_from_the_policy_file"),
    m("M-N18-P7f manifest thiếu policy_sha256 vẫn được qua bước kiểm thiếu",
      off(OFF, "if r.manifest.policy_sha256 is None:", "M-N18-P7f"),
      "test_policy_sha_mismatch_or_missing_stops"),
    # ---- LK / G4: không nhìn phần đo ----
    m("M-N18-LKa bỏ kiểm split đầu fit_fold",
      off(CAL, 'if any(c.split != "calibration" for c in train):', "M-N18-LKa"),
      "test_leakage_any_test_case_in_train_raises[fixed]"),
    m("M-N18-LKb phần huấn luyện lẫn phần đo",
      sub(OFF, "for r in in_sample if r.fold != i]", "for r in in_sample if r.fold >= 0]", "M-N18-LKb"),
      "test_g4_calibrator_ignores_the_test_fold_labels_but_follows_train_labels"),
    m("M-N18-G4a ma trận thiếu độ nhạy 20",
      sub(CAL, "SENSITIVITY_RATIOS: Final = (5.0, 10.0, 20.0)", "SENSITIVITY_RATIOS: Final = (5.0, 10.0)", "M-N18-G4a"),
      "test_sensitivity_5_10_20_and_theory_threshold_recorded"),
    # ---- Q: câu hỏi mẫu A đã chốt ----
    m("M-N18-Q2a bỏ kiểm fold trong predictions khớp CSV",
      off(OFF, "if base.fold is not None and base.fold != fold:", "M-N18-Q2a"),
      "test_fold_in_predictions_must_equal_csv"),
    m("M-N18-Q3a kb_gap null không dừng",
      sub(OFF, "null_gap += src.kb_gap is None", "null_gap += 0", "M-N18-Q3a"),
      "test_kb_gap_null_on_llm_case_stops_with_message_for_the_harness"),
    m("M-N18-Q4a ca không tới điểm log 4 không chuyển L2",
      sub(OFF, 'return "no_log4" if r.final_state is None or r.exit_code == E9 else "out"', 'return "out"', "M-N18-Q4a"),
      "test_q4_no_log4_goes_to_l2_e1_and_unlabeled_stay_out_of_sample"),
    m("M-N18-Q4b mọi ca route null (E3…) bị chuyển L2",
      sub(OFF, 'return "no_log4" if r.final_state is None or r.exit_code == E9 else "out"', 'return "no_log4"', "M-N18-Q4b"),
      "test_q4_no_log4_goes_to_l2_e1_and_unlabeled_stay_out_of_sample"),
    m("M-N18-Q4c hết hạn lượt (final_state null) không còn chuyển L2",
      sub(OFF, 'return "no_log4" if r.final_state is None or r.exit_code == E9 else "out"',
          'return "no_log4" if r.exit_code == E9 else "out"', "M-N18-Q4c"),
      "test_q4_no_log4_goes_to_l2_e1_and_unlabeled_stay_out_of_sample"),
    m("M-N18-Q4d lỗi chưa lường trước (E9) không còn chuyển L2",
      sub(OFF, 'return "no_log4" if r.final_state is None or r.exit_code == E9 else "out"',
          'return "no_log4" if r.final_state is None else "out"', "M-N18-Q4d"),
      "test_q4_no_log4_goes_to_l2_e1_and_unlabeled_stay_out_of_sample"),
    m("M-N18-Q4e E1 không còn được loại trước điều kiện hết hạn lượt",
      off(OFF, "if r.exit_code == E1:", "M-N18-Q4e"),
      "test_q4_e1_is_out_of_sample_even_when_final_state_is_null"),
    m("M-N18-Q5a biến thể được chọn thiếu p không chuyển L2",
      sub(OFF, 'up |= {"route": "ESCALATE_L2", "raw_prob": None, "calibrated_prob": None}',
          'up |= {"route": "HITL", "raw_prob": None, "calibrated_prob": None}', "M-N18-Q5a"),
      "test_q5_chosen_variant_missing_on_test_case_goes_to_l2_and_is_counted"),
    m("M-N18-Q5b ca thiếu biến thể vẫn vào so sánh",
      sub(CAL, "common = [c for c in llm if all(v in c.probs for v in variants)]", "common = list(llm)", "M-N18-Q5b"),
      "test_incomplete_cases_leave_comparison_but_stay_counted"),
    m("M-N18-Q7a thiếu started_at không dừng",
      off(OFF, "if t is None or t.utcoffset() is None:", "M-N18-Q7a"),
      "test_started_at_missing_stops"),
    m("M-N18-Q9a Hybrid-guarded dùng lại run_id của S1",
      sub(OFF, '"run_id": derived_run_id(s1, s2), "strategy": "hybrid_guarded"', '"run_id": s1.manifest.run_id, "strategy": "hybrid_guarded"', "M-N18-Q9a"),
      "test_manifest_of_derived_arms"),
    m("M-N18-Q9b bản ghi Hybrid-guarded giữ strategy hybrid",
      sub(OFF, 'up = {**up, "run_id": derived_run_id, "strategy": "hybrid_guarded"}', 'up = {**up, "run_id": derived_run_id}', "M-N18-Q9b"),
      "test_outputs_load_in_report_and_build_report", "test_manifest_of_derived_arms"),
    m("M-N18-Q6a ca đã hiệu chỉnh không ghi calibrated_prob",
      sub(OFF, '"raw_prob": p, "calibrated_prob": cal.transform(p) if cal is not None else None,',
          '"raw_prob": p, "calibrated_prob": None,', "M-N18-Q6a"),
      "test_llm_rows_carry_calibrated_prob_and_chosen_variant_probability"),
    m("M-N18-Q8a ghi đè thư mục đầu ra",
      off(OFF, "if args.out.exists():", "M-N18-Q8a"),
      "test_out_directory_must_be_new"),
]  # fmt: skip

MUTATIONS = ALL
if "--only" in sys.argv:
    at = sys.argv.index("--only") + 1
    prefix = sys.argv[at] if at < len(sys.argv) else ""
    MUTATIONS = [x for x in ALL if x.name.startswith(prefix + " ")]


def test_env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(test: str, failed: list[str]) -> bool:
    if "[" in test:
        return any(f.endswith("::" + test) for f in failed)
    return any(f.endswith("::" + test) or ("::" + test + "[") in f for f in failed)


def main() -> int:
    if not MUTATIONS:  # `--only` sai tên → không đột biến nào chạy; trả 0 là "xanh rỗng"
        print("DỪNG: không có đột biến nào khớp `--only` (mã dạng M-N18-P1a)")
        return 2
    env = test_env()
    files = sorted({rel for x in MUTATIONS for rel, *_ in x.edits})
    stop = n3.guard(REPO, files, [x.cmd for x in MUTATIONS], env)  # N3: không dấu sót, mốc xanh
    if stop is not None:
        return stop
    before = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 trước  {before[rel]}  {rel}")
    diff_before = git_diff_stat()
    bad = 0
    for x in MUTATIONS:
        originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel, *_ in x.edits}
        mutated = dict(originals)
        wrong = [f"{rel}: {mutated[rel].count(old)}/{n}" for rel, old, _, n in x.edits if mutated[rel].count(old) != n]
        if wrong:
            print(f"!! {x.name}: chuỗi gốc không khớp số lần {wrong} — bỏ qua")
            bad += 1
            continue
        for rel, old, new, _ in x.edits:
            mutated[rel] = mutated[rel].replace(old, new)
        unmarked = [rel for rel, text in mutated.items() if n3.MARK not in text]
        if unmarked:
            print(f"!! {x.name}: file đột biến thiếu chữ {n3.MARK!r} {unmarked} — bỏ qua (N3a không bắt được nếu bị giết)")
            bad += 1
            continue
        try:
            for rel, text in mutated.items():
                (REPO / rel).write_text(text, encoding="utf-8")
            out = subprocess.run(x.cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        finally:
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?::\w+(?:\[.*?\])?)(?: - |$)", out.stdout, re.MULTILINE)))
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in x.expect if not _hit(e, failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        bad += bool(missing)
        print(f"{x.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(len(errors)) if errors else ''}")
        for f in failed[:8]:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
    after = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 sau    {after[rel]}  {rel}")
    assert after == before, "md5 khác sau khôi phục!"
    print("md5 sau khôi phục: khớp")
    assert git_diff_stat() == diff_before, "git diff --stat khác lúc đầu!"
    print("git diff --stat: khớp lúc đầu")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
