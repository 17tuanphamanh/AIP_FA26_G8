"""Mutation tay G5 — báo cáo M8 (`backend/app/eval/report.py`). Khung giống `mutate_g1.py`: mỗi đột biến áp lên file thật, chạy test
báo cáo, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau.

Chốt (như N3 của các script cũ, viết lại ở đây): (a) file đích còn chữ `MUTATION` → dừng; (b) mốc xanh một lần trước khi đột biến;
(c) sau khi chạy: md5 khớp, `git diff --stat` khớp, không file đích nào còn chữ `MUTATION`. Chuỗi gốc phải xuất hiện đúng số lần khai báo.

  uv run python scripts/mutation/mutate_g5.py
  uv run python scripts/mutation/mutate_g5.py --only M-G5-6

Chỉ unit (dữ liệu tổng hợp, không Docker, không DB). Không đọc `.env`.
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
MARK = "MUTATION"
REP = "backend/app/eval/report.py"
UT = ["uv", "run", "pytest", "backend/tests/unit/eval/test_report.py", "-q", "-p", "no:cacheprovider"]


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def swap(old: str, new: str, tag: str) -> tuple[str, str, str, int]:
    return (REP, old, new.rstrip("\n") + f"  # MUTATION {tag}\n", 1)


_ANY = '        k += any(r.route == "AUTO" for r in rows)\n'
_COST = "    return mean_route_cost(rs).value\n"
_SPLIT = '    if first.split != "test" or mf.split != "test":\n'
_SAMPLE = "        self.sample: dict[str, list[PredictionRecord]] = {n: self.restrict(a.records) for n, a in self.rq1.items()}\n"
_HI = "    if diff.hi < 0:\n"
_MAPPING = "            self.mapping: Mapping[str, str] | None = situations.mapping\n"
_LIMIT = "        safe = PASS if fnr.upper95 < SAFETY_UPPER_LIMIT else FAIL\n"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-G5-1 FNR tình huống: ít nhất một câu AUTO → mọi câu AUTO",
             [swap(_ANY, _ANY.replace("any(", "all("), "M-G5-1")], UT,
             ["test_situation_fnr_unit_changes_the_number", "test_t3a_situation_fnr_rows"]),
    Mutation("M-G5-2 số chính RQ1 lấy chi phí có trọng số 70/20/10",
             [swap(_COST, "    return operating_metrics(rs).main.cost.value", "M-G5-2")], UT,
             ["test_t1_primary_cost_unweighted_on_common_set", "test_t2_cost_diff_points"]),
    Mutation("M-G5-3 bỏ chặn split ≠ test (số calibration lọt vào báo cáo)",
             [swap(_SPLIT, "    if False:", "M-G5-3")], UT, ["test_load_arm_refuses_calibration_split"]),
    Mutation("M-G5-4 không lấy phần giao (mỗi phương án một tập lá)",
             [swap(_SAMPLE, _SAMPLE.replace("self.restrict(a.records)", "list(a.records)"), "M-G5-4")], UT,
             ["test_t1_primary_cost_unweighted_on_common_set", "test_meta_columns"]),
    Mutation("M-G5-5 vế 1 chi phí: hi < 0 → hi <= 0",
             [swap(_HI, "    if diff.hi <= 0:", "M-G5-5")], UT, ["test_verdict_cost_boundary_zero_is_not_pass"]),
    Mutation("M-G5-6 bỏ qua --situations, luôn dùng family",
             [swap(_MAPPING, "            self.mapping: Mapping[str, str] | None = None", "M-G5-6")], UT,
             ["test_t3a_situation_fnr_rows", "test_cli_matches_golden"]),
    Mutation("M-G5-7 vế 2 an toàn: cận trên < 10% → <= 10%",
             [swap(_LIMIT, _LIMIT.replace("<", "<="), "M-G5-7")], UT, ["test_verdict_cost_worse_and_safety_limit"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    at = sys.argv.index("--only") + 1
    prefix = sys.argv[at] if at < len(sys.argv) else ""
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix + " ")]


def test_env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def marked(files: list[str]) -> list[str]:
    return [rel for rel in files if MARK in (REPO / rel).read_text(encoding="utf-8")]


def guard(files: list[str], cmds: list[list[str]], env: dict[str, str]) -> int | None:
    left = marked(files)
    if left:
        print(f"DỪNG: file đích còn chữ {MARK!r} {left} — khôi phục tay trước")
        return 2
    for cmd in {tuple(c): c for c in cmds}.values():
        out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        if out.returncode != 0:
            print(f"DỪNG: mốc chưa xanh — {' '.join(cmd)}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
            return 2
    print("mốc xanh: " + " | ".join(" ".join(c) for c in {tuple(c): c for c in cmds}.values()))
    return None


def _hit(test: str, failed: list[str]) -> bool:
    return any(f.endswith("::" + test) or ("::" + test + "[") in f for f in failed)


def main() -> int:
    if not MUTATIONS:
        print(f"DỪNG: không có đột biến nào khớp `--only` (mã: M-G5-1 … M-G5-{len(MUTATIONS_ALL)})")
        return 2
    env = test_env()
    files = sorted({rel for m in MUTATIONS for rel, *_ in m.edits})
    stop = guard(files, [m.cmd for m in MUTATIONS], env)
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
        try:
            for rel, text in mutated.items():
                (REPO / rel).write_text(text, encoding="utf-8")
            out = subprocess.run(m.cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        finally:
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?::\w+(?:\[.*?\])?)(?: - |$)", out.stdout, re.MULTILINE)))
        missing = [e for e in m.expect if not _hit(e, failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        bad += bool(missing)
        print(f"{m.name}: {status} — {len(failed)} test đỏ")
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
    assert not marked(files), f"còn chữ {MARK!r} trong file đích sau khôi phục!"
    print(f"không còn chữ {MARK!r} trong file đích")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
