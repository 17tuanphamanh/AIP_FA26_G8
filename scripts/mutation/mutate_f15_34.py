"""Mutation F15 — Việc treo 34 (luật entropy trên token đã chứa mặt nạ), khuôn `mutate_t23a.py`. Mỗi đột biến áp lên file thật,
chạy bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` →
dừng; mốc xanh một lần trước khi đột biến. Chỉ đụng file của Việc treo 34 — chạy được khi chỉ có commit việc này.

  uv run python scripts/mutation/mutate_f15_34.py                  # cả 3 mã (unit, sandbox, không Docker)
  uv run python scripts/mutation/mutate_f15_34.py --only M-F15-34-2

Mỗi đột biến chạy TRỌN lệnh test (không chỉ test dự đoán); test đỏ ngoài dự đoán cũng tính là lệch.
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


PRIVACY = "backend/app/guard/privacy.py"
CMD = pt("backend/tests/unit/test_guard_privacy.py", "backend/tests/unit/test_output_guard.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ — và chỉ những test này


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


_OLD = "            if mask not in core and hit(core):  # logic trước F15, giữ nguyên: đã che thì dùng kết quả này\n"
_SPLIT = "            return mask.join(piece(p) for p in token.split(mask))\n"

A, E = "test_f15_a_random_tail_glued_to_mask_is_masked", "test_f15_e_two_random_pieces_around_mask"
OLD_ONLY = [  # bản chỉ-tách để lọt (soát F15 lần 1–2); logic cũ che được
    "test_f15_g_tail_after_mask_starting_with_slash_masked",
    "test_f15_h_short_tail_after_mask_masked",
    "test_f15_i_short_head_before_mask_masked",
    "test_f15_j_short_head_ending_with_field_separator_masked",
    "test_f15_k_short_piece_between_two_masks_masked",
    "test_f15_l_output_guard_blocks_head_glued_to_mask",
    "test_f15_never_weaker_than_old[fixtures]",
    "test_f15_never_weaker_than_old[random]",
]

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-F15-34-1 bỏ nhánh tách (chỉ còn logic cũ)",
             [one(PRIVACY, _SPLIT, "            return token  # MUTATION M-F15-34-1\n")], CMD, [A, E]),
    Mutation("M-F15-34-2 bỏ nhánh cũ (chỉ còn tách)",
             [one(PRIVACY, _OLD, "            if False:  # MUTATION M-F15-34-2\n")], CMD, OLD_ONLY),
    Mutation("M-F15-34-3 nhánh tách bỏ qua mảnh cuối",
             [one(PRIVACY, _SPLIT, "            return mask.join([*map(piece, token.split(mask)[:-1]), token.split(mask)[-1]])"
                                   "  # MUTATION M-F15-34-3\n")],
             CMD, [A, E]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    wanted = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.split()[0] in wanted]


def test_env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(test: str, failed: list[str]) -> bool:
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
        extra = [f for f in failed if not any(_hit(e, [f]) for e in m.expect)]
        status = "ĐỎ đúng dự đoán" if not (missing or extra or errors) else ("ĐỎ (lệch dự đoán)" if failed else "SỐNG")
        bad += bool(missing or extra or errors)
        print(f"{m.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing or extra:
            print(f"    thiếu test dự đoán: {missing}; đỏ ngoài dự đoán: {extra}")
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
