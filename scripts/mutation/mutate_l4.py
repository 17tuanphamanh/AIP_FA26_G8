"""Mutation L4 (phase4:739, ĐP 24/10) — lỗi tạm khi đọc alias ghi `error_stage="alias"`, không phải "search". Đột biến áp lên
file thật, chạy bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ
`MUTATION` → dừng; mốc xanh một lần cho mỗi lệnh test trước khi đột biến.

  uv run python scripts/mutation/mutate_l4.py

M-L4-1 trả lại "search" ở nhánh `_Transient` của `alias_target` (retriever `_pinned`) → PHẢI đỏ đúng 2 test: c13 (Retriever tới
Qdrant sai cổng) và test chuỗi SpyIndex → Retriever → B8 → audit.check. Test lỗi bước search THẬT không được đỏ.
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


RETRIEVER = "backend/app/rag/retriever.py"

BE = pt("backend/tests/unit/test_rag_retriever.py", "backend/tests/unit/test_b08_retrieve.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ — và CHỈ các test này
    exact: bool = True


_ALIAS_TRANSIENT = '                raise RetrievalSystemError("alias", retries.total, detail=str(e)) from e\n'
_BACK_TO_SEARCH = (
    '                raise RetrievalSystemError("search", retries.total, detail=str(e)) from e'
    "  # MUTATION M-L4-1\n"
)

MUTATIONS: list[Mutation] = [
    Mutation("M-L4-1 lỗi tạm đọc alias trả lại stage \"search\"",
             [(RETRIEVER, _ALIAS_TRANSIENT, _BACK_TO_SEARCH, 1)],
             BE, ["test_c13_unreachable_qdrant_gives_alias_stage_with_two_retries",
                  "test_alias_transient_error_chain_logs_alias_stage_and_passes_audit_check"]),
]  # fmt: skip


def test_env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


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
        names = {f.rsplit("::", 1)[-1] for f in failed}
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in m.expect if e not in names]
        extra = sorted(names - set(m.expect)) if m.exact else []
        status = "ĐỎ đúng dự đoán" if not missing and not extra else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        bad += bool(missing or extra)
        print(f"{m.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing}")
        if extra:
            print(f"    test đỏ ngoài dự đoán: {extra}")
        if missing or extra:
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
