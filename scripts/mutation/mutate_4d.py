"""Mutation tay chặng 4d (phase4 mục 7.5, PLAN-4d mục 6) — lượt 1 cuối DỪNG 1, lượt 2 cuối DỪNG 2. Mỗi đột biến áp lên file thật, chạy
bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc
xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_4d.py                 # đột biến unit (ghi đè, audit_check, B17 P7, B16 Q-4d-3, bấm muộn, hết hạn)
  uv run python scripts/mutation/mutate_4d.py --integration   # đột biến bắt bằng PG + e2e (testcontainers, mock cổng local — ngoài sandbox)
  uv run python scripts/mutation/mutate_4d.py --only M-4d-10

Ghi chú:
- M-4d-1 ("ghi đè đổi `tickets.final_state`") đặt ở `SqlApprovals.record_override` (chỗ ghi THẬT) → chỉ test PG giết được: unit dùng
  `MemoryApprovals` (bản giả không bị đột biến). e2e i13 cũng giết (chạy ở `make verify`).
- M-4d-8, M-4d-9 có cả lượt unit (hàm thuần) lẫn lượt PG (`run` trên Postgres thật) — hai lớp test độc lập.
- DỪNG 2 (lượt 2, PLAN-4d mục 11.6): M-4d-6 (B16 timeout → `S_EXECUTING`), M-4d-7 (bấm muộn đổi status phiếu), M-4d-15 (B16 bỏ so
  hash — Q-4d-3), M-4d-16 (B16 bỏ lớp phiếu), M-4d-17 (`audit_check` bỏ dòng B16 E5 khỏi điểm 6). Làn `--integration` thêm e2e: i6
  (M-4d-6), i7 (M-4d-7), i8c + i8b (M-4d-15), i8b (M-4d-16), i8d (M-4d-10 — i8b nay do B16 bắt nên B17 lớp 2 cần ca riêng).
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


ROUTE = "backend/app/api/tickets.py"
DOMAIN = "backend/app/domain/override.py"
STORE = "backend/app/approval/store.py"
CHECK = "backend/app/audit/check.py"
B17 = "backend/app/graph/nodes/b17_execute.py"
B16 = "backend/app/graph/nodes/approval_wait.py"
DECIDE = "backend/app/api/approvals.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_override_route", "test_override_domain", "test_audit_check", "test_b17_approval_hash", "test_auth_route_scan",
        "test_b17_execute", "test_b17_decided_by", "test_b16_plan_hash", "test_b16_approval_wait", "test_graph_worker",
        "test_approvals_api",
    )
])  # fmt: skip
IT = pt("backend/tests/integration/test_override_pg.py", "backend/tests/integration/test_audit_check_pg.py")
E2E = pt("backend/tests/e2e/test_gate4_hitl.py", "-k", "test_i6_ or test_i7_ or test_i8b_ or test_i8c_ or test_i8d_")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_REAUTH = '    p: Annotated[Principal, Depends(require("decision:override", recent_login=True))],\n'
_CAN = "    if not can_override(p, row):  # người gửi tự ghi đè\n"
_OPEN = "    if row.final_state is None:\n"
_SAME = "    if body.override_decision == original:\n"
_NOTE = "    note = redacted.text if redacted is not None and redacted.text.strip() else None\n"
_KEY = '"idempotency_key": override_key(self.ticket_id, self.overrider_id),\n'
_ROUTE_MAP = '_BY_ROUTE: Final[Mapping[str, Decision]] = {"AUTO": "AUTO", "HITL": "HITL", "ESCALATE_L2": "L2"}\n'
_RECORD = "        return await AuditWriter(self._engine).record_new(rec.audit_row())\n"
_SCAN = "    found = []\n    for row in rows:\n"
_P5 = '    if (step, event) == ("B15", "queued"):\n'
_RULES = "                rules += [r for r in scanner.hits(text) if r not in rules]\n"
_P7 = "            if row is not None and row.action_plan_hash != current:"
_TIMEOUT = '            state, S_ESCALATED, next_node="b20_audit", step="B16", event="approval_timeout",\n'
_LATE = "    if late is not None:\n        await record_late(\n"
_B16_HASH = '        if kind == "approved" and (changed := _plan_mismatch(state, a)) is not None:  # [5] Q-4d-3\n'
_B16_APPROVAL = "    if a is not None and a.action_plan_hash != new:\n"
_P6_ROW = '    if step == "B16" and event in ("approved", "rejected", "approval_timeout", _B16_PLAN_CHANGED):\n'
B16_HASH_TESTS = [
    "test_q1_state_hash_mismatch_e5_at_b16_not_e9", "test_q2_approval_hash_mismatch_e5_at_b16",
    "test_q4_both_layers_differ_reports_state_first", "test_q5_state_hash_missing_is_mismatch_hash_old_null",
    "test_q6_crash_before_e5_audit_rerun_once",
]  # fmt: skip

OPEN = "test_o3_i14_open_ticket_409_ticket_open"
SELF = "test_o3_i14_requester_self_override_403_permission_denied"
SAME = "test_o3_i14_same_as_original_422_guard_not_called"
P5_DROP = "test_a1_drop_one_required_field_exact_missing"

UNIT: list[Mutation] = [
    Mutation("M-4d-2 bỏ recent_login ở route ghi đè",
             [one(ROUTE, _REAUTH, '    p: Annotated[Principal, Depends(require("decision:override"))],  # MUTATION M-4d-2\n')],
             UT, ["test_o4_i14b_login_older_than_10_minutes_403_reauth", "test_o1_row3_before_row4_missing_ticket_still_reauth",
                  "test_override_route_requires_permission_and_reauth"]),
    Mutation("M-4d-3 lưu note chưa che",
             [one(ROUTE, _NOTE, "    note = body.note if redacted is not None and redacted.text.strip() else None  # MUTATION M-4d-3\n")],
             UT, ["test_o3_i14_note_with_secret_stored_redacted_and_event",
                  "test_o3_i14_note_with_password_real_guard_notices"]),
    Mutation("M-4d-4 ghi đè cho ticket đang mở",
             [one(ROUTE, _OPEN, "    if False:  # MUTATION M-4d-4\n")],
             UT, [OPEN]),
    Mutation("M-4d-5 khoá idempotency mỗi lần một khoá",
             [one(DOMAIN, _KEY,
                  '"idempotency_key": override_key(self.ticket_id, self.overrider_id + self.created_at.isoformat()),  # MUTATION M-4d-5\n')],
             # o2 lần 2 sau +30 s → khoá mới → 201 + 2 dòng. (row11 gửi lần 2 CÙNG giờ FakeClock → khoá đột biến vẫn trùng → không giết)
             UT, ["test_o2_i13_override_finished_ticket_one_row_nothing_else_changes",
                  "test_p4_audit_row_key_ignores_time_and_decision"]),
    Mutation("M-4d-8 audit_check bỏ quét bí mật",
             [one(CHECK, _SCAN, "    found = []\n    for row in []:  # MUTATION M-4d-8\n")],
             UT, ["test_a3_scan_rows_every_text_column", "test_a3_scan_rows_every_json_column_nested_leaf",
                  "test_a3_scan_rows_rules_in_text_and_json_columns"]),
    Mutation("M-4d-9 audit_check bỏ điểm 5",
             [one(CHECK, _P5, "    if False:  # MUTATION M-4d-9\n")],
             UT, [f"{P5_DROP}[p5-approver_id]", f"{P5_DROP}[p5-detail.choice_reason]",
                  "test_a1_two_fields_missing_same_row_one_entry"]),
    Mutation("M-4d-10 B17 bỏ so hash phiếu (lớp 2)",
             [one(B17, _P7, "            if False:  # MUTATION M-4d-10")],
             UT, ["test_h1_approval_hash_changed_is_e5_hash_source_approval_zero_writes", "test_h1_approval_hash_empty_is_e5",
                  "test_h1_approval_hash_of_other_action_is_e5"]),
    Mutation("M-4d-11 bỏ kiểm same_as_original",
             [one(ROUTE, _SAME, "    if False:  # MUTATION M-4d-11\n")],
             UT, [SAME, "test_o1_row8_before_row9_same_as_original_does_not_call_broken_guard"]),
    Mutation("M-4d-12 bỏ can_override (người gửi tự ghi đè được)",
             [one(ROUTE, _CAN, "    if False:  # MUTATION M-4d-12\n")],
             UT, [SELF, "test_o1_row5_before_row6_self_override_on_open_ticket_403"]),
    Mutation("M-4d-13 kết quả quét mang giá trị trúng (render in ra)",
             [one(CHECK, _RULES, '                rules += [f"{r}={text}" for r in scanner.hits(text) if r not in rules]  # MUTATION M-4d-13\n')],
             UT, ["test_a5_render_from_real_scan_has_no_secret_value"]),
    Mutation("M-4d-14 ESCALATE_L2 không đổi sang L2",
             [one(DOMAIN, _ROUTE_MAP,
                  '_BY_ROUTE: Final[Mapping[str, Decision]] = {"AUTO": "AUTO", "HITL": "HITL", "ESCALATE_L2": "HITL"}  # MUTATION M-4d-14\n')],
             UT, ["test_o6_original_decision_table", "test_o6_route_original_decision_from_audit_trail[route-ESCALATE_L2]"]),
    # ---- DỪNG 2 (lượt 2) ----
    Mutation("M-4d-6 B16 hết hạn → S_EXECUTING",
             [one(B16, _TIMEOUT, '            state, S_EXECUTING, next_node="b17_execute", step="B16", event="approval_timeout",  # MUTATION M-4d-6\n')],
             UT, ["test_c2_point6_timeout_response_time_null", "test_approval_deadline_fires_e6_and_closes_approval",
                  "test_late_click_before_scan"]),
    Mutation("M-4d-7 bấm muộn đổi status phiếu",
             [one(DECIDE, _LATE, "    if late is not None:\n        await desk.approvals.close(approval_id, \"timeout\", now)  # MUTATION M-4d-7\n"
                                 "        await record_late(\n")],
             UT, ["test_late_click_before_scan"]),
    Mutation("M-4d-15 B16 bỏ so hash (Q-4d-3)",
             [one(B16, _B16_HASH, "        if False and (changed := _plan_mismatch(state, a)) is not None:  # MUTATION M-4d-15\n")],
             UT, B16_HASH_TESTS),
    Mutation("M-4d-16 B16 bỏ lớp so hash PHIẾU",
             [one(B16, _B16_APPROVAL, "    if False:  # MUTATION M-4d-16\n")],
             UT, ["test_q2_approval_hash_mismatch_e5_at_b16"]),
    Mutation("M-4d-17 audit_check bỏ dòng B16 E5 khỏi điểm 6",
             [one(CHECK, _P6_ROW, '    if step == "B16" and event in ("approved", "rejected", "approval_timeout"):  # MUTATION M-4d-17\n')],
             UT, ["test_q7_audit_check_point6_e5_row_missing_field"]),
]  # fmt: skip

INTEGRATION: list[Mutation] = [
    Mutation("M-4d-1 ghi đè đổi tickets.final_state (SQL, cùng giao dịch)",
             [one(STORE, _RECORD,
                  "        async with self._engine.begin() as conn:  # MUTATION M-4d-1\n"
                  "            await conn.execute(text(\"UPDATE tickets SET final_state = 'S_ESCALATED' WHERE ticket_id = :t\"),\n"
                  "                               {\"t\": rec.ticket_id})\n" + _RECORD)],
             IT, ["test_pg_record_override_one_row_idempotent_per_person_tickets_unchanged"]),
    Mutation("M-4d-8 (PG) audit_check bỏ quét bí mật",
             [one(CHECK, _SCAN, "    found = []\n    for row in []:  # MUTATION M-4d-8\n")],
             IT, ["test_pg_run_canary_planted_in_detail_hits_with_log_id"]),
    Mutation("M-4d-9 (PG) audit_check bỏ điểm 5",
             [one(CHECK, _P5, "    if False:  # MUTATION M-4d-9\n")],
             IT, ["test_pg_run_b15_queued_without_approver_id_is_point5"]),
    # ---- DỪNG 2: e2e (TQ-11 — răng của e2e i6, i7, i8b/c/d) ----
    Mutation("M-4d-6 (e2e) B16 hết hạn → S_EXECUTING",
             [one(B16, _TIMEOUT, '            state, S_EXECUTING, next_node="b17_execute", step="B16", event="approval_timeout",  # MUTATION M-4d-6\n')],
             E2E, ["test_i6_tc20_timeout_e6_no_write_approval_timeout"]),
    Mutation("M-4d-7 (e2e) bấm muộn đổi status phiếu",
             [one(DECIDE, _LATE, "    if late is not None:\n        await desk.approvals.close(approval_id, \"timeout\", now)  # MUTATION M-4d-7\n"
                                 "        await record_late(\n")],
             E2E, ["test_i7_tc27_late_click_409_approval_still_pending_then_worker_e6"]),
    Mutation("M-4d-15 (e2e) B16 bỏ so hash",
             [one(B16, _B16_HASH, "        if False and (changed := _plan_mismatch(state, a)) is not None:  # MUTATION M-4d-15\n")],
             E2E, ["test_i8c_intended_action_changed_while_pending_e5_at_b16_zero_writes",
                   "test_i8b_approval_hash_changed_while_pending_e5_at_b16_zero_writes"]),
    Mutation("M-4d-16 (e2e) B16 bỏ lớp so hash PHIẾU",
             [one(B16, _B16_APPROVAL, "    if False:  # MUTATION M-4d-16\n")],
             E2E, ["test_i8b_approval_hash_changed_while_pending_e5_at_b16_zero_writes"]),
    Mutation("M-4d-10 (e2e) B17 bỏ so hash phiếu (lớp 2)",
             [one(B17, _P7, "            if False:  # MUTATION M-4d-10")],
             E2E, ["test_i8d_approval_hash_changed_after_b16_checkpoint_b17_layer2_e5"]),
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
