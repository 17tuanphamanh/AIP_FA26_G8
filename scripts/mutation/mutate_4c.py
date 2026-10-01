"""Mutation tay chặng 4c (phase4 mục 6.3, PLAN-4c mục 6) — 1 lượt. Mỗi đột biến áp lên file thật, chạy bộ test, khôi phục trong
`finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi
đột biến.

  uv run python scripts/mutation/mutate_4c.py                 # đột biến unit (DỪNG 1: M-4c-1a, 2a, 7; DỪNG 2: M-4c-3…6)
  uv run python scripts/mutation/mutate_4c.py --integration   # đột biến SQL (M-4c-1b, 2b nhắc; M-4c-3b hộp thư) — testcontainers
  uv run python scripts/mutation/mutate_4c.py --only M-4c-7

Ghi chú:
- "Bỏ `IS NULL` ở nhắc" và "nhắc sau hạn" có HAI chỗ chặn: hàm thuần `next_reminder` (a — unit giết qua bảng `test_next_reminder_table`)
  và câu SQL P3 của `SqlDeadlineStore.mark_reminder_once` (b — chỉ test PG giết được: `test_mark_reminder_once_*`, c4 với hai worker
  bị ép đọc trước khi đánh dấu). Ở mức `WorkerJobs` unit, chặn (b) của bản giả che chặn (a) và ngược lại — nên mỗi chỗ có test riêng.
- `--integration` chạy pytest trên testcontainers (KHÔNG đụng stack dev); như `make test`: có socket colima thì đặt `DOCKER_HOST` +
  `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE` (Makefile dòng đầu) — không đọc `.env`.
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


DOMAIN = "backend/app/domain/approval.py"
RUNTIME = "backend/app/db/runtime.py"
B16 = "backend/app/graph/nodes/approval_wait.py"
AUTHZ = "backend/app/auth/authz.py"
ROUTE = "backend/app/api/approvals.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_approval_reminders", "test_b16_approval_wait", "test_rejection_text", "test_side_effects_ast",
        "test_graph_worker", "test_approvals_api", "test_goto_audit_columns",
        "test_approvals_view", "test_approvals_inbox", "test_authz", "test_auth_idor",
    )
])  # fmt: skip
IT = pt("backend/tests/integration/test_b16_reminders_pg.py", "backend/tests/integration/test_approvals_view_pg.py")
STORE = "backend/app/approval/store.py"


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_R2_NULL = "        return 2 if reminder_2_at is None else None\n"
_R1_NULL = "        return 1 if reminder_1_at is None else None\n"
_DEADLINE = "    if now >= deadline:\n        return None\n"
_SQL_INBOX = "WHERE (a.approver_id = :me OR (a.backup_approver_id = :me AND a.reminder_2_at IS NOT NULL)) {status}\n"
_SQL_MARK = '        f"AND reminder_{n}_at IS NULL AND deadline > :now RETURNING approver_id, backup_approver_id"\n'
_BACKUP = "    elif a.backup_approver_id is not None and a.backup_approver_id == p.user_id and a.reminder_2_at is not None:\n"
_VIEW_ROLE = "    role = approval_role(p, a, parties)\n"
_VIEW_HASH = "    if action is None or hash_action(action) != a.action_plan_hash:  # G4-13: không bao giờ trả object khác object đã băm\n"
_VIEW_WRITE = "    if role is not None:  # chỉ người được giao / dự phòng đủ điều kiện ghi lần xem đầu; manager xem không ghi\n"
_ONCE = (
    "        ref = await effects.once(\n"
    '            state, "notify_user", deps.notifier.notify_user, state["ticket_id"], text, "none", step="B16"\n'
    "        )\n"
)

TABLE = "test_next_reminder_table"
C4 = "test_c4_two_workers_one_notification_per_milestone"
NOT_AFTER = "test_mark_reminder_once_not_at_or_after_deadline"

UNIT: list[Mutation] = [
    Mutation("M-4c-1a next_reminder bỏ kiểm cột nhắc NULL",
             [one(DOMAIN, _R2_NULL, "        return 2  # MUTATION M-4c-1a\n"),
              one(DOMAIN, _R1_NULL, "        return 1  # MUTATION M-4c-1a\n")],
             UT, [f"{TABLE}[da-nhac-1]", f"{TABLE}[truoc-moc-2]", f"{TABLE}[sau-moc-2-khong-bao-gio-nhac-1]",
                  f"{TABLE}[da-nhac-ca-hai]"]),
    Mutation("M-4c-2a next_reminder nhắc cả khi đã tới hạn",
             [one(DOMAIN, _DEADLINE, "    if False:  # MUTATION M-4c-2a\n        return None\n")],
             UT, [f"{TABLE}[dung-han-khong-nhac]", f"{TABLE}[dung-han-chua-nhac-gi]", f"{TABLE}[qua-han]"]),
    Mutation("M-4c-7 tin từ chối gửi thẳng, không qua effects.once",
             [one(B16, _ONCE, '        ref = await deps.notifier.notify_user(state["ticket_id"], text, "none")  # MUTATION M-4c-7\n')],
             UT, ["test_graph_nodes_never_call_side_effects_directly",
                  "test_c1_crash_after_notify_before_audit_rerun_sends_once"]),
    # ---- DỪNG 2: dự phòng, xem phiếu (P4, P6) ----
    Mutation("M-4c-3 dự phòng không cần nhắc 2",
             [one(AUTHZ, _BACKUP, "    elif a.backup_approver_id is not None and a.backup_approver_id == p.user_id:  # MUTATION M-4c-3\n")],
             UT, ["test_c5_backup_before_reminder2_decide_403_no_resume",
                  "test_c7_backup_before_reminder2_view_404_same_as_missing"]),
    Mutation("M-4c-4 xem phiếu không kiểm người được giao (mọi L1 = primary)",
             [one(ROUTE, _VIEW_ROLE, '    role = approval_role(p, a, parties) or "primary"  # MUTATION M-4c-4\n')],
             UT, ["test_c7_other_l1_view_404_same_as_missing"]),
    Mutation("M-4c-5 ApprovalView không so hash",
             [one(ROUTE, _VIEW_HASH, "    if action is None:  # MUTATION M-4c-5\n")],
             UT, ["test_c9_plan_changed_409_no_view_no_write[chi-action]",
                  "test_c9_plan_changed_409_no_view_no_write[action-va-hash-state]"]),
    Mutation("M-4c-6 manager xem cũng ghi first_viewed_at",
             [one(ROUTE, _VIEW_WRITE, "    if True:  # MUTATION M-4c-6\n")],
             UT, ["test_c7_manager_not_assigned_view_200_viewer_no_write"]),
]  # fmt: skip

INTEGRATION: list[Mutation] = [
    Mutation("M-4c-1b SQL mark_reminder_once bỏ `reminder_n_at IS NULL`",
             [one(RUNTIME, _SQL_MARK,
                  '        f"AND deadline > :now RETURNING approver_id, backup_approver_id"  # MUTATION M-4c-1b\n')],
             IT, ["test_mark_reminder_once_first_wins_second_none", C4]),
    Mutation("M-4c-2b SQL mark_reminder_once bỏ `deadline > :now` (nhắc sau hạn)",
             [one(RUNTIME, _SQL_MARK,
                  '        f"AND reminder_{n}_at IS NULL RETURNING approver_id, backup_approver_id"  # MUTATION M-4c-2b\n')],
             IT, [f"{NOT_AFTER}[dung-han]", f"{NOT_AFTER}[qua-han]"]),
    # DỪNG 2 — lớp SQL độc lập với `approval_role` (IDOR hộp thư): chỉ test PG giết được
    Mutation("M-4c-3b SQL inbox: dự phòng thấy phiếu trước nhắc 2",
             [one(STORE, _SQL_INBOX,
                  "WHERE (a.approver_id = :me OR a.backup_approver_id = :me) {status} -- MUTATION M-4c-3b\n")],
             IT, ["test_c10_pg_inbox_role_filter_assigned_or_backup_after_reminder2"]),
]  # fmt: skip

MUTATIONS = INTEGRATION if "--integration" in sys.argv else UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in UNIT + INTEGRATION if m.name.startswith(prefix)]


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
