"""Mutation chặng 3f (hạn cả lượt S0, tách slots/facts, B3 VPN, B6–B7 VPN): áp từng đột biến, chạy test, KHÔI PHỤC, so md5;
in test đỏ của mỗi đột biến. Khuôn `mutate_3e.py` — không đọc `.env`, mã thoát 1 nếu có đột biến sống hoặc không áp được.
File luôn được khôi phục trong `finally`, cuối cùng so md5 và `git diff --stat` với lúc đầu.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_3f.py                  # phần unit (sandbox, không Docker, không mở cổng)
  uv run python scripts/mutation/mutate_3f.py --e2e            # f8/f10/f11/f13 với mock THẬT (mở cổng local)
  uv run python scripts/mutation/mutate_3f.py --integration    # f17 checkpoint Postgres — cần Docker
  uv run python scripts/mutation/mutate_3f.py --only "M-3f-7"  # chỉ đột biến có tên bắt đầu bằng tiền tố

Bảng: PLAN-3f mục 1 (S7) = phase3 9.7 M-3f-1…6 + đề bài 3f M-3f-7…11. Lệch với bảng (ghi PROGRESS, không âm thầm sửa bảng):
- M-3f-7 tách 4 điểm gọi (7a registry, 7b ml, 7c LLM, 7d RAG) — soát bảo mật (6) liệt kê từng điểm.
- M-3f-9 → f3 (không phải f10): tool cert chỉ trả cert của CHÍNH người gửi (9.5) nên với seed thật máy của người khác luôn
  `cert_status="none"` — f10 không thể thấy action tự đặt; f3 dựng dữ liệu bất thường để bắt.
- Thêm M-3f-12…19 (ngoài bảng): diagnostics lưu model Pydantic, điểm log 1 chứa câu người dùng, `tool_errors` chép nguyên
  lỗi (URL), bỏ kiểm `span` (Q-3f-4), đếm "≥ 2 ý" chỉ trên in_scope (Q-3f-6), audit chép key tự do (Q-3f-5), tool ghi gửi
  với timeout rút ngắn, `tool_retry_count` cộng thẳng `attempts` (Q-3f-1).

Mỗi đột biến chạy TRỌN các file test của chặng (không chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, "-q", "-p", "no:cacheprovider"]


SLOTS = "backend/app/domain/slots.py"
B03 = "backend/app/graph/nodes/b03_classify.py"
B06 = "backend/app/graph/nodes/b06_diagnose.py"
VPN = "backend/app/tools/diagnosis/vpn.py"
REGISTRY = "backend/app/tools/registry.py"
ML_CLIENT = "backend/app/ml/client.py"
LLM_CLIENT = "backend/app/llm/client.py"
RETRIEVER = "backend/app/rag/retriever.py"
BOUNDARY = "backend/app/graph/boundary.py"
UT = [
    f"backend/tests/unit/{name}.py"
    for name in (
        "test_slots_facts", "test_config_files", "test_infer_vpn", "test_b03_classify", "test_b06_diagnose",
        "test_facts_ast", "test_turn_budget", "test_turn_deadline", "test_turn_worst_case", "test_graph_select_nodes",
        "test_b02_screen", "test_call_with_retry",
    )
]  # fmt: skip
E2E = "backend/tests/e2e/test_b06_vs_mock.py"
IT_B06 = "backend/tests/integration/test_b06_pg.py"

_ORDER = (
    "        if it.confidence < deps.constants.TAU_INTENT:  # D-27: không chắc thì không đoán\n"
    "            return await goto(\n"
    '                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_low_confidence",\n'
    "                audit_detail=info, exit_code=ExitCode.E1.value, reasoning_loops=loops,\n"
    '                escalation_reason_detail="intent_low_confidence",\n'
    "            )  # fmt: skip\n"
)
_ENABLED = (
    "        if it.type not in deps.enabled_intents:  # 3-Q27\n"
    "            return await goto(\n"
    '                state, S_ESCALATED, next_node="b20_audit", step="B4", event="intent_not_enabled", audit_detail=info,\n'
    '                exit_code=ExitCode.E1.value, reasoning_loops=loops, escalation_reason_detail="intent_not_enabled",\n'
    "            )  # fmt: skip\n"
)
_OWNER = 'facts["device_owner_is_requester"] = dev is not None and dev.owner_id == requester_id'
_ACTION = 'if facts["device_owner_is_requester"] and (action := ACTION_BY_CERT.get(str(facts["cert_status"]))):'
_B7 = 'if errors := [f"{r.tool}: {_error_kind(r.error)}" for r in results if r.error is not None]:  # B7'
_MERGE_ANCHOR = "        added = {k: v for k, v in inferred.items() if k not in slots}"
_INFER = "        if len(devices) == 1:  # ĐÚNG 1 máy mới tự suy; ≥ 2 → để B11 hỏi\n"
_REGISTERED = 'facts["device_registered"] = dev is not None and dev.registered'
_DIAG = 'diagnostics={t: (None if m is None else m.model_dump(mode="json")) for t, m in diag.items()},'

UNIT = [
    ("M-3f-1 sanitize_slots không loại FACT_KEYS", SLOTS,
     "        if k in FACT_KEYS:\n", "        if False:  # MUTATION không loại FACT_KEYS\n",
     pt(*UT), ["test_f1_drops_with_reason", "test_f5_fact_named_slot_dropped_and_audited"]),
    ("M-3f-2 B6 gộp slots vào facts", B06,
     _MERGE_ANCHOR, "        facts = {**slots, **facts}  # MUTATION gộp slots vào facts\n" + _MERGE_ANCHOR,
     pt(*UT), ["test_f5_fact_named_slot_dropped_and_audited", "test_p3_b06_facts_only_from_infer_vpn"]),
    ("M-3f-3 device_owner_is_requester luôn true", VPN,
     _OWNER, 'facts["device_owner_is_requester"] = True  # MUTATION',
     pt(*UT), ["test_f3_other_persons_device_owner_false_no_action",
               "test_f10_nv001_names_nv002_device_owner_false_no_action"]),
    ("M-3f-4 tự suy máy khi ≥ 2 máy (lấy máy đầu)", VPN,
     _INFER, "        if len(devices) >= 1:  # MUTATION suy cả khi ≥ 2 máy\n",
     pt(*UT), ["test_f3_two_devices_never_inferred", "test_f8_nv002_two_devices_no_device_id"]),
    ("M-3f-5 máy không tồn tại → device_registered=true", VPN,
     _REGISTERED, 'facts["device_registered"] = dev is None or dev.registered  # MUTATION',
     pt(*UT), ["test_f3_nonexistent_device_not_registered", "test_f11_nv001_names_missing_device_not_registered"]),
    ("M-3f-6 đổi thứ tự kiểm B3 (intent chưa bật trước confidence)", B03,
     _ORDER + _ENABLED, _ENABLED + _ORDER,
     pt(*UT), ["test_f4_e1_branches"]),
    ("M-3f-7a registry: tool đọc bỏ cắt timeout theo phần còn lại", REGISTRY,
     "                return await handler(inp, cap_timeout(spec.timeout_s, self._clock, what=what))\n",
     "                return await handler(inp, spec.timeout_s)  # MUTATION bỏ cắt theo hạn lượt\n",
     pt(*UT), ["test_registry_read_caps_each_attempt_and_stops_before_useless_backoff",
               "test_f19_worst_case_turn_ends_e2_within_budget_and_no_call_exceeds_remaining",
               "test_external_call_sites_use_turn_budget"]),
    ("M-3f-7b MlClient bỏ cắt timeout theo phần còn lại", ML_CLIENT,
     '                timeout = cap_timeout(TIMEOUT_S[endpoint], self._clock, what=f"ml:{endpoint}")  # 9.0\n',
     "                timeout = TIMEOUT_S[endpoint]  # MUTATION bỏ cắt theo hạn lượt\n",
     pt(*UT), ["test_ml_timeout_shrinks_to_remaining", "test_ml_exhausted_turn_sends_nothing",
               "test_f19_worst_case_turn_ends_e2_within_budget_and_no_call_exceeds_remaining"]),
    ("M-3f-7c LLM gateway bỏ cắt deadline theo phần còn lại", LLM_CLIENT,
     '        limit_s, call.turn_bound = window(role_left, self._clock, what=f"llm:{prompt.id}")',
     "        limit_s, call.turn_bound = role_left, False  # MUTATION bỏ cắt theo hạn lượt",
     pt(*UT), ["test_llm_turn_bound_deadline_raises_turn_budget_not_unavailable",
               "test_llm_exhausted_turn_sends_no_request", "test_external_call_sites_use_turn_budget"]),
    ("M-3f-7d Retriever bỏ cắt khung theo phần còn lại", RETRIEVER,
     '        limit_s, turn_bound = window(self._cfg.deadline_s, self._clock, what="rag:retrieve")  # 9.0\n',
     "        limit_s, turn_bound = self._cfg.deadline_s, False  # MUTATION bỏ cắt theo hạn lượt\n",
     pt(*UT), ["test_retriever_turn_window_raises_turn_budget", "test_retriever_exhausted_turn_touches_nothing",
               "test_external_call_sites_use_turn_budget"]),
    ("M-3f-8 bỏ kiểm slot có trong câu", SLOTS,
     "        elif k in MUST_APPEAR_IN_TEXT and not in_text(k, value, text):\n",
     "        elif False:  # MUTATION bỏ kiểm slot có trong câu\n",
     pt(*UT), ["test_f18_slot_not_in_text_is_dropped", "test_f18_hallucinated_device_dropped_at_node"]),
    ("M-3f-9 infer_vpn đặt action khi owner ≠ requester", VPN,
     _ACTION, 'if (action := ACTION_BY_CERT.get(str(facts["cert_status"]))):  # MUTATION',
     pt(*UT), ["test_f3_other_persons_device_never_gets_action_even_if_cert_shows_expired"]),
    ("M-3f-10 lỗi tool bị coi là rỗng", B06,
     _B7, _B7.replace("if r.error is not None]:  # B7", "if False]:  # MUTATION lỗi = rỗng"),
     pt(*UT), ["test_f13_cert_500_goes_e2_tool_system_error"]),
    ("M-3f-11 boundary: hết hạn lượt → E9", BOUNDARY,
     '            if isinstance(exc, TurnBudgetExceeded) and state.get("status") not in TERMINAL | {S_ESCALATED}:\n',
     "            if False:  # MUTATION hết hạn lượt → E9\n",
     pt(*UT), ["test_b1_turn_budget_exceeded_goes_e2_via_boundary", "test_b8_turn_budget_exceeded_goes_e2_via_boundary"]),
    ("M-3f-12 diagnostics lưu model Pydantic (không JSON)", B06,
     _DIAG, "diagnostics=diag,  # MUTATION model Pydantic trong state",
     pt(*UT), ["test_f17_diagnostics_json_and_facts_roundtrip_serde"]),
    ("M-3f-13 điểm log 1 chứa câu người dùng", B03,
     "        info[\"prompt\"], info[\"is_multi\"] = f\"{meta.prompt_id}@{meta.prompt_version}\", out.is_multi\n",
     ("        info[\"prompt\"], info[\"is_multi\"] = f\"{meta.prompt_id}@{meta.prompt_version}\", out.is_multi\n"
      "        info[\"text\"] = text  # MUTATION detail chứa câu người dùng\n"),
     pt(*UT), ["test_point1_on_every_branch_without_user_text"]),
    ("M-3f-14 tool_errors chép nguyên lỗi (có URL)", B06,
     '    return error.split(":", 1)[0].strip()[:64]\n', "    return error  # MUTATION chép nguyên lỗi\n",
     pt(*UT), ["test_f13_cert_500_goes_e2_tool_system_error"]),
    ("M-3f-15 bỏ kiểm span có trong câu (Q-3f-4)", B03,
     "        span = it.span if it.span.strip() and phrase_in_text(it.span, text) else None  # Q-3f-4\n",
     "        span = it.span  # MUTATION bỏ kiểm span\n",
     pt(*UT), ["test_q3f4_span_kept_only_if_in_text"]),
    ("M-3f-16 đếm ≥ 2 ý chỉ trên in_scope (Q-3f-6)", B03,
     "        if len(out.intents) >= 2:", "        if len(in_scope) >= 2:  # MUTATION",
     pt(*UT), ["test_f4_e1_branches", "test_q3f6_out_of_scope_request_is_second_intent"]),
    ("M-3f-17 audit chép key tự do của LLM (Q-3f-5)", SLOTS,
     "    listed = known | FACT_KEYS\n", "    listed = known | FACT_KEYS | frozenset(dropped)  # MUTATION\n",
     pt(*UT), ["test_audit_dropped_hides_free_text_keys", "test_q3f5_free_text_slot_keys_never_reach_audit"]),
    ("M-3f-18 tool ghi gửi với timeout rút ngắn", REGISTRY,
     "            timeout = cap_timeout(spec.timeout_s, self._clock, what=what, full=True)\n",
     "            timeout = cap_timeout(spec.timeout_s, self._clock, what=what)  # MUTATION bỏ full=True\n",
     pt(*UT), ["test_registry_write_needs_full_timeout"]),
    ("M-3f-19 tool_retry_count cộng thẳng attempts (Q-3f-1)", B06,
     "        retries = sum(retries_of(r.attempts, failed=r.error is not None) for r in results)\n",
     "        retries = sum(r.attempts for r in results)  # MUTATION cộng thẳng\n",
     pt(*UT), ["test_f13_cert_500_goes_e2_tool_system_error"]),
]  # fmt: skip

E2E_MUTATIONS = [
    ("M-3f-3 device_owner_is_requester luôn true (mock thật)", VPN,
     _OWNER, 'facts["device_owner_is_requester"] = True  # MUTATION', pt(E2E), ["test_f10_nv001_names_lap0417"]),
    ("M-3f-4 tự suy máy khi ≥ 2 máy (mock thật)", VPN,
     _INFER, "        if len(devices) >= 1:  # MUTATION\n", pt(E2E), ["test_f8_nv002_two_devices"]),
    ("M-3f-5 máy không tồn tại → registered (mock thật)", VPN,
     _REGISTERED, 'facts["device_registered"] = dev is None or dev.registered  # MUTATION', pt(E2E),
     ["test_f11_nv001_names_lap9999"]),
    ("M-3f-10 lỗi tool bị coi là rỗng (mock thật)", B06,
     _B7, _B7.replace("if r.error is not None]:  # B7", "if False]:  # MUTATION"), pt(E2E),
     ["test_f13_certs_500_e2"]),
]  # fmt: skip

INTEGRATION = [
    ("M-3f-12 diagnostics lưu model Pydantic (PG f17)", B06,
     _DIAG, "diagnostics=diag,  # MUTATION model Pydantic trong state", pt(IT_B06),
     ["test_f17_checkpoint_roundtrip_after_b6_pg"]),
]  # fmt: skip

if "--integration" in sys.argv:
    MUTATIONS = INTEGRATION
elif "--e2e" in sys.argv:
    MUTATIONS = E2E_MUTATIONS
else:
    MUTATIONS = UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS if m[0].startswith(prefix)]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def main() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    before = {m[1]: md5(REPO / m[1]) for m in MUTATIONS}
    for rel, digest in sorted(before.items()):
        print(f"md5 trước  {digest}  {rel}")
    diff_before = git_diff_stat()
    bad = 0
    for name, rel, old, new, cmd, expect in MUTATIONS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if original.count(old) != 1:
            print(f"!! {name}: chuỗi gốc xuất hiện {original.count(old)} lần — bỏ qua")
            bad += 1
            continue
        mutated = original.replace(old, new)
        try:
            path.write_text(mutated, encoding="utf-8")
            out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        finally:
            path.write_text(original, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?::\w+(?:\[.*?\])?)(?: - |$)", out.stdout, re.MULTILINE)))
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in expect if not any(f.endswith("::" + e) or ("::" + e + "[") in f for f in failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        if missing:
            bad += 1
        print(f"{name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
    after = {rel: md5(REPO / rel) for rel in before}
    for rel, digest in sorted(after.items()):
        print(f"md5 sau    {digest}  {rel}")
    assert after == before, "md5 khác sau khôi phục!"
    print("md5 sau khôi phục: khớp")
    assert git_diff_stat() == diff_before, "git diff --stat khác lúc đầu!"
    print("git diff --stat: khớp lúc đầu")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
