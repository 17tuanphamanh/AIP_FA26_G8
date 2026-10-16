"""Mutation tay chặng 6D (phase6 mục 7.4) — 1 lượt, M-6D-1…6. Khuôn `mutate_6a.py`: mỗi đột biến áp lên file thật, chạy lệnh test,
khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau (file 6D còn untracked thì chỉ md5 có tác dụng). Luật N3 (`n3.py`): file
đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_6d.py                  # M-6D-1…5 (unit, hàm thuần — chạy được trong sandbox)
  uv run python scripts/mutation/mutate_6d.py --integration    # M-6D-6 (r11, Postgres testcontainers — ngoài sandbox, không compose)
  uv run python scripts/mutation/mutate_6d.py --only M-6D-3

`--integration` như `make test`: có socket colima thì đặt `DOCKER_HOST` + `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE` (khuôn `mutate_4d.py`).
Không đọc `.env`.
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


MR = "backend/app/audit/m5_review.py"
UT = pt("backend/tests/unit/test_m5_review.py")
IT = pt("backend/tests/integration/test_m5_review_pg.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_SHARE = '        recommend = "sampling_k5" if share > threshold else "self_report"\n'
_DEDUP = "        if p.reason in seen:\n"
_OUT_FN = '    return [p.reason or "" for p in pick(rows, n=n, seed=seed, min_llm=min_llm)]\n'
_OUT_SHELL = "    lines = [f\"{i}. {_one_line(p.reason or '')}\" for i, p in enumerate(picked, 1)]\n"
_WARN = '    if llm_backend != "real":\n        lines.append('
_ROUND = "    levels = Counter(round(v, 2) for v in _checked(values))\n"
_ENGINE = "    return readonly_engine(dsn)\n"

R7 = "test_r7_exactly_60_percent_is_self_report"
UNIT: list[Mutation] = [
    Mutation("M-6D-1 share >= threshold",
             [one(MR, _SHARE, '        recommend = "sampling_k5" if share >= threshold else "self_report"  # MUTATION M-6D-1\n')],
             UT, [f"{R7}[20]", f"{R7}[30]"]),
    Mutation("M-6D-2 bỏ bỏ-trùng reason",
             [one(MR, _DEDUP, "        if False:  # MUTATION M-6D-2\n")],
             UT, ["test_r2_dedup_verbatim_reason", "test_r2_dedup_keeps_first_row"]),
    Mutation("M-6D-3 đầu ra kèm route (hàm + vỏ)",
             [one(MR, _OUT_FN, '    return [f"{p.reason} [{p.route}]" for p in pick(rows, n=n, seed=seed, min_llm=min_llm)]  # MUTATION M-6D-3\n'),
              one(MR, _OUT_SHELL, "    lines = [f\"{i}. {_one_line(p.reason or '')} [{p.route}]\" for i, p in enumerate(picked, 1)]  # MUTATION M-6D-3\n")],
             UT, ["test_r5_function_output_has_no_field_canary", "test_r5_shell_stdout_has_no_field_canary"]),
    Mutation("M-6D-4 bỏ cảnh báo ScriptedLLM",
             [one(MR, _WARN, "    if False:  # MUTATION M-6D-4\n        lines.append(")],
             UT, ["test_r10_scripted_warns_first_line_exit_3", "test_r10_none_backend_warns_exit_3"]),
    Mutation("M-6D-5 bỏ làm tròn 2 chữ số",
             [one(MR, _ROUND, "    levels = Counter(v for v in _checked(values))  # MUTATION M-6D-5\n")],
             UT, ["test_r8_rounding_to_two_digits"]),
]  # fmt: skip
INTEGRATION: list[Mutation] = [
    Mutation("M-6D-6 engine không READ ONLY",
             [one(MR, _ENGINE, "    from sqlalchemy.ext.asyncio import create_async_engine  # MUTATION M-6D-6\n\n"
                               "    return create_async_engine(dsn)\n")],
             IT, ["test_r11_open_engine_refuses_insert"]),
]  # fmt: skip


MUTATIONS = INTEGRATION if "--integration" in sys.argv else UNIT
if "--only" in sys.argv:
    at = sys.argv.index("--only") + 1
    prefix = sys.argv[at] if at < len(sys.argv) else ""
    MUTATIONS = [m for m in UNIT + INTEGRATION if m.name.startswith(prefix + " ")]


def test_env() -> dict[str, str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    colima = Path.home() / ".colima/default/docker.sock"
    if colima.exists():  # như Makefile: testcontainers qua colima
        env.setdefault("DOCKER_HOST", f"unix://{colima}")
        env.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")
    desktop_bin = Path("/Applications/Docker.app/Contents/Resources/bin")
    if (desktop_bin / "docker-credential-desktop").exists():
        env["PATH"] = f"{desktop_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


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
        print("DỪNG: không có đột biến nào khớp `--only` (mã: M-6D-1 … M-6D-6)")
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
