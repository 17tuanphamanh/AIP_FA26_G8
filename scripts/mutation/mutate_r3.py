"""Mutation chặng R3 (`TicketView.deadline`) — khuôn `mutate_t23a.py`. Mỗi đột biến áp lên file thật, chạy bộ test, khôi phục trong
`finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần cho mỗi lệnh
test trước khi đột biến.

  uv run python scripts/mutation/mutate_r3.py                 # M-R3-1, 2, 3a (unit, không Docker)
  uv run python scripts/mutation/mutate_r3.py --pg            # thêm M-R3-3b: SQL bỏ lọc pending — CHỈ chạy test_approval_store_pg.py
  uv run python scripts/mutation/mutate_r3.py --only M-R3-3a

M-R3-1/2 chỉ bị giết bởi ca ĐẶT TAY r9a/r9b: ở luồng thật ticket đã kết thúc / ticket cha không bao giờ có `waiting_for` tra hạn (guard
phòng thủ theo hợp đồng). Unit chạy `MemoryApprovals` nên lọc `pending` của SQL (M-R3-3b) chỉ test PG bắt được — mặc định tắt (cần Docker).
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


ROUTE = "backend/app/api/tickets.py"
FAKE = "backend/tests/fakes/graph.py"
STORE = "backend/app/approval/store.py"
UNIT = pt("backend/tests/unit/test_ticket_deadline.py", "backend/tests/unit/test_tickets_api.py")
PG = pt("backend/tests/integration/test_approval_store_pg.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_GUARD = '    if row.final_state is None and not row.is_parent and waiting_for in ("approval", "clarify", "confirm"):  # R3\n'
_FAKE_PENDING = (
    '            pending = [a for a in self._table.values() if a["ticket_id"] == ticket_id and a["status"] == "pending"]\n'
)
_SQL_PENDING = (
    "    \"SELECT deadline FROM approvals WHERE ticket_id = :t AND status = 'pending' ORDER BY created_at DESC, approval_id DESC LIMIT 1\"\n"
)

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-R3-1 trả deadline cả khi đã kết thúc",
             [one(ROUTE, _GUARD, _GUARD.replace("row.final_state is None and ", "").replace("# R3", "# MUTATION M-R3-1"))],
             UNIT, ["test_r3_r9b_guard_final_state_pending_approval_deadline_null"]),
    Mutation("M-R3-2 cha trả deadline phiếu",
             [one(ROUTE, _GUARD, _GUARD.replace("not row.is_parent and ", "").replace("# R3", "# MUTATION M-R3-2"))],
             UNIT, ["test_r3_r9a_guard_is_parent_pending_approval_deadline_null"]),
    Mutation("M-R3-3a fake lấy phiếu không lọc pending",
             [one(FAKE, _FAKE_PENDING, _FAKE_PENDING.replace(' and a["status"] == "pending"]', "]  # MUTATION M-R3-3a"))],
             UNIT, ["test_r3_r2_closed_approval_while_checkpoint_waiting_deadline_null"]),
]  # fmt: skip
if "--pg" in sys.argv:
    MUTATIONS_ALL.append(
        Mutation("M-R3-3b SQL lấy phiếu không lọc pending",
                 [one(STORE, _SQL_PENDING, _SQL_PENDING.replace(" AND status = 'pending'", "").replace("\n", "  # MUTATION M-R3-3b\n"))],
                 PG, ["test_open_deadline_approval_only_pending"]),
    )  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix)]


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
