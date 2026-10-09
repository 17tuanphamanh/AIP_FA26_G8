"""Mutation tay chặng 6A (phase6 mục 4.7, PLAN-6A mục 5) — 1 lượt, M-6A-1…12. Mỗi đột biến áp lên file thật, chạy 3 file test
6A, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau (file 6A còn untracked thì chỉ md5 có tác dụng). Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng;
mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_6a.py
  uv run python scripts/mutation/mutate_6a.py --only M-6A-7

Chỉ unit (hàm thuần, không DB/stack). Không đọc `.env`.
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


DM = "backend/app/risk/decision_math.py"
CAL = "backend/app/risk/calibrator.py"
UT = pt(*[f"backend/tests/unit/{name}.py" for name in ("test_decision_math", "test_calibrator", "test_risk_no_eval_import")])


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_ROUTE = "    if x < lo:\n"
_STAR = "    return c_review / c_miss\n"
_CP = "    return float(beta.ppf(c, int(k) + 1, int(n) - int(k)))\n"
_ECE = "    k = np.minimum(np.floor(np.round(p * n_bins, 9)), n_bins - 1).astype(int)\n"
_TIE = "    best = np.lexsort((_GRID[hi_idx], _GRID[lo_idx], key_cost))[0]\n"
_LEAK = '    wrong = sum(1 for s in samples if s.split != "calibration")\n    if wrong:\n'
_LR = "    model = LogisticRegression(C=np.inf, tol=1e-10, max_iter=1000)\n"
_BRIER = "    return float(np.mean((p - y) ** 2))\n"
_REQ = "    require_calibration_split(samples)\n    rows, raw, y = _prepare(samples, now)\n"  # fit_platt + fit_temperature
_RET = "    return _build("  # fit_platt + fit_temperature
_SORT = "    rows = sorted(samples, key=_sort_key)\n"
_DIGEST = (
    '    if not version.endswith("-" + _version_digest(_numbers(params), params.fitted_on.data_sha256)):\n'
    '        raise ValueError("version: không khớp tham số")'
)
_A_POS = "    if a <= 0:"

LEAK = "test_cb1_leakage"
UNIT: list[Mutation] = [
    Mutation("M-6A-1 route_for: `<` → `<=`",
             [one(DM, _ROUTE, "    if x <= lo:  # MUTATION M-6A-1\n")],
             UT, ["test_dm2_route_for_boundaries"]),
    Mutation("M-6A-2 t_low_star đảo thành c_miss/c_review",
             [one(DM, _STAR, "    return c_miss / c_review  # MUTATION M-6A-2\n")],
             UT, ["test_dm1_t_low_star"]),
    Mutation("M-6A-3 CP hai phía (conf 0,975)",
             [one(DM, _CP, "    return float(beta.ppf(1 - (1 - c) / 2, int(k) + 1, int(n) - int(k)))  # MUTATION M-6A-3\n")],
             UT, ["test_dm5_clopper_pearson"]),
    Mutation("M-6A-4 ece bỏ làm tròn 9 chữ số",
             [one(DM, _ECE, "    k = np.minimum(np.floor(p * n_bins), n_bins - 1).astype(int)  # MUTATION M-6A-4\n")],
             UT, ["test_dm6_ece[bien-0.7-0.4]"]),
    Mutation("M-6A-5 hoà chọn t_low lớn nhất",
             [one(DM, _TIE, "    best = np.lexsort((_GRID[hi_idx], -_GRID[lo_idx], key_cost))[0]  # MUTATION M-6A-5\n")],
             UT, ["test_dm4_select_thresholds", "test_dm12_ties"]),
    Mutation("M-6A-6 LeakageError chỉ khi MỌI mẫu là test",
             [one(CAL, _LEAK, '    wrong = sum(1 for s in samples if s.split != "calibration")\n'
                              "    if wrong == len(samples):  # MUTATION M-6A-6\n")],
             UT, [f"{LEAK}[require-dau]", f"{LEAK}[require-giua]", f"{LEAK}[require-cuoi]",
                  f"{LEAK}[platt-giua]", f"{LEAK}[temperature-giua]"]),
    Mutation("M-6A-7 Platt có phạt mặc định (bỏ C=np.inf)",
             [one(CAL, _LR, "    model = LogisticRegression()  # MUTATION M-6A-7\n")],
             UT, ["test_cb3_platt_matches_reference"]),
    Mutation("M-6A-8 brier dùng trị tuyệt đối",
             [one(DM, _BRIER, "    return float(np.mean(np.abs(p - y)))  # MUTATION M-6A-8\n")],
             UT, ["test_dm7_brier[bon-diem]", "test_dm7_brier[nam-diem]"]),
    Mutation("M-6A-9 require_calibration_split gọi SAU khi fit",
             [(CAL, _REQ, "    rows, raw, y = _prepare(samples, now)\n", 2),
              (CAL, _RET, "    require_calibration_split(samples)  # MUTATION M-6A-9\n    return _build(", 2)],
             UT, ["test_cb1_no_fit_before_split_check[platt]", "test_cb1_no_fit_before_split_check[temperature]"]),
    Mutation("M-6A-10 bỏ bước sắp mẫu trước khi fit",
             [one(CAL, _SORT, "    rows = list(samples)  # MUTATION M-6A-10\n")],
             UT, ["test_cb5_order_invariant[platt]", "test_cb5_order_invariant[temperature]"]),
    # ---- Q-6A-4 = A (MẪU B bổ sung) ----
    Mutation("M-6A-11 load_calibrator bỏ bước so đuôi băm version",
             [one(CAL, _DIGEST, "    if False:  # MUTATION M-6A-11\n        raise ValueError(\"version: không khớp tham số\")")],
             UT, ["test_cb9a_hand_edited_digest_mismatch[b-am-50]", "test_cb9a_hand_edited_digest_mismatch[a-duong-x10]",
                  "test_cb9a_hand_edited_digest_mismatch[T-trong-mien]", "test_cb9a_hand_edited_digest_mismatch[sha-platt]"]),
    Mutation("M-6A-12 fit_platt bỏ chặn a ≤ 0",
             [one(CAL, _A_POS, "    if False:  # MUTATION M-6A-12")],
             UT, ["test_cb9e_fit_platt_rejects_inverted"]),
]  # fmt: skip


MUTATIONS = UNIT
if "--only" in sys.argv:
    at = sys.argv.index("--only") + 1
    prefix = sys.argv[at] if at < len(sys.argv) else ""
    MUTATIONS = [m for m in UNIT if m.name.startswith(prefix + " ")]


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
        print("DỪNG: không có đột biến nào khớp `--only` (mã: M-6A-1 … M-6A-12)")
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
