"""Mutation `thong_bao` (`GET /api/me/notifications`, P10 mục 3.1) — khuôn `mutate_t23a.py` / `mutate_r3.py`. Mỗi đột biến áp lên file
thật, chạy bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` →
dừng; mốc xanh một lần cho mỗi lệnh test trước khi đột biến.

  uv run python scripts/mutation/mutate_thong_bao.py                  # đột biến chạy được bằng unit (không DB)
  uv run python scripts/mutation/mutate_thong_bao.py --pg             # thêm đột biến CHỈ test PG bắt được (cụm PG tạm, xem dưới)
  uv run python scripts/mutation/mutate_thong_bao.py --only M-TB-1

M-TB-1 (bỏ điều kiện requester khỏi SQL): unit bắt bằng test chuỗi SQL; thử "xem chéo" thật chỉ có ở PG → `--pg` chạy lại M-TB-1 với
bộ test PG (test chống xem chéo ĐỎ). M-TB-1c đổi route (nguồn giả lọc requester) → test A/B ở unit đỏ.

`--pg`: Postgres 16 CỤC BỘ thay PostgresContainer bằng plugin pytest NGOÀI repo (không sửa repo). Cần biến môi trường
`PG_PLUGIN_DIR` (thư mục chứa `pg_local_plugin.py`), `PG_LOCAL_PORT` (cổng cụm tạm) — plugin tự dựng lại DB + 3 role bằng CHÍNH
`docker/postgres/init-roles.sh`. Không đọc `.env`.
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


ROUTE = "backend/app/api/notifications.py"
DB = "backend/app/db/notifications.py"
UNIT = pt("backend/tests/unit/test_notifications_api.py")
PG_FILE = "backend/tests/integration/test_notifications_pg.py"
PG = ["uv", "run", "pytest", "-p", "pg_local_plugin", PG_FILE, "-q", "-p", "no:cacheprovider"]


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_PRED = 'REQUESTER_PREDICATE = "t.requester_id = :user_id"\n'
_PRED_OFF = 'REQUESTER_PREDICATE = "CAST(:user_id AS text) IS NOT NULL"  # MUTATION M-TB-1: không còn lọc requester\n'
_ROUTE_USER = "    rows = await source.page(p.user_id, limit + 1, cursor)"
_NEUTRAL = "        if is_neutral(row.exit_code, row.reason_detail):\n"
_GUARD = "    if note and guard.violation(note) is None:  # cổng của B16 (`approval_wait._rejected`)\n"
_LT = ') < (:c_at, :c_id) {_ORDER}'
_STATUS = "a.status IN ('approved', 'rejected') AND "
_COALESCE = "COALESCE(t.parent_ticket_id, t.ticket_id)"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-TB-1 SQL bỏ điều kiện requester (unit: chuỗi SQL)",
             [one(DB, _PRED, _PRED_OFF)], UNIT,
             ["test_sql_filters_requester_in_both_branches_of_both_queries"]),
    Mutation("M-TB-1c route gọi nguồn với người cố định",
             [one(ROUTE, _ROUTE_USER, _ROUTE_USER.replace("p.user_id", '"nv001"') + "  # MUTATION M-TB-1c")], UNIT,
             ["test_employee_never_sees_other_employees_notifications_even_via_cursor"]),
    Mutation("M-TB-2 bỏ nhánh lời trung tính",
             [one(ROUTE, _NEUTRAL, "        if False:  # MUTATION M-TB-2\n")], UNIT,
             ["test_suspected_attack_is_neutral_and_result_is_real"]),
    Mutation("M-TB-3 ghi chú từ chối không qua output guard",
             [one(ROUTE, _GUARD, "    if note:  # MUTATION M-TB-3\n")], UNIT,
             ["test_rejection_note_passes_output_guard_or_is_dropped"]),
    Mutation("M-TB-4 keyset dùng <= (trùng dòng ở biên trang)",
             [one(DB, _LT, ') <= (:c_at, :c_id) /* MUTATION M-TB-4 */ {_ORDER}')], UNIT,
             ["test_sql_filters_requester_in_both_branches_of_both_queries"]),
]  # fmt: skip
if "--pg" in sys.argv:
    MUTATIONS_ALL += [
        Mutation("M-TB-1 (PG) SQL bỏ điều kiện requester",
                 [one(DB, _PRED, _PRED_OFF)], PG,
                 ["test_requester_isolation_in_sql_even_with_tiny_limit_and_foreign_cursor",
                  "test_route_real_sql_json_contract_and_isolation"]),
        Mutation("M-TB-4 (PG) keyset <= : trùng dòng ở biên trang",
                 [one(DB, _LT, ') <= (:c_at, :c_id) /* MUTATION M-TB-4 */ {_ORDER}')], PG,
                 ["test_cursor_boundary_is_exclusive", "test_keyset_over_ties_c_collation_no_dup_no_gap"]),
        Mutation("M-TB-5 (PG) phiếu duyệt không lọc trạng thái",
                 [one(DB, _STATUS, "TRUE /* MUTATION M-TB-5 */ AND ")], PG,
                 ["test_sources_filters_and_created_at"]),
        Mutation("M-TB-6 (PG) ticket con trả id của chính con",
                 [(DB, _COALESCE, "t.ticket_id /* MUTATION M-TB-6 */", 2)], PG,
                 ["test_sources_filters_and_created_at", "test_route_real_sql_json_contract_and_isolation"]),
    ]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix)]


def test_env() -> dict[str, str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if "--pg" in sys.argv:
        plugin = os.environ.get("PG_PLUGIN_DIR")
        if not plugin:
            sys.exit("--pg cần PG_PLUGIN_DIR (thư mục chứa pg_local_plugin.py) và PG_LOCAL_PORT")
        env |= {"PYTHONPATH": plugin + os.pathsep + env.get("PYTHONPATH", ""), "PG_LOCAL_REPO": str(REPO)}
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
