"""Mutation chặng "nối thật mốc G" (G10 + G11): factory gateway, lượt eval, collector G11, collector G10, `probe-input`. Mỗi đột biến áp
lên file thật, chạy bộ test liên quan (unit và/hoặc Postgres), khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3
(`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_noi_that.py                  # mọi mã (cần Postgres cho các mã suite "pg")
  uv run python scripts/mutation/mutate_noi_that.py --only M-NT-5
  uv run python scripts/mutation/mutate_noi_that.py --suite unit     # chỉ các mã chạy được không cần Postgres

Suite "pg" = `backend/tests/integration/test_noi_that_pg.py` — dùng testcontainers (Docker). Không có Docker: đặt `MUTATE_PG_ARGS` (vd
`-p localpg`, kèm PYTHONPATH tới plugin thay `PostgresContainer` bằng Postgres cục bộ) — script chuyển nguyên cho pytest.
Chuỗi gốc là CẢ DÒNG (kể cả "\n") để chữ MUTATION nằm cuối dòng. Dự đoán test đỏ ghi theo TIỀN TỐ tên test.
"""

import hashlib
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import n3  # scripts/mutation/n3.py — cùng thư mục (sys.path[0] khi chạy script)

REPO = Path(__file__).resolve().parents[2]
EVAL = "backend/app/eval/"
FACTORY, DBREAD, COLLECT, PROB, PROBE, SCORING = (
    EVAL + f for f in ("llm_factory.py", "dbread.py", "groundedness/collect.py", "prob_collect.py", "groundedness/probe_input.py",
                       "groundedness/scoring.py")
)  # fmt: skip
UNIT = ["backend/tests/unit/eval/test_noi_that_unit.py", "backend/tests/unit/eval/test_groundedness_scoring.py"]
PG = ["backend/tests/integration/test_noi_that_pg.py"]
SUITES: dict[str, list[str]] = {
    "unit": ["uv", "run", "pytest", *UNIT, "-q", "-p", "no:cacheprovider", "-W", "ignore", "-o", "addopts="],
    "pg": ["uv", "run", "pytest", *shlex.split(os.environ.get("MUTATE_PG_ARGS", "")), *PG, "-q", "-p", "no:cacheprovider",
           "-W", "ignore", "-o", "addopts="],
}  # fmt: skip


class Mutation(NamedTuple):
    name: str
    suite: str  # "unit" | "pg"
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    expect: list[str]  # tiền tố tên test PHẢI đỏ


