"""Mutation chặng T22a (phase5 mục 4.8, PLAN-T22a TQ-12) — 2 lượt. Mỗi đột biến áp lên file thật, chạy bộ test, khôi phục trong
`finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi
đột biến. JSON (`policy.json`): chữ `MUTATION` chèn vào `description` của luật bị phá (như `mutate_4b.py`).

  uv run python scripts/mutation/mutate_t22a.py                    # lượt hiện hành (unit, sandbox, không Docker)
  uv run python scripts/mutation/mutate_t22a.py --only M-T22a-8

Lượt 1 (DỪNG 1 — chưa có R01–R15, `rule_coverage.py` còn stub): M-T22a-8 (g1, g5), -9 (g4), -12 (h7). Lượt 2 (DỪNG 2 — bản này):
đủ 13 mã (M-T22a-1…12 + 5b) với kỳ vọng bảng 4.8, chỉnh theo chốt PLAN-T22a mục 11: M-T22a-10 → e15 (0, −1) thay d10/e14 (engine
so kiểu chặt: `"FULL"`, `1`, `"30"`, `True` không khớp dù lọt `fact_view` — lớp DSL chặn lần hai); M-T22a-11 → r1b (+ r3) vì 3 kịch bản
mẫu của r1 không có ca approval_required; M-T22a-3 → f8 (ca thiếu `license_paid`; f7 thiếu `in_catalog` vẫn không khớp R11).

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


CONTEXT = "backend/app/risk/context.py"
FACTS = "backend/app/domain/facts.py"
POLICY_JSON = "config/policy.json"
ENGINE = "backend/app/risk/policy_engine.py"
COVERAGE = "scripts/rule_coverage.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_policy_rules_all", "test_build_ctx_targets", "test_rule_coverage", "test_policy_rules_vpn",
        "test_hrule_4b_owner", "test_b12_assess", "test_config_files", "test_slots_facts", "test_policy_engine_signature",
        "test_tool_models_p7",
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

_OWNER = '        or (device_target and action.facts.get("device_owner_is_requester") is not True)\n'
_VALUE_SET = "        if facts[key] not in FACT_VALUE_SETS[key]:\n"
_PARAMS = '        "action.params": {k: v for k, v in action.params.items() if param_ok(k, v)},  # T22a P3: sai kiểu/ngoài tập = thiếu\n'
_COUNT = "            by_family.setdefault(r.family, Counter())[r.decision] += 1\n"
_OTHER = '      {"fact": "ctx.target_is_other", "op": "is_false"},\n'
_R01_PRIV = _OTHER + '      {"fact": "action.facts.target_account_privilege", "op": "eq", "value": "standard_user"},\n'
_R02_LOCK = '      {"fact": "action.facts.target_lock_reason", "op": "eq", "value": "bad_password"},\n'
_R11_PAID = '      {"fact": "action.facts.license_paid", "op": "is_false"},\n'
_R10_STATUS = '      {"fact": "action.facts.target_user_status", "op": "in", "value": ["active", "probation"]},\n'
# T20a (PLAN-T20a TQ-14): R10 thêm điều kiện cuối `existing_permission_level` → dòng `duration_days` không còn đóng `]},`.
_R10_DAYS = '      {"fact": "action.params.duration_days", "op": "lte", "value": 90},\n'
_R10_SAME = '      {"fact": "action.facts.same_department", "op": "is_true"},\n'
_R12_TYPE = '{"id": "R12", "type": "deny",'
_R09_ACTION = '{"id": "R09", "type": "approval_required", "intent": "access", "action": ["grant_permission", "extend_permission"],'
DESC = {
    "R01": "Đặt lại mật khẩu tài khoản thường của chính mình",
    "R02": "Mở khoá tài khoản thường của chính mình bị khoá do nhập sai mật khẩu",
    "R09": "Cấp/gia hạn quyền vào tài nguyên phòng ban khác (vượt cấp quản lý) cần người duyệt",
    "R10": "Gia hạn quyền cũ (≤ 90 ngày) vào thư mục không nhạy cảm của phòng mình",
    "R11": "Cài phần mềm miễn phí trong danh mục lên máy của mình",
    "R12": "Cấm cấp quyền cho tài khoản bị vô hiệu hoá vì lý do bảo mật",
}


def mark(rule_id: str, code: str) -> tuple[str, str, str, int]:
    """JSON không có chú thích → chữ `MUTATION` chèn vào `description` của luật bị phá (N3a)."""
    old = f'"description": "{DESC[rule_id]}"'
    return one(POLICY_JSON, old, old[:-1] + f' MUTATION {code}"')


B = "test_bang_4_7_luat_a_den_f"

G = "test_g_build_ctx_target_is_other_theo_dich"
G1, G4, G5 = (f"{G}[g1-account-tu-lam-khong-fact-may-False]", f"{G}[g4-vpn-device-thieu-fact-chu-may-True]",
              f"{G}[g5-access-tu-xem-False]")  # fmt: skip
H7 = "test_h7_check_facts_tap_gia_tri_target_user_status"

UNIT: list[Mutation] = [
    Mutation("M-T22a-1 R01 bỏ điều kiện privilege",
             [one(POLICY_JSON, _R01_PRIV, _OTHER), mark("R01", "M-T22a-1")],
             UT, [f"{B}[a2-R01-thieu-target_account_privilege]", f"{B}[a8-R01-privilege-elevated]"]),
    Mutation("M-T22a-2 R02 bỏ lock_reason",
             [one(POLICY_JSON, _R02_LOCK, ""), mark("R02", "M-T22a-2")],
             UT, [f"{B}[b2-R02-lock_reason-admin-ho-L3]", f"{B}[b2-R02-lock_reason-inactivity-ho-L3]"]),
    Mutation("M-T22a-3 R11 bỏ license_paid is_false",
             [one(POLICY_JSON, _R11_PAID, ""), mark("R11", "M-T22a-3")],
             UT, [f"{B}[f8-R11-thieu-license_paid]"]),
    Mutation("M-T22a-4 R10 bỏ duration_days lte 90",
             [one(POLICY_JSON, _R10_DAYS, ""), mark("R10", "M-T22a-4")],
             UT, [f"{B}[e2-R10-180-ngay-ho-L4]", f"{B}[e4-R10-91-ngay]"]),
    Mutation("M-T22a-5 R10 bỏ same_department is_true",
             [one(POLICY_JSON, _R10_SAME, ""), mark("R10", "M-T22a-5")],
             UT, [f"{B}[e8-R10-thieu-same_department]"]),
    Mutation("M-T22a-5b R10 bỏ target_user_status in [active, probation]",
             [one(POLICY_JSON, _R10_STATUS, ""), mark("R10", "M-T22a-5b")],
             UT, [f"{B}[e12b-R10-disabled-thieu-target_disable_reason]"]),
    Mutation("M-T22a-6 R12 deny → approval_required",
             [one(POLICY_JSON, _R12_TYPE, '{"id": "R12", "type": "approval_required",'), mark("R12", "M-T22a-6")],
             UT, [f"{B}[d6-R12-disabled-security-deny]", f"{B}[d7-R12+R07-chat-nhat-thang-deny]",
                  f"{B}[e13-R12-extend-deny]"]),
    Mutation("M-T22a-7 R09 chỉ grant_permission",
             [one(POLICY_JSON, _R09_ACTION, _R09_ACTION.replace('["grant_permission", "extend_permission"]',
                                                                '"grant_permission"')),
              mark("R09", "M-T22a-7")],
             UT, [f"{B}[e6-R09-extend-khac-phong]"]),
    Mutation("M-T22a-8 build_ctx áp vế chủ máy cho mọi đích",
             [one(CONTEXT, _OWNER, '        or action.facts.get("device_owner_is_requester") is not True  # MUTATION M-T22a-8\n')],
             UT, [G1, G5, f"{B}[a1-R01-khop]", f"{B}[c1-R06-khop]"]),
    Mutation("M-T22a-9 build_ctx bỏ vế chủ máy",
             [one(CONTEXT, _OWNER, "        or False  # MUTATION M-T22a-9\n")],
             UT, [G4, f"{B}[f11-R11-thieu-device_owner_is_requester]"]),
    Mutation("M-T22a-10 fact_view nhận action.params sai kiểu/ngoài tập",
             [one(ENGINE, _PARAMS, '        "action.params": dict(action.params),  # MUTATION M-T22a-10\n')],
             UT, [f"{B}[e15-R10-duration_days-0]", f"{B}[e15-R10-duration_days-am-1]"]),
    Mutation("M-T22a-11 rule_coverage đếm approval_required vào none",
             [one(COVERAGE, _COUNT, '            by_family.setdefault(r.family, Counter())'
                                    '["none" if r.decision == "approval_required" else r.decision] += 1  # MUTATION M-T22a-11\n')],
             UT, ["test_r1b_approval_required_khong_bi_dem_vao_none", "test_r3_fact_lech_seed_canh_bao_thoat_0"]),
    Mutation("M-T22a-12 check_facts bỏ kiểm tập giá trị",
             [one(FACTS, _VALUE_SET, "        if False:  # MUTATION M-T22a-12\n")],
             UT, [H7]),
]  # fmt: skip

MUTATIONS = UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in UNIT if m.name.startswith(prefix)]


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
