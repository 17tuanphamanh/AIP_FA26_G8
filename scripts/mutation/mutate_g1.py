"""Mutation tay G1 — chỉ số theo route có trọng số + điểm hoà vốn (`metrics.py`: `operating_metrics`, `manual_baseline`, `breakeven`;
plan G1 mục Mutation). Khung giống `mutate_g2.py`: mỗi đột biến áp lên file thật, chạy test eval, khôi phục trong `finally`, so md5 +
`git diff --stat` trước/sau.

Chốt N3 VIẾT LẠI ở đây, KHÔNG import `n3.py` (file đó nằm trong danh sách chặn đọc tới 25/10 — import = chạy code của file bị chặn):
(a) file đích còn chữ `MUTATION` → dừng; (b) mốc xanh một lần trước khi đột biến; (c) sau khi chạy: md5 khớp, `git diff --stat` khớp,
không file đích nào còn chữ `MUTATION`; (d) chuỗi gốc của đột biến cũ (`mutate_t29.py`, `mutate_g2.py`, `mutate_v11.py`) và của file
này vẫn xuất hiện ĐÚNG 1 lần trong `metrics.py` nếu có xuất hiện — đọc VĂN BẢN script bằng `ast` (không import → không chạy n3.py).

  uv run python scripts/mutation/mutate_g1.py
  uv run python scripts/mutation/mutate_g1.py --only M-G1-7
  uv run python scripts/mutation/mutate_g1.py --check-old    # chỉ chạy N3d

Chỉ unit (dữ liệu tổng hợp, không Docker, không DB). Không đọc `.env`.
"""

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
MARK = "MUTATION"


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, "-q", "-p", "no:cacheprovider"]


