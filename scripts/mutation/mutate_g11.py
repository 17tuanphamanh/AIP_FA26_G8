"""Mutation chặng G11 (groundedness offline, `backend/app/eval/groundedness/`). Mỗi đột biến áp lên file thật, chạy
`backend/tests/unit/eval/test_groundedness_*.py`, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`):
file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_g11.py                   # cả 10 mã (unit backend, không Docker, không LLM thật)
  uv run python scripts/mutation/mutate_g11.py --only M-G11-6

Chuỗi gốc là CẢ DÒNG (kể cả "\n") để chữ MUTATION nằm cuối dòng — chèn giữa biểu thức thì file hỏng cú pháp.
Dự đoán test đỏ ghi theo TIỀN TỐ tên test (`test_counts` khớp `test_counts_and_rates_hand_computed`).
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
PKG = "backend/app/eval/groundedness/"
SPLIT, JUDGE, SCORING, REVIEW = (PKG + f for f in ("split.py", "judge.py", "scoring.py", "review.py"))
TESTS = "backend/tests/unit/eval"
CMD = ["uv", "run", "pytest", *(f"{TESTS}/test_groundedness_{n}.py" for n in ("split", "judge", "scoring", "review", "io", "cli")),
       "-q", "-p", "no:cacheprovider", "-W", "ignore"]  # fmt: skip


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    expect: list[str]  # tiền tố tên test PHẢI đỏ


def one(file: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (file, old, new, 1)


MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-G11-1 không bỏ khối 'Nguồn:' (dòng nguồn thành ý)",
             [one(SPLIT, "        if line.strip() == SOURCES_HEADER:\n", "        if False:  # MUTATION M-G11-1\n")],
             ["test_numbered_steps", "test_sources_block", "test_rendered_answer_round_trip"]),
    Mutation("M-G11-2 partial tính là hỗ trợ",
             [one(SCORING, '    n_supported = sum(c.verdict == "supported" for c in claims)\n',
                  '    n_supported = sum(c.verdict != "unsupported" for c in claims)  # MUTATION M-G11-2\n')],
             ["test_counts_and_rates", "test_partial_only_chunk"]),
    Mutation("M-G11-3 bỏ kiểm chunk_ids thuộc đoạn đã đưa cho người chấm",
             [one(JUDGE, "    if any(not set(v.chunk_ids) <= valid for v in out.verdicts):\n",
                  "    if False:  # MUTATION M-G11-3\n")],
             ["test_contract_violation"]),
    Mutation("M-G11-4 mọi đoạn được dẫn đều tính là chính xác",
             [one(SCORING, "    return sum(1 for c in answer.citations if c in supporting), len(answer.citations)\n",
                  "    return len(answer.citations), len(answer.citations)  # MUTATION M-G11-4\n")],
             ["test_citation_precision", "test_partial_only_chunk", "test_citation_not_in_chunks"]),
    Mutation("M-G11-5 ca không có trích dẫn bị loại khỏi mẫu số",
             [one(SCORING, '    judged = [a for a in answers if a.status == "judged"]\n',
                  '    judged = [a for a in answers if a.status == "judged" and "no_citation" not in a.flags]  # MUTATION M-G11-5\n')],
             ["test_counts_and_rates", "test_answers_without_pairs"]),
    Mutation("M-G11-6 mẫu bỏ qua seed",
             [one(REVIEW, "    rng = random.Random(seed)\n", "    rng = random.Random()  # MUTATION M-G11-6\n")],
             ["test_same_seed", "test_sample_is_blind"]),
    Mutation("M-G11-7 bản soát rò verdict của LLM",
             [one(REVIEW, '                "human_supported": None, "note": None,\n',
                  '                "human_supported": None, "note": None, "llm_verdict": claim.verdict,  # MUTATION M-G11-7\n')],
             ["test_review_sample_is_blind", "test_sample_is_blind"]),
    Mutation("M-G11-8 κ = tỉ lệ khớp (bỏ phần khớp ngẫu nhiên)",
             [one(REVIEW, "    return (po - pe) / (1 - pe), None\n", "    return po, None  # MUTATION M-G11-8\n")],
             ["test_agreement_hand_computed", "test_agree_end_to_end"]),
    Mutation("M-G11-9 nhãn người thiếu bị bỏ qua im lặng (coi như khớp LLM)",
             [one(REVIEW, "    if missing or extra:\n", "    if extra:  # MUTATION M-G11-9\n"),
              one(REVIEW, '        llm_pos, human_pos = verdict == "supported", labels[(sid, cid)]\n',
                  '        llm_pos, human_pos = verdict == "supported", labels.get((sid, cid), verdict == "supported")\n')],
             ["test_agreement_rejects"]),
    Mutation("M-G11-10 bootstrap rút lại ca thay vì họ",
             [one(SCORING, "        n0, d0 = support_units[a.family]\n", "        n0, d0 = support_units[a.scenario_id]  # MUTATION M-G11-10\n"),
              one(SCORING, "        support_units[a.family] = (n0 + s, d0 + len(a.claims))\n",
                  "        support_units[a.scenario_id] = (n0 + s, d0 + len(a.claims))\n")],
             ["test_single_family_bootstrap"]),
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
