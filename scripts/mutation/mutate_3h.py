"""Mutation chặng 3h (luật VPN R16–R20 + DSL, B12, B17–B18, executor VPN, `transaction_log`, runner, mock `/_admin/calls`,
`make gate3` / `make vpn-smoke`): áp từng đột biến, chạy test, KHÔI PHỤC, so md5; in test đỏ của mỗi đột biến. Khuôn
`mutate_3g.py` + luật N3 (`n3.py`): trước đột biến đầu tiên, file đích còn chữ `MUTATION` → dừng; mốc xanh một lần mỗi lệnh test —
đỏ → dừng; mọi file đã đột biến phải mang chữ `MUTATION` (JSON: chèn vào một giá trị chuỗi). Không đọc `.env`. Mã thoát 1 nếu
có đột biến sống (trừ đột biến ghi "tương đương") hoặc không áp được; 2 nếu N3 dừng.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_3h.py                   # phần unit (sandbox, không Docker)
  uv run python scripts/mutation/mutate_3h.py --e2e             # e2e cổng 3 (h10, h11, h14, h15, h16, h17) — Docker
  uv run python scripts/mutation/mutate_3h.py --integration     # transaction_log + boundary/recover (Việc treo 21) trên PG — Docker
  uv run python scripts/mutation/mutate_3h.py --only "M-3h-5"   # chỉ đột biến có tên bắt đầu bằng tiền tố

Bảng: phase3 11.8 M-3h-1…9 + PLAN-3h chỉnh 4 M-3h-10…13 + lời giao DỪNG 3 M-3h-14…16 + đề xuất M-3h-17…27 + chốt FAIL mục 7
(soát DỪNG 3b) M-3h-28 (bắt buộc: bỏ nhánh bắt lỗi sau begun) và M-3h-29…33 + Việc treo 21 M-3h-34 (bắt buộc: bỏ nhánh kiểm
begun ở boundary — chốt gọi "M-3h-29", số đó đã dùng) và M-3h-35 (recover chỉ theo `snap.next`) + Q-3h-11 (a) M-3h-36 (bỏ strip
thẻ `[fake:…]` khỏi câu truy hồi). Ghi chú:
- M-3h-1 (bỏ điều kiện owner của R20): h11 VẪN XANH — `ctx.target_is_other` (P3) tính owner≠True là "người khác", R20 đòi
  `target_is_other is_false` → hai lớp. Unit: test ghim policy.json + ca C5 dựng `RiskContext` tay đỏ. Lượt `--e2e` ghi là
  "tương đương" với h11 (h11 phải xanh).
- M-3h-5 = bỏ kiểm `begun` ở CẢ bước [0] của B17 lẫn `PlanExecutor` (điểm ghi; trước T24 là `VpnExecutor`) → h15 ghi 2 lần. 5a / 5b: từng lớp một.
- M-3h-8: DSL đọc `action.facts` qua `fact_view`, không đọc `RiskContext.facts` — đột biến chỉ bị test AST h21 bắt; e2e h14
  VẪN XANH vì `sanitize_slots` đã bỏ khoá fact khỏi slot ở B3 (lượt `--e2e` ghi "tương đương" với h14).
- M-3h-15 (bước [0] chỉ xét lượt hiện tại): `TxLog.has_begun(ticket_id)` không nhận lượt (chốt DỪNG 2) — muốn lùi phải đổi cả
  Protocol, `SqlTxLog`, fake `MemoryTxLog` (test dùng chung) và 2 điểm gọi; đột biến đổi đủ 5 chỗ như một lần lùi code thật.
- M-3h-21 chạy test mock (`mock_services/tests`); M-3h-24…27 đột biến chính script `gate3.py`/`vpn_smoke.py`.
- Lượt `--e2e` có thêm M-3f-2 (spec 9.7: "f5 + e2e 3h (h14)" — phần e2e của 3f chưa ai chạy).

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


POLICY_JSON = "config/policy.json"
POLICY = "backend/app/domain/policy.py"
CONTEXT = "backend/app/risk/context.py"
ESTIMATOR = "backend/app/risk/estimator.py"
B17 = "backend/app/graph/nodes/b17_execute.py"
VPN = "backend/app/executor/plan_executor.py"  # T24: đổi tên từ executor/vpn.py (VpnExecutor → PlanExecutor)
TXLOG = "backend/app/executor/txlog.py"
MEM_TXLOG = "backend/tests/fakes/executor.py"
FAKES = "backend/app/graph/fakes.py"
STATE = "backend/app/domain/ticket_state.py"
RUNNER = "backend/app/graph/runner.py"
BOUNDARY = "backend/app/graph/boundary.py"
RAG_QUERY = "backend/app/rag/query.py"
MOCK_MAIN = "mock_services/app/main.py"
GATE3 = "backend/tests/stack/gate3.py"
SMOKE = "backend/tests/stack/vpn_smoke.py"
B06 = "backend/app/graph/nodes/b06_diagnose.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_policy_rules_vpn", "test_business_hours", "test_b12_assess", "test_b17_execute", "test_executor_vpn",
        "test_executor_plans", "test_policy_engine_signature", "test_config_files", "test_runner_durability",
        "test_graph_runtime", "test_turn_budget", "test_side_effects_ast", "test_start_event_redacted_ast", "test_gate3",
        "test_vpn_smoke", "test_recover_limit", "test_boundary_begun", "test_rag_query",
    )
])  # fmt: skip
MOCK_UT = ["uv", "run", "pytest", "mock_services/tests", "-o", "pythonpath=mock_services", "-q", "-p", "no:cacheprovider"]
E2E = pt("backend/tests/e2e/test_gate3_vpn.py")
IT = pt("backend/tests/integration/test_txlog_pg.py")
IT_T21 = pt("backend/tests/integration/test_graph_pg.py", "-k", "t21")


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

_R20_OWNER = '      {"fact": "action.facts.device_owner_is_requester", "op": "is_true"},\n'
_R20_DESC = '"description": "Cấp lại cho thiết bị đã đăng ký của chính người gửi"}'
_MISSING = "        return False  # thiếu fact → điều kiện SAI [Chốt]\n"
_RANK = 'DECISION_RANK: Mapping[str, int] = {"allow": 1, "approval_required": 2, "deny": 3}'
_WINDOW = "    return local.isoweekday() in hours.weekdays and hours.start <= local.time() < hours.end\n"
_STEP0 = '        if await deps.txlog.has_begun(state["ticket_id"]):  # [0] NGHI-2 — TRƯỚC mọi bước kiểm lại\n'
_EXEC_BEGUN = "        if await self._txlog.has_begun(ticket_id):\n"
_WRITE = "                result = await self._registry.call(step.tool, step_args(step.tool, action), caller_step=WRITE_STEP)\n"
_APPROVED = '            approved = state.get("approval_result") == "approved" and db_status == "approved"\n'
_CTX_FACTS = "        requester=requester, facts=dict(action.facts), now=now,\n"
_ESTIMATE = '        raise LLMUnavailable("lớp LLM rủi ro (B14) chưa bật ở Phase 3 — 3-Q30")\n'
_TARGET = (
    '        flags.get("target_is_other", False) is not False\n'
    "        or action.requested_for != requester.user_id\n"
    '        or (device_target and action.facts.get("device_owner_is_requester") is not True)\n'
)
_P4 = '        cap_timeout(need, self._clock, what="executor:plan", full=True)  # P4 — TRƯỚC begun\n'
_BEGAN = "            progress.began = True\n"
_AFTER_BEGUN = "            if not progress.began:\n                raise  # trước begun: chưa gửi gì → boundary E9 như cũ\n"
_CATCH_ALL = "        except Exception as e:\n            if not progress.began:"
_CAUSE = "            cause = type(e).__name__  # CHỈ tên lớp lỗi — không str(e), không nội dung phản hồi (luật 8.9)\n"
_MAYBE = 'MAYBE_APPLIED_KINDS = frozenset({"timeout", "http_5xx", "other"})'
_GIVE_UP_BEGUN = "        if node != AUDIT and await self._txlog.has_begun(ticket_id):  # chốt FAIL mục 7 (d): theo ticket, mọi lượt\n"
_B18_CATCH = "        except Exception as exc:  # noqa: BLE001 — xem dòng trên\n"
_VIA = '        via_approval = bool(state.get("approval_id")) or state.get("approval_result") is not None\n'
_OUTPUTS = "        return {str(k): v for k, v in value.items() if _valid_output(str(k), v)}\n"
_WATCH = (
    "        changed = [f for f in watched if fresh is None or getattr(fresh, f) != getattr(requester, f)]\n"
    "        if fresh is None or changed:\n"
)
_PROTO = "    async def has_begun(self, ticket_id: str) -> bool: ...\n"
_SQL_SIG = "    async def has_begun(self, ticket_id: str) -> bool:\n        async with self._engine.connect() as conn:\n"
_SQL_WHERE = '.where(_TABLE.c.ticket_id == ticket_id, _TABLE.c.status == "begun")'
_MEM = (
    "    async def has_begun(self, ticket_id: str) -> bool:\n"
    '        return any(r["ticket_id"] == ticket_id and r["status"] == "begun" for r in self.rows)\n'
)
_DURABILITY = 'DURABILITY: Durability = "sync"  # NGHI-3 — xem docstring module'
_PERSON = "            if err is not None or data is None or status in INVALID_PEOPLE or ad_disabled:\n"
_VERDICT = "        verdict = evaluate(action, build_ctx(state, run.clock.now(), deps.business_hours))  # [1] P8: hiện hành\n"
_MOCK_MW = (
    '    app.middleware("http")(fault_middleware)\n'
    '    app.middleware("http")(count_middleware)  # SAU fault_middleware = ngoài cùng (đếm cả request bị bơm lỗi)\n'
)
_NOTE = 'INTERRUPTED_NOTE = f"Thực thi bị gián đoạn (worker không chạy lại B17): {MAY_HAVE_WRITTEN}."\n'
_BOUNDARY_BEGUN = '            if open_ and await current_run().txlog.has_begun(state["ticket_id"]):\n'
_PENDING_TASKS = "    return snap.tasks[0].name if snap.tasks else None\n"
_STRIP_TAG = "    base = strip_fake_tag(redacted_request).strip()  # thẻ preset dev/test không vào câu truy hồi (Q-3h-11 a)\n"
_B18_SEND = (
    "            ref = await effects.once(\n"
    '                state, "notify_user", deps.notifier.notify_user, state["ticket_id"], text, "confirm", step="B18",\n'
    "            )  # fmt: skip\n"
)
_ROUTE = '        return Risk("R20", "AUTO", frozenset({"R20"})) if in_hours else Risk("R18", "HITL", frozenset({"R18", "R20"}))\n'
_CAP = "    if type(cap) not in (int, float) or not cast(float, cap) <= CAP_MAX_USD:  # NaN, thiếu, > 1 → từ chối\n"  # P5 4a: cast
_PROBE_ECHO = """    'if [ -n "$(printenv "$v")" ]; then echo "$v=1"; else echo "$v=0"; fi; done; '\n"""
_MERGE_ANCHOR = "        added = {k: v for k, v in inferred.items() if k not in slots}"  # như mutate_3f.py M-3f-2
_TC28_FINALLY = '    finally:\n        ctx.shell.compose("start", "qdrant")  # lỗi giữa chừng vẫn bật lại\n'

H10 = "test_h10_r19_probation_hitl_no_write"
H11 = "test_h11_g02_other_persons_device_no_rule_e5_no_write"
H14 = "test_h14_g01_fact_in_slot_dropped_r17_hitl_no_write"
H15 = "test_h15_api_recover_after_write_e7_exec_interrupted_single_write"
H16 = "test_h16_write_fault_500_e7_exec_failed_no_revoke_four_part_note"
H17 = "test_h17_requester_disabled_before_b17_e5_no_write"
M5_UNIT = [
    "test_begun_exists_is_e7_exec_interrupted_zero_writes", "test_nghi2_rerun_after_write_is_e7_not_e5",
    "test_nghi2_begun_of_other_turn_is_e7_before_recheck", "test_nghi2_step0_runs_even_without_intended_action",
    "test_begun_exists_interrupted_zero_writes", "test_begun_of_other_turn_also_blocks", "test_begun_blocks_even_empty_plan",
]  # fmt: skip

_M5 = [one(B17, _STEP0, "        if False:  # MUTATION M-3h-5 bỏ bước [0]\n"),
       one(VPN, _EXEC_BEGUN, "        if False:  # MUTATION M-3h-5 bỏ kiểm begun ở executor\n")]  # fmt: skip
_M8 = [one(CONTEXT, _CTX_FACTS,
           '        requester=requester, facts={**dict(action.facts), **dict(state.get("slots") or {})}, now=now,'
           "  # MUTATION M-3h-8\n")]  # fmt: skip
_M15 = [
    one(TXLOG, _PROTO, "    async def has_begun(self, ticket_id: str, turn_id: str | None = None) -> bool: ...  # MUTATION M-3h-15\n"),
    one(TXLOG, _SQL_SIG, "    async def has_begun(self, ticket_id: str, turn_id: str | None = None) -> bool:  # MUTATION M-3h-15\n"
                         "        async with self._engine.connect() as conn:\n"),
    one(TXLOG, _SQL_WHERE, _SQL_WHERE[:-1] + ", *([_TABLE.c.turn_id == turn_id] if turn_id else []))"),
    one(MEM_TXLOG, _MEM, "    async def has_begun(self, ticket_id: str, turn_id: str | None = None) -> bool:  # MUTATION M-3h-15\n"
                         '        return any(r["ticket_id"] == ticket_id and r["status"] == "begun"\n'
                         '                   and turn_id in (None, r["turn_id"]) for r in self.rows)\n'),
    one(B17, _STEP0, _STEP0.replace('has_begun(state["ticket_id"])', 'has_begun(state["ticket_id"], run.turn_id)')
        .replace("# [0] NGHI-2", "# MUTATION M-3h-15 chỉ lượt hiện tại —")),
    one(VPN, _EXEC_BEGUN, "        if await self._txlog.has_begun(ticket_id, turn_id):  # MUTATION M-3h-15\n"),
]  # fmt: skip

UNIT = [
    Mutation("M-3h-1 R20 bỏ điều kiện device_owner_is_requester",
             [one(POLICY_JSON, _R20_OWNER, ""),
              one(POLICY_JSON, _R20_DESC, _R20_DESC.replace('người gửi"', 'người gửi MUTATION M-3h-1"'))],
             UT, ["test_hrule_policy_json_khop_spec_11_2", "test_policy_json_rules_are_exactly_spec_11_2",
                  "test_hrule_c5_luat_khop_va_suyt_khop"]),
    Mutation("M-3h-2 thiếu fact → điều kiện ĐÚNG",
             [one(POLICY, _MISSING, "        return True  # MUTATION M-3h-2 thiếu fact → đúng\n")],
             UT, ["test_hrule_bang_11_2", "test_hrule_c5_luat_khop_va_suyt_khop"]),
    Mutation("M-3h-3 allow thắng approval_required",
             [one(POLICY, _RANK, 'DECISION_RANK: Mapping[str, int] = {"allow": 2, "approval_required": 1, "deny": 3}'
                                 "  # MUTATION M-3h-3")],
             UT, ["test_hrule_bang_11_2", "test_after_hours_r18_goes_to_b15"]),
    Mutation("M-3h-4 biên giờ end bao gồm (≤ end)",
             [one(POLICY, _WINDOW, _WINDOW.replace("< hours.end", "<= hours.end").rstrip("\n") + "  # MUTATION M-3h-4\n")],
             UT, ["test_h20_bien_gio_hanh_chinh", "test_hours_label_uses_policy_business_hours"]),
    Mutation("M-3h-5 bỏ kiểm transaction_log begun (bước [0] + executor)", _M5, UT, M5_UNIT),
    Mutation("M-3h-5a chỉ bỏ bước [0] của B17 (executor còn chặn)", [_M5[0]],
             UT, ["test_nghi2_rerun_after_write_is_e7_not_e5", "test_nghi2_begun_of_other_turn_is_e7_before_recheck",
                  "test_nghi2_step0_runs_even_without_intended_action"]),
    Mutation("M-3h-5b chỉ bỏ kiểm begun ở PlanExecutor (bước [0] còn chặn)", [_M5[1]],
             UT, ["test_begun_exists_interrupted_zero_writes", "test_begun_of_other_turn_also_blocks",
                  "test_begun_blocks_even_empty_plan"]),
    Mutation("M-3h-6 thử lại lệnh ghi khi lỗi",
             [one(VPN, _WRITE, _WRITE + "                if result.error is not None:  # MUTATION M-3h-6 retry lệnh ghi\n"
                               "    " + _WRITE)],
             UT, ["test_write_error_single_call_handoff_four_parts"]),
    Mutation("M-3h-7 \"đã duyệt\" chỉ đọc state, bỏ bảng approvals",
             [one(B17, _APPROVED, '            approved = state.get("approval_result") == "approved"  # MUTATION M-3h-7\n')],
             UT, ["test_state_approved_db_pending_is_e5", "test_state_approved_db_not_approved_is_e5"]),
    Mutation("M-3h-8 build_ctx đọc slots (gộp vào facts)", _M8,
             UT, ["test_h21_build_ctx_reads_only_action_requester_flags"]),
    Mutation("M-3h-9 DisabledEstimator trả p=0 thay vì ném lỗi",
             [one(ESTIMATOR, _ESTIMATE, '        return 0.0, "self_report"  # MUTATION M-3h-9\n')],
             UT, ["test_no_rule_disabled_estimator_e5_llm_layer_disabled"]),
    Mutation("M-3h-10 target_is_other chỉ so requested_for",
             [one(CONTEXT, _TARGET, "        action.requested_for != requester.user_id  # MUTATION M-3h-10\n")],
             UT, ["test_hrule_bang_11_2", "test_hrule_p3_build_ctx_target_is_other",
                  "test_ctx_flag_target_is_other_only_tightens"]),
    Mutation("M-3h-11 INSERT begun trước kiểm hạn lượt",
             [one(VPN, _P4, "        # MUTATION M-3h-11: kiểm hạn lượt chuyển xuống SAU begin\n"),
              one(VPN, _BEGAN, _BEGAN + "            cap_timeout(sum(self._specs[s.tool].timeout_s for s in steps), self._clock, "
                                        'what="executor:plan", full=True)  # MUTATION M-3h-11\n')],
             UT, ["test_p4_not_enough_budget_before_begun", "test_p4_budget_is_e2_before_begun"]),
    Mutation("M-3h-12 có approval_id nhưng bỏ đọc bảng khi luật hiện hành allow",
             [one(B17, _VIA, _VIA.rstrip("\n").replace("= bool(", "= (bool(")
                  + ') and verdict.decision != "allow"  # MUTATION M-3h-12\n')],
             UT, ["test_state_approved_db_pending_is_e5[allow-M-3h-12]"]),
    Mutation("M-3h-13 outputs không lọc regex",
             [one(STATE, _OUTPUTS, "        return {str(k): str(v) for k, v in value.items()}  # MUTATION M-3h-13\n")],
             UT, ["test_q3h2_c_bad_outputs_dropped_and_not_in_message"]),
    Mutation("M-3h-14 Q-3h-7: bỏ so trường requester.* (AD mới vs bản chụp B1)",
             [one(B17, _WATCH, "        changed: list[str] = []  # MUTATION M-3h-14\n        if False:\n")],
             UT, ["test_q3h7_active_at_b1_probation_now_is_e5", "test_q3h7_fields_follow_policy_department",
                  "test_q3h7_unmappable_groups_is_e5"]),
    Mutation("M-3h-15 bước [0] (và executor) chỉ xét begun của lượt hiện tại", _M15,
             UT, ["test_nghi2_begun_of_other_turn_is_e7_before_recheck", "test_begun_of_other_turn_also_blocks",
                  "test_begun_blocks_even_empty_plan"]),
    Mutation("M-3h-16 durability sync → async (mặc định LangGraph)",
             [one(RUNNER, _DURABILITY, 'DURABILITY: Durability = "async"  # MUTATION M-3h-16')],
             UT, ["test_runner_waits_for_checkpoint_before_next_node"]),
    # ---- đề xuất ----
    Mutation("M-3h-17 RefusingExecutor (worker) không đọc transaction_log",
             [one(FAKES, _EXEC_BEGUN, "        if False:  # MUTATION M-3h-17\n")],
             UT, ["test_s12_refusing_executor_reads_txlog", "test_s12_worker_refusing_executor_with_begun_is_exec_interrupted"]),
    Mutation("M-3h-18 ghi chú bàn giao chép chữ lỗi của hệ thống ngoài",
             [one(VPN, "                kind = error_kind(result.error)\n",
                  "                kind = result.error  # MUTATION M-3h-18\n")],
             UT, ["test_write_error_single_call_handoff_four_parts"]),
    Mutation("M-3h-19 B17 bỏ kiểm người (disabled/terminated/lỗi AD)",
             [one(B17, _PERSON, "            if False:  # MUTATION M-3h-19\n")],
             UT, ["test_requester_no_longer_valid_is_e5", "test_beneficiary_terminated_is_e5"]),
    Mutation("M-3h-20 B17 kiểm lại theo giờ lúc B1 thay vì Clock hiện hành (P8)",
             [one(B17, _VERDICT, "        verdict = evaluate(action, build_ctx(state, requester.captured_at, deps.business_hours))"
                                 "  # MUTATION M-3h-20\n")],
             UT, ["test_auto_path_now_after_hours_is_e5"]),
    Mutation("M-3h-21 mock: middleware đếm đăng ký TRƯỚC bơm lỗi (không còn ngoài cùng)",
             [one(MOCK_MAIN, _MOCK_MW, '    app.middleware("http")(count_middleware)  # MUTATION M-3h-21\n'
                                       '    app.middleware("http")(fault_middleware)\n')],
             MOCK_UT, ["test_injected_fault_is_still_counted"]),
    Mutation("M-3h-22 ghi chú gián đoạn của runner bỏ câu \"có thể đã gửi lệnh ghi\"",
             [one(RUNNER, _NOTE, 'INTERRUPTED_NOTE = "Thực thi bị gián đoạn (worker không chạy lại B17): cần L2 kiểm tra trạng '
                                 'thái thật (MUTATION M-3h-22)."\n')],
             UT, ["test_interrupted_notes_both_paths_say_write_may_have_happened"]),
    Mutation("M-3h-23 B18 gửi tin thẳng, không qua effects.once",
             [one(B17, _B18_SEND, '            ref = await deps.notifier.notify_user(state["ticket_id"], text, "confirm")'
                                  "  # MUTATION M-3h-23\n")],
             UT, ["test_graph_nodes_never_call_side_effects_directly"]),
    Mutation("M-3h-24 gate3: route mong đợi đảo trong/ngoài giờ",
             [one(GATE3, _ROUTE, _ROUTE.replace("if in_hours", "if not in_hours").rstrip("\n") + "  # MUTATION M-3h-24\n")],
             UT, ["test_expected_risk_equals_real_policy_engine", "test_expected_risk_table"]),
    Mutation("M-3h-25 vpn-smoke cho LLM thật chạy khi cap_usd > 1",
             [one(SMOKE, _CAP, "    if False:  # MUTATION M-3h-25\n")],
             UT, ["test_refusal_reasons", "test_refuses_before_any_ticket_or_llm_call"]),
    Mutation("M-3h-26 gate3 dò env in GIÁ TRỊ biến",
             [one(GATE3, _PROBE_ECHO, """    'if [ -n "$(printenv "$v")" ]; then echo "$v=$(printenv "$v")"; else echo "$v=0"; fi; done; '"""
                                      "  # MUTATION M-3h-26\n")],
             UT, ["test_env_probe_prints_names_and_flags_only"]),
    Mutation("M-3h-27 tc28 chỉ bật lại Qdrant khi không lỗi (try/else thay finally)",
             [one(GATE3, _TC28_FINALLY, _TC28_FINALLY.replace(
                 "finally:", "except KeyError:  # MUTATION M-3h-27\n        raise\n    else:"))],
             UT, ["test_tc28_always_starts_qdrant_again", "test_tc28_failure_is_reported_and_run_continues"]),
    # ---- chốt FAIL mục 7 (soát DỪNG 3b) ----
    Mutation("M-3h-28 bỏ nhánh bắt lỗi SAU begun ở executor (lỗi lọt lên → E9)",
             [one(VPN, _AFTER_BEGUN, "            if True:  # MUTATION M-3h-28 bỏ nhánh bắt lỗi sau begun\n                raise\n")],
             UT, ["test_fail7_error_after_begin_is_interrupted_one_write", "test_fail7_error_after_begin_is_e7_warning_not_e9",
                  "test_fail7_error_while_undoing_is_interrupted_counts_every_sent_write"]),
    Mutation("M-3h-29 recover cạn lượt bỏ xét begun theo ticket (E9 \"xử lý thủ công\")",
             [one(RUNNER, _GIVE_UP_BEGUN, "        if False:  # MUTATION M-3h-29\n")],
             UT, ["test_fail7_recover_exhausted_with_begun_of_earlier_turn_is_e7_warning"]),
    Mutation("M-3h-30 B17 bỏ bắt lỗi ở đoạn B18 sau khi đã ghi",
             [one(B17, _B18_CATCH, "        except ZeroDivisionError as exc:  # MUTATION M-3h-30\n")],
             UT, ["test_fail7_b18_error_after_successful_write_is_e7_not_e9"]),
    Mutation("M-3h-31 executor bắt BaseException (nuốt CancelledError)",
             [one(VPN, _CATCH_ALL, "        except BaseException as e:  # MUTATION M-3h-31\n            if not progress.began:")],
             UT, ["test_fail7_cancelled_after_begin_is_not_swallowed", "test_fail7_cancelled_after_begin_propagates_through_node"]),
    Mutation("M-3h-32 cause chép thông điệp lỗi (str(e))",
             [one(VPN, _CAUSE, '            cause = f"{type(e).__name__}: {e}"  # MUTATION M-3h-32\n')],
             UT, ["test_fail7_error_after_begin_is_interrupted_one_write", "test_fail7_error_after_begin_is_e7_warning_not_e9"]),
    Mutation("M-3h-33 ghi chú lỗi mơ hồ bỏ \"có thể đã được áp dụng\"",
             [one(VPN, _MAYBE, "MAYBE_APPLIED_KINDS: frozenset[str] = frozenset()  # MUTATION M-3h-33")],
             UT, ["test_fail7_ambiguous_error_note_says_may_have_been_applied"]),
    # ---- Việc treo 21 (chốt DỪNG 3b) ----
    Mutation("M-3h-34 boundary bỏ nhánh kiểm begun (lỗi sau begun → E9/E2)",
             [one(BOUNDARY, _BOUNDARY_BEGUN, "            if False:  # MUTATION M-3h-34 bỏ kiểm begun ở boundary\n")],
             UT, ["test_t21_error_in_b19_on_ticket_with_begun_is_e7_warning", "test_t21_turn_budget_after_begun_is_e7",
                  "test_t21_has_begun_error_propagates_not_e9",
                  "test_t21_has_begun_error_keeps_turn_open_then_recover_exhausted_is_e7",
                  "test_t21_final_goto_error_after_write_is_e7_not_e9"]),
    Mutation("M-3h-35 recover chỉ theo snap.next (node chờ resume lỗi bị coi là đã kết thúc)",
             [one(RUNNER, _PENDING_TASKS, "    return None  # MUTATION M-3h-35 chỉ theo snap.next\n")],
             UT, ["test_t21_has_begun_error_keeps_turn_open_then_recover_exhausted_is_e7",
                  "test_t21_recover_reruns_resumed_wait_node_that_raised"]),
    # ---- Q-3h-11 (a) (chốt gate3 lần 1) ----
    Mutation("M-3h-36 build_query bỏ dòng strip thẻ [fake:…] (thẻ vào câu truy hồi)",
             [one(RAG_QUERY, _STRIP_TAG, "    base = redacted_request.strip()  # MUTATION M-3h-36\n")],
             UT, ["test_fake_tag_never_reaches_retrieval_query"]),
]  # fmt: skip

_BY_NAME = {m.name.split(" ", 1)[0]: m for m in UNIT}
E2E_MUTATIONS = [
    _BY_NAME["M-3h-1"]._replace(name="M-3h-1 (e2e h11 — hai lớp: P3 vẫn chặn)", cmd=E2E, expect=[], keep_green=(H11,),
                                equivalent=True),
    _BY_NAME["M-3h-3"]._replace(name="M-3h-3 (e2e h10)", cmd=E2E, expect=[H10]),
    _BY_NAME["M-3h-5"]._replace(name="M-3h-5 (e2e h15)", cmd=E2E, expect=[H15]),
    _BY_NAME["M-3h-6"]._replace(name="M-3h-6 (e2e h16)", cmd=E2E, expect=[H16]),
    _BY_NAME["M-3h-8"]._replace(name="M-3h-8 (e2e h14 — sanitize_slots đã bỏ khoá fact)", cmd=E2E, expect=[],
                                keep_green=(H14,), equivalent=True),
    _BY_NAME["M-3h-9"]._replace(name="M-3h-9 (e2e h11)", cmd=E2E, expect=[H11]),
    _BY_NAME["M-3h-18"]._replace(name="M-3h-18 (e2e h16)", cmd=E2E, expect=[H16]),
    _BY_NAME["M-3h-19"]._replace(name="M-3h-19 (e2e h17)", cmd=E2E, expect=[H17]),
    # spec 9.7: M-3f-2 phải bị f5 (3f, unit) VÀ e2e 3h h14 bắt — phần e2e chạy ở đây (đột biến giống mutate_3f.py)
    Mutation("M-3f-2 (e2e h14) B6 gộp slots vào facts",
             [one(B06, _MERGE_ANCHOR, "        facts = {**slots, **facts}  # MUTATION gộp slots vào facts\n" + _MERGE_ANCHOR)],
             E2E, [H14]),
]  # fmt: skip
INTEGRATION = [
    _BY_NAME["M-3h-5b"]._replace(name="M-3h-5b (PG)", cmd=IT, expect=["test_executor_with_pg_txlog_begun_then_interrupted"]),
    _BY_NAME["M-3h-15"]._replace(name="M-3h-15 (PG)", cmd=IT, expect=["test_executor_with_pg_txlog_begun_then_interrupted"]),
    _BY_NAME["M-3h-34"]._replace(name="M-3h-34 (PG)", cmd=IT_T21,
                                 expect=["test_t21_b19_error_on_ticket_with_begun_is_e7_on_postgres"]),
    _BY_NAME["M-3h-35"]._replace(name="M-3h-35 (PG — AsyncPostgresSaver)", cmd=IT_T21,
                                 expect=["test_t21_resumed_wait_node_error_recovered_on_postgres"]),
]  # fmt: skip

MUTATIONS = E2E_MUTATIONS if "--e2e" in sys.argv else INTEGRATION if "--integration" in sys.argv else UNIT
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