def one(file: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (file, old, new, 1)


MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-NT-1 cache của factory là `default` thay vì `eval`", "pg",
             [one(FACTORY, '        eval_settings = settings.model_copy(update={"llm_cache_mode": "eval"})\n',
                  '        eval_settings = settings.model_copy(update={"llm_cache_mode": "default"})  # MUTATION M-NT-1\n')],
             ["test_gateway_records_llm_call"]),
    Mutation("M-NT-2 factory chạy được khi không bật EVAL_MODE", "unit",
             [one(FACTORY, "    if not settings.eval_mode:\n", "    if False:  # MUTATION M-NT-2\n")],
             ["test_gateway_refuses_without_eval_mode"]),
    Mutation("M-NT-3 factory chạy được với backend scripted", "unit",
             [one(FACTORY, '    if settings.llm_backend != "real":\n', "    if False:  # MUTATION M-NT-3\n")],
             ["test_gateway_refuses_without_eval_mode"]),
    Mutation("M-NT-4 bỏ guard temperature = 0", "unit",
             [one(FACTORY, "    hot = [r for r in ROLES if setup.config.roles[r].temperature != 0]\n", "    hot: list[str] = []  # MUTATION M-NT-4\n")],
             ["test_gateway_refuses_nonzero_role_temperature"]),
    Mutation("M-NT-5 lượt eval có ended_at NULL (worker sẽ recover lượt này)", "pg",
             [one(FACTORY, "                \"VALUES (:u, :t, 'submit', :now, :now) ON CONFLICT DO NOTHING\"\n",
                  "                \"VALUES (:u, :t, 'submit', :now, NULL) ON CONFLICT DO NOTHING\"  # MUTATION M-NT-5\n")],
             ["test_eval_turn_is_idempotent_ended"]),
    Mutation("M-NT-6 ticket eval ghi lại mỗi lần (không idempotent)", "pg",
             [one(FACTORY, "                \"VALUES (:t, :u, 'employee', :r, :now, false) ON CONFLICT DO NOTHING\"\n",
                  "                \"VALUES (:t, :u, 'employee', :r, :now, false)\"  # MUTATION M-NT-6\n")],
             ["test_eval_turn_is_idempotent_ended"]),
    Mutation("M-NT-7 --max-usd không được áp", "pg",
             [one(FACTORY, "        if max_usd is not None:\n", "        if False:  # MUTATION M-NT-7\n")],
             ["test_run_cap_blocks"]),
    Mutation("M-NT-8 collector không ép phiên chỉ đọc", "pg",
             [one(DBREAD, '    engine = create_async_engine(settings.database_url, connect_args={"options": READ_ONLY_OPTION}, hide_parameters=True)  # F15\n',
                  "    engine = create_async_engine(settings.database_url, hide_parameters=True)  # MUTATION M-NT-8\n"),
              one(DBREAD, "        async with open_postgres_saver(read_only_url(settings.database_url), max_size=POOL_SIZE) as saver:\n",
                  "        async with open_postgres_saver(settings.database_url, max_size=POOL_SIZE) as saver:\n")],
             ["test_reader_sessions_are_read_only"]),
    Mutation("M-NT-9 family suy từ tiền tố scenario_id thay vì lấy từ đầu vào", "pg",
             [one(COLLECT, '        "scenario_id": q.scenario_id, "family": q.family, "answer": answer, "citations": citations,\n',
                  '        "scenario_id": q.scenario_id, "family": q.scenario_id.rsplit("-", 1)[0], "answer": answer,\n'
                  '        "citations": citations,  # MUTATION M-NT-9\n')],
             ["test_collect_builds_answers_row"]),
    Mutation("M-NT-10 parse khối bằng chứng mất chunk liền kề (chỉ giữ đoạn văn đầu)", "unit",
             [one(COLLECT, "        text_ = body[begin:] if last else body[begin : found[i + 1][0] - len(BLOCK_SEP)]\n",
                  '        text_ = (body[begin:] if last else body[begin : found[i + 1][0] - len(BLOCK_SEP)]).split("\\n\\n")[0]'
                  "  # MUTATION M-NT-10\n")],
             ["test_parse_evidence_keeps_adjacent_chunks"]),
    Mutation("M-NT-11 lấy lời gọi b10_answer ĐẦU thay vì cuối", "pg",
             [one(COLLECT, "    if not good or not good[-1][0]:\n", "    if not good or not good[0][0]:  # MUTATION M-NT-11\n"),
              one(COLLECT, "    blocks = parse_evidence(str(good[-1][0]), retrieved)\n", "    blocks = parse_evidence(str(good[0][0]), retrieved)\n")],
             ["test_collect_uses_the_last_successful"]),
    Mutation("M-NT-12 ca cannot_answer bị coi như ca có câu trả lời", "pg",
             [one(COLLECT, "        if event == CANNOT_EVENT:\n", "        if False:  # MUTATION M-NT-12\n")],
             ["test_collect_cannot_answer_and_skips"]),
    Mutation("M-NT-13 G10 bỏ qua ctx_flags khi dựng RiskContext", "pg",
             [one(PROB, '             "ctx_flags": state.get("ctx_flags") or {}}, created, hours,\n',
                  '             "ctx_flags": {}}, created, hours,  # MUTATION M-NT-13\n')],
             ["test_gather_target_is_other_comes_from_ctx_flags_alone"]),  # ca dựng-cùng-b12 còn có requested_for khác → vẫn True
    Mutation("M-NT-14 G10 đọc kb_gap ngược chiều", "pg",
             [one(PROB, '                             "raw_prob": r.raw_prob, "kb_gap": kb_gap == "true"})  # fmt: skip\n',
                  '                             "raw_prob": r.raw_prob, "kb_gap": kb_gap != "true"})  # MUTATION M-NT-14\n')],
             ["test_gather_builds_with_rows_and_cases", "test_collect_no_evidence_pipeline"]),
    Mutation("M-NT-15 probe-input: họ = phần tử CUỐI của expected_doc_ids", "unit",
             [one(PROBE, "            family = item.expected_doc_ids[0]\n", "            family = item.expected_doc_ids[-1]  # MUTATION M-NT-15\n")],
             ["test_probe_input_family_is_the_first"]),  # bộ thật: mỗi câu chỉ 1 tài liệu đáp án → đầu = cuối
    Mutation("M-NT-16 probe-input: gộp mọi câu âm tính vào MỘT họ", "unit",
             [one(PROBE, "            family, own_family = item.id, own_family + 1\n",
                  '            family, own_family = "khong-co-dap-an", own_family + 1  # MUTATION M-NT-16\n')],
             ["test_probe_input_on_the_real_retrieval_set", "test_probe_input_family_is_the_first"]),
    Mutation("M-NT-17 summary đếm số ca thay vì số họ", "unit",
             [one(SCORING, '        "n_families": len({a.family for a in judged}),  # số họ trong các ca được chấm = số đơn vị rút lại của bootstrap\n',
                  '        "n_families": len(judged),  # MUTATION M-NT-17\n')],
             ["test_counts_and_rates"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(sys.argv[sys.argv.index("--only") + 1])]
if "--suite" in sys.argv:
    MUTATIONS = [m for m in MUTATIONS if m.suite == sys.argv[sys.argv.index("--suite") + 1]]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(prefix: str, failed: list[str]) -> bool:
    return any(f.split("::")[-1].startswith(prefix) for f in failed)


def main() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    files = sorted({rel for m in MUTATIONS for rel, *_ in m.edits})
    stop = n3.guard(REPO, files, [SUITES[s] for s in sorted({m.suite for m in MUTATIONS})], env)  # N3: không dấu sót, mốc xanh
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
            out = subprocess.run(SUITES[m.suite], cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
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
