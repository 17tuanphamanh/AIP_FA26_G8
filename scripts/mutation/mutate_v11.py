"""Mutation tay hợp đồng `predictions.jsonl` v1.1 (P8 v1.4 §5.6; plan v1.1 mục Mutation). Khung giống `mutate_g2.py`: mỗi đột biến áp
lên file thật, chạy test eval, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau.

File riêng (không mở rộng `mutate_g2.py`): `mutate_g2.py` thuộc PR #58 chưa gộp — PR v1.1 xếp chồng không sửa nó.

Chốt N3 VIẾT LẠI ở đây, KHÔNG import `n3.py` (file đó nằm trong danh sách chặn đọc tới 25/10 — import = chạy code của file bị chặn):
(a) file đích còn chữ `MUTATION` → dừng; (b) mốc xanh một lần trước khi đột biến; (c) sau khi chạy: md5 khớp, `git diff --stat` khớp,
không file đích nào còn chữ `MUTATION`.

  uv run python scripts/mutation/mutate_v11.py
  uv run python scripts/mutation/mutate_v11.py --only M-V11-5

Chỉ unit (stack giả, không Docker, không DB). Không đọc `.env`.
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


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, "-q", "-p", "no:cacheprovider"]


PRED = "backend/app/eval/predictions.py"
COL = "backend/app/eval/collect.py"
RUN = "backend/app/eval/runner.py"
UT = pt("backend/tests/unit/eval")


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


# ---- predictions.py ---------------------------------------------------------------------------------------------------

_VERSION = "    schema_version: SchemaVersion\n"
_IS_V1 = "            if _is_v1(e):\n"
_FOLD = "Fold = Annotated[int, Field(ge=1, le=CV_K)]\n"
_PARTIAL = "    if any(folded) and not all(folded):\n"
_FAMILY = "        if r.fold is not None and fold_of.setdefault(r.family, r.fold) != r.fold:\n"
_RISK = '_RISK_FIELDS = ("decided_by", "raw_prob", "calibrated_prob", "p_method", "kb_gap")  # trường điểm log 4 (kb_gap: P8 §0.1)\n'
_TZ = "    if t.tzinfo is None:\n"

# ---- collect.py / runner.py -------------------------------------------------------------------------------------------

_STARTED = "            record = collect(c.sql, s, ticket_id, c.meta, started_at=started)\n"
_NULLS = "        **dict.fromkeys(UNAVAILABLE),\n"
_MANIFEST = '        "predictions_unavailable": list(UNAVAILABLE),\n'

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-V11-1 schema_version nhận mọi chuỗi",
             [_swap(PRED, _VERSION, "    schema_version: str", "M-V11-1")], UT,
             ["test_schema_version_exact", "test_load_bad_schema_version_not_called_v1"]),
    Mutation("M-V11-2 file v1 báo lỗi thường (không nói bản v1)",
             [_off(PRED, _IS_V1, "M-V11-2")], UT, ["test_load_v1_file_rejected", "test_load_v1_first_line_rejected"]),
    Mutation("M-V11-3 fold nhận 0",
             [_swap(PRED, _FOLD, _FOLD.replace("ge=1", "ge=0"), "M-V11-3")], UT, ["test_fold_bounds[0-False]"]),
    Mutation("M-V11-4 fold nhận 6",
             [_swap(PRED, _FOLD, _FOLD.replace("le=CV_K", "le=6"), "M-V11-4")], UT, ["test_fold_bounds[6-False]"]),
    Mutation("M-V11-5 bỏ kiểm một họ một phần",
             [_off(PRED, _FAMILY, "M-V11-5")], UT, ["test_load_rejects_family_in_two_folds"]),
    Mutation("M-V11-6 bỏ kiểm fold gán dở",
             [_off(PRED, _PARTIAL, "M-V11-6")], UT, ["test_load_rejects_partial_folds"]),
    Mutation("M-V11-7 kb_gap ngoài bất biến route None",
             [_swap(PRED, _RISK, _RISK.replace(', "kb_gap")', ")"), "M-V11-7")], UT,
             ["test_route_none_requires_null_risk_fields[kb_gap]"]),
    Mutation("M-V11-8 run_started_at nhận giờ không múi giờ",
             [_off(PRED, _TZ, "M-V11-8")], UT,
             ["test_run_started_at_rejected[2026-10-19T10:00:00]", "test_run_started_at_rejected[2026-10-19]"]),
    Mutation("M-V11-9 run_started_at = giờ thu bản ghi (không phải giờ bắt đầu ca)",
             [_swap(RUN, _STARTED, _STARTED.replace("started_at=started)", "started_at=c.now().isoformat())"), "M-V11-9")], UT,
             ["test_run_started_at_per_case"]),
    Mutation("M-V11-10 trường chưa có nguồn ghi False giả",
             [_swap(COL, _NULLS, "        **dict.fromkeys(UNAVAILABLE, False),", "M-V11-10")], UT,
             ["test_collect_v11_unavailable_null", "test_collect_full_record", "test_v11_unavailable_fields_null"]),
    Mutation("M-V11-11 manifest bỏ predictions_unavailable",
             [_swap(RUN, _MANIFEST, "", "M-V11-11")], UT, ["test_manifest_v11", "test_manifest_keys"]),
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
    """N3 (viết lại, không import n3): (a) không file đích nào còn dấu `MUTATION`; (b) mốc xanh một lần."""
    left = marked(files)
    if left:
        print(f"DỪNG (N3a): file đích còn chữ {MARK!r} {left} — khôi phục tay trước")
        return 2
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
    if not MUTATIONS:
        print(f"DỪNG: không có đột biến nào khớp `--only` (mã: M-V11-1 … M-V11-{len(MUTATIONS_ALL)})")
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
