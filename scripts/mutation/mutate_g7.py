"""Mutation tay G7 — khung giờ `at` + `skipped_hours` + `--resume` (`schedule.py`, phần G7 của `runner.py`; plan G7 mục 5). Khung
giống `mutate_g1.py`: mỗi đột biến áp lên file thật, chạy test eval, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau.

Chốt N3 VIẾT LẠI ở đây, KHÔNG import `n3.py` (file đó nằm trong danh sách chặn đọc tới 25/10 — import = chạy code của file bị chặn):
(a) file đích còn chữ `MUTATION` → dừng; (b) mốc xanh một lần trước khi đột biến; (c) sau khi chạy: md5 khớp, `git diff --stat` khớp,
không file đích nào còn chữ `MUTATION`; (d) chuỗi gốc của đột biến cũ (`mutate_t29.py`, `mutate_g2.py`, `mutate_v11.py`,
`mutate_g1.py`) và của file này vẫn xuất hiện ĐÚNG 1 lần trong `runner.py` / `schedule.py` nếu có xuất hiện — đọc VĂN BẢN script
bằng `ast` (không import → không chạy n3.py).

  uv run python scripts/mutation/mutate_g7.py
  uv run python scripts/mutation/mutate_g7.py --only M-G7-7
  uv run python scripts/mutation/mutate_g7.py --check-old    # chỉ chạy N3d

Chỉ unit (dữ liệu tổng hợp, policy giả tự dựng trong test, không Docker, không DB). Không đọc `.env`, không đọc file policy nào.
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


SCH = "backend/app/eval/schedule.py"
RUN = "backend/app/eval/runner.py"
TARGETS = (SCH, RUN)
UT = pt("backend/tests/unit/eval")
OLD_SCRIPTS = ("mutate_t29.py", "mutate_g2.py", "mutate_v11.py", "mutate_g1.py", "mutate_g7.py")


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


# ---- schedule.py --------------------------------------------------------------------------------------------------------

_BUF = "BUFFER = timedelta(minutes=10)\n"
_BOUND = "    if before != now_in or now_in != after:\n"
_MISMATCH = "    if now_in != at_in:\n"
_SKIP_BIEN = '        return HoursCheck(at_in=at_in, now_in=now_in, hours_class="bien_gio", skip="bien_gio")\n'
_SKIP_LECH = '        return HoursCheck(at_in=at_in, now_in=now_in, hours_class=cls, skip="lech_loai_gio")\n'
_SCRIPT = '''    "print(json.dumps({'in_hours': [within_business_hours(datetime.fromisoformat(a), h) for a in sys.argv[1:]]}))\\n"\n'''
_NAIVE = "    if t.tzinfo is None or t.utcoffset() is None:\n"
_PROBE_T = "    return (at, now - buffer, now, now + buffer)\n"
_PROBE_N = "    if not isinstance(v, list) or len(v) != n or not all(isinstance(x, bool) for x in v):\n"
_PENDING = "    return [sid for sid, outcome in last.items() if outcome == SKIPPED]\n"
_MERGE_KEYS = '    return {k: v if k in ("loaded", SKIPPED) else prior.get(k, 0) + v for k, v in now.items()}\n'

# ---- runner.py (phần G7) ------------------------------------------------------------------------------------------------

_OUTCOMES = 'OUTCOMES: tuple[Outcome, ...] = ("done", "timeout", "multi_leaf", "error", "skipped_hours")\n'
_CO_AT = "    if n := schedule.bad_at([s.at for s in ds.scenarios]):  # G7-Q6: chỉ số đếm, không giá trị\n"
_RUN_AT = "    if schedule.bad_at([s.at for s in ds.scenarios]):\n"
_OUT_BOTH = "    if args.out is not None:\n"
_NORERUN = "        schedule.check_no_rerun(ids, prior.outcomes, {r.scenario_id for r in prior.records})\n"
_NOTHING = "    if not todo:\n"
_RUNID = '    if prior is not None and prior.manifest["run_id"] != run_id:  # G7: giữ run_id = cùng cấu hình + dữ liệu + commit\n'
_LONG = "    if args.timeout_s > schedule.LONG_TIMEOUT_S:  # G7-Q3\n"
_GATE = "            case = run_case(s, ctx) if chk.skip is None else Case(\n"
_PC_REASON = ('                + (f" {case.error_type or case.skip_reason}" if case.error_type or case.skip_reason else ""))'
              "  # fmt: skip\n")  # fmt: skip
_PASSES = ('    passes = [*(prior.manifest["passes"] if prior else ()), schedule.pass_entry(pass_no, started_at.isoformat(), '
           "finished_at, checks)]\n")  # fmt: skip
_MERGE = '        counts, records = schedule.merge_counts(prior.manifest["counts"], counts), [*prior.records, *records]\n'
_PRIOR_LINES = '    (out_dir / "outcomes.jsonl").write_text("".join(prior_lines) + "".join(json.dumps({\n'
_IBH = ('        "in_business_hours": c.in_business_hours, "hours_class": c.hours_class, "skip_reason": c.skip_reason, '
        '"pass": pass_no,\n')  # fmt: skip
_SUM_SKIP = "        f\"skipped_hours={counts['skipped_hours']}\")  # fmt: skip\n"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-G7-1 decide bỏ kiểm biên",
             [_off(SCH, _BOUND, "M-G7-1")], UT,
             ["test_start_boundary", "test_end_boundary", "test_friday_end_monday_start", "test_runner_boundary_no_ticket"]),
    Mutation("M-G7-2 decide bỏ kiểm lệch loại giờ",
             [_off(SCH, _MISMATCH, "M-G7-2")], UT,
             ["test_mismatch_skipped", "test_weekend_is_out", "test_runner_mixed", "test_resume_runs_only_skipped"]),
    Mutation("M-G7-3 bỏ mẫu now+10 (chỉ bắt biên phía sau)",
             [_swap(SCH, _BOUND, "    if before != now_in:", "M-G7-3")], UT,
             ["test_start_boundary[now1-bien_gio]", "test_end_boundary[now1-bien_gio]"]),
    Mutation("M-G7-4 bỏ mẫu now−10 (chỉ bắt biên phía trước)",
             [_swap(SCH, _BOUND, "    if now_in != after:", "M-G7-4")], UT,
             ["test_start_boundary[now3-bien_gio]", "test_end_boundary[now3-bien_gio]"]),
    Mutation("M-G7-5 vùng đệm 5 phút",
             [_swap(SCH, _BUF, "BUFFER = timedelta(minutes=5)", "M-G7-5")], UT,
             ["test_start_boundary[now1-bien_gio]", "test_start_boundary[now3-bien_gio]", "test_end_boundary[now1-bien_gio]",
              "test_end_boundary[now3-bien_gio]", "test_probe_times_buffer"]),
    Mutation("M-G7-6 đảo hai lý do bỏ qua",
             [_swap(SCH, _SKIP_BIEN, _SKIP_BIEN.replace('skip="bien_gio"', 'skip="lech_loai_gio"'), "M-G7-6"),
              _swap(SCH, _SKIP_LECH, _SKIP_LECH.replace('skip="lech_loai_gio"', 'skip="bien_gio"'), "M-G7-6")], UT,
             ["test_mismatch_skipped", "test_start_boundary", "test_runner_boundary_no_ticket"]),
    Mutation("M-G7-7 HOURS_SCRIPT trả True cố định (không gọi within_business_hours)",
             [_swap(SCH, _SCRIPT, _SCRIPT.replace("within_business_hours(datetime.fromisoformat(a), h)", "True"), "M-G7-7")], UT,
             ["test_hours_script_uses_backend_function_and_policy"]),
    Mutation("M-G7-8 parse_at nhận datetime naive",
             [_off(SCH, _NAIVE, "M-G7-8")], UT,
             ["test_parse_at_rejects[2026-10-20T09:00:00]", "test_bad_at_counts", "test_check_only_counts_bad_at"]),
    Mutation("M-G7-9 probe hỏi now thay at",
             [_swap(SCH, _PROBE_T, "    return (now, now - buffer, now, now + buffer)", "M-G7-9")], UT,
             ["test_probe_times_buffer", "test_mismatch_skipped", "test_runner_mixed"]),
    Mutation("M-G7-10 parse_probe không kiểm số phần tử",
             [_swap(SCH, _PROBE_N, _PROBE_N.replace("len(v) != n or ", ""), "M-G7-10")], UT,
             ["test_parse_probe_bad"]),
    Mutation("M-G7-11 resume chọn mọi ca (không chỉ skipped_hours)",
             [_swap(SCH, _PENDING, "    return list(last)", "M-G7-11")], UT,
             ["test_pending_latest_outcome", "test_resume_runs_only_skipped"]),
    Mutation("M-G7-12 merge_counts cộng dồn cả skipped_hours",
             [_swap(SCH, _MERGE_KEYS, _MERGE_KEYS.replace('("loaded", SKIPPED)', '("loaded",)'), "M-G7-12")], UT,
             ["test_merge_counts", "test_resume_passes_manifest"]),
    Mutation("M-G7-13 OUTCOMES bỏ skipped_hours",
             [_swap(RUN, _OUTCOMES, 'OUTCOMES: tuple[Outcome, ...] = ("done", "timeout", "multi_leaf", "error")', "M-G7-13")], UT,
             ["test_runner_mixed", "test_manifest_keys"]),
    Mutation("M-G7-14 runner bỏ cổng giờ (luôn chạy run_case)",
             [_swap(RUN, _GATE, "            case = run_case(s, ctx) if True else Case(", "M-G7-14")], UT,
             ["test_runner_mixed", "test_runner_boundary_no_ticket"]),
    Mutation("M-G7-15 --check-only bỏ kiểm at",
             [_swap(RUN, _CO_AT, "    if n := 0:", "M-G7-15")], UT, ["test_check_only_counts_bad_at"]),
    Mutation("M-G7-16 lượt chạy bỏ kiểm at trước khi gọi stack",
             [_off(RUN, _RUN_AT, "M-G7-16")], UT, ["test_bad_at_stops_before_stack"]),
    Mutation("M-G7-17 --resume nhận kèm --out",
             [_off(RUN, _OUT_BOTH, "M-G7-17")], UT, ["test_resume_with_out_rejected"]),
    Mutation("M-G7-18 bỏ check_no_rerun",
             [_swap(RUN, _NORERUN, "        pass", "M-G7-18")], UT, ["test_resume_no_duplicate"]),
    Mutation("M-G7-19 resume không còn ca vẫn chạy + ghi",
             [_off(RUN, _NOTHING, "M-G7-19")], UT, ["test_resume_nothing_pending"]),
    Mutation("M-G7-20 resume không so run_id với manifest",
             [_off(RUN, _RUNID, "M-G7-20")], UT, ["test_resume_run_id_changed_stops"]),
    Mutation("M-G7-21 bỏ cảnh báo timeout_s > 600",
             [_off(RUN, _LONG, "M-G7-21")], UT, ["test_long_timeout_warns"]),
    Mutation("M-G7-22 --per-case không in lý do bỏ qua",
             [_swap(RUN, _PC_REASON, '                + (f" {case.error_type}" if case.error_type else ""))', "M-G7-22")], UT,
             ["test_per_case_skip_reason"]),
    Mutation("M-G7-23 manifest.passes chỉ giữ lần cuối",
             [_swap(RUN, _PASSES, _PASSES.replace('*(prior.manifest["passes"] if prior else ()), ', ""), "M-G7-23")], UT,
             ["test_resume_passes_manifest", "test_resume_still_skipped_then_again"]),
    Mutation("M-G7-24 resume không gộp counts (chỉ số của lần này)",
             [_swap(RUN, _MERGE, '        counts, records = counts, [*prior.records, *records]', "M-G7-24")], UT,
             ["test_resume_passes_manifest"]),
    Mutation("M-G7-25 resume bỏ predictions cũ",
             [_swap(RUN, _MERGE, '        counts, records = schedule.merge_counts(prior.manifest["counts"], counts), records',
                    "M-G7-25")], UT,
             ["test_resume_runs_only_skipped"]),
    Mutation("M-G7-26 resume ghi đè outcomes (mất dòng cũ)",
             [_swap(RUN, _PRIOR_LINES, _PRIOR_LINES.replace('"".join(prior_lines) + ', ""), "M-G7-26")], UT,
             ["test_resume_runs_only_skipped", "test_resume_still_skipped_then_again"]),
    Mutation("M-G7-27 outcomes in_business_hours = null",
             [_swap(RUN, _IBH, _IBH.replace('"in_business_hours": c.in_business_hours', '"in_business_hours": None'), "M-G7-27")],
             UT, ["test_runner_mixed", "test_runner_out_hours_runs_out_scenarios"]),
    Mutation("M-G7-28 dòng outcomes: không in skipped_hours",
             [_swap(RUN, _SUM_SKIP, '        f"")', "M-G7-28")], UT,
             ["test_runner_mixed", "test_default_output_aggregate_only"]),
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
    """N3d: chuỗi của các script đột biến có mặt trong file đích G7 thì phải đúng 1 lần (mọi edit dùng `one`)."""
    bad: list[str] = []
    for rel in TARGETS:
        text = (REPO / rel).read_text(encoding="utf-8")
        for name in OLD_SCRIPTS:
            for s in sorted(_line_strings(REPO / "scripts/mutation" / name)):
                if text.count(s) > 1:
                    bad.append(f"{name} → {rel}: {s.strip()[:60]!r} ×{text.count(s)}")
    return bad


def guard(files: list[str], cmds: list[list[str]], env: dict[str, str]) -> int | None:
    """N3 (viết lại, không import n3): (a) không file đích nào còn dấu `MUTATION`; (d) chuỗi gốc cũ đúng 1 lần; (b) mốc xanh."""
    left = marked(files)
    if left:
        print(f"DỪNG (N3a): file đích còn chữ {MARK!r} {left} — khôi phục tay trước")
        return 2
    dup = check_old()
    if dup:
        print("DỪNG (N3d): chuỗi gốc đột biến xuất hiện > 1 lần:")
        print("    " + "\n    ".join(dup))
        return 2
    print(f"N3d: chuỗi gốc của {', '.join(OLD_SCRIPTS)} — không chuỗi nào lặp trong {', '.join(TARGETS)}")
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
        texts = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in TARGETS}
        present = {s for name in OLD_SCRIPTS for s in _line_strings(REPO / "scripts/mutation" / name)
                   if any(s in t for t in texts.values())}  # fmt: skip
        print(f"N3d: {n} hằng chuỗi nhiều dòng trong {len(OLD_SCRIPTS)} script; {len(present)} có mặt trong {', '.join(TARGETS)}")
        for d in dup:
            print(f"    LẶP {d}")
        print("N3d: ĐẠT" if not dup else "N3d: KHÔNG ĐẠT")
        return 1 if dup else 0
    if not MUTATIONS:
        print(f"DỪNG: không có đột biến nào khớp `--only` (mã: M-G7-1 … M-G7-{len(MUTATIONS_ALL)})")
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
