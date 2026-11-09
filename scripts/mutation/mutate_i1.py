"""Mutation chặng I1 (trang Trạng thái LLM chỉ đọc, `backend/app/api/llm_status.py`). Mỗi đột biến áp lên file thật, chạy
`backend/tests/unit/test_llm_status_api.py`, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`):
file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_i1.py                    # cả 3 mã (unit backend, không Docker, không LLM)
  uv run python scripts/mutation/mutate_i1.py --only M-I1-2

Dự đoán test đỏ ghi theo TIỀN TỐ tên test (`test_other_roles` khớp `test_other_roles_403`).
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
API = "backend/app/api/llm_status.py"
CMD = ["uv", "run", "pytest", "backend/tests/unit/test_llm_status_api.py", "-q", "-p", "no:cacheprovider"]


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    expect: list[str]  # tiền tố tên test PHẢI đỏ


def one(old: str, new: str, times: int = 1) -> tuple[str, str, str, int]:
    return (API, old, new, times)


# Chuỗi gốc là CẢ DÒNG (kể cả "\n") để chữ MUTATION nằm cuối dòng — chèn giữa biểu thức thì file hỏng cú pháp.
_PERM = '    request: Request, _: Annotated[Principal, Depends(require("llm_status:read"))]\n'
_OVER = '    status: SpendState = "over" if total >= cap else "warn" if total >= cap * warn_ratio else "ok"\n'
_WARN = "        spend=_spend(usage.spent_usd, cfg.spend.cap_usd, cfg.spend.warn_ratio), usage=_usage(usage),\n"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-I1-1 route chỉ cần đăng nhập (mất quyền llm_status:read)",
             [one(_PERM, "    request: Request, _: Annotated[Principal, Depends(require())]  # MUTATION M-I1-1\n")],
             ["test_other_roles", "test_route_marker"]),
    Mutation("M-I1-2 đúng trần chi vẫn chưa `over` (>= thành >)",
             [one(_OVER, '    status: SpendState = "over" if total > cap else "warn" if total >= cap * warn_ratio else "ok"  # MUTATION M-I1-2\n')],
             ["test_spend_status_boundaries", "test_warn_ratio_comes_from_config"]),
    Mutation("M-I1-3 ngưỡng cảnh báo cứng 0,8 thay vì warn_ratio của cấu hình",
             [one(_WARN, "        spend=_spend(usage.spent_usd, cfg.spend.cap_usd, 0.8), usage=_usage(usage),  # MUTATION M-I1-3\n")],
             ["test_warn_ratio_comes_from_config"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix)]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(prefix: str, failed: list[str]) -> bool:
    return any(f.split("::")[-1].startswith(prefix) for f in failed)


def main() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    files = sorted({rel for m in MUTATIONS for rel, *_ in m.edits})
    stop = n3.guard(REPO, files, [CMD], env)  # N3: không dấu sót, mốc xanh
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
        wrong = []
        for rel, old, new, n in m.edits:
            if mutated[rel].count(old) != n:
                wrong.append(f"{rel}: {mutated[rel].count(old)}/{n}")
            mutated[rel] = mutated[rel].replace(old, new)
        if wrong:
            print(f"!! {m.name}: chuỗi gốc không khớp số lần {wrong} — bỏ qua")
            bad += 1
            continue
        unmarked = [rel for rel, text in mutated.items() if n3.MARK not in text]
        if unmarked:
            print(f"!! {m.name}: file đột biến thiếu chữ {n3.MARK!r} {unmarked} — bỏ qua (N3a không bắt được nếu bị giết)")
            bad += 1
            continue
        try:
            for rel, text in mutated.items():
                (REPO / rel).write_text(text, encoding="utf-8")
            out = subprocess.run(CMD, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
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
