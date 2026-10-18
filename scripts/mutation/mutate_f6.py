"""Mutation chặng F6 (màn duyệt: `affected`, `risk_view`, `response_model`) — khuôn `mutate_t23a.py`. Mỗi đột biến áp lên file
thật, chạy bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION`
→ dừng; mốc xanh một lần cho mỗi lệnh test trước khi đột biến.

  uv run python scripts/mutation/mutate_f6.py                 # cả 4 mã (unit, không Docker)
  uv run python scripts/mutation/mutate_f6.py --only M-F6-2
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


ROUTE = "backend/app/api/approvals.py"
VIEW = pt("backend/tests/unit/test_approvals_view.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_KNOWN = "    if me is not None and me.manager_id is not None:\n"
_ME = "    me = await users.get_user(affected_id)\n"
_RISK = '    return RiskView(**dict(risk), calibrated=risk.calibrated_prob is not None, auto_allowed=risk.route == "AUTO")\n'
_DECO = '@router.get("/api/approvals/{approval_id}", response_model=ApprovalView)\n'

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-F6-1 known khi manager_id NULL",
             [one(ROUTE, _KNOWN, "    if me is not None:  # MUTATION M-F6-1\n")],
             VIEW, ["test_f6_f3_f5_affected_row_without_manager_unknown"]),
    Mutation("M-F6-2 không có dòng users → lấy dòng người gửi",
             [one(ROUTE, _ME, "    me = await users.get_user(affected_id) or await users.get_user(requester_id)  # MUTATION M-F6-2\n")],
             VIEW, ["test_f6_f4_f5_affected_no_users_row_unknown"]),
    Mutation("M-F6-3 calibrated luôn True",
             [one(ROUTE, _RISK, _RISK.replace("calibrated=risk.calibrated_prob is not None", "calibrated=True")
                                    .replace(")\n", ")  # MUTATION M-F6-3\n"))],
             VIEW, ["test_f6_f6_f10_risk_view_rule_twelve_keys", "test_f6_f7_f10_risk_view_llm_uncalibrated"]),
    Mutation("M-F6-4 bỏ response_model",
             [one(ROUTE, _DECO, '@router.get("/api/approvals/{approval_id}", response_model=None)  # MUTATION M-F6-4\n')],
             VIEW, ["test_f6_f12_openapi_approval_view_schema"]),
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
