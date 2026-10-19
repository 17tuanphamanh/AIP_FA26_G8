"""Mutation tay G2 — harness chạy kịch bản trên stack (plan G2 mục 8; theo mẫu `mutate_t29.py`). Mỗi đột biến áp lên file thật, chạy
test eval, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau (file G2 còn untracked → md5 là chốt chính).

Chốt N3 VIẾT LẠI ở đây, KHÔNG import `n3.py` (file đó nằm trong danh sách chặn đọc tới 25/10 — import = chạy code của file bị chặn):
(a) file đích còn chữ `MUTATION` → dừng; (b) mốc xanh một lần trước khi đột biến; (c) sau khi chạy: md5 khớp, `git diff --stat` khớp,
không file đích nào còn chữ `MUTATION`.

  uv run python scripts/mutation/mutate_g2.py
  uv run python scripts/mutation/mutate_g2.py --only M-G2-7

Chỉ unit (stack giả, không Docker, không DB). Không đọc `.env`.
"""

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


COL = "backend/app/eval/collect.py"
STK = "backend/app/eval/stack.py"
ACT = "backend/app/eval/actors.py"
RUN = "backend/app/eval/runner.py"
DS = "backend/app/eval/dataset.py"
MET = "backend/app/eval/metrics.py"
UT = pt("backend/tests/unit/eval")


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


# ---- collect.py: điểm log 4, B11, B8, lá nhiều ý ---------------------------------------------------------------------

_STEP = 'LOG4_STEP = "B13/B14"\n'
_FIELDS = ("LOG4_FIELDS = (\"'route', detail->>'route', 'strategy', detail->>'strategy', 'decided_by', decided_by, "
           "'raw_prob', raw_prob, \"\n")  # fmt: skip
_STRAT_NE = '        if r["strategy"] != strategy:\n'
_STRAT_NONE = '        if r["strategy"] is None:\n'
_ROUTES = '    if len({r["route"] for r in rows}) > 1:\n'
_TURN_NONE = '        if r["turn"] is None:  # dòng của clarify_wait (hết hạn / chặn injection) — không có detail.turn\n'
_TURN_MAX = '        best = max(best, int(r["turn"]) + (r["event"] == "asked"))\n'
_B8_LAST = '    last = max(rows, key=lambda r: (datetime.fromisoformat(r["created_at"]), r["log_id"]))\n'
_PARENT = '    if ticket["is_parent"]:\n'

# ---- stack.py ---------------------------------------------------------------------------------------------------------

_SQL_RUN = '        out = self.run([*self.compose_base, "exec", "-T", "postgres", "sh", "-c", PSQL], stdin=READ_ONLY + query)\n'
_DEADLINE = "        return self.elapsed() >= self.seconds\n"
_API_ERR = '            raise StackError(f"{method} {shown}: HTTP {r.status_code}")\n'
_RUN_ERR = '            raise StackError(f"lệnh lỗi (mã {code}): {shlex.join(cmd[:4])} …")\n'

# ---- actors.py --------------------------------------------------------------------------------------------------------

_NEXT = "        return self._replies.pop(0)\n"
_CONFIRM_POP = "            return self._confirms.pop(0)\n"
_IGNORE = '        if decision == "ignore":\n'
_REJECT = '            self.api.decide(headers, approval_id, "rejected", REJECT_NOTE)\n'
_USERNAME = "        username = username_of(self.sql, approver_id)\n"
_LOGIN = "        headers = self.api.login(username, self.password)\n"

# ---- runner.py / dataset.py -------------------------------------------------------------------------------------------

