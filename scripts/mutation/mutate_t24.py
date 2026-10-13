"""Mutation chặng T24 (phase5 mục 7.7, PLAN-T24 S10/S16) — khuôn `mutate_t20a.py`. Mỗi đột biến áp lên file thật, chạy bộ test,
khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một
lần trước khi đột biến.

  uv run python scripts/mutation/mutate_t24.py                     # lượt hiện hành (unit, sandbox, không Docker)
  uv run python scripts/mutation/mutate_t24.py --only M-T24-3
  uv run python scripts/mutation/mutate_t24.py --only M-T24-1,M-T24-9   # nhiều mã, so ĐÚNG mã (không theo tiền tố)

Lượt 1 (DỪNG 1 — bản này): M-T24-1…9. M-T24-4: `Action` không mang người gửi → đột biến giả lập "dùng người gửi" bằng hằng `nv001`
(người gửi của mọi ca p4; `requested_for` của ca ≠ nv001).

Mỗi đột biến chạy TRỌN bộ test của chặng (không chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.
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


PLANS = "backend/app/executor/plans.py"
EXECUTOR = "backend/app/executor/plan_executor.py"
MESSAGES = "backend/app/domain/messages.py"
B17 = "backend/app/graph/nodes/b17_execute.py"
WIRING = "backend/app/executor/wiring.py"
ACCESS = "backend/app/tools/diagnosis/access.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_plans_t24", "test_executor_t24", "test_handoff_t24", "test_messages_t24", "test_b17_t24", "test_registry_t24",
        "test_access_n8", "test_n7_rejection_pin", "test_enable_intents_t24", "test_executor_vpn", "test_executor_plans",
        "test_b17_execute", "test_b17_approval_hash", "test_b17_decided_by", "test_infer_access", "test_policy_rules_all",
        "test_approvers_t20a", "test_rejection_text", "test_turn_budget",
    )
])  # fmt: skip


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_SKIP_NOT_REV = "            if step.undo is None:  # T24 P3: bước không hoàn tác được (license đã cấp) → KHÔNG gọi gì, chỉ ghi nhận\n"
_FILTER = '    return tuple(s for s in steps if s.when == "always" or (s.when == "paid_license" and paid))\n'
_PAID = '    paid = action.facts.get("license_paid") is not False  # thiếu fact → coi như CÓ phí (D-48)\n'
_STEP_USER = '    p = action.params\n    user = {"user_id": action.requested_for}\n    builders: dict[str, Any] = {\n        "renew_vpn_cert"'
_EXTEND = '        "extend_permission": lambda: {**user, "resource_path": p["resource_path"], "duration_days": p["duration_days"]},\n'
_OUT_CHECK = (
    "    if not isinstance(value, str) or pattern is None or not pattern.fullmatch(value):\n"
    "        return None\n"
)
_L2 = '        f"L2 cần làm tay: {manual}."\n'
_NONE_RULE = '            if meta.reversibility == "none" and undoable:\n'
_FILESERVER = "        **fileserver_write.write_handlers(http),\n"
_N8_GUARD = '        if status is not None and (res.owner_department or status.department):  # T24 N8 (Q-T24-6): hai phía rỗng ≠ "cùng phòng"\n'
_SAME_DEPT = '            facts["same_department"] = res.owner_department == status.department\n'
_WRITE_CALLS = '        if s == "undone" or (s.startswith("UNDO_FAILED: ") and s != "UNDO_FAILED: turn_budget_exceeded")\n'

X1 = "test_x1_paid_install_fails_after_license_no_undo_call"
X2 = "test_x2_paid_install_assign_409_one_call_none_needed"
X8 = "test_x8_three_steps_partial_rollback_order"
P3 = "test_p3_plan_for_install_license_step"

UNIT = [
    Mutation("M-T24-1 hoàn tác gọi cả bước không hoàn tác được",
             [one(EXECUTOR, _SKIP_NOT_REV, "            if step.undo is None and False:  # MUTATION M-T24-1\n")],
             UT, [X1, X8]),
    Mutation("M-T24-2 plan_for bỏ bước license",
             [one(PLANS, _FILTER, '    return tuple(s for s in steps if s.when == "always")  # MUTATION M-T24-2\n')],
             UT, [P3, X1, X2]),
    Mutation("M-T24-3 thiếu license_paid → coi như miễn phí",
             [one(PLANS, _PAID, '    paid = action.facts.get("license_paid") is True  # MUTATION M-T24-3\n')],
             UT, [f"{P3}[thieu-fact-coi-nhu-co-phi]", "test_p3_executor_missing_license_paid_assigns_first"]),
    Mutation("M-T24-4 step_args dùng người gửi thay requested_for",
             [one(PLANS, _STEP_USER, _STEP_USER.replace('{"user_id": action.requested_for}',
                                                        '{"user_id": "nv001"}  # MUTATION M-T24-4 (giả lập người gửi)'))],
             UT, ["test_p4_reset_unlock_user_is_requested_for_not_sender", "test_p4_assign_license_user_is_requested_for",
                  "test_p4_grant_args"]),
    Mutation("M-T24-5 extend gửi mức quyền",
             [one(PLANS, _EXTEND, '        "extend_permission": lambda: {**user, "resource_path": p["resource_path"], '
                                  '"duration_days": p["duration_days"], "level": "full"},  # MUTATION M-T24-5\n')],
             UT, ["test_p4_extend_args_no_permission_level"]),
    Mutation("M-T24-6 result_text chép giá trị không qua regex",
             [one(MESSAGES, _OUT_CHECK, "    if not isinstance(value, str):  # MUTATION M-T24-6\n        return None\n"
                                        "    return value\n")],
             UT, ["test_m2_bad_values_dropped"]),
    Mutation("M-T24-7 handoff bỏ phần 'L2 cần làm tay'",
             [one(EXECUTOR, _L2, '        ""  # MUTATION M-T24-7\n')],
             UT, ["test_m4_handoff_four_parts_and_l2_sentence"]),
    Mutation("M-T24-8 check_plans bỏ luật 'reversibility none ⇒ không undo'",
             [one(PLANS, _NONE_RULE, "            if False:  # MUTATION M-T24-8\n")],
             UT, ["test_p2_reversibility_none_with_undo_step_refuses"]),
    Mutation("M-T24-9 _write_calls đếm not_reversible",
             [one(B17, _WRITE_CALLS, _WRITE_CALLS.replace('if s == "undone" or (', 'if s in ("undone", "not_reversible") or (')
                  .rstrip("\n") + "  # MUTATION M-T24-9\n")],
             UT, ["test_x10_write_calls_does_not_count_not_reversible"]),
    Mutation("M-T24-11 registry ghi thiếu fileserver_write",
             [one(WIRING, _FILESERVER, "        # MUTATION M-T24-11 bỏ fileserver_write\n")],
             UT, ["test_w1_every_write_tool_has_handler_one_post"]),
    Mutation("M-T24-12 same_department với chuỗi rỗng → True",
             [one(ACCESS, _N8_GUARD, "        if status is not None:  # MUTATION M-T24-12\n"),
              one(ACCESS, _SAME_DEPT, '            facts["same_department"] = res.owner_department == status.department or "" in '
                                      "(res.owner_department, status.department)\n")],
             UT, ["test_n8_both_empty_not_true", "test_n8_user_department_empty_false", "test_n8_owner_department_empty_false"]),
]  # fmt: skip

MUTATIONS = UNIT
if "--only" in sys.argv:
    codes = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    MUTATIONS = [m for m in UNIT if m.name.split(" ", 1)[0] in codes]


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
