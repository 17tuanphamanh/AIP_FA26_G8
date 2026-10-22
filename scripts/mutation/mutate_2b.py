"""Mutation gói 2b (đặc tả `claude/dac-ta-bat-2-model.md` mục 8 "Mutation gói 2b"; PLAN-2B1 mục 5) — khuôn `mutate_t23a.py`: mỗi đột
biến áp lên file thật, chạy bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ
`MUTATION` → dừng; mốc xanh một lần cho mỗi lệnh test trước khi đột biến.

Phần 1 (chống spam, D-54 a): mã 11, 12, 13, 14, 20, 21, 22. Mã 15–19 (cảnh báo L2, lịch sử người gửi, luật M9) thêm ở phần sau.

  uv run python scripts/mutation/mutate_2b.py                 # 3 mã unit (11, 13, 22) — sandbox, không Docker
  uv run python scripts/mutation/mutate_2b.py --pg            # 5 mã trên test Postgres (11, 12, 14, 20, 21) — CẦN Docker (testcontainers)
  uv run python scripts/mutation/mutate_2b.py --only 2b-14    # chỉ mã có tên bắt đầu bằng chuỗi này (dùng kèm --pg khi là mã Postgres)

Mã 11 chạy ở cả hai chế độ (bản giả của unit test dùng chung hàm so ngưỡng với bản SQL). Mỗi đột biến chạy TRỌN lệnh của nó (không
chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.
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
    return ["uv", "run", "pytest", *args, "-q", "-rf", "-p", "no:cacheprovider"]


RATE = "backend/app/db/rate_limits.py"
TICKETS = "backend/app/api/tickets.py"

UNIT = pt("backend/tests/unit/test_rate_limit_api.py", "backend/tests/unit/test_rate_limits.py")
PG = pt("backend/tests/integration/test_rate_limits_pg.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_GE = "    return count >= w.limit\n"
_OWN = "        own = (_TICKETS.c.requester_id == user_id) & _TICKETS.c.parent_ticket_id.is_(None)\n"
_SEEN = "        if not (await conn.execute(select(seen))).scalar_one():\n"
_INSERT = (
    "            if not over_limit(count, w):\n"
    "                await conn.execute(insert(_HITS).values(user_id=user_id, created_at=now))\n"
    "                return None\n"
)
_DELETE = "            await conn.execute(delete(_HITS).where(mine & (_HITS.c.created_at <= since(w, now))))\n"
_MSG_ORDER = (
    "    await limit_messages(request, p, desk)  # 429 trước `_owned_leaf`: id giả vẫn 429 (gói 2b)\n"
    '    await _owned_leaf(request, p, desk, ticket_id, "ticket:message")\n'
)
_CONFIRM = "    await limit_messages(request, p, desk)  # chung bộ tin nhắn: /confirm sai bước vẫn chạy guard + ghi late_event (gói 2b)\n"

M11 = one(RATE, _GE, "    return count > w.limit  # MUTATION 2b-11\n")
M11_UNIT = ["test_u13_over_limit_is_count_ge_limit", "test_u1_ten_tickets_in_10min_pass_eleventh_429_retry_after_300",
            "test_u10_wrong_step_409_and_422_still_counted"]  # fmt: skip

MUTATIONS_UNIT: list[Mutation] = [
    Mutation("2b-11 `>` thay `>=` ở ngưỡng 429", [M11], UNIT, M11_UNIT),
    Mutation("2b-13 /messages: 429 đặt sau `_owned_leaf`",
             [one(TICKETS, _MSG_ORDER,
                  '    await _owned_leaf(request, p, desk, ticket_id, "ticket:message")\n'
                  "    await limit_messages(request, p, desk)  # MUTATION 2b-13 429 sau _owned_leaf\n")],
             UNIT, ["test_u5_over_limit_fake_id_429_not_404_no_denied_no_guard"]),
    Mutation("2b-22 /confirm không qua bộ B",
             [one(TICKETS, _CONFIRM, "    pass  # MUTATION 2b-22 /confirm không đếm\n")],
             UNIT, ["test_u11_messages_reply_confirm_share_one_bucket"]),
]  # fmt: skip

MUTATIONS_PG: list[Mutation] = [
    Mutation("2b-11 `>` thay `>=` ở ngưỡng 429 (SQL)", [M11], PG, ["test_p1_messages_until_limit_then_429_writes_no_row"]),
    Mutation("2b-12 bộ A đếm cả ticket con",
             [one(RATE, _OWN, "        own = _TICKETS.c.requester_id == user_id  # MUTATION 2b-12 đếm cả ticket con\n")],
             PG, ["test_p5_child_tickets_not_counted_parent_counted"]),
    Mutation("2b-14 ghi `rate_limited` mỗi lần thay vì mỗi đợt",
             [one(RATE, _SEEN, "        if True:  # MUTATION 2b-14 không chống trùng đợt\n")],
             PG, ["test_p6_messages_one_event_per_burst_columns", "test_p6_tickets_two_windows_two_events_once"]),
    Mutation("2b-20 ghi `rate_hits` cả khi trả 429",
             [one(RATE, _INSERT,
                  "            await conn.execute(insert(_HITS).values(user_id=user_id, created_at=now))  # MUTATION 2b-20\n"
                  "            if not over_limit(count, w):\n"
                  "                return None\n")],
             PG, ["test_p1_messages_until_limit_then_429_writes_no_row", "test_p4_retry_after_from_db_rows"]),
    Mutation("2b-21 bỏ xoá dòng cũ của người gửi",
             [one(RATE, _DELETE, "            pass  # MUTATION 2b-21 không dọn dòng cũ\n")],
             PG, ["test_p2_cleanup_only_own_rows_older_than_10min"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_PG if "--pg" in sys.argv else MUTATIONS_UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS if m.name.startswith(prefix)]


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
    if not MUTATIONS:
        print("không có đột biến nào khớp lựa chọn")
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
