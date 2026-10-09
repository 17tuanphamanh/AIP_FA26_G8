"""Mutation chặng T22a (phase5 mục 4.8, PLAN-T22a TQ-12) — 2 lượt. Mỗi đột biến áp lên file thật, chạy bộ test, khôi phục trong
`finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi
đột biến. JSON (`policy.json`): chữ `MUTATION` chèn vào `description` của luật bị phá (như `mutate_4b.py`).

  uv run python scripts/mutation/mutate_t22a.py                    # lượt hiện hành (unit, sandbox, không Docker)
  uv run python scripts/mutation/mutate_t22a.py --only M-T22a-8

Lượt 1 (DỪNG 1 — chưa có R01–R15, `rule_coverage.py` còn stub): chỉ các mã chạy được — M-T22a-8 (g1, g5; a1, c1 còn xfail chờ
DỪNG 2), M-T22a-9 (g4; f11 cần R11), M-T22a-12 (h7). Lượt 2 (DỪNG 2): đủ 13 mã với kỳ vọng đầy đủ bảng 4.8.

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


CONTEXT = "backend/app/risk/context.py"
FACTS = "backend/app/domain/facts.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_policy_rules_all", "test_build_ctx_targets", "test_rule_coverage", "test_policy_rules_vpn",
        "test_hrule_4b_owner", "test_b12_assess", "test_config_files", "test_slots_facts", "test_policy_engine_signature",
        "test_tool_models_p7",
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

_OWNER = '        or (device_target and action.facts.get("device_owner_is_requester") is not True)\n'
_VALUE_SET = "        if facts[key] not in FACT_VALUE_SETS[key]:\n"

G = "test_g_build_ctx_target_is_other_theo_dich"
G1, G4, G5 = (f"{G}[g1-account-tu-lam-khong-fact-may-False]", f"{G}[g4-vpn-device-thieu-fact-chu-may-True]",
              f"{G}[g5-access-tu-xem-False]")  # fmt: skip
H7 = "test_h7_check_facts_tap_gia_tri_target_user_status"

UNIT: list[Mutation] = [
    Mutation("M-T22a-8 build_ctx áp vế chủ máy cho mọi đích",
             [one(CONTEXT, _OWNER, '        or action.facts.get("device_owner_is_requester") is not True  # MUTATION M-T22a-8\n')],
             UT, [G1, G5]),
    Mutation("M-T22a-9 build_ctx bỏ vế chủ máy",
             [one(CONTEXT, _OWNER, "        or False  # MUTATION M-T22a-9\n")],
             UT, [G4]),
    Mutation("M-T22a-12 check_facts bỏ kiểm tập giá trị",
             [one(FACTS, _VALUE_SET, "        if False:  # MUTATION M-T22a-12\n")],
             UT, [H7]),
]  # fmt: skip

MUTATIONS = UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in UNIT if m.name.startswith(prefix)]


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
