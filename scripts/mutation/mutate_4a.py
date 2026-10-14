"""Mutation chặng 4a — S0 (Q-4-U A+, D-34; phase4 mục 4.0 + chốt MẪU A S0-A1, S0-A3): B9 chỉ cho câu trả lời, căn cứ hành động
= `procedure_doc` (B11), cờ `GROUNDING_GATE_ACTIONS`, ghi chú bàn giao đánh dấu tài liệu dưới ngưỡng. Khuôn `mutate_3h.py` + luật N3
(`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần mỗi lệnh test — đỏ → dừng; mọi file đã đột biến mang chữ
`MUTATION`. Áp từng đột biến, chạy test, KHÔI PHỤC, so md5 + `git diff --stat`. Không đọc `.env`. Mã thoát 1 nếu có đột biến
sống (trừ đột biến ghi "tương đương") hoặc không áp được; 2 nếu N3 dừng.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_4a.py                  # phần unit (sandbox, không Docker) — 1 lượt (tầng B)
  uv run python scripts/mutation/mutate_4a.py --e2e            # e2e cổng 3 (s8, h7) — Docker, không bắt buộc
  uv run python scripts/mutation/mutate_4a.py --integration    # c5 + procedure_available trên Qdrant thật — Docker, không bắt buộc
  uv run python scripts/mutation/mutate_4a.py --only "M-S0-5"
  uv run python scripts/mutation/mutate_4a.py --hmac           # DỪNG 2 mục 4.6 M-4a-1, 2 + Q-4a-5 M-4a-3, 4 + Q-4a-6 M-4a-5…8

Bảng: phase4 4.0 M-S0-1…8 + chốt S0-A1 M-S0-9 + chốt Q-4a-1 M-S0-10. Ghi chú:
- M-S0-1 (bỏ ngưỡng nhánh info): e2e h7 (s7) VẪN XANH — preset h7 cho `b10_answer` trả `cannot_answer` → E3 `no_grounding` ở
  B10 (lớp thứ hai). Unit s1/s4 bắt; lượt `--e2e` ghi "tương đương" với h7.
- M-S0-4 (kiểm ngưỡng SAU `b10_answer`): E3 vẫn ra nhưng đã tốn `expand` + `b10_answer` → s1 đỏ vì đếm lời gọi.

Mỗi đột biến chạy TRỌN các file test của chặng (không chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.
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


B10 = "backend/app/graph/nodes/b10_route.py"
B11 = "backend/app/graph/nodes/b11_slots.py"
B12 = "backend/app/graph/nodes/b12_assess.py"
FILTERS = "backend/app/rag/filters.py"
HANDOFF = "backend/app/audit/handoff.py"
AUTH = "backend/app/auth/service.py"
USER_SYNC = "backend/app/auth/user_sync.py"  # Phase 4 4b P5: `_upsert`/`_carry_ghost_lock` tách từ service.py
USERNAME_HASH = "backend/app/auth/username_hash.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_s0_grounding", "test_b08_retrieve", "test_b10_route", "test_b11_slots", "test_b12_assess", "test_b20_audit",
        "test_final_handoff", "test_gate3", "test_turn_budget", "test_config_files", "test_rag_retriever", "test_rag_filters",
        "test_rag_expand", "test_graph_static",
    )
])  # fmt: skip
AUTH_UT = pt("backend/tests/unit/test_auth_username_hash.py", "backend/tests/unit/test_auth_login.py",
             "backend/tests/unit/test_user_sync.py")  # 4b: AdUserSync dùng chung auth + B15
E2E = pt("backend/tests/e2e/test_gate3_vpn.py", "-k", "s8 or h7 or h6 or h2")
IT = pt("backend/tests/integration/test_b08_pg.py")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ
    keep_green: tuple[str, ...] = ()  # đột biến tương đương (với bộ test này): test hành vi PHẢI xanh
    equivalent: bool = False


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_INFO_GATE = "        if not above:  # B9 (S0-P2): câu trả lời cần đoạn KB đạt ngưỡng — kiểm TRƯỚC expand/b10_answer\n"
_INFO_BLOCK = (
    _INFO_GATE
    + "            return await goto(\n"
    + '                state, S_ESCALATED, next_node="b20_audit", step="B9", event="no_evidence", audit_detail=info,\n'
    + '                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="no_grounding",\n'
    + "                kb_version=kb_version,  # cột audit_logs.kb_version như dòng B9 cũ ở B8 (soát NGHI-5)\n"
    + "            )  # fmt: skip\n"
)
_AFTER_ANSWER = '        info["prompt"], info["trimmed_evidence"] = f"{meta.prompt_id}@{meta.prompt_version}", meta.trimmed_evidence\n'
_ACTION_GATE = "            if deps.grounding_gate_actions and not above:  # S0-P11: ablation — hành vi 3h (B9 chặn cả hành động)\n"
_ABOVE = "    above = bool(chunks) and score is not None and score >= threshold\n"
_EVIDENCE = (  # 6C: khối nằm trong `if needs_llm(...)` của B12 → thụt 16 (đồng bộ chuỗi gốc, giữ ý đột biến)
    "                evidence = evidence_for_estimator(\n"
    '                    state.get("retrieved") or [], state.get("retrieval_score"), deps.constants.RETRIEVAL_THRESHOLD\n'
    "                )  # S0-P9\n"
)
_PROCEDURE = "        if not check.available:\n"
_PROC_FILTER = '    return query_filter(role, FieldCondition(key="doc_id", match=MatchValue(value=doc_id)))'
_KB_LINE = "    template = KB_ABOVE_THRESHOLD if score is not None and score >= threshold else KB_BELOW_THRESHOLD\n"
_NO_PROC_NOTE = "        parts.append(NO_PROCEDURE_NOTE)\n"

S1 = "test_s1_info_below_threshold_e3_at_b9_without_expand_or_answer"
S4 = "test_s4_info_no_chunks_e3_without_expand"
S2S3 = "test_s2_s3_action_goes_to_b11_regardless_of_score"
S2G = "test_s2_graph_low_score_action_reaches_b12_not_b9"
S13 = "test_s13_procedure_doc_disabled_in_kb_e3_no_procedure"
S13G = "test_s13_graph_no_procedure_zero_writes_zero_approvals_handoff"
S15 = "test_s15_flag_on_action_below_threshold_e3_like_3h"
H7 = "test_h7_tc16_no_kb_e3_no_grounding_template"

UNIT: list[Mutation] = [
    Mutation("M-S0-1 bỏ kiểm ngưỡng ở nhánh info",
             [one(B10, _INFO_GATE, "        if False:  # MUTATION M-S0-1 bỏ ngưỡng nhánh info\n")],
             UT, [S1, S4, "test_s1b_info_missing_or_nan_score_is_below_threshold_fail_closed",
                  "test_s4b_info_high_score_but_no_chunks_is_e3"]),
    Mutation("M-S0-2 áp ngưỡng cho nhánh action (bất kể cờ)",
             [one(B10, _ACTION_GATE, "            if not above:  # MUTATION M-S0-2 áp ngưỡng cho hành động\n")],
             UT, [S2S3, S2G, S13G]),
    Mutation("M-S0-3 ngưỡng `>=` → `>` (bằng ngưỡng bị chặn)",
             [one(B10, _ABOVE, "    above = bool(chunks) and score is not None and score > threshold  # MUTATION M-S0-3\n")],
             UT, ["test_s5_info_score_equal_threshold_answers", "test_s15_flag_on_action_above_threshold_still_b11"]),
    Mutation("M-S0-4 kiểm ngưỡng nhánh info SAU expand/b10_answer",
             [one(B10, _INFO_BLOCK, "        # MUTATION M-S0-4 — kiểm ngưỡng dời xuống sau b10_answer\n"),
              one(B10, _AFTER_ANSWER, _AFTER_ANSWER + _INFO_BLOCK)],
             UT, [S1, S4]),
    Mutation("M-S0-5 B12 truyền thẳng state[\"retrieved\"] cho estimator",
             [one(B12, _EVIDENCE, '                evidence = state.get("retrieved") or []  # MUTATION M-S0-5\n')],
             UT, ["test_s6_b12_reads_retrieval_only_through_evidence_for_estimator",
                  "test_s11_b12_passes_only_grounded_chunks_to_estimator[kb_gap]"]),
    Mutation("M-S0-6 bỏ kiểm procedure_available ở B11",
             [one(B11, _PROCEDURE, "        if False:  # MUTATION M-S0-6 bỏ kiểm quy trình\n")],
             UT, [S13, S13G, "test_m_s0_7_restricted_procedure_employee_e3_l1_passes",
                  "test_s0a3_alias_switched_to_kb_without_procedure_after_b8_is_e3"]),
    Mutation("M-S0-7 procedure_available không dùng base_filter",
             [one(FILTERS, _PROC_FILTER,
                  '    return Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])  # MUTATION M-S0-7')],
             UT, ["test_m_s0_7_restricted_procedure_employee_e3_l1_passes", S13,
                  "test_retriever_procedure_available_filters_like_retrieve[restricted-employee]",
                  "test_retriever_procedure_available_filters_like_retrieve[tat-employee]",
                  "test_s12_procedure_in_current_kb_reaches_b12_and_audits_doc"]),
    Mutation("M-S0-8 cờ GROUNDING_GATE_ACTIONS đảo nghĩa",
             [one(B10, _ACTION_GATE, "            if not deps.grounding_gate_actions and not above:  # MUTATION M-S0-8\n")],
             UT, [S15, S2S3, S2G]),
    Mutation("M-S0-9 ghi chú bàn giao luôn in câu cũ \"tra được\" (S0-A1)",
             [one(HANDOFF, _KB_LINE, "    template = KB_ABOVE_THRESHOLD  # MUTATION M-S0-9\n")],
             UT, ["test_s0a1_handoff_kb_docs_below_threshold_are_marked_not_grounds",
                  "test_s0a1_b20_handoff_marks_below_threshold_docs", S13G]),
    Mutation("M-S0-10 ghi chú bàn giao no_procedure bỏ câu \"không phải căn cứ\" (Q-4a-1)",
             [one(HANDOFF, _NO_PROC_NOTE, "        pass  # MUTATION M-S0-10\n")],
             UT, ["test_q4a1_no_procedure_note_only_for_no_procedure[no_procedure]",
                  "test_q4a1_no_procedure_after_grounded_retrieval_handoff_says_not_grounds"]),
]  # fmt: skip

_BY_NAME = {m.name.split(" ", 1)[0]: m for m in UNIT}
E2E_MUTATIONS = [
    _BY_NAME["M-S0-1"]._replace(name="M-S0-1 (e2e h7 — lớp 2 cannot_answer vẫn E3)", cmd=E2E, expect=[], keep_green=(H7,),
                                equivalent=True),
    _BY_NAME["M-S0-2"]._replace(name="M-S0-2 (e2e s8)", cmd=E2E,
                                expect=["test_s8_tc09_low_rerank_score_still_pending_approval_no_write"]),
]  # fmt: skip
INTEGRATION = [
    _BY_NAME["M-S0-1"]._replace(name="M-S0-1 (PG/Qdrant c5)", cmd=IT, expect=["test_c5_mfa_question_gives_e3_no_grounding"]),
    _BY_NAME["M-S0-7"]._replace(name="M-S0-7 (Qdrant thật)", cmd=IT,
                                expect=["test_s0_procedure_available_on_real_qdrant[tat]",
                                        "test_s0_procedure_available_on_real_qdrant[restricted-employee]"]),
]  # fmt: skip

_STORED = "        return stored_username(username, known=user is not None, key=self._username_key)\n"
_COUNT_LOCK = (
    "        return await self.store.count_failures(self._failure_keys(username, user), since) >= self.config.max_failures\n"
)
_COUNT_THRESHOLD = "            self._failure_keys(username, user), now - self.config.failure_window\n"
_FAILURE_KEYS = "    return (username, hashed) if known else (hashed,)\n"  # 4b: hàm thuần `username_hash.failure_keys`
_DERIVE = "    return hmac.new(jwt_signing_key, USERNAME_KEY_LABEL, hashlib.sha256).digest()\n"
_CARRY_IF = "        if previous_role is None:  # dòng VỪA tạo bởi chính lời gọi này (kết quả INSERT … ON CONFLICT — AuthStore.upsert_user)\n"
_CARRY_COUNT = "        failures = await self.store.count_failures(keys, since)\n"
_CARRY_GE = "        if failures >= self.lock.max_failures:\n"
_CARRY_UNTIL = "            until = (last or now) + self.lock.lockout\n"
Q4A6_CARRY = ["test_q4a6a_ghost_lock_carried_to_new_row_blocks_before_ad", "test_q4a6e_verbatim_and_hashed_failures_sum",
              # 4b (phase4 4.10 #11): cùng đột biến phải giết cả test mức AdUserSync (đường B15 ensure dùng chung)
              "test_a_ghost_lock_carried_to_new_row_without_new_event",
              "test_a_ghost_lock_carried_when_row_created_as_manager_in_chain"]
Q4A5 = ["test_q4a5a_ghost_failures_count_after_own_first_login",
        "test_q4a5b_ghost_failures_count_after_row_created_by_ensure_manager[binh.tt-lan.dt]",
        "test_q4a5b_ghost_failures_count_after_row_created_by_ensure_manager[ha.lt-quan.tm]"]  # fmt: skip
HMAC = [  # phase4 mục 4.6 (mutation tay 2 cái — HMAC) + chốt Q-4a-5 (M-4a-3)
    Mutation("M-4a-1 username ma lưu nguyên văn",
             [one(AUTH, _STORED, "        return username  # MUTATION M-4a-1\n")],
             AUTH_UT, ["test_4a1_ghost_username_is_stored_hashed_never_verbatim",
                       "test_4a1_ghost_lock_event_and_alert_are_hashed",
                       "test_q4a5c_role_unmappable_username_attempted_follows_users_row"]),
    Mutation("M-4a-2 ghi dùng băm nhưng đếm khoá dùng chuỗi gốc",
             [one(AUTH, _COUNT_LOCK,
                  "        return await self.store.count_failures((username,), since) >= self.config.max_failures  # MUTATION\n"),
              one(AUTH, _COUNT_THRESHOLD, "            (username,), now - self.config.failure_window  # MUTATION\n")],
             AUTH_UT, ["test_4a3_ghost_locked_after_5_failures_like_real_user",
                       "test_locked_ghost_username_responds_exactly_like_locked_real_user"]),
    Mutation("M-4a-3 người đã có dòng users chỉ đếm nguyên văn (mất lần sai lưu băm trước chuyển tiếp — Q-4a-5)",
             [one(USERNAME_HASH, _FAILURE_KEYS, "    return (username,) if known else (hashed,)  # MUTATION M-4a-3\n")],
             AUTH_UT, [*Q4A5, "test_b_verbatim_and_hashed_failures_sum"]),
    Mutation("M-4a-4 khoá HMAC = thẳng khoá ký (mất tách miền Q-4-S — security-reviewer lượt 2, H6)",
             [one(USERNAME_HASH, _DERIVE, "    return jwt_signing_key  # MUTATION M-4a-4\n")],
             AUTH_UT, ["test_4a4_known_answer_independent_of_product_code"]),
    # Q-4a-6 (chốt (ii)): mang khoá trượt của username ma sang `locked_until` khi dòng users VỪA tạo
    Mutation("M-4a-5 bỏ phép đếm lúc tạo dòng",
             [one(USER_SYNC, _CARRY_COUNT, "        failures = 0  # MUTATION M-4a-5\n")], AUTH_UT, Q4A6_CARRY),
    Mutation("M-4a-6 đủ ngưỡng: >= thành >",
             [one(USER_SYNC, _CARRY_GE, "        if failures > self.lock.max_failures:  # MUTATION M-4a-6\n")], AUTH_UT, Q4A6_CARRY),
    Mutation("M-4a-7 đếm cả khi dòng đã tồn tại",
             [one(USER_SYNC, _CARRY_IF, "        if True:  # MUTATION M-4a-7\n")],
             AUTH_UT, ["test_q4a6d_existing_row_upsert_neither_counts_nor_overwrites_lock",
                       "test_c_existing_row_neither_counts_nor_overwrites_lock"]),
    Mutation("M-4a-8 locked_until tính từ now() thay vì lần sai cuối",
             [one(USER_SYNC, _CARRY_UNTIL, "            until = now + self.lock.lockout  # MUTATION M-4a-8\n")],
             AUTH_UT, Q4A6_CARRY),
]  # fmt: skip

MUTATIONS = (
    E2E_MUTATIONS if "--e2e" in sys.argv else INTEGRATION if "--integration" in sys.argv
    else HMAC if "--hmac" in sys.argv else UNIT
)  # fmt: skip
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
        broke = [g for g in m.keep_green if _hit(g, failed)]
        if m.equivalent:
            status = "TƯƠNG ĐƯƠNG — hành vi sống" if not broke else "KHÔNG tương đương (test hành vi đỏ)"
        else:
            status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
            bad += bool(missing)
        print(f"{m.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing}")
        if broke:
            print(f"    test hành vi đáng lẽ xanh: {broke}")
        if (missing and not m.equivalent) or broke or (not failed and out.returncode != 0):
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
