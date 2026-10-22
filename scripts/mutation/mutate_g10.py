"""Mutation tay G10 — `scripts/eval/prob_variants.py` (3 biến thể xác suất thô, P8 v1.4 §5.4/§5.6). Mỗi đột biến áp lên file thật, chạy
`backend/tests/unit/test_eval_prob_variants.py`, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau (file còn untracked
thì chỉ md5 có tác dụng). Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_g10.py
  uv run python scripts/mutation/mutate_g10.py --only M-G10-3

Mọi đột biến PHẢI làm đúng các test dự đoán đỏ (SỐNG hay khác dự đoán → mã thoát 1). Chỉ unit, không DB/stack. Không đọc `.env`.
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
SRC = "scripts/eval/prob_variants.py"
CMD = ["uv", "run", "pytest", "backend/tests/unit/test_eval_prob_variants.py", "-q", "-p", "no:cacheprovider"]


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ (tên hàm, hoặc `tên[tham số]`)


def line(old: str, new: str, tag: str) -> list[tuple[str, str, str, int]]:
    """Thay MỘT dòng (cả thụt lề + xuống dòng) bằng `new` + chú thích đánh dấu."""
    return [(SRC, old, f"{new}  # MUTATION {tag}\n", 1)]


def off(old: str, tag: str) -> list[tuple[str, str, str, int]]:
    """`if <điều kiện>:` → `if False:` (giữ thụt lề)."""
    indent = old[: len(old) - len(old.lstrip())]
    return line(old, f"{indent}if False:", tag)


ALL: list[Mutation] = [
    Mutation("M-G10-1 max → min",
             line("        rows.append(ProbRow(scenario_id=r.scenario_id, variant=\"max\", raw_prob=max(r.raw_prob, no)))\n",
                  "        rows.append(ProbRow(scenario_id=r.scenario_id, variant=\"max\", raw_prob=min(r.raw_prob, no)))", "M-G10-1"),
             CMD, ["test_build_three_variants_and_max_is_max_of_raw", "test_build_kb_gap_copies_with_evidence_and_counts"]),
    Mutation("M-G10-2 gọi cả ca kb_gap",
             line("    todo = [r for r in recorded if not r.kb_gap]\n", "    todo = list(recorded)", "M-G10-2"),
             CMD, ["test_collect_kb_gap_case_is_never_called_and_needs_no_input"]),
    Mutation("M-G10-3 gửi trích đoạn khác rỗng",
             line("            est = await estimator.estimate(case.action, case.ctx, [])\n",
                  "            est = await estimator.estimate(case.action, case.ctx, [None])", "M-G10-3"),
             CMD, ["test_collect_estimator_receives_empty_retrieved_list"]),
    Mutation("M-G10-4 build: ca kb_gap không chép",
             off("        if r.kb_gap:\n", "M-G10-4"),
             CMD, ["test_build_kb_gap_copies_with_evidence_and_counts", "test_cli_build_writes_file_and_prints_counts"]),
    Mutation("M-G10-5 compare: fit trên cả mẫu test",
             line("    fitted = fit_variant(cal, now=now) if cal else \"không có mẫu calibration\"\n",
                  "    fitted = fit_variant(samples, now=now) if cal else \"không có mẫu calibration\"", "M-G10-5"),
             CMD, ["test_compare_mixed_splits_do_not_raise_leakage", "test_compare_raw_metrics_match_hand_computation"]),
    Mutation("M-G10-6 fit_variant nuốt cả LeakageError",
             line("    except ValueError as e:\n", "    except Exception as e:", "M-G10-6"),
             CMD, ["test_fit_variant_does_not_swallow_leakage"]),
    Mutation("M-G10-7 build: bỏ kiểm trùng WITHOUT",
             line("    _unique([w.scenario_id for w in without], \"without\")\n", "    pass", "M-G10-7"),
             CMD, ["test_build_rejects_unknown_duplicate_and_kb_gap_called"]),
    Mutation("M-G10-8 raw_prob không chặn trên 1",
             line("Prob = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]\n",
                  "Prob = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]", "M-G10-8"),
             CMD, ["test_prob_row_rejects_contract_violations"]),
    Mutation("M-G10-9 build: bỏ sắp theo scenario_id",
             line("    for r in sorted(recorded, key=lambda c: c.scenario_id):\n", "    for r in recorded:", "M-G10-9"),
             CMD, ["test_build_rows_sorted_by_scenario_then_variant_and_order_independent",
                   "test_probs_bytes_identical_for_shuffled_inputs"]),
    Mutation("M-G10-10 build: không đếm ca lỗi",
             [(SRC, "                failed[w.error or \"?\"] += 1\n", "                pass  # MUTATION M-G10-10\n", 1)],
             CMD, ["test_build_error_drops_no_evidence_and_max_but_keeps_with_evidence",
                   "test_cli_build_writes_file_and_prints_counts"]),
    Mutation("M-G10-11 nhãn y = gold == ESCALATE_L2",
             [(SRC, "y=meta[i].gold_route != \"AUTO\")\n", "y=meta[i].gold_route == \"ESCALATE_L2\")  # MUTATION M-G10-11\n", 1)],
             CMD, ["test_compare_label_is_gold_not_auto"]),
    Mutation("M-G10-12 write_jsonl ghi đè",
             [(SRC, "    with path.open(\"x\", encoding=\"utf-8\", newline=\"\\n\") as f:\n",
               "    with path.open(\"w\", encoding=\"utf-8\", newline=\"\\n\") as f:  # MUTATION M-G10-12\n", 1)],
             CMD, ["test_write_never_overwrites", "test_cli_build_refuses_existing_output_and_input_overwrite"]),
    Mutation("M-G10-13 mô hình nhận trường lạ",
             [(SRC, "ConfigDict(frozen=True, extra=\"forbid\", strict=True, hide_input_in_errors=True)",
               "ConfigDict(frozen=True, strict=True, hide_input_in_errors=True)  # MUTATION M-G10-13", 1)],
             CMD, ["test_prob_row_rejects_contract_violations"]),
    Mutation("M-G10-14 phạm vi common = own",
             [(SRC, "common & set(by_variant[v]))\n", "set(by_variant[v]))  # MUTATION M-G10-14\n", 1)],
             CMD, ["test_compare_own_vs_common_scope"]),
    Mutation("M-G10-15 compare: nhận trùng (scenario_id, variant)",
             off("        if row.scenario_id in by_variant[row.variant]:\n", "M-G10-15"),
             CMD, ["test_compare_rejects_unknown_or_duplicate_rows"]),
    Mutation("M-G10-16 collect: bỏ kiểm thiếu đầu vào",
             off("    if missing:\n", "M-G10-16"),
             CMD, ["test_collect_missing_input_fails_before_any_call"]),
    Mutation("M-G10-17 lỗi LLMSchemaError không còn là lỗi chịu được",
             [(SRC, "RECOVERABLE = (LLMUnavailable, LLMSchemaError, LLMBudgetExceeded, TurnBudgetExceeded)",
               "RECOVERABLE = (LLMUnavailable, LLMBudgetExceeded, TurnBudgetExceeded)  # MUTATION M-G10-17", 1)],
             CMD, ["test_collect_recoverable_error_becomes_error_row_and_run_continues"]),
    Mutation("M-G10-18 build: ca kb_gap vẫn được phép gọi lại",
             off("    if called_kb_gap:\n", "M-G10-18"),
             CMD, ["test_build_rejects_unknown_duplicate_and_kb_gap_called"]),
    Mutation("M-G10-19 mô hình không strict (bool lọt vào raw_prob)",
             [(SRC, "ConfigDict(frozen=True, extra=\"forbid\", strict=True, hide_input_in_errors=True)\n",
               "ConfigDict(frozen=True, extra=\"forbid\", hide_input_in_errors=True)  # MUTATION M-G10-19\n", 1)],
             CMD, ["test_prob_row_rejects_contract_violations[bad5]"]),
    Mutation("M-G10-20 WithoutRow nhận cả hai hoặc không có gì",
             off("        if (self.raw_prob is None) == (self.error is None):\n", "M-G10-20"),
             CMD, ["test_without_row_needs_exactly_one_of_prob_or_error"]),
]  # fmt: skip

MUTATIONS = ALL
if "--only" in sys.argv:
    at = sys.argv.index("--only") + 1
    prefix = sys.argv[at] if at < len(sys.argv) else ""
    MUTATIONS = [m for m in ALL if m.name.startswith(prefix + " ")]


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
        print(f"DỪNG: không có đột biến nào khớp `--only` (mã: M-G10-1 … M-G10-{len(ALL)})")
        return 2
    env = test_env()
    files = sorted({rel for m in MUTATIONS for rel, *_ in m.edits})
    stop = n3.guard(REPO, files, [m.cmd for m in MUTATIONS], env)  # N3: không dấu sót, mốc xanh
    if stop is not None:
        return stop
    before = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 trước  {before[rel]}  {rel}")
    diff_before = git_diff_stat()
    bad = 0
    for m in MUTATIONS:
        originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel, *_ in m.edits}
        mutated = dict(originals)
        wrong = [f"{rel}: {mutated[rel].count(old)}/{n}" for rel, old, _, n in m.edits if mutated[rel].count(old) != n]
        if wrong:
            print(f"!! {m.name}: chuỗi gốc không khớp số lần {wrong} — bỏ qua")
            bad += 1
            continue
        for rel, old, new, _ in m.edits:
            mutated[rel] = mutated[rel].replace(old, new)
        unmarked = [rel for rel, text in mutated.items() if n3.MARK not in text]
        if unmarked:
            print(f"!! {m.name}: file đột biến thiếu chữ {n3.MARK!r} {unmarked} — bỏ qua (N3a không bắt được nếu bị giết)")
            bad += 1
            continue
        try:
            for rel, text in mutated.items():
                (REPO / rel).write_text(text, encoding="utf-8")
            out = subprocess.run(m.cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        finally:
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?::\w+(?:\[.*?\])?)(?: - |$)", out.stdout, re.MULTILINE)))
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in m.expect if not _hit(e, failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        bad += bool(missing)
        print(f"{m.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
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
