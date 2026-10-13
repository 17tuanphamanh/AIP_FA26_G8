"""Mutation chặng T20a (phase5 mục 5.1.7, PLAN-T20a TQ-13) — khuôn `mutate_t22a.py`. Mỗi đột biến áp lên file thật, chạy bộ test,
khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một
lần trước khi đột biến. JSON (`policy.json`): chữ `MUTATION` chèn vào `description` của luật bị phá.

  uv run python scripts/mutation/mutate_t20a.py                    # lượt hiện hành (unit, sandbox, không Docker)
  uv run python scripts/mutation/mutate_t20a.py --only M-T20a-3
  uv run python scripts/mutation/mutate_t20a.py --only M-T20a-7,M-T20a-15   # nhiều mã, so ĐÚNG mã (không theo tiền tố)

Lượt 1 (DỪNG 1): M-T20a-1…10, kỳ vọng CHỈ các test của DỪNG 1 (TQ-13). M-8, M-9 bỏ luôn lớp kiểm `_check_params` của `build_action`
— để chứng minh chính test a8/a9/a13 bắt được (không chỉ lớp kiểm phòng thủ). Lượt 2 (DỪNG 2 — bản này): đủ 14 mã + kỳ vọng đủ cột
5.1.7 (M-5 + g2/g8, M-6 + g3, M-7 + g2/g8); M-T20a-15 (duyệt DỪNG 1, Q-T20a-4: B6 ghi đè cờ `target_is_other` về False → g10, n7) và
M-T20a-16 (agent thêm: B3 không đặt cờ khi `target_user` bị bỏ → g10 — mỗi chỗ trong 3 chỗ của Q-T20a-4 đều có test bắt);
M-T20a-17 (duyệt DỪNG 2, Q-T20a-6: `clarify_wait` không bật cờ → g11). Q-T20a-5 = A: g8 kiểm `requested_for` → M-T20a-7 đỏ cả g8.

Mỗi đột biến chạy TRỌN bộ test của chặng (không chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.
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


POLICY_JSON = "config/policy.json"
ACTION = "backend/app/domain/action.py"
ACCOUNT = "backend/app/tools/diagnosis/account.py"
SOFTWARE = "backend/app/tools/diagnosis/software.py"
ACCESS = "backend/app/tools/diagnosis/access.py"
B03 = "backend/app/graph/nodes/b03_classify.py"
B06 = "backend/app/graph/nodes/b06_diagnose.py"
B11 = "backend/app/graph/nodes/b11_slots.py"
CLARIFY = "backend/app/graph/nodes/clarify_wait.py"
SLOTS = "backend/app/domain/slots.py"
MESSAGES = "backend/app/domain/messages.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_policy_rules_all", "test_infer_account", "test_infer_software", "test_infer_access", "test_build_action_t20a",
        "test_slots_t20a", "test_diagnosis_tools_t20a", "test_facts_ast", "test_slots_facts", "test_nodes_t20a",
        "test_chain_t20a", "test_approvers_t20a", "test_target_phrase", "test_infer_vpn", "test_b06_diagnose", "test_b11_slots",
        "test_b03_classify", "test_rejection_text", "test_b16_approval_wait",
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

_R10_DAYS = '      {"fact": "action.params.duration_days", "op": "lte", "value": 90},\n'
_R10_LEVEL = '      {"fact": "action.facts.existing_permission_level", "op": "in", "value": ["read", "write"]}]},\n'
_R10_DESC = '"description": "Gia hạn quyền cũ (≤ 90 ngày) vào thư mục không nhạy cảm của phòng mình"'
_MAX_LEVEL = "            facts[\"existing_permission_level\"] = max(rows, key=lambda p: LEVEL_RANK[p.level]).level\n"
_IN_CATALOG = '        facts["in_catalog"] = entry is not None and entry.in_catalog\n'
_SAME_DEPT = '            facts["same_department"] = res.owner_department == status.department\n'
_RF_ACCOUNT = '    rf = requested_for_of("account", slots, requester_id)\n'
_RF_ACCESS = '    rf = requested_for_of("access", slots, requester_id)\n'
_SW_TARGET = '        return f"device:{device_id}", {\n'
_RF_BUILD = "    rf = requested_for_of(intent, slots, requester.user_id)\n"
_CHECK = "    _check_params(action_type, params)\n"
_GRANT_LEVEL = '    if action_type == "grant_permission":\n'
_LOCK_OTHER = 'lock_reason if lock_reason in LOCK_REASONS else "other"'
_B11_MISSING = "        missing = spec.missing(slots)  # T20a P4\n"
_B11_INFER = "            _, facts = module.infer(diag, requester_id=requester, slots=slots)\n"
_TOKEN = 'TOKEN_IN_TEXT = frozenset({"device_id", "error_code", "target_user", "resource_path"})\n'
_PHRASE = '    kind, _, ident = action.target.partition(":")\n'
_B6_FLAG = '        other = bool((state.get("ctx_flags") or {}).get("target_is_other"))  # Q-T20a-4: B3 đã đặt True thì giữ\n'
_B3_FLAG = '        flags = {"ctx_flags": {"target_is_other": True}} if "target_user" in dropped else {}  # Q-T20a-4\n'
_CLARIFY_FLAG = '        flags = {"ctx_flags": {"target_is_other": True}} if "target_user" in dropped else {}  # Q-T20a-6\n'

# `_hit` so theo TÊN test (khuôn mutate_t22a) — tên test T20a không trùng giữa các file.
I = C = S = A = ""
R = "test_bang_4_7_luat_a_den_f"
G = "test_g_chain_b3_b6_b11_b12"
G2 = "test_g2_other_persons_account_target_is_other"
G8 = f"{G}[g8-nv001-cap-cho-nv004-R12-deny-kem-R09]"
G10 = "test_g10_dropped_target_user_is_other_no_rule"
G11 = "test_g11_target_user_in_clarify_reply_is_other[g11-nguoi-khac-o-luot-tra-loi-khong-luat]"

UNIT: list[Mutation] = [
    Mutation("M-T20a-1 R10 bỏ điều kiện existing_permission_level",
             [one(POLICY_JSON, _R10_DAYS + _R10_LEVEL, _R10_DAYS[:-2] + "]},\n"),
              one(POLICY_JSON, _R10_DESC, _R10_DESC[:-1] + ' MUTATION M-T20a-1"')],
             UT, [f"{R}[r2-R10-existing_permission_level-full]", f"{R}[r3-R10-thieu-existing_permission_level]"]),
    Mutation("M-T20a-2 existing_permission_level lấy mức thấp nhất",
             [one(ACCESS, _MAX_LEVEL, _MAX_LEVEL.replace("= max(", "= min(")[:-1] + "  # MUTATION M-T20a-2\n")],
             UT, [f"{C}test_c4_highest_level_over_all_rows_same_path"]),
    Mutation("M-T20a-3 catalog 404 → không đặt in_catalog",
             [one(SOFTWARE, _IN_CATALOG, '        if entry is not None:  # MUTATION M-T20a-3\n'
                                         '            facts["in_catalog"] = entry.in_catalog\n')],
             UT, [f"{S}test_s3_photoshop_404_in_catalog_false_only"]),
    Mutation("M-T20a-4 same_department khi thư mục 404 → True",
             [one(ACCESS, _SAME_DEPT, _SAME_DEPT + '    elif path is not None and status is not None:  # MUTATION M-T20a-4\n'
                                                  '        facts["same_department"] = True\n')],
             UT, [f"{C}test_c5_unknown_folder_404_no_folder_facts"]),
    Mutation("M-T20a-5 infer_account/infer_access tra người gửi thay vì rf",
             [one(ACCOUNT, _RF_ACCOUNT, "    rf = requester_id  # MUTATION M-T20a-5\n"),
              one(ACCESS, _RF_ACCESS, "    rf = requester_id  # MUTATION M-T20a-5\n")],
             UT, [f"{I}test_i7_calls_use_target_user_not_requester", f"{I}test_i7_target_user_every_call_at_receiver_is_nv005",
                  f"{C}test_c8_calls_use_target_user", f"{C}test_c8_target_user_nv004_disabled_security", G2, G8]),
    Mutation("M-T20a-6 install_software đích user:",
             [one(ACTION, _SW_TARGET, '        return f"user:{rf}", {  # MUTATION M-T20a-6\n')],
             UT, [f"{A}test_a13_invariants[a13-install_software]", f"{G}[g3-nv001-cai-Zoom-khong-neu-may-R11]"]),
    Mutation("M-T20a-7 build_action bỏ target_user (rf luôn người gửi)",
             [one(ACTION, _RF_BUILD, "    rf = requester.user_id  # MUTATION M-T20a-7\n")],
             UT, [f"{A}test_a7_account_target_user_is_requested_for", f"{A}test_a7_access_grant_target_user_is_requested_for",
                  f"{A}test_a7_view_permissions_target_user", G2, G8]),
    Mutation("M-T20a-8 params chép mọi slot",
             [one(ACTION, _CHECK, "    params = {**params, **slots}  # MUTATION M-T20a-8\n")],
             UT, [f"{A}test_a8_free_text_slots_never_in_params", f"{A}test_a13_invariants[a13-reset_password]"]),
    Mutation("M-T20a-9 extend giữ permission_level",
             [one(ACTION, _GRANT_LEVEL, '    if action_type == "grant_permission" or "permission_level" in slots:  # MUTATION M-T20a-9\n'),
              one(ACTION, _CHECK, "    pass  # MUTATION M-T20a-9: bỏ lớp kiểm _check_params\n")],
             UT, [f"{A}test_a9_extend_never_carries_permission_level"]),
    Mutation("M-T20a-10 target_lock_reason lạ → bad_password",
             [one(ACCOUNT, _LOCK_OTHER, 'lock_reason if lock_reason in LOCK_REASONS else "bad_password"  # MUTATION M-T20a-10')],
             UT, [f"{I}test_i3_unknown_lock_reason_becomes_other"]),
    # ---- lượt 2 (DỪNG 2): node + slot + tin ----
    Mutation("M-T20a-11 B11 bỏ required_by_action",
             [one(B11, _B11_MISSING, "        missing = [s for s in spec.required if s not in slots]  # MUTATION M-T20a-11\n")],
             UT, ["test_p2_b11_grant_missing_duration_asks_duration", "test_p2_b11_grant_missing_duration_last_turn_e4",
                  "test_p2_b11_grant_only_action_asks_in_declared_order"]),
    Mutation("M-T20a-12 B11 giữ fact của B6 cho intent mới",
             [one(B11, _B11_INFER, "            _, fresh = module.infer(diag, requester_id=requester, slots=slots)\n"
                                   "            facts = fresh | dict(state.get(\"facts\") or {})  # MUTATION M-T20a-12\n")],
             UT, ["test_n3_b11_access_recomputes_all_facts_for_final_path",
                  "test_n3_b11_drops_stale_folder_facts_on_unknown_path",
                  "test_n3_account_b6_ad_lookup_b11_recomputes_for_email"]),
    Mutation("M-T20a-13 resource_path bỏ khỏi TOKEN_IN_TEXT",
             [one(SLOTS, _TOKEN, 'TOKEN_IN_TEXT = frozenset({"device_id", "error_code", "target_user"})  # MUTATION M-T20a-13\n')],
             UT, ["test_p5_target_slots_not_in_text_dropped[p5-resource_path-bia]"]),
    Mutation("M-T20a-14 target_phrase mọi đích → máy …",
             [one(MESSAGES, _PHRASE, _PHRASE + '    return f"máy {ident}" if DEVICE_ID.fullmatch(ident) else "máy của bạn"'
                                               '  # MUTATION M-T20a-14\n')],
             UT, ["test_m1_target_phrase[m1-user-nv005]", "test_m1_target_phrase[m1-folder-finance-Q3]",
                  "test_m2_b16_rejects_grant_permission_folder_phrase"]),
    Mutation("M-T20a-15 B6 ghi đè cờ target_is_other về False",
             [one(B06, _B6_FLAG, "        other = False  # MUTATION M-T20a-15\n")],
             UT, [G10, "test_n7_b6_keeps_target_is_other_from_b3[n7-vpn]", "test_n7_b6_keeps_target_is_other_from_b3[n7-account]",
                  "test_n7_b6_keeps_target_is_other_from_b3[n7-ablation]"]),
    Mutation("M-T20a-16 B3 không đặt cờ khi target_user bị bỏ",
             [one(B03, _B3_FLAG, _B3_FLAG.replace('"target_user" in dropped', "False")[:-1] + "  # MUTATION M-T20a-16\n")],
             UT, [G10]),
    Mutation("M-T20a-17 clarify_wait không bật cờ khi target_user bị bỏ",
             [one(CLARIFY, _CLARIFY_FLAG,
                  _CLARIFY_FLAG.replace('"target_user" in dropped', "False")[:-1] + "  # MUTATION M-T20a-17\n")],
             UT, [G11]),
]  # fmt: skip

MUTATIONS = UNIT
if "--only" in sys.argv:
    codes = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    MUTATIONS = [m for m in UNIT if m.name.split(" ", 1)[0] in codes]


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
