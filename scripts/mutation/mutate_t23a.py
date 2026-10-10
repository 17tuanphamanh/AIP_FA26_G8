"""Mutation chặng T23a (phase5 mục 6.3, PLAN-T23a TQ-9) — lượt 1 ở T23a, lượt 2 ở ngày đệm trước cổng 5. Mỗi đột biến áp lên
file thật, chạy bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ
`MUTATION` → dừng; mốc xanh một lần cho mỗi lệnh test trước khi đột biến.

  uv run python scripts/mutation/mutate_t23a.py                    # cả 9 mã (unit backend + ml_service, sandbox, không Docker)
  uv run python scripts/mutation/mutate_t23a.py --only M-T23a-9

Hai lệnh test: `BE` (B2 + client ml-service + compose) và `ML` (ml_service, không `ml_real` — không cần torch). Mỗi đột biến chạy
TRỌN lệnh của nó (không chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.
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


GUARD = "ml_service/app/guard.py"
B02 = "backend/app/graph/nodes/b02_screen.py"
SETTINGS = "backend/app/settings.py"
CLIENT = "backend/app/ml/client.py"

BE = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in ("test_b02_screen", "test_ml_client", "test_ml_deploy", "test_fake_ml", "test_ml_timeouts")
])  # fmt: skip
ML = pt("ml_service/tests", "-o", "pythonpath=ml_service", "-m", "not ml_real")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_MAX = "    p_malicious = max(softmax(row)[guard.injection_index] for row in rows)\n"
_CAP = "        raise TooManyWindows(count)\n"
_SHA = "        if actual != expected:\n"
_ACTIVE = '        if p_mal is not None and clf_mode == "active":\n'
_DEFAULT = '    b2_classifier_mode: Literal["shadow", "active"] = "shadow"\n'
_L3_422 = '    return endpoint == "classify" and response.status_code == 422 and _error_code(response) == "too_many_windows"\n'

_SHADOW_BLOCKS = (
    "        if p_mal is not None and p_mal >= TAU_BLOCK:  # MUTATION M-T23a-2: chặn theo điểm bất kể mode\n"
    '            return await _block(state, layer_decided="classifier", p_mal=p_mal, clf_mode=clf_mode)\n'
)
_SHADOW_PASSES = (
    "        if p_mal is not None and p_mal <= TAU_PASS:  # MUTATION M-T23a-3: cho qua theo điểm bất kể mode\n"
    '            return await _pass(state, layer_decided="classifier", p_mal=p_mal, clf_mode=clf_mode)\n'
)

SHADOW = "test_shadow_classifier_never_decides"
T2 = "test_t23a_too_many_windows_goes_l4"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-T23a-1 chỉ chấm cửa sổ đầu",
             [one(GUARD, _MAX, _MAX.replace("for row in rows)", "for row in rows[:1])  # MUTATION M-T23a-1"))],
             ML, ["test_suspicious_tail_in_last_window_is_scored"]),
    Mutation("M-T23a-2 shadow vẫn chặn ≥ TAU_BLOCK",
             [one(B02, _ACTIVE, _SHADOW_BLOCKS + _ACTIVE)],
             BE, [f"{SHADOW}[0.95]"]),
    Mutation("M-T23a-3 shadow vẫn cho qua ≤ TAU_PASS",
             [one(B02, _ACTIVE, _SHADOW_PASSES + _ACTIVE)],
             BE, [f"{SHADOW}[0.05]", "test_shadow_low_score_attack_still_judged_by_llm"]),
    Mutation("M-T23a-4 mặc định → active",
             [one(SETTINGS, _DEFAULT, _DEFAULT.replace('= "shadow"', '= "active"  # MUTATION M-T23a-4'))],
             BE, ["test_mode_defaults_to_shadow"]),
    Mutation("M-T23a-5 max → mean",
             [one(GUARD, _MAX, '    p_malicious = sum(softmax(row)[guard.injection_index] for row in rows) / len(rows)'
                               "  # MUTATION M-T23a-5\n")],
             ML, ["test_max_over_windows_not_mean"]),
    Mutation("M-T23a-6 lật chỉ số lớp",
             [one(GUARD, _MAX, _MAX.replace("[guard.injection_index] for row in rows)",
                                            "[1 - guard.injection_index] for row in rows)  # MUTATION M-T23a-6"))],
             ML, ["test_class_index_from_id2label"]),
    Mutation("M-T23a-7 bỏ kiểm SHA",
             [one(GUARD, _SHA, "        if False:  # MUTATION M-T23a-7\n")],
             ML, ["test_sha_mismatch_refuses"]),
    Mutation("M-T23a-8 vượt trần cắt bớt vẫn trả điểm",
             [one(GUARD, _CAP, "        count = MAX_WINDOWS  # MUTATION M-T23a-8\n")],
             ML, ["test_48_windows_scored_49_rejected_without_scoring"]),
    Mutation("M-T23a-9 422 too_many_windows → MlContractError (E9)",
             [one(CLIENT, _L3_422, "    return False  # MUTATION M-T23a-9\n")],
             BE, ["test_t23a_classify_too_many_windows_is_value", f"{T2}[shadow]", f"{T2}[active]"]),
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
