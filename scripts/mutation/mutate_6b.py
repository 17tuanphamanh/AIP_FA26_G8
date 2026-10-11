"""Mutation tay chặng 6B (phase6 mục 5.7, PLAN-6B mục 3 TQ-17…19) — 2 lượt: lượt 1 (DỪNG 1) M-6B-1, 2, 3, 7, 8 (estimator +
prompt); lượt 2 (DỪNG 2) đủ M-6B-1…9. Mỗi đột biến áp lên file thật (`.py` và YAML prompt thật — M-6B-7), chạy 3 file test,
khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau (file 6B còn untracked thì chỉ md5 có tác dụng). Luật N3
(`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_6b.py --luot 1
  uv run python scripts/mutation/mutate_6b.py              # lượt 2: cả 9
  uv run python scripts/mutation/mutate_6b.py --only M-6B-7

Chỉ unit (không DB/stack, không LLM thật). Không đọc `.env`.
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


EST = "backend/app/risk/estimator.py"
PROMPT = "config/prompts/b14_risk_estimate.yaml"
STRAT = "backend/app/risk/strategy.py"
UT = pt(*[f"backend/tests/unit/{name}.py" for name in ("test_risk_estimator", "test_risk_strategy", "test_llm_prompts")])


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_CACHE = '        self._cache_policy: CachePolicy = "default" if eval_mode else "bypass"\n'
_IDX = '            "strong", "b14_risk_vote", {**variables, "sample_idx": idx}, RiskVoteOut,\n'
_ALL5 = (
    "        for r in results:\n"
    "            if isinstance(r, BaseException):\n"
    "                raise r\n"
    "        votes = [r for r in results if not isinstance(r, BaseException)]\n"
    "        meta = votes[0][1]\n"
    "        p = sum(v.needs_human for v, _ in votes) / K\n"
)
_VARS = "allowed_vars: [intended_action, risk_context, evidence]\n"
_BODY = "  Trích đoạn quy định liên quan:\n  {{ evidence }}\n"
_CTX = '            "within_business_hours": ctx.within_business_hours,\n'
_UNCAL = '        if route == "AUTO":\n            route = "HITL"  # D-38: chưa hiệu chỉnh — raw > t_high → L2, còn lại HITL\n'
_KBGAP = '    demoted = kb_gap and route == "AUTO"\n'
_CHECK = "    if strategy in EVAL_ONLY and not eval_mode:\n"
_GUARD = '    return not v.matched or v.decision == "allow"\n'

LUOT1: list[Mutation] = [
    Mutation("M-6B-1 luôn cache_policy=\"default\"",
             [one(EST, _CACHE, '        self._cache_policy: CachePolicy = "default"  # MUTATION M-6B-1\n')],
             UT, ["test_es1_self_report_call_params_via_recording_port[False-bypass]",
                  "test_es1_gateway_runtime_never_caches"]),
    Mutation("M-6B-2 sample_idx hằng 0 (5 bản render trùng — TQ-17)",
             [one(EST, _IDX, '            "strong", "b14_risk_vote", {**variables, "sample_idx": 0}, RiskVoteOut,'
                             "  # MUTATION M-6B-2\n")],
             UT, ["test_es4_k5_gateway_five_distinct_renders_keys_p06_factor_order"]),
    Mutation("M-6B-3 k = 5 bỏ qua lời gọi lỗi, tính p trên phần còn lại",
             [one(EST, _ALL5, "        votes = [r for r in results if not isinstance(r, BaseException)]  # MUTATION M-6B-3\n"
                              "        meta = votes[0][1]\n"
                              "        p = sum(v.needs_human for v, _ in votes) / len(votes)\n")],
             UT, ["test_es5_k5_one_unavailable_call_fails_whole_estimate"]),
    Mutation("M-6B-7 thêm redacted_request vào allowed_vars + thân prompt (YAML thật — TQ-18)",
             [one(PROMPT, _VARS, "allowed_vars: [intended_action, risk_context, evidence, redacted_request]  # MUTATION M-6B-7\n"),
              one(PROMPT, _BODY, _BODY + "  {{ redacted_request }}\n")],
             UT, ["test_es7_real_prompt_whitelist_cache_role[b14_risk_estimate-expected_vars0]"]),
    Mutation("M-6B-8 risk_context gồm now",
             [one(EST, _CTX, '            "now": ctx.now.isoformat(),  # MUTATION M-6B-8\n' + _CTX)],
             UT, ["test_es2_risk_context_drops_time_and_identity"]),
]  # fmt: skip

LUOT2: list[Mutation] = [
    Mutation("M-6B-4 chưa hiệu chỉnh vẫn so t_low (cho AUTO)",
             [one(STRAT, _UNCAL, "        pass  # MUTATION M-6B-4: bỏ bước hạ AUTO → HITL khi chưa hiệu chỉnh\n")],
             UT, ["test_st7_uncalibrated_never_auto[0.01-HITL-medium]"]),
    Mutation("M-6B-5 bỏ bước kb_gap",
             [one(STRAT, _KBGAP, "    demoted = False  # MUTATION M-6B-5\n")],
             UT, ["test_st5_kb_gap_demotes_auto_to_hitl"]),
    Mutation("M-6B-6 check_strategy cho llm_only khi không eval",
             [one(STRAT, _CHECK, '    if strategy in EVAL_ONLY - {"llm_only"} and not eval_mode:  # MUTATION M-6B-6\n')],
             UT, ["test_st15_check_strategy_eval_only_blocked_outside_eval"]),
    Mutation("M-6B-9 hybrid_guarded gọi LLM cả khi luật approval_required",
             [one(STRAT, _GUARD, '    return not v.matched or v.decision in ("allow", "approval_required")  # MUTATION M-6B-9\n')],
             UT, ["test_st13_guarded_approval_required_rule_hitl_no_llm"]),
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
        print("DỪNG: không có đột biến nào khớp `--only`/`--luot` (mã: M-6B-1 … M-6B-9)")
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
