"""Mutation chặng T20b (phase5 mục 5.2.9, PLAN-T20b S9/S16) — khuôn `mutate_t24.py`. Mỗi đột biến áp lên file thật, chạy bộ test,
khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một
lần trước khi đột biến.

  uv run python scripts/mutation/mutate_t20b.py                      # lượt hiện hành (unit, sandbox, không Docker)
  uv run python scripts/mutation/mutate_t20b.py --only M-T20b-3
  uv run python scripts/mutation/mutate_t20b.py --only M-T20b-1,M-T20b-9   # nhiều mã, so ĐÚNG mã (không theo tiền tố)

Lượt 1 (DỪNG 1): M-T20b-1…10 (mã có đích đã code ở DỪNG 1). Lượt 2 (DỪNG 2 — bản này): đủ 14 mã = M-T20b-1…10 lần 2 + M-T20b-11 (`/reply`
bỏ `validate` items ≡ awaiting), -12 (`parent_wait` không `goto` quay lại sau `interrupt`), -13 (`after_turn` chỉ đánh thức khi con kết
thúc), -14 (cờ `target_is_other` của một ý áp cho MỌI con — "con kế thừa ctx_flags của ý khác").
- M-T20b-4 "con ở approval_wait tính là đã dừng" = `stopped()` luôn True (con chờ duyệt không có notice nào).
- M-T20b-6 đích là `SqlDeadlineStore` (SQL) — test n4 dùng kết nối GIẢ qua `current_tx` (PLAN TQ-7) nên đỏ được trong sandbox.
- M-T20b-7 "không đánh dấu delivered_round" = `parent_wait` truyền danh sách notice rỗng cho `deliver_round`.
- M-T20b-8 đảo ưu tiên ở cả hai chỗ phụ thuộc thứ tự: dòng MIXED và nhãn khi có đủ 3 loại.
- M-T20b-10 bỏ CẢ hai lớp chống giao lại: kiểm node/trạng thái trong `ChildOps.deliver` và `peek("child_event")` ở `parent_reply_wait`.

Sau duyệt MẪU B DỪNG 2 (Q-T20b-8…12): chạy lại 12 mã có file đích vừa sửa (`--only` M-T20b-1…4,6…12,14); chuỗi đích M-T20b-3
(`ref = …`, thêm `intents`/`intent_type` — Q-T20b-12) và M-T20b-11 (`redacted.items` — Q-T20b-8) cập nhật theo code.

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


B03 = "backend/app/graph/nodes/b03_classify.py"
CHILDREN_DOMAIN = "backend/app/domain/children.py"
NOTIFY = "backend/app/notify/child.py"
RUNTIME = "backend/app/db/runtime.py"
PARENT_WAIT = "backend/app/graph/nodes/parent_wait.py"
REPLY_WAIT = "backend/app/graph/nodes/parent_reply_wait.py"
CHILD_OPS = "backend/app/graph/children.py"
API = "backend/app/api/tickets.py"
RUNNER = "backend/app/graph/runner.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_t20b_split", "test_t20b_seed", "test_t20b_notify", "test_t20b_wake", "test_t20b_parent", "test_t20b_reply",
        "test_t20b_digest", "test_t20b_flows", "test_t20b_api", "test_t20b_scan", "test_t20b_resolver", "test_t20b_s10_fixes",
        "test_t20b_q5_q6", "test_t20b_dung2_fixes", "test_gate5", "test_b03_classify",
        "test_side_effects_ast", "test_state_keys_ast", "test_graph_static", "test_graph_runtime", "test_b20_audit",
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

_SPLIT_LOOP = "        for i, (it, verdict) in enumerate(zip(intents, verdicts, strict=True), start=1):\n"
_SPAN_TEXT = "        slots, dropped = sanitize_slots(deps.slots.intents[it.type], raw, text=l0(it.span))  # P2: text = span của ý\n"
_CREATE = (
    "            ref = await effects.once(\n"
    '                state, "child_create", deps.tickets.create_child, cid, parent_id=parent,\n'
    '                redacted_request=seeds[cid]["redacted_request"], created_at=run.clock.now(), step="B5", sub=cid,\n'
    "                intents=len(intents), intent_type=it.type,\n"
    "            )  # fmt: skip\n"
)
_STOPPED = '    return view.final_state is not None or any(n.needs != "none" for n in view.pending)\n'
_NOTIFY_BRANCH = "        if parent_id is None:  # ticket thường / cha: như cũ\n"
_CHILD_SKIP = "        if who is not None and who.parent_ticket_id is not None:\n"
_DELIVER_IDS = '            state, "notify_user", deps.tickets.deliver_round, state["ticket_id"], rnd, digest.notice_ids,\n'
_MIXED = '        return S_ESCALATED, "MIXED"\n'
_THREE = '    return S_RESOLVED, "PARTIALLY_ESCALATED" if esc else "PARTIALLY_REJECTED"\n'
_DONE = '            done: dict[str, Any] = {"aggregate_status": agg, "parent_round": rnd, "conversation": [digest.msg]}\n'
_DELIVER_CHECK = '                    if snap.values.get("status") != status or snap.next != (node,):\n'
_VALIDATE = '            session_id=p.session_id, wait_node="parent_reply_wait", validate=_items_match(redacted.items),\n'
_WOKEN = '            return await goto(state, S_CLASSIFYING, next_node="parent_wait", step="B5", event="parent_woken")\n'
_STOPS = 'CHILD_STOPS = frozenset({None, "clarify_wait", "confirm_wait"})'
_FLAG = '        if "target_user" in dropped:  # Q-T20a-4 áp TỪNG con\n'
_EVENT_PEEK = '            if await effects.peek(state, "child_event", step="B5", sub=sub) is not None:\n'

UNIT = [
    Mutation("M-T20b-1 ý out_of_scope bị bỏ im lặng (không tạo con E1)",
             [one(B03, _SPLIT_LOOP, "        for i, (it, verdict) in enumerate([(a, b) for a, b in zip(intents, verdicts, strict=True) "
                                    'if b != "out_of_scope"], start=1):  # MUTATION M-T20b-1\n')],
             UT, ["test_v2_one_runnable_one_out_of_scope_splits", "test_tc32_out_of_scope_child_e1_immediately_partially_escalated"]),
    Mutation("M-T20b-2 sanitize_slots(text=cả câu) thay vì span",
             [one(B03, _SPAN_TEXT, _SPAN_TEXT.replace("text=l0(it.span))", "text=text)").rstrip("\n") + "  # MUTATION M-T20b-2\n")],
             UT, ["test_v6_slot_only_in_other_span_dropped"]),
    Mutation("M-T20b-3 child_create gọi thẳng, không effects.once",
             [one(B03, _CREATE, "            ref = await deps.tickets.create_child(  # MUTATION M-T20b-3\n"
                                '                cid, parent_id=parent, redacted_request=seeds[cid]["redacted_request"], '
                                "created_at=run.clock.now(), intents=len(intents), intent_type=it.type,\n"
                                "            )  # fmt: skip\n")],
             UT, ["test_k1_crash_after_child_create_before_parent_checkpoint"]),
    Mutation("M-T20b-4 con ở approval_wait tính là đã dừng",
             [one(CHILDREN_DOMAIN, _STOPPED, "    return True  # MUTATION M-T20b-4\n")],
             UT, ["test_p1_one_child_stopped_other_in_approval_wait_parent_waits_zero_messages",
                  "test_tc34_two_children_one_needs_approval_all_resolved"]),
    Mutation("M-T20b-5 notifier của con gửi thẳng (không ghi child_notices)",
             [one(NOTIFY, _NOTIFY_BRANCH, "        if True:  # MUTATION M-T20b-5\n")],
             UT, ["test_n1_n2_child_notify_writes_notice_not_inner", "test_n1_n4_graph_child_b18_notice_no_message_no_deadline"]),
    Mutation("M-T20b-6 con đặt hạn riêng",
             [one(RUNTIME, _CHILD_SKIP, "        if False:  # MUTATION M-T20b-6\n")],
             UT, ["test_n4_sql_child_skip_no_wait_deadlines_write"]),
    Mutation("M-T20b-7 không đánh dấu delivered_round",
             [one(PARENT_WAIT, _DELIVER_IDS, _DELIVER_IDS.replace("digest.notice_ids,", "(),").rstrip("\n") + "  # MUTATION M-T20b-7\n")],
             UT, ["test_p2_all_stopped_confirm_only_one_digest_round1", "test_p3_rerun_after_sent_no_resend_no_remark"]),
    Mutation("M-T20b-8 aggregate_children đảo ưu tiên (REJECTED > ESCALATED)",
             [one(CHILDREN_DOMAIN, _MIXED, '        return S_REJECTED, "MIXED"  # MUTATION M-T20b-8\n'),
              one(CHILDREN_DOMAIN, _THREE, '    return S_RESOLVED, "PARTIALLY_REJECTED" if rej else "PARTIALLY_ESCALATED"\n')],
             UT, ["test_p5_aggregate_children_table_525"]),
    Mutation("M-T20b-9 cha ghi exit_code",
             [one(PARENT_WAIT, _DONE, _DONE.replace('{"aggregate_status"', '{"exit_code": "E1", "aggregate_status"').rstrip("\n")
                  + "  # MUTATION M-T20b-9\n")],
             UT, ["test_p4_p6_all_children_end_before_parent_wait_closes_now"]),
    Mutation("M-T20b-10 deliver giao lại khi đã giao (bỏ kiểm node + peek)",
             [one(CHILD_OPS, _DELIVER_CHECK, "                    if False:  # MUTATION M-T20b-10\n"),
              one(REPLY_WAIT, _EVENT_PEEK, "            if False:  # MUTATION M-T20b-10\n")],
             UT, ["test_r3_rerun_after_child1_delivered_child1_not_twice_child2_receives"]),
    Mutation("M-T20b-11 /reply bỏ kiểm items ≡ awaiting",
             [one(API, _VALIDATE, _VALIDATE.replace("validate=_items_match(redacted.items),", "validate=None,").rstrip("\n")
                  + "  # MUTATION M-T20b-11\n")],
             UT, ["test_a2_items_must_equal_awaiting_422"]),
    Mutation("M-T20b-12 parent_wait không goto quay lại sau interrupt",
             [one(PARENT_WAIT, _WOKEN, "            pass  # MUTATION M-T20b-12\n")],
             UT, ["test_p1_one_child_stopped_other_in_approval_wait_parent_waits_zero_messages"]),
    Mutation("M-T20b-13 after_turn không đánh thức khi con dừng ở node chờ",
             [one(RUNNER, _STOPS, "CHILD_STOPS = frozenset({None})  # MUTATION M-T20b-13")],
             UT, ["test_w1_child_stops_at_clarify_wait_wakes_parent_after_release", "test_w1_child_stops_at_confirm_wait_wakes_parent"]),
    Mutation("M-T20b-14 con kế thừa ctx_flags của ý khác (cờ áp cho mọi con)",
             [one(B03, _FLAG, "        if True:  # MUTATION M-T20b-14\n")],
             UT, ["test_v7_target_user_dropped_flag_only_on_that_child"]),
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
