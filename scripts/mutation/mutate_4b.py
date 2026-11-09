"""Mutation tay chặng 4b (phase4 mục 5.4) — mỗi đột biến áp lên file thật, chạy bộ test, khôi phục trong `finally`, so md5 +
`git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_4b.py            # mọi đột biến unit: M-4b-1…14 (DỪNG 1: 1…7, 11; DỪNG 2: 8, 9, 10, 12, 13, 14)
  uv run python scripts/mutation/mutate_4b.py --only M-4b-6

Ghi chú:
- M-4b-5 ("lỗi AD coi như không hợp lệ") áp ở `memo_lookup` — MỌI lời tra của `choose_approver` đi qua đó (x9 mức hàm; DỪNG 2
  thêm x9 qua node).
- M-4b-6/7 sửa `config/policy.json` (JSON không có chú thích — chữ `MUTATION` chèn vào `description` của luật bị phá, N3a).
- M-4b-11 (Q-4b-2): route dùng chuỗi CHỈ sếp trực tiếp → b2 (`l1_lead`, sếp trực tiếp) vẫn 403; b2b (`it_mgr01`, chuỗi 2 cấp)
  và ca sếp cấp 5 phải đỏ.
- DỪNG 2 (node B15 thật, B17 P13): M-4b-9 = "bỏ `peek` + báo người VỪA CHỌN" (Q-4b-3 — chỉ bỏ báo theo phiếu thì tương đương dưới
  `peek`); M-4b-13 = chỉ bỏ `peek`; M-4b-12 giết ở unit nhờ FK giả của `MemoryApprovals` (PG: `test_b15_pg` b3 — chạy ở verify);
  M-4b-14 giết ở b8 (Q-4b-4: cột `intended_action` có `type` + `target`).
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


APPROVAL = "backend/app/domain/approval.py"
POLICY = "config/policy.json"
ROUTE = "backend/app/api/approvals.py"
B15 = "backend/app/graph/nodes/b15_prepare_approval.py"
B17 = "backend/app/graph/nodes/b17_execute.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_approval_domain", "test_hrule_4b_owner", "test_policy_rules_vpn", "test_config_files", "test_b12_assess",
        "test_approvals_route_chain", "test_approvals_api", "test_authz",
        "test_b15_prepare_approval", "test_b17_decided_by", "test_goto_audit_columns", "test_b17_execute",
    )
])  # fmt: skip


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_FIRST = "    conflict = await conflict_of(first) if first is not None else None\n"
_HEAD_CONFLICT = "        head_conflict = await conflict_of(head)\n"
_CHAIN = "        chain = await manager_chain(cand.user_id, cand.manager_id, fetch_manager)\n"
_INACTIVE = '    if ad.employment_status != "active":\n        return "inactive"\n'
_MEMO = "            seen[user_id] = await lookup(user_id)  # ném → không ghi gì vào `seen`\n"
_R17 = (
    '      {"fact": "action.facts.device_registered", "op": "is_false"},\n'
    '      {"fact": "action.facts.device_owner_is_requester", "op": "is_true"}]},\n'
    '     "description": "Thiết bị chưa đăng ký cần người duyệt"},\n'
)
_R18 = (
    '      {"fact": "time.within_business_hours", "op": "is_false"},\n'
    '      {"fact": "action.facts.device_owner_is_requester", "op": "is_true"}]},\n'
    '     "description": "Yêu cầu gửi ngoài giờ hành chính cần người duyệt"},\n'
)
_ROUTE_CHAIN = "    return await manager_chain(user_id, me.manager_id if me else None, fetch_manager)\n"
_GUARD = (
    '        if action_has_device_target(action) and action.facts.get("device_owner_is_requester") is not True:  # [1] P6\n'
)
_PEEK = '        existing = await effects.peek(state, "approval_create", step="B15")  # [2] P9\n'
_NOTIFY = '            state, "notify_approver", deps.approvals.notify_approver, approval_id, a.approver_id, step="B15",\n'
_ENSURE = "                    await deps.approver_users.ensure(ad_user, lookup, now=now)\n"
_INTENDED = "            approval_id=approval_id, action_plan_hash=hash_action(action), intended_action=action,\n"
_DECIDED = "        if decided_by is not None:  # P13 — SAU người gửi/người hưởng lợi\n"

X = "test_x_table_3_2_choose_approver"
X2, X3, X4, X7 = (
    f"{X}[x2-TC19-l1_01-tu-gui-self-truong-BP]", f"{X}[x3-l1_lead-sep-truc-tiep-truong-BP]",
    f"{X}[x4-it_mgr01-sep-chuoi-roi-head-self-Refuse]", f"{X}[x7-l1_01-disabled-l1_02-backup-it_mgr01]",
)  # fmt: skip
X9 = [f"test_x9_lookup_error_raises_not_invalid[{i}]" for i in ("primary", "backup", "giua-chuoi-quan-ly-cua-l1_01",
                                                                 "truong-BP")]  # fmt: skip
HRULE = "test_hrule_p7_not_own_device_no_rule_e5"
X12 = "test_x12_device_target_owner_not_true_e5_before_any_ad_call"
X14, X14B = "test_x14_rerun_after_kill_one_approval_notifies_old_approver_no_ad", "test_x14b_rerun_with_ad_down_keeps_old_approval_not_e2"
B6 = "test_b6_decided_by_no_longer_valid_is_e5_zero_writes"
B8 = "test_b8_point5_columns_not_null_closed_values_no_free_text"

UNIT: list[Mutation] = [
    Mutation("M-4b-1 xung đột → chọn dự phòng thay Trưởng BP",
             [one(APPROVAL, _FIRST, _FIRST + "    if conflict is not None and len(valid_l1) > 1:  # MUTATION M-4b-1\n"
                                             "        first, conflict = valid_l1[1], None\n")],
             UT, [X2, X3]),
    Mutation("M-4b-2 không kiểm xung đột cho Trưởng BP",
             [one(APPROVAL, _HEAD_CONFLICT, "        head_conflict = None  # MUTATION M-4b-2\n")],
             UT, [X4]),
    Mutation("M-4b-3 boss_of_approver chỉ sếp trực tiếp",
             [one(APPROVAL, _CHAIN, "        chain = (cand.manager_id,) if cand.manager_id else ()  # MUTATION M-4b-3\n")],
             UT, [X4]),
    Mutation("M-4b-4 valid() bỏ kiểm employment_status",
             [one(APPROVAL, _INACTIVE, '    if False:  # MUTATION M-4b-4\n        return "inactive"\n')],
             UT, [X7]),
    Mutation("M-4b-5 lỗi AD coi như không hợp lệ (đi tiếp)",
             [one(APPROVAL, _MEMO, "            try:  # MUTATION M-4b-5\n"
                                   "                seen[user_id] = await lookup(user_id)\n"
                                   "            except ApproverLookupError:\n"
                                   "                seen[user_id] = None\n")],
             UT, X9),
    Mutation("M-4b-6 bỏ điều kiện chủ máy ở R18",
             [one(POLICY, _R18, '      {"fact": "time.within_business_hours", "op": "is_false"}]},\n'
                                '     "description": "Ngoài giờ hành chính MUTATION M-4b-6"},\n')],
             UT, [f"{HRULE}[P7-ngoai-gio-20h-may-nguoi-khac-E5-x5]", "test_x5_graph_other_persons_device_at_20h_e5_no_approval",
                  "test_hrule_c5_luat_khop_va_suyt_khop[R18-suyt-20h-may-nguoi-khac]",
                  "test_p5_other_persons_device_after_hours_is_e5_not_hitl"]),
    Mutation("M-4b-7 bỏ điều kiện chủ máy ở R17",
             [one(POLICY, _R17, '      {"fact": "action.facts.device_registered", "op": "is_false"}]},\n'
                                '     "description": "Thiết bị chưa đăng ký MUTATION M-4b-7"},\n')],
             UT, [f"{HRULE}[P7-may-khong-ton-tai-E5-x6]", "test_x6_graph_nonexistent_device_e5_no_approval",
                  "test_hrule_c5_luat_khop_va_suyt_khop[R17-suyt-may-nguoi-khac]"]),
    Mutation("M-4b-11 route dùng chuỗi chỉ sếp trực tiếp (Q-4b-2)",
             [one(ROUTE, _ROUTE_CHAIN, "    return (me.manager_id,) if me and me.manager_id else ()  # MUTATION M-4b-11\n")],
             UT, ["test_b2_requester_in_approver_chain_from_users_table_403[b2b-it_mgr01]",
                  "test_b2_chain_level_5_boss_403"]),
    # ---- DỪNG 2: node B15 thật, B17 P13 ----
    Mutation("M-4b-8 bỏ chốt phòng thủ B15 (P6)",
             [one(B15, _GUARD, "        if False:  # MUTATION M-4b-8\n")],
             UT, [f"{X12}[owner-thieu]", f"{X12}[owner-false]"]),
    Mutation("M-4b-9 bỏ peek + báo người VỪA CHỌN thay vì a.approver_id (Q-4b-3)",
             [one(B15, _PEEK, "        existing = None  # MUTATION M-4b-9 bỏ peek\n"),
              one(B15, _NOTIFY, _NOTIFY.replace("a.approver_id", "(choice.approver.user_id if choice else a.approver_id)"))],
             UT, [X14]),
    Mutation("M-4b-10 B17 bỏ kiểm decided_by (P13)",
             [one(B17, _DECIDED, "        if False:  # MUTATION M-4b-10\n")],
             UT, [f"{B6}[b6-disabled]", "test_b7_ad_error_on_decided_by_only_is_e2_approver_lookup_error"]),
    Mutation("M-4b-12 không ensure người duyệt trước khi tạo phiếu",
             [one(B15, _ENSURE, "                    pass  # MUTATION M-4b-12\n")],
             UT, ["test_b3_approver_without_users_row_gets_row_and_chain_no_session"]),
    Mutation("M-4b-13 bỏ peek — chạy lại luôn chọn người/tra AD (P9)",
             [one(B15, _PEEK, "        existing = None  # MUTATION M-4b-13\n")],
             UT, [X14B]),
    Mutation("M-4b-14 B15 không truyền intended_action vào goto (Q-4b-4)",
             [one(B15, _INTENDED, "            approval_id=approval_id, action_plan_hash=hash_action(action),  # MUTATION M-4b-14\n")],
             UT, [f"{B8}[x1-normal]"]),
]  # fmt: skip

MUTATIONS = UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS if m.name.startswith(prefix)]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(test: str, failed: list[str]) -> bool:
    if "[" in test:
        return any(f.endswith("::" + test) for f in failed)
    return any(f.endswith("::" + test) or ("::" + test + "[") in f for f in failed)


def main() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
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