MET = "backend/app/eval/metrics.py"
UT = pt("backend/tests/unit/eval")
OLD_SCRIPTS = ("mutate_t29.py", "mutate_g2.py", "mutate_v11.py", "mutate_g1.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ (không có "[…]" → mọi tham số của test đó đều tính)


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


def _off(rel: str, old: str, tag: str) -> tuple[str, str, str, int]:
    """`if <điều kiện>:` → `if False:` (giữ thụt lề)."""
    indent = old[: len(old) - len(old.lstrip())]
    return one(rel, old, f"{indent}if False:  # MUTATION {tag}\n")


def _swap(rel: str, old: str, new: str, tag: str) -> tuple[str, str, str, int]:
    return one(rel, old, new.rstrip("\n") + f"  # MUTATION {tag}\n")


# ---- operating_metrics -------------------------------------------------------------------------------------------------

_GROUP = "            rows[n3_group(r.expected_route)].append(r)\n"
_REACHED = "        if r.route is not None:\n"
_WEIGH = "    return missing, None if missing else sum(frozen[g] * cast(float, parts[g]) for g in GROUPS)\n"
_GCOST = "    means = {g: mean_route_cost(rs, cost) if rs else Mean(0.0, 0) for g, rs in reached.items()}\n"
_AUTO = '        automation=_share(reached, frozen, ("AUTO",), unlabeled),\n'
_REVIEW = '        review=_share(reached, frozen, ("HITL",), unlabeled),\n'
_POINT_MIX = "    frozen = check_mix(mix)\n    return OperatingPoint(\n"
_SENS = "        sensitivity=MappingProxyType({k: _point(reached, m, cost, unlabeled) for k, m in sensitivity_mixes.items()}),\n"
_N_M5 = "        n_m5=plain.n,\n"
_OM_UNLAB = "        n_unlabeled=unlabeled,\n"
_PLAIN = "        cost=plain,\n"

# ---- manual_baseline + breakeven -----------------------------------------------------------------------------------------

_ACTION = "        if r.route is not None:  # lá có hành động\n"
_HITL = '            update["route"] = "HITL"\n'
_C2 = "_C2 = cost_matrix_for_ratio(2).costs\n"
_FIXED = "    {g: MappingProxyType({p: _C1[g][p] - _MISS[g][p] for p in ROUTES}) for g in ROUTES}\n"
_RSTAR = "    num = fb - fa\n"
_EQUAL = "    if abs(ma - mb) <= SLOPE_TOL:\n"
_DOMINATED = '    return (r, "ok") if r > 0 else (None, "dominated")  # r* ≤ 0 → một bên rẻ hơn với mọi r > 0 (G1-Q2)\n'
_NUM_TOL = "    if abs(num) <= FIXED_TOL:\n"
_NUM_ZERO = "        num = 0.0  # fixed bằng nhau: r* = 0 → bên miss nhỏ hơn rẻ hơn với mọi r > 0\n"
_FIXED_TOL = ("FIXED_TOL = 1e-9  # |fixed_A − fixed_B| ≤ FIXED_TOL → tử số r* = 0 (Tuấn Anh 22/10, Q-G1-11): chênh lệch chỉ là"
              " nhiễu số thực\n")
_TOL_TESTS = ["test_breakeven_fixed_tol_float_noise", "test_breakeven_fixed_tol_within"]
_COMMON_A = "    common_a = [r for r in records_a if r.scenario_id in keep]\n"
_COMMON_B = "    common_b = [r for r in records_b if r.scenario_id in keep]\n"
_SAME_SCN = "    if gold_a.keys() != gold_b.keys():\n"
_SAME_GOLD = "    if any(gold_a[s] != gold_b[s] for s in gold_a):\n"
_UNWEIGHTED = "    if frozen is None:\n        return (), _avg(_FIXED, pairs), _avg(_MISS, pairs)\n"
_SAVING = "    saving = {r: _minus(_cost_at(common_b, frozen, cm), _cost_at(common_a, frozen, cm)) for r, cm in matrices.items()}\n"
_MATRICES = "    matrices = {float(r): cost_matrix_for_ratio(r) for r in ratios}  # ratio ≤ 0 → ValueError\n"
_LABELLED = "    labelled = [s for s, g in gold_a.items() if g is not None]\n"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-G1-1 nhóm theo route thay expected_route",
             [_swap(MET, _GROUP, "            rows[n3_group(r.route)].append(r)", "M-G1-1")], UT,
             ["test_operating_group_by_gold", "test_operating_weighted_hand"]),
    Mutation("M-G1-2 nhóm thiếu → chuẩn hoá lại trên nhóm còn lại",
             [_swap(MET, _WEIGH, "    return missing, (sum(frozen[g] * cast(float, parts[g]) for g in GROUPS if g not in missing)"
                                 " / sum(frozen[g] for g in GROUPS if g not in missing)) if len(missing) < len(GROUPS) else None",
                    "M-G1-2")], UT, ["test_operating_empty_group"]),
    Mutation("M-G1-3 cost nhóm bỏ qua tham số cost",
             [_swap(MET, _GCOST, _GCOST.replace("mean_route_cost(rs, cost)", "mean_route_cost(rs, DEFAULT_COST)"), "M-G1-3")], UT,
             ["test_operating_cost_param"]),
    Mutation("M-G1-4 automation đếm route != AUTO",
             [_swap(MET, _AUTO, _AUTO.replace('("AUTO",)', '("HITL", "ESCALATE_L2")'), "M-G1-4")], UT,
             ["test_operating_weighted_hand", "test_operating_shares_sum_to_one"]),
    Mutation("M-G1-5 review đếm HITL + L2 (chốt 5)",
             [_swap(MET, _REVIEW, _REVIEW.replace('("HITL",)', '("HITL", "ESCALATE_L2")'), "M-G1-5")], UT,
             ["test_review_counts_hitl_only", "test_operating_shares_sum_to_one"]),
    Mutation("M-G1-6 n_g gồm cả lá route None",
             [_swap(MET, _REACHED, "        if True:", "M-G1-6")], UT, ["test_operating_excludes_route_none"]),
    Mutation("M-G1-7 độ nhạy dùng mix chính cho mọi bộ",
             [_swap(MET, _SENS, _SENS.replace("_point(reached, m, cost", "_point(reached, mix, cost"), "M-G1-7")], UT,
             ["test_operating_weighted_hand"]),
    Mutation("M-G1-8 bỏ check_mix trong operating_metrics",
             [one(MET, _POINT_MIX, "    frozen = MappingProxyType(dict(mix))  # MUTATION M-G1-8\n    return OperatingPoint(\n")], UT,
             ["test_operating_mix_validated"]),
    Mutation("M-G1-9 n_m5 đếm cả lá route None",
             [_swap(MET, _N_M5, "        n_m5=len(_labelled(records)),", "M-G1-9")], UT, ["test_operating_excludes_route_none"]),
    Mutation("M-G1-10 n_unlabeled của OperatingMetrics luôn 0",
             [_swap(MET, _OM_UNLAB, "        n_unlabeled=0,", "M-G1-10")], UT,
             ["test_operating_skips_unlabeled", "test_operating_all_unlabeled"]),
    Mutation("M-G1-11 cost chính = chi phí trọng số mix chính (chốt 4)",
             [_swap(MET, _PLAIN, "        cost=Mean(_point(reached, mix, cost, unlabeled).cost.value or 0.0, 1),", "M-G1-11")], UT,
             ["test_operating_plain_cost_is_main"]),
    Mutation("M-G1-12 manual_baseline đổi cả lá route None thành HITL",
             [_swap(MET, _ACTION, "        if True:", "M-G1-12")], UT, ["test_manual_baseline"]),
    Mutation("M-G1-13 manual_baseline gán ESCALATE_L2 thay HITL",
             [_swap(MET, _HITL, '            update["route"] = "ESCALATE_L2"', "M-G1-13")], UT,
             ["test_manual_baseline", "test_breakeven_vs_manual_hand"]),
    Mutation("M-G1-14 r* đổi dấu tử số",
             [_swap(MET, _RSTAR, "    num = fa - fb", "M-G1-14")], UT,
             ["test_breakeven_vs_manual_hand", "test_breakeven_cost_equal_at_rstar"]),
    Mutation("M-G1-15 bỏ nhánh equal_miss",
             [_off(MET, _EQUAL, "M-G1-15")], UT,
             ["test_breakeven_equal_miss", "test_breakeven_equal_miss_before_fixed_tol"]),
    Mutation("M-G1-16 bỏ nhánh dominated (trả r* ≤ 0)",
             [_swap(MET, _DOMINATED, '    return r, "ok"', "M-G1-16")], UT,
             ["test_breakeven_dominated", "test_breakeven_rstar_zero_is_dominated"]),
    Mutation("M-G1-17 phần cố định = C(1) (quên trừ phần theo r)",
             [_swap(MET, _FIXED, _FIXED.replace("_C1[g][p] - _MISS[g][p]", "_C1[g][p]"), "M-G1-17")], UT,
             ["test_breakeven_vs_manual_hand", "test_breakeven_cells_from_cost_matrix"]),
    Mutation("M-G1-18 phần theo r lấy C(3) − C(1) (gấp đôi)",
             [_swap(MET, _C2, "_C2 = cost_matrix_for_ratio(3).costs", "M-G1-18")], UT,
             ["test_breakeven_l2_miss_counts_double", "test_breakeven_vs_manual_hand"]),
    Mutation("M-G1-19 không lấy phần giao",
             [_swap(MET, _COMMON_A, "    common_a = [r for r in records_a if r.route is not None and r.expected_route is not None]",
                    "M-G1-19"),
              _swap(MET, _COMMON_B, "    common_b = [r for r in records_b if r.route is not None and r.expected_route is not None]",
                    "M-G1-19")], UT, ["test_breakeven_intersection"]),
    Mutation("M-G1-20 bỏ kiểm cùng tập scenario_id",
             [_off(MET, _SAME_SCN, "M-G1-20")], UT, ["test_breakeven_input_mismatch"]),
    Mutation("M-G1-21 bỏ kiểm cùng expected_route theo scenario_id",
             [_off(MET, _SAME_GOLD, "M-G1-21")], UT, ["test_breakeven_input_mismatch"]),
    Mutation("M-G1-22 có mix mà vẫn tính không trọng số",
             [one(MET, _UNWEIGHTED, "    if True:  # MUTATION M-G1-22\n        return (), _avg(_FIXED, pairs), _avg(_MISS, pairs)\n")], UT,
             ["test_breakeven_weighted_hand"]),
    Mutation("M-G1-23 saving = cost_A − cost_B",
             [_swap(MET, _SAVING, "    saving = {r: _minus(_cost_at(common_a, frozen, cm), _cost_at(common_b, frozen, cm))"
                                  " for r, cm in matrices.items()}", "M-G1-23")], UT,
             ["test_breakeven_savings_hand", "test_breakeven_savings_affine"]),
    Mutation("M-G1-24 saving luôn tính ở r = 10",
             [_swap(MET, _MATRICES, "    matrices = {float(r): cost_matrix_for_ratio(10) for r in ratios}", "M-G1-24")], UT,
             ["test_breakeven_savings_hand"]),
    Mutation("M-G1-25 breakeven không lọc lá chưa nhãn",
             [_swap(MET, _LABELLED, "    labelled = list(gold_a)", "M-G1-25")], UT,
             ["test_breakeven_skips_unlabeled", "test_breakeven_all_unlabeled"]),
    # ---- dung sai fixed: tử số trong FIXED_TOL → 0 → dominated (Tuấn Anh 22/10, Q-G1-11) ----
    Mutation("M-G1-26 bỏ dung sai (so == 0)",
             [_swap(MET, _NUM_TOL, "    if num == 0.0:", "M-G1-26")], UT, _TOL_TESTS),
    Mutation("M-G1-27 trong dung sai trả r* = 0, ok",
             [_swap(MET, _NUM_ZERO, '        return 0.0, "ok"', "M-G1-27")], UT,
             ["test_breakeven_rstar_zero_is_dominated", *_TOL_TESTS]),
    Mutation("M-G1-28 tử số không về 0 (giữ nhiễu; = bỏ nhánh dung sai)",
             [_swap(MET, _NUM_ZERO, "        num = num", "M-G1-28")], UT, _TOL_TESTS),
    Mutation("M-G1-29 dung sai một phía (thiếu abs)",
             [_swap(MET, _NUM_TOL, "    if num <= FIXED_TOL:", "M-G1-29")], UT, ["test_breakeven_antisymmetric"]),
    Mutation("M-G1-30 dung sai quá rộng (1e-6)",
             [_swap(MET, _FIXED_TOL, "FIXED_TOL = 1e-6", "M-G1-30")], UT, ["test_breakeven_fixed_tol_outside"]),
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


