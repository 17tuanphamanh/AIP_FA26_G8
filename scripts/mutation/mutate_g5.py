"""Mutation tay G5 — báo cáo M8 (`backend/app/eval/report.py`) và phần dời sang nơi đặt công thức (`metrics.py`: `situation_fnr`,
`full_auto_baseline`; `stats.py`: Clopper–Pearson hai phía). Khung giống `mutate_g1.py`: mỗi đột biến áp lên file thật, chạy test
eval, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau.

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
MET = "backend/app/eval/metrics.py"
STA = "backend/app/eval/stats.py"
UT = ["uv", "run", "pytest", "backend/tests/unit/eval", "-q", "-p", "no:cacheprovider"]


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def swap(old: str, new: str, tag: str, rel: str = REP) -> tuple[str, str, str, int]:
    return (rel, old, new.rstrip("\n") + f"  # MUTATION {tag}\n", 1)


_ANY = '        k += any(r.route == "AUTO" for r in rows)\n'  # metrics.situation_fnr (dời từ report.py)
_COST = "    return mean_route_cost(rs).value\n"
_SPLIT = '    if first.split != "test" or mf.split != "test":\n'
_SAMPLE = "        self.sample: dict[str, list[PredictionRecord]] = {n: self.restrict(a.records) for n, a in self.rq1.items()}\n"
_HI = "    if diff.hi < 0:\n"
_MAPPING = "            self.mapping: Mapping[str, str] | None = situations.mapping\n"
_LIMIT = "        safe = PASS if fnr.upper95 < SAFETY_UPPER_LIMIT else FAIL\n"
# T7 trên phần giao chung (report.py)
_T7_A = "        rs = c.sample.get(name)\n        if not rs:  # phương án vắng hoặc phần giao rỗng → không dòng (không bịa số)\n"
_T7_RULE = '            against.append(("Chỉ-luật", c.sample["rule_only"], "rule_only"))\n'
_T7_META = '                t.add(c.meta(metas, be.n), f"{c.label(name)} vs {other_label}", mix_label, be.n,\n'
# metrics.py (dời từ report.py)
_FULL_AUTO = ('    return [r.model_copy(update={"strategy": "full_auto", **({"route": "AUTO"} if r.route is not None else {})}) '
              "for r in records]\n")  # fmt: skip
_HIDDEN = '        if (hidden == "only" and not is_hidden) or (hidden == "except" and is_hidden):\n'
_ONLY_LLM = '        if r.expected_route is None or r.route is None or (only_llm and r.decided_by != "llm"):\n'
# stats.py
_CP_LO = "    return float(beta.ppf(1.0 - float(conf), int(k), int(n) - int(k) + 1))\n"
_CP_TWO = "    c = (1.0 + level) / 2.0\n"
_CP_K = "    if not 0 <= k <= n:\n"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-G5-1 FNR tình huống: ít nhất một câu AUTO → mọi câu AUTO",
             [swap(_ANY, _ANY.replace("any(", "all("), "M-G5-1", MET)], UT,
             ["test_situation_fnr_unit_changes_the_number", "test_t3a_situation_fnr_rows", "test_situation_fnr_any_not_all"]),
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
    # Hai edit: chỉ đổi một bên → breakeven ValueError ở fixture → pytest báo ERROR, không đếm là đỏ.
    Mutation("M-G5-8 T7 về tập lá riêng (toàn bộ bản ghi của X và của Chỉ-luật)",
             [swap(_T7_A, "        rs = list(c.rq1[name].records) if name in c.rq1 else None\n"
                          "        if not rs:  # phương án vắng hoặc phần giao rỗng → không dòng (không bịa số)", "M-G5-8"),
              swap(_T7_RULE, _T7_RULE.replace('c.sample["rule_only"]', 'list(c.rq1["rule_only"].records)'), "M-G5-8")], UT,
             ["test_t7_breakeven", "test_t7_same_sample_as_t1", "test_cli_matches_golden"]),
    Mutation("M-G5-9 T7 meta lấy n_unlabeled của breakeven (lệch T1)",
             [swap(_T7_META, _T7_META.replace("c.meta(metas, be.n)", "c.meta(metas, be.n, n_unlabeled=be.n_unlabeled)"), "M-G5-9")], UT,
             ["test_t7_same_sample_as_t1"]),
    Mutation("M-G5-10 Full-auto đổi cả lá route None thành AUTO",
             [swap(_FULL_AUTO, '    return [r.model_copy(update={"strategy": "full_auto", "route": "AUTO"}) for r in records]', "M-G5-10", MET)],
             UT, ["test_full_auto_baseline", "test_full_auto_baseline_hand"]),
    Mutation("M-G5-11 FNR tình huống bỏ lọc hidden_factor",
             [swap(_HIDDEN, "        if False:", "M-G5-11", MET)], UT,
             ["test_situation_fnr_llm_layer_and_hidden", "test_situation_fnr_hidden"]),
    Mutation("M-G5-12 FNR tình huống bỏ lọc only_llm",
             [swap(_ONLY_LLM, "        if r.expected_route is None or r.route is None:", "M-G5-12", MET)], UT,
             ["test_situation_fnr_llm_layer_and_hidden", "test_situation_fnr_only_llm"]),
    Mutation("M-G5-13 cận dưới CP lấy phân vị conf thay 1 − conf",
             [swap(_CP_LO, _CP_LO.replace("1.0 - float(conf)", "float(conf)"), "M-G5-13", STA)], UT,
             ["test_cp_lower_hand", "test_situation_fnr_clopper_pearson"]),
    Mutation("M-G5-14 khoảng hai phía dùng level cho mỗi phía (thay (1 + level)/2)",
             [swap(_CP_TWO, "    c = level", "M-G5-14", STA)], UT,
             ["test_cp_two_sided_hand", "test_situation_fnr_clopper_pearson"]),
    Mutation("M-G5-15 cận dưới CP bỏ kiểm 0 ≤ k ≤ n",
             [swap(_CP_K, "    if False:", "M-G5-15", STA)], UT, ["test_cp_lower_rejects"]),
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
