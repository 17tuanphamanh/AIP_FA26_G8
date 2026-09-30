"""Mutation chặng 3g (output guard, tin nhắn, B10 trả lời có trích dẫn, B11 hỏi lại, `clarify_wait`, `validate_targets`): áp
từng đột biến, chạy test, KHÔI PHỤC, so md5; in test đỏ của mỗi đột biến. Khuôn `mutate_3f.py` — không đọc `.env`, mã thoát 1
nếu có đột biến sống (trừ đột biến ghi "tương đương") hoặc không áp được. File luôn được khôi phục trong `finally`, cuối cùng so
md5 và `git diff --stat` với lúc đầu.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_3g.py                  # phần unit (sandbox, không Docker)
  uv run python scripts/mutation/mutate_3g.py --integration    # g1/g2/g23 trên Postgres THẬT — cần Docker
  uv run python scripts/mutation/mutate_3g.py --only "M-3g-7"  # chỉ đột biến có tên bắt đầu bằng tiền tố

Bảng: phase3 10.6 M-3g-1…6 + đề bài 3g M-3g-7…14 + PLAN-3g M-3g-15…17 (duyệt). Lệch với bảng (ghi PROGRESS):
- Một đột biến có thể sửa NHIỀU chỗ (M-3g-2: B10 bỏ gửi + `confirm_wait` gửi; M-3g-7: khoá `effects` bỏ `turn_id` + B11 bỏ
  `sub`) — mỗi chỗ phải khớp đúng số lần khai báo.
- M-3g-7 = bỏ `sub` VÀ `turn_id` (Q-3g-5). M-3g-7b = chỉ bỏ `sub`: TƯƠNG ĐƯƠNG về hành vi (khoá đã có `turn_id`, mỗi câu hỏi
  ở một lượt khác) — g13 phải XANH; chỉ test AST g25 (`sub` là f-string) đỏ. Không tính vào số sống/chết.
- M-3g-14 tách 3 lớp cắt hạn lượt mà lời gọi mới của 3g đi qua: 14a LLM gateway (b10_answer, b11_clarify_question), 14b
  registry (tool `validate_targets`), 14c `expand_for_answer`.
- M-3g-6 "e2e canary": 3g chưa có e2e (3h) — đo bằng g4 unit + node B10/B11 (P4).

Mỗi đột biến chạy TRỌN các file test của chặng (không chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.

Luật N3 (vá ở 3h, `n3.py`): trước đột biến đầu tiên (a) file đích còn chữ `MUTATION` → dừng; (b) chạy mốc xanh một lần mỗi lệnh
test — đỏ → dừng. Mọi file sau khi áp đột biến phải mang chữ `MUTATION` (thiếu → đột biến bị bỏ qua, tính là lỗi) — M-3g-4,
M-3g-7/7b, M-3g-11 trước đây thay chữ không để dấu, nay thêm dấu vô hại (`(x, "MUTATION …")[0]`, dòng chú thích).
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


ANSWER = "backend/app/domain/answer.py"
OUTPUT = "backend/app/guard/output.py"
EFFECTS = "backend/app/graph/effects.py"
B10 = "backend/app/graph/nodes/b10_route.py"
B11 = "backend/app/graph/nodes/b11_slots.py"
CLARIFY = "backend/app/graph/nodes/clarify_wait.py"
CONFIRM = "backend/app/graph/nodes/confirm_wait.py"
LLM_CLIENT = "backend/app/llm/client.py"
REGISTRY = "backend/app/tools/registry.py"
EXPAND = "backend/app/rag/expand.py"
UT = [
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_b10_route", "test_b11_slots", "test_output_guard", "test_redact_idempotent", "test_lineage",
        "test_side_effects_ast", "test_turn_budget", "test_tickets_api", "test_llm_prompts", "test_llm_config",
        "test_state_keys_ast", "test_b02_screen", "test_config_files",
    )
]  # fmt: skip
IT = [f"backend/tests/integration/{n}.py" for n in ("test_b10_pg", "test_b11_pg", "test_guard_pg")]


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ
    keep_green: tuple[str, ...] = ()  # đột biến tương đương: test hành vi PHẢI xanh
    equivalent: bool = False


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


_SEND_B10 = (
    "        ref = await effects.once(\n"
    '            state, "notify_user", deps.notifier.notify_user, state["ticket_id"], body, "confirm", step="B10",\n'
    "        )  # fmt: skip\n"
)
_WAIT_CONFIRM = '        ev = interrupt({"wait": "confirm"})\n'
_SEND_IN_WAIT = (
    '        answers = [m for m in state.get("conversation") or [] if m.get("kind") == "answer"]\n'
    "        if answers:  # MUTATION M-3g-2: gửi câu trả lời ở node chờ (trước interrupt — chạy lại mỗi lần resume)\n"
    "            await effects.once(\n"
    '                state, "notify_user", deps.notifier.notify_user, state["ticket_id"], answers[-1]["text"], "confirm",\n'
    '                step="B19",\n'
    "            )\n"
)
_GUARD_B10 = '        info["guard"] = deps.output_guard.violation(body)\n'
_ANCHORS = "        anchors = {c.chunk_id for c in chunks} & {b.anchor_chunk_id for b in evidence}\n"
_EXPANDED = (
    "        anchors = {f\"{b.anchor_chunk_id.rsplit('#', 1)[0]}#{int(b.anchor_chunk_id.rsplit('#', 1)[1]) + d}\" "
    "for b in evidence for d in (-1, 0, 1)}  # MUTATION M-3g-13 hậu kiểm trên bằng chứng đã mở rộng\n"
)
_SUB = '\n            sub=f"q{n}",'
_NO_SUB = "\n            # MUTATION bỏ sub"
_KEY = '        key=effect_key(state["ticket_id"], step, run.turn_id, loop_seq, kind, sub),\n'
_SANITIZE = "got.slots, text=text, allowed=frozenset(missing)"
_B11_ERRORS = 'for r in results if r.error is not None]:\n'

G2_UNIT = "test_g2_crash_after_b10_goto_then_recover_single_answer"
G13 = "test_g13_three_turns_still_missing_e4_exhausted"
G22_B10 = "test_g22_turn_budget_at_b10_answer_is_e2"
G23 = "test_g23_three_questions_three_distinct_effects_rerun_sends_nothing_pg"

UNIT = [
    Mutation("M-3g-1 cho trích dẫn chunk liền kề (cùng tài liệu)",
             [one(ANSWER, "    if not citations or not set(citations) <= anchors:\n",
                  '    if not citations or not {c.rsplit("#", 1)[0] for c in citations} <= '
                  '{a.rsplit("#", 1)[0] for a in anchors}:  # MUTATION M-3g-1\n')],
             pt(*UT), ["test_g3_check_citations", "test_g3_node_citation_outside_anchor_is_e3",
                       "test_g6_citing_neighbor_seen_in_expanded_evidence_is_e3"]),
    Mutation("M-3g-2 gửi câu trả lời trong confirm_wait thay vì B10",
             [one(B10, _SEND_B10, "        ref = None  # MUTATION M-3g-2: B10 không gửi\n"),
              one(CONFIRM, _WAIT_CONFIRM, _SEND_IN_WAIT + _WAIT_CONFIRM)],
             pt(*UT), ["test_g7_resume_confirm_wait_twice_single_answer",
                       "test_info_answer_sends_once_sets_confirm_deadline_and_lineage"]),
    Mutation("M-3g-3 B10 gọi notifier.notify_user thẳng, không qua effects.once",
             [one(B10, _SEND_B10,
                  '        ref = await deps.notifier.notify_user(state["ticket_id"], body, "confirm")  # MUTATION M-3g-3\n')],
             pt(*UT), ["test_graph_nodes_never_call_side_effects_directly", G2_UNIT,
                       "test_rerun_same_turn_sends_nothing_more_single_lineage"]),
    Mutation("M-3g-4 extract_slots không giới hạn allowed=missing",
             [one(CLARIFY, _SANITIZE, 'got.slots, text=text, allowed=(None, "MUTATION M-3g-4")[0]')],
             pt(*UT), ["test_g16_fact_in_reply_dropped_device_facts_from_tool"]),
    Mutation("M-3g-5 >= → > ở kiểm lượt hỏi",
             [one(B11, "        if turns >= deps.constants.MAX_CLARIFICATION_TURNS:\n",
                  "        if turns > deps.constants.MAX_CLARIFICATION_TURNS:  # MUTATION M-3g-5\n")],
             pt(*UT), [G13]),
    Mutation("M-3g-6 bỏ output guard (violation luôn None)",
             [one(OUTPUT, "    def violation(self, text: str) -> Violation | None:\n",
                  "    def violation(self, text: str) -> Violation | None:\n"
                  "        return None  # MUTATION M-3g-6 bỏ output guard\n")],
             pt(*UT), ["test_g4_four_cases", "test_g4_each_secret_rule_blocks", "test_g4_canary_case_and_l0_insensitive",
                       "test_g4_system_line_after_case_and_whitespace_changes", "test_g20_unit_question_with_canary_blocked",
                       "test_output_guard_blocks_before_sending", "test_g20_question_with_canary_blocked_e3_no_notify"]),
    Mutation("M-3g-7 khoá effects B11 không theo lượt (bỏ turn_id + bỏ sub)",
             [one(EFFECTS, _KEY, _KEY.replace("run.turn_id", '""').rstrip("\n") + "  # MUTATION M-3g-7\n"),
              (B11, _SUB, _NO_SUB, 2)],
             pt(*UT), [G13, "test_g25_b11_effects_keyed_per_question_turn"]),
    Mutation("M-3g-7b chỉ bỏ sub (khoá vẫn có turn_id) — TƯƠNG ĐƯƠNG",
             [(B11, _SUB, _NO_SUB, 2)],
             pt(*UT), ["test_g25_b11_effects_keyed_per_question_turn"], keep_green=(G13,), equivalent=True),
    Mutation("M-3g-8 bỏ output guard ở câu hỏi B11",
             [one(B11, '        info["guard"] = deps.output_guard.violation(q.text)\n',
                  '        info["guard"] = None  # MUTATION M-3g-8\n')],
             pt(*UT), ["test_g20_question_with_canary_blocked_e3_no_notify"]),
    Mutation("M-3g-9 giữ fact máy cũ khi đổi device_id",
             [one(B11, "        facts = kept | {k: v for k, v in fresh.items() if k in vpn.DEVICE_FACTS}\n",
                  "        facts = {k: v for k, v in fresh.items() if k in vpn.DEVICE_FACTS} | dict(state.get(\"facts\") or {})"
                  "  # MUTATION M-3g-9 fact máy cũ thắng\n")],
             pt(*UT), ["test_g21_switched_device_recomputes_device_facts"]),
    Mutation("M-3g-10 lưu/gửi LLM câu trả lời chưa che L1",
             [one(CLARIFY, "        text = deps.privacy.redact_text(raw).text  # P3: từ đây chỉ dùng bản ĐÃ CHE\n",
                  "        text = raw  # MUTATION M-3g-10 không che L1\n")],
             pt(*UT), ["test_g19_raw_reply_redacted_before_llm_and_conversation",
                       "test_extract_llm_errors_e2_reply_stored_redacted"]),
    Mutation("M-3g-11 sanitize_slots text=redacted_request thay vì câu trả lời",
             [one(CLARIFY, _SANITIZE,
                  'got.slots, text=(state["redacted_request"], "MUTATION M-3g-11")[0], allowed=frozenset(missing)')],
             pt(*UT), ["test_g12_two_devices_ask_then_unregistered_pc"]),
    Mutation("M-3g-12 lỗi tool validate_targets bị cho qua",
             [one(B11, _B11_ERRORS, "for r in results if False]:  # MUTATION M-3g-12\n")],
             pt(*UT), ["test_g24_validate_targets_tool_500_e2"]),
    Mutation("M-3g-13 hậu kiểm trích dẫn trên bằng chứng đã mở rộng thay vì top-5",
             [one(B10, _ANCHORS, _EXPANDED)],
             pt(*UT), ["test_g3_node_citation_outside_anchor_is_e3", "test_citing_evidence_anchor_outside_top5_is_e3",
                       "test_g6_citing_neighbor_seen_in_expanded_evidence_is_e3"]),
    Mutation("M-3g-14a LLM gateway bỏ cắt theo hạn lượt (b10_answer, b11_clarify_question)",
             [one(LLM_CLIENT, '        limit_s, call.turn_bound = window(role_left, self._clock, what=f"llm:{prompt.id}")',
                  "        limit_s, call.turn_bound = role_left, False  # MUTATION M-3g-14a")],
             pt(*UT), [G22_B10, "test_g22_turn_budget_at_clarify_question_e2"]),
    Mutation("M-3g-14b registry bỏ cắt theo hạn lượt (tool validate_targets)",
             [one(REGISTRY, "                return await handler(inp, cap_timeout(spec.timeout_s, self._clock, what=what))\n",
                  "                return await handler(inp, spec.timeout_s)  # MUTATION M-3g-14b\n")],
             pt(*UT), ["test_g22_turn_budget_at_validate_targets_tool_e2"]),
    Mutation("M-3g-14c expand_for_answer bỏ cắt theo hạn lượt",
             [one(EXPAND, '    limit_s, turn_bound = window(cfg.deadline_s, retriever._clock, what="rag:expand")  # 9.0\n',
                  "    limit_s, turn_bound = cfg.deadline_s, False  # MUTATION M-3g-14c\n")],
             pt(*UT), ["test_g22_turn_budget_at_expand_is_e2", "test_external_call_sites_use_turn_budget"]),
    Mutation("M-3g-15 cannot_answer bị bỏ qua (vẫn trả lời)",
             [one(ANSWER, '    if cannot_answer:\n        return "no_grounding"\n',
                  '    if False:  # MUTATION M-3g-15\n        return "no_grounding"\n')],
             pt(*UT), ["test_g3_check_citations", "test_q3g1_cannot_answer_is_e3_no_grounding"]),
    Mutation("M-3g-16 B10 gửi tin trước output guard",
             [one(B10, _GUARD_B10,
                  '        await effects.once(state, "notify_user", deps.notifier.notify_user, state["ticket_id"], body, '
                  '"confirm", step="B10")  # MUTATION M-3g-16\n' + _GUARD_B10)],
             pt(*UT), ["test_output_guard_blocks_before_sending"]),
    Mutation("M-3g-17 lạc đề không đặt lại 0 khi có slot sạch",
             [one(CLARIFY,
                  '        streak = 0 if clean and not got.off_topic else int(state.get("off_topic_streak") or 0) + 1\n',
                  '        streak = int(state.get("off_topic_streak") or 0) + (0 if clean and not got.off_topic else 1)'
                  "  # MUTATION M-3g-17\n")],
             pt(*UT), [G13]),
]  # fmt: skip

_BY_NAME = {m.name.split(" ", 1)[0]: m for m in UNIT}
INTEGRATION = [
    _BY_NAME["M-3g-2"]._replace(name="M-3g-2 (PG g1)", cmd=pt(*IT),
                                expect=["test_g1_resume_confirm_wait_twice_single_b10_notice_pg"]),
    _BY_NAME["M-3g-3"]._replace(name="M-3g-3 (PG g2)", cmd=pt(*IT),
                                expect=["test_g2_crash_after_b10_goto_rerun_same_turn_single_notice_single_lineage_pg"]),
    _BY_NAME["M-3g-5"]._replace(name="M-3g-5 (PG g23)", cmd=pt(*IT), expect=[G23]),
    _BY_NAME["M-3g-7"]._replace(name="M-3g-7 (PG g23)", cmd=pt(*IT), expect=[G23]),
    _BY_NAME["M-3g-17"]._replace(name="M-3g-17 (PG g23)", cmd=pt(*IT), expect=[G23]),
]

MUTATIONS = INTEGRATION if "--integration" in sys.argv else UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS if m.name.startswith(prefix)]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(test: str, failed: list[str]) -> bool:
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