def _docstrings(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _line_strings(path: Path) -> set[str]:
    """Hằng chuỗi có xuống dòng và có chữ (bỏ docstring, bỏ mảnh của f-string) — ứng viên chuỗi gốc của đột biến."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values)
    return {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and "\n" in n.value and n.value.strip()
    }


def check_old() -> list[str]:
    """N3d: chuỗi của các script đột biến có mặt trong `metrics.py` thì phải đúng 1 lần (mọi edit dùng `one`)."""
    text = (REPO / MET).read_text(encoding="utf-8")
    bad: list[str] = []
    for name in OLD_SCRIPTS:
        for s in sorted(_line_strings(REPO / "scripts/mutation" / name)):
            if text.count(s) > 1:
                bad.append(f"{name}: {s.strip()[:60]!r} ×{text.count(s)}")
    return bad


def guard(files: list[str], cmds: list[list[str]], env: dict[str, str]) -> int | None:
    """N3 (viết lại, không import n3): (a) không file đích nào còn dấu `MUTATION`; (d) chuỗi gốc cũ đúng 1 lần; (b) mốc xanh."""
    left = marked(files)
    if left:
        print(f"DỪNG (N3a): file đích còn chữ {MARK!r} {left} — khôi phục tay trước")
        return 2
    dup = check_old()
    if dup:
        print("DỪNG (N3d): chuỗi gốc đột biến xuất hiện > 1 lần trong metrics.py:")
        print("    " + "\n    ".join(dup))
        return 2
    print(f"N3d: chuỗi gốc của {', '.join(OLD_SCRIPTS)} — không chuỗi nào lặp trong {MET}")
    for cmd in {tuple(c): c for c in cmds}.values():
        out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        if out.returncode != 0:
            print(f"DỪNG (N3b): mốc chưa xanh — {' '.join(cmd)}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
            return 2
    print("mốc xanh: " + " | ".join(" ".join(c) for c in {tuple(c): c for c in cmds}.values()))
    return None


def _hit(test: str, failed: list[str]) -> bool:
    if "[" in test:
        return any(f.endswith("::" + test) for f in failed)
    return any(f.endswith("::" + test) or ("::" + test + "[") in f for f in failed)


def main() -> int:
    if "--check-old" in sys.argv:
        dup = check_old()
        n = sum(len(_line_strings(REPO / "scripts/mutation" / s)) for s in OLD_SCRIPTS)
        present = {s for name in OLD_SCRIPTS for s in _line_strings(REPO / "scripts/mutation" / name)
                   if s in (REPO / MET).read_text(encoding="utf-8")}  # fmt: skip
        print(f"N3d: {n} hằng chuỗi nhiều dòng trong {len(OLD_SCRIPTS)} script; {len(present)} có mặt trong {MET}")
        for d in dup:
            print(f"    LẶP {d}")
        print("N3d: ĐẠT" if not dup else "N3d: KHÔNG ĐẠT")
        return 1 if dup else 0
    if not MUTATIONS:
        print(f"DỪNG: không có đột biến nào khớp `--only` (mã: M-G1-1 … M-G1-{len(MUTATIONS_ALL)})")
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
        unmarked = [rel for rel, text in mutated.items() if MARK not in text]
        if unmarked:
            print(f"!! {m.name}: file đột biến thiếu chữ {MARK!r} {unmarked} — bỏ qua (N3a không bắt được nếu bị giết)")
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
    assert not marked(files), f"còn chữ {MARK!r} trong file đích sau khôi phục!"
    print(f"không còn chữ {MARK!r} trong file đích")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