_PER_CASE = "        if args.per_case:\n"
_ERR_TYPE = '            outcome, error_type = "error", error_type or type(e).__name__\n'
_WARM = "        warm = deps.backend.warmup(args.warmup_rounds)\n"
_MULTI = '    if outcome != "multi_leaf" and ticket_id is not None:\n'
_PW = "    if not password.strip():\n"
_TMP = '    tmp.write_text("".join(r.model_dump_json() + "\\n" for r in records), encoding="utf-8")\n'
_RECHECK = "    if records:\n"
_HEALTH = "        health = Api(deps.http).health()\n"
_LOGIN_REQ = "        h = c.api.login(c.usernames[s.id], c.password)\n"
_UNLABELED = '        "unlabeled": sum(r.expected_route is None for r in records),\n'
_SEED_CHECK = "            if s.requester.user_id not in users:\n"
_ROUTE_OPT = "    expected_route: Route | None  # None = chưa nhãn (tới 25/10)\n"
_SAFETY_PAIRS = "    pairs = _pairs(_gold(records))\n    need = "
_N_UNLAB = "        n_unlabeled=n_unlabeled(records),\n"
_SLA = "    if not isinstance(sla, int) or isinstance(sla, bool) or sla <= 0:  # G2-Q6 (Tuấn Anh 19/10): ca ignore phải ra E6 trước timeout\n"
_WHERE = '        where = self.name if show_name else f"file #{self.index}/{self.total}"\n'
_IGNORED = "            ignored += dropped\n"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-G2-1 log 4 lọc step B12 thay B13/B14",
             [_swap(COL, _STEP, 'LOG4_STEP = "B12"', "M-G2-1")], UT, ["test_log4_step_filter"]),
    Mutation("M-G2-2 bỏ kiểm strategy của log 4",
             [_off(COL, _STRAT_NE, "M-G2-2")], UT, ["test_strategy_mismatch_aborts", "test_strategy_abort_exit2"]),
    Mutation("M-G2-3 thiếu khoá strategy coi như có (không báo thiếu khoá)",
             [_off(COL, _STRAT_NONE, "M-G2-3")], UT,
             ["test_strategy_missing_key_aborts", "test_strategy_abort_messages_differ"]),
    Mutation("M-G2-4 clarification_turns: turn + asked → turn",
             [_swap(COL, _TURN_MAX, '        best = max(best, int(r["turn"]))', "M-G2-4")], UT, ["test_turns_max_formula"]),
    Mutation("M-G2-5 bỏ bỏ-qua dòng B11 không có turn",
             [_off(COL, _TURN_NONE, "M-G2-5")], UT, ["test_turns_skip_rows_without_turn"]),
    Mutation("M-G2-6 B8 lấy dòng ĐẦU theo created_at",
             [_swap(COL, _B8_LAST, _B8_LAST.replace("max(rows", "min(rows"), "M-G2-6")], UT, ["test_doc_ids_last_b8"]),
    Mutation("M-G2-7 hết giờ: >= → >",
             [_swap(STK, _DEADLINE, "        return self.elapsed() > self.seconds", "M-G2-7")], UT, ["test_deadline_boundary"]),
    Mutation("M-G2-8 reject không gửi note",
             [_swap(ACT, _REJECT, '            self.api.decide(headers, approval_id, "rejected")', "M-G2-8")], UT,
             ["test_sim_approver_reject", "test_sim_approver_decides[reject-rejected-body1]", "test_flow_reject"]),
    Mutation("M-G2-9 ignore → vẫn duyệt",
             [_off(ACT, _IGNORE, "M-G2-9")], UT, ["test_sim_approver_ignore", "test_flow_ignore_waits_for_worker"]),
    Mutation("M-G2-10 mặc định in từng ca",
             [_swap(RUN, _PER_CASE, "        if True:", "M-G2-10")], UT, ["test_default_output_aggregate_only"]),
    Mutation("M-G2-11 ghi/in thông điệp exception thay tên lớp",
             [_swap(RUN, _ERR_TYPE, '            outcome, error_type = "error", error_type or f"{type(e).__name__}: {e}"',
                    "M-G2-11")], UT, ["test_error_message_not_printed"]),
    Mutation("M-G2-12 log 4 SELECT nguyên detail",
             [_swap(COL, _FIELDS, _FIELDS.replace("(\"'route',", "(\"'detail', detail, 'route',"), "M-G2-12")], UT,
             ["test_sql_detail_keys_whitelist"]),
    Mutation("M-G2-13 đọc detail->>'turn' ở câu log 4",
             [_swap(COL, _FIELDS, _FIELDS.replace("(\"'route',", "(\"'turn', detail->>'turn', 'route',"), "M-G2-13")], UT,
             ["test_sql_detail_keys_whitelist"]),
    Mutation("M-G2-14 bỏ tiền tố READ ONLY",
             [_swap(STK, _SQL_RUN, _SQL_RUN.replace("stdin=READ_ONLY + query)", "stdin=query)"), "M-G2-14")], UT,
             ["test_sql_read_only_prefix"]),
    Mutation("M-G2-15 bỏ làm nóng rerank",
             [_swap(RUN, _WARM, '        warm = {"rounds": args.warmup_rounds, "first_ms": 0, "last_ms": 0}', "M-G2-15")],
             UT, ["test_warmup_before_first_ticket", "test_warmup_fail_aborts"]),
    Mutation("M-G2-16 ghi bản ghi cho lá nhiều ý",
             [_swap(RUN, _MULTI, "    if ticket_id is not None:", "M-G2-16"), _off(COL, _PARENT, "M-G2-16")], UT,
             ["test_multi_leaf_skipped", "test_multi_leaf_raises"]),
    Mutation("M-G2-17 thiếu EVAL_PASSWORD → chạy với chuỗi rỗng",
             [_off(RUN, _PW, "M-G2-17")], UT, ["test_password_missing_exit2"]),
    Mutation("M-G2-18 log 4 khác route → lấy dòng đầu",
             [_off(COL, _ROUTES, "M-G2-18")], UT, ["test_log4_dup_diff_route_raises"]),
    Mutation("M-G2-19 bỏ đọc lại bằng load_predictions + ghi trùng",
             [_swap(RUN, _TMP, _TMP.replace("for r in records)", "for r in records + records)"), "M-G2-19"),
              _off(RUN, _RECHECK, "M-G2-19")], UT, ["test_written_file_roundtrip"]),
    Mutation("M-G2-20 lỗi nạp in tên file khi không có --per-case",
             [_swap(DS, _WHERE, "        where = self.name", "M-G2-20")], UT,
             ["test_load_error_hides_file_name", "test_cli_load_error_no_file_name"]),
    Mutation("M-G2-21 --allow-extra-fields không ghi ignored_fields",
             [_swap(DS, _IGNORED, "            ignored += []", "M-G2-21")], UT,
             ["test_allow_extra_fields_records_paths", "test_cli_ignored_fields_manifest"]),
    Mutation("M-G2-22 Shell.sql in câu SQL",
             [one(STK, _SQL_RUN, "        print(query)  # MUTATION M-G2-22\n" + _SQL_RUN)], UT, ["test_shell_sql_no_echo"]),
    Mutation("M-G2-23 Api đưa id thật vào thông điệp lỗi",
             [_swap(STK, _API_ERR, '            raise StackError(f"{method} {path}: HTTP {r.status_code}")', "M-G2-23")], UT,
             ["test_api_error_shows_template_not_id"]),
    Mutation("M-G2-24 Shell.run chép đầu ra lệnh vào lỗi",
             [_swap(STK, _RUN_ERR, '            raise StackError(f"lệnh lỗi (mã {code}): {shlex.join(cmd[:4])} … {out}")',
                    "M-G2-24")], UT, ["test_shell_error_hides_output"]),
    Mutation("M-G2-25 ScriptedUser không tiến con trỏ",
             [_swap(ACT, _NEXT, "        return self._replies[0]", "M-G2-25")], UT,
             ["test_scripted_user_sequence"]),
    Mutation("M-G2-26 SimApprover đăng nhập bằng requester của ticket",
             [_swap(ACT, _USERNAME, "        username = username_of(self.sql, str(self.sql(f\"SELECT to_json(requester_id) "
                                    "FROM tickets WHERE ticket_id = '{ticket_id}'\")))", "M-G2-26")], UT,
             ["test_sim_approver_decides", "test_flow_clarify_approve_resolve"]),
    Mutation("M-G2-27 preflight gọi GET /api/policy (Rev 27)",
             [one(RUN, _HEALTH, '        deps.http.get("/api/policy")  # MUTATION M-G2-27\n' + _HEALTH)], UT,
             ["test_harness_never_calls_policy_api"]),
    Mutation("M-G2-28 SimApprover đăng nhập bằng approver_id thay username",
             [_swap(ACT, _LOGIN, "        headers = self.api.login(approver_id, self.password)", "M-G2-28")], UT,
             ["test_sim_approver_decides"]),
    Mutation("M-G2-29 bỏ kiểm APPROVAL_SLA_MINUTES_DEV (G2-Q6)",
             [_off(RUN, _SLA, "M-G2-29")], UT, ["test_preflight_sla_required"]),
    # ---- G2-schema (20/10): cấu trúc kịch bản thật ----
    Mutation("M-G2-30 ScriptedUser lấy reply CUỐI (không theo thứ tự)",
             [_swap(ACT, _NEXT, "        return self._replies.pop()", "M-G2-30")], UT, ["test_scripted_user_replies_in_order"]),
    Mutation("M-G2-31 đăng nhập bằng user_id (bỏ tra seed)",
             [_swap(RUN, _LOGIN_REQ, "        h = c.api.login(s.requester.user_id, c.password)", "M-G2-31")], UT,
             ["test_login_uses_seed_username", "test_password_from_env_used"]),
    Mutation("M-G2-32 bỏ kiểm requester.user_id có trong seed",
             [_off(DS, _SEED_CHECK, "M-G2-32")], UT, ["test_requester_unknown_user_id", "test_unknown_user_check_only_no_value"]),
    Mutation("M-G2-33 coi expected_route null là lỗi",
             [_swap(DS, _ROUTE_OPT, "    expected_route: Route", "M-G2-33")], UT,
             ["test_expected_route_null_unlabelled", "test_cli_check_only_real_shape"]),
    Mutation("M-G2-34 runner không đếm unlabeled",
             [_swap(RUN, _UNLABELED, '        "unlabeled": 0,', "M-G2-34")], UT, ["test_manifest_unlabeled"]),
    Mutation("M-G2-35 safety không lọc lá chưa nhãn",
             [one(MET, _SAFETY_PAIRS, "    pairs = _pairs(records)  # type: ignore[arg-type]  # MUTATION M-G2-35\n    need = ")], UT,
             ["test_safety_skips_unlabeled"]),
    Mutation("M-G2-36 n_unlabeled của safety luôn 0",
             [_swap(MET, _N_UNLAB, "        n_unlabeled=0,", "M-G2-36")], UT, ["test_safety_skips_unlabeled"]),
    Mutation("M-G2-37 bước xác nhận luôn \"Đã ổn\" (bỏ on_confirm của kịch bản)",
             [_swap(ACT, _CONFIRM_POP, "            return DEFAULT_ON_CONFIRM", "M-G2-37")], UT,
             ["test_scripted_user_confirms_in_order", "test_confirm_uses_scenario_on_confirm"]),
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


def guard(files: list[str], cmds: list[list[str]], env: dict[str, str]) -> int | None:
    """N3 (viết lại, không import n3): (a) không file đích nào còn dấu `MUTATION`; (b) mốc xanh một lần."""
    left = marked(files)
    if left:
        print(f"DỪNG (N3a): file đích còn chữ {MARK!r} {left} — khôi phục tay trước")
        return 2
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
    if not MUTATIONS:
        print(f"DỪNG: không có đột biến nào khớp `--only` (mã: M-G2-1 … M-G2-{len(MUTATIONS_ALL)})")
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
