"""Mutation tay chặng 6C (phase6 mục 6.5, PLAN-6C TQ-12, TQ-15, TQ-16) — 2 lượt: lượt 1 (DỪNG 1) M-6C-2, 3, 4, 5, 7, 8, 9 (khởi động,
B12 đường LLM, `audit_check`, N1, `kb_gap`) + M-6C-10, 11, 12 (Q-6C-8, 9); lượt 2 (DỪNG 2) đủ M-6C-1…14 (+ B17 D-42, B12
`action_plan_hash`, Q-6C-10, Q-6C-12). Khuôn `mutate_6b.py`:
mỗi đột biến áp lên file thật, chạy lệnh unit, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`):
file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_6c.py --luot 1
  uv run python scripts/mutation/mutate_6c.py              # lượt 2: cả 14
  uv run python scripts/mutation/mutate_6c.py --only M-6C-3

M-6C-3 bỏ kiểm chiến lược ở CẢ `open_runtime` lẫn lớp thứ hai trong `_open` (cũng trước DB — bỏ một chỗ là đột biến tương đương).
M-6C-9 cùng chỗ sửa với M-6B-4 (`strategy.py`) nhưng phải bị c3 (mức node B12) bắt. Chỉ unit (không DB/stack, không LLM thật).
Không đọc `.env`.
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


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, "-q", "-p", "no:cacheprovider"]


B12 = "backend/app/graph/nodes/b12_assess.py"
WIRING = "backend/app/graph/wiring.py"
CHECK = "backend/app/audit/check.py"
EST = "backend/app/risk/estimator.py"
STRAT = "backend/app/risk/strategy.py"
B17 = "backend/app/graph/nodes/b17_execute.py"
UT = pt(*[f"backend/tests/unit/{name}.py" for name in (
    "test_m5_startup", "test_b12_llm", "test_audit_check_m5", "test_estimator_vars_n1", "test_b12_assess", "test_audit_check",
    "test_risk_estimator", "test_b12_llm_guards", "test_b17_llm_auto", "test_chain_m5", "test_b17_llm_guards",
)])  # fmt: skip


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_KBGAP_CALL = "            gap = kb_gap(evidence, est)\n"
_STRAT_RUNTIME = "    m5_strategy(settings)\n"
_STRAT_OPEN = "        calibrator=calibrator, strategy=m5_strategy(settings), eval_mode=settings.eval_mode,\n"
_POINT4 = '_POINT4 = ("decided_by", "policy_decision", "matched_rule_id", "risk_level", "reason", "route", "raw_prob", "p_method")\n'
_PARAM_ELSE = "    return False  # software_name, resource_path, khoá lạ — không bao giờ gửi\n"
_NULL_OK = '    if decided_by is None and strategy == "full_auto" and route == "AUTO":\n'
_KBGAP = "    return min(len(evidence), MAX_EVIDENCE) - trimmed <= 0\n"
_TRIM_GUARD = "    if type(trimmed) is not int or trimmed < 0:  # `type(...) is int` loại cả bool (lớp con của int)\n"
_FACTS_GUARD = "            check_facts(action.facts)\n"
_TYPE_GUARD = "            if action.type not in PARAMS_BY_ACTION:\n"
_UNCAL = '        if route == "AUTO":\n            route = "HITL"  # D-38: chưa hiệu chỉnh — raw > t_high → L2, còn lại HITL\n'

LUOT1: list[Mutation] = [
    Mutation("M-6C-2 B12 bỏ kb_gap (truyền False)",
             [one(B12, _KBGAP_CALL, "            gap = False  # MUTATION M-6C-2\n")],
             UT, ["test_c6a_empty_evidence_kb_gap_demotes_auto_to_hitl", "test_c6_trimmed_evidence_kb_gap[b-2-cat-2]"]),
    Mutation("M-6C-3 bỏ kiểm chiến lược khỏi open_runtime (cả lớp thứ hai ở _open)",
             [one(WIRING, _STRAT_RUNTIME, "    pass  # MUTATION M-6C-3\n"),
              one(WIRING, _STRAT_OPEN, _STRAT_OPEN.replace("m5_strategy(settings)", "settings.strategy"))],
             UT, ["test_c1_eval_only_strategy_without_eval_mode_refused_before_db",
                  "test_c1_manual_strategy_refused_in_every_mode_before_db"]),
    Mutation("M-6C-4 điểm 4 ca LLM bỏ raw_prob",
             [one(B12, _POINT4, _POINT4.replace(' "raw_prob",', "").rstrip("\n") + "  # MUTATION M-6C-4\n")],
             UT, ["test_c3_no_match_uncalibrated_low_raw_goes_hitl_b15"]),
    Mutation("M-6C-5 estimator_vars giữ software_name",
             [one(EST, _PARAM_ELSE, '    return key == "software_name"  # MUTATION M-6C-5\n')],
             UT, ["test_c16_intended_action_whitelisted[software]", "test_c16_canary_absent_from_vars_json[software]",
                  "test_c15_canary_never_reaches_b14_prompt[software-llm_only-software_name-self_report]"]),
    Mutation("M-6C-7 audit_check chấp nhận decided_by NULL không ghi chú",
             [one(CHECK, _NULL_OK, "    if decided_by is None:  # MUTATION M-6C-7\n")],
             UT, ["test_c13_null_without_annotation_missing_decided_by"]),
    Mutation("M-6C-8 kb_gap bỏ vế trimmed_evidence",
             [one(B12, _KBGAP, "    return min(len(evidence), MAX_EVIDENCE) <= 0  # MUTATION M-6C-8\n")],
             UT, ["test_c6_trimmed_evidence_kb_gap[b-2-cat-2]", "test_c6_trimmed_evidence_kb_gap[c-5-cat-3]"]),
    Mutation("M-6C-9 calibrator null nhưng vẫn so t_low",
             [one(STRAT, _UNCAL, "        pass  # MUTATION M-6C-9: chưa hiệu chỉnh vẫn cho AUTO\n")],
             UT, ["test_c3_no_match_uncalibrated_low_raw_goes_hitl_b15"]),
    # ---- chốt thêm sau soát bảo mật DỪNG 1 (Q-6C-8, Q-6C-9 — Tuấn Anh 13/10) ----
    Mutation("M-6C-10 kb_gap bỏ chặn evidence_trimmed sai kiểu/âm (Q-6C-8)",
             [one(B12, _TRIM_GUARD, "    if False:  # MUTATION M-6C-10\n")],
             UT, ["test_q6c8_bad_evidence_trimmed_is_kb_gap_never_auto[am]",
                  "test_q6c8_bad_evidence_trimmed_is_kb_gap_never_auto[bool-True]",
                  "test_q6c8_bad_evidence_trimmed_is_kb_gap_never_auto[chuoi]",
                  "test_q6c8_bad_evidence_trimmed_is_kb_gap_never_auto[so-thuc]"]),
    Mutation("M-6C-11 B14 bỏ kiểm lại facts (Q-6C-9)",
             [one(B12, _FACTS_GUARD, "            pass  # MUTATION M-6C-11\n")],
             UT, ["test_q6c9_bad_facts_is_e9_estimator_not_called"]),
    Mutation("M-6C-12 B14 bỏ kiểm action.type ∈ PARAMS_BY_ACTION (Q-6C-9)",
             [one(B12, _TYPE_GUARD, "            if False:  # MUTATION M-6C-12\n")],
             UT, ["test_q6c9_unknown_action_type_is_e9_estimator_not_called"]),
]  # fmt: skip

_LLM_AUTO = ('        risk.decided_by == "llm" and risk.route == "AUTO" and state.get("action_plan_hash") == '
             'hash_action(action)\n')  # fmt: skip
_SET_HASH = '            llm_auto = {"action_plan_hash": hash_action(action)}  # D-42: B17 nhận AUTO do LLM chỉ khi hash khớp\n'
_VIA_LLM = "        via_llm = not via_approval and not verdict.matched and llm_auto(state, action)  # 6C P6 (D-42)\n"
_CALIBRATED = "        and risk.calibrated_prob is not None  # Q-6C-10\n"

LUOT2: list[Mutation] = [  # DỪNG 2 (B17 D-42, B12 action_plan_hash) — chạy cùng LUOT1 thành lượt 2
    Mutation("M-6C-1 B17 nhận LLM-AUTO khi hash lệch",
             [one(B17, _LLM_AUTO, '        risk.decided_by == "llm" and risk.route == "AUTO"  # MUTATION M-6C-1\n')],
             UT, ["test_c10_llm_auto_condition_missing_is_e5_recheck_failed[a-hash-lech]",
                  "test_c10_hash_of_other_action_is_e5"]),
    Mutation("M-6C-6 B12 không đặt action_plan_hash ở ca AUTO",
             [one(B12, _SET_HASH, "            llm_auto = {}  # MUTATION M-6C-6\n")],
             UT, ["test_c5_calibrated_low_p_with_evidence_auto_sets_action_plan_hash",
                  "test_c18_llm_auto_cases_continue_to_b17_and_execute"]),
    # ---- chốt thêm sau soát bảo mật DỪNG 2 (Q-6C-10, Q-6C-12 — Tuấn Anh 14/10) ----
    Mutation("M-6C-13 B17 via_llm bỏ vế not verdict.matched (Q-6C-12)",
             [one(B17, _VIA_LLM, "        via_llm = not via_approval and llm_auto(state, action)  # MUTATION M-6C-13\n")],
             UT, ["test_c11_llm_auto_access_full_r08_approval_required_is_e5",
                  "test_c11_llm_auto_now_after_hours_r18_approval_required_is_e5",
                  "test_c11_llm_auto_policy_now_approval_required_monkeypatched_is_e5"]),
    Mutation("M-6C-14 B17 llm_auto bỏ vế calibrated_prob (Q-6C-10)",
             [one(B17, _CALIBRATED, "        and True  # MUTATION M-6C-14\n")],
             UT, ["test_q6c10_llm_auto_without_calibrated_prob_is_e5_not_executed"]),
]  # fmt: skip

ALL = sorted(LUOT1 + LUOT2, key=lambda m: int(m.name.split()[0].rsplit("-", 1)[1]))
MUTATIONS = LUOT1 if "--luot" in sys.argv and sys.argv[sys.argv.index("--luot") + 1 :][:1] == ["1"] else ALL
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
        print("DỪNG: không có đột biến nào khớp `--only`/`--luot` (mã: M-6C-1 … M-6C-14)")
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
