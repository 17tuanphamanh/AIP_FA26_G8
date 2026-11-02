"""Mutation be-target-guard (L-03 — hành động chạy trên SAI ĐỐI TƯỢNG), khuôn `mutate_t23a.py`: mỗi đột biến áp lên file thật, chạy
TRỌN bộ test của nhánh, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ
`MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_target_guard.py                 # cả 3 mã (unit backend, ScriptedLLM, không Docker)
  uv run python scripts/mutation/mutate_target_guard.py --only M-TG-B

- M-TG-A bỏ A: `mention_reason` luôn None (câu nêu người khác không bật cờ) → ca lỗi nguyên văn đỏ.
- M-TG-B bỏ B: B11 không chèn `target_user` khi cờ bật → dựng Action trên người gửi → test "không Action trên người gửi" đỏ.
- M-TG-C bỏ C: B15 không chốt `requested_for == người gửi` khi cờ bật → test B15 / Q4 đỏ.
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


TARGET = "backend/app/domain/target.py"
B11 = "backend/app/graph/nodes/b11_slots.py"
B15 = "backend/app/graph/nodes/b15_prepare_approval.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in ("test_target_mention", "test_target_guard", "test_chain_t20a", "test_t20b_split", "test_t20b_parent",
                 "test_t20b_q5_q6", "test_b15_prepare_approval", "test_approvers_t20a", "test_nodes_t20a", "test_gate5")
])  # fmt: skip


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_MENTION = "    if _has_identifier(text, requester_id, _ignored_values(ignore)):\n"
_NEED = "        need_target = target_required(state, slots)\n"
_GUARD_C = "        if state[\"intent\"] in TARGET_USER_INTENTS and flag and action.requested_for == requester.user_id:  # [1b] L-03\n"

CHAIN_BUG = "test_chain_bug_case_asks_target_then_r03_for_svc_backup"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-TG-A mention_reason luôn None",
             [one(TARGET, _MENTION, "    return None  # MUTATION M-TG-A\n" + _MENTION)],
             UT, [CHAIN_BUG, "test_chain_bug_case_bad_target_twice_e4_off_topic",
                  "test_b3_sets_flag_when_other_target[i-khong-target]", "test_mentions_other_target_true[cau-loi-nguyen-van]",
                  "test_clarify_reply_names_other_sets_flag", "test_a2_multi_intent_self_account_flagged_by_other_span"]),
    Mutation("M-TG-B B11 không chèn target_user khi cờ bật",
             [one(B11, _NEED, "        need_target = False  # MUTATION M-TG-B\n")],
             UT, [CHAIN_BUG, "test_chain_bug_case_bad_target_twice_e4_off_topic",
                  "test_b11_flag_without_target_asks_fixed_question_no_llm", "test_b11_flag_last_turn_e4_clarification_exhausted",
                  "test_g10_dropped_target_user_is_other_no_rule"]),
    Mutation("M-TG-C B15 bỏ chốt cờ + requested_for == người gửi",
             [one(B15, _GUARD_C, "        if False:  # MUTATION M-TG-C\n")],
             UT, ["test_b15_flag_and_requested_for_is_requester_e5_no_approval",
                  "test_q4_self_id_reply_no_allow_rule_never_auto_then_b15_e5"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix)]


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
