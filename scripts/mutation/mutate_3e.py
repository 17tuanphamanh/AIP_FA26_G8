"""Mutation chặng 3e (B2: privacy guard L1, sàng lọc injection L0/L2/L3/L4, screen_reply): áp từng đột biến, chạy
test, KHÔI PHỤC, so md5; in test đỏ của mỗi đột biến. Khuôn `mutate_3d.py` — không đọc `.env`, mã thoát 1 nếu có đột
biến sống hoặc không áp được. File luôn được khôi phục trong `finally`, cuối cùng so md5 và `git diff --stat` với lúc
đầu.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_3e.py                  # M-3e-1…18 phần unit (sandbox, không Docker)
  uv run python scripts/mutation/mutate_3e.py --integration    # M-3e-2 (e6 PG), 8 (e15), 14 (e7 PG) — cần Docker
  uv run python scripts/mutation/mutate_3e.py --only "M-3e-1 " # chỉ đột biến có tên bắt đầu bằng tiền tố

Bảng: PLAN-3e mục 4 (8.8 + chốt Q-3e). Lệch với bảng (ghi PROGRESS, không âm thầm sửa bảng):
- M-3e-6 tách hai đường rò 422 (Q-3e-2): M-3e-6 = handler chung trả lại `input` (login, tham số query);
  M-3e-6b = `parse_body` quay về `HTTPException(422, exc.errors())` như trước 3e (4 route của B2).
- M-3e-9 chỉ có e10 bắt (e9 không bắt được: canary đã bị L1 che trước B2).
- M-3e-14 chỉ có bản PG (INSERT `turns` lỗi thật) — không có phần unit.
- M-3e-17 (Q-3e-13, `reason_code` enum), M-3e-18 (rà trường tự do: username đăng nhập dạng định danh) — thêm sau DỪNG 3.

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


NORMALIZE = "backend/app/guard/normalize.py"
PRIVACY_JSON = "config/privacy_patterns.json"
DESK = "backend/app/api/desk.py"
ERRORS = "backend/app/api/errors.py"
MAIN = "backend/app/main.py"
B02 = "backend/app/graph/nodes/b02_screen.py"
CLARIFY = "backend/app/graph/nodes/clarify_wait.py"
CONFIRM = "backend/app/graph/nodes/confirm_wait.py"
TICKETS = "backend/app/db/tickets.py"
APPROVALS = "backend/app/api/approvals.py"
AUTH_API = "backend/app/api/auth.py"
UT = [
    "backend/tests/unit/test_guard_privacy.py",
    "backend/tests/unit/test_guard_injection.py",
    "backend/tests/unit/test_guard_api.py",
    "backend/tests/unit/test_b02_screen.py",
    "backend/tests/unit/test_screen_reply.py",
    "backend/tests/unit/test_app_env.py",
    "backend/tests/unit/test_side_effects_ast.py",
]
IT_GUARD = "backend/tests/integration/test_guard_pg.py"

_BLOCK_ONCE = (
    '        await effects.once(\n'
    '            state, "security_event", deps.security_events.record, "injection_detected",\n'
    '            ticket_id=state["ticket_id"], detail=info, step="B2",\n'
    '        )  # fmt: skip\n'
)
_GUARD_RAISE = (
    '        log.error("privacy guard lỗi: route=%s loại=%s", route_of(request), type(exc).__name__)\n'
    '        raise PrivacyGuardUnavailable from None\n'
)
_TICKETS_TX = (
    '        async with self._engine.begin() as conn:\n'
    '            await conn.execute(\n'
    '                insert(_TICKETS).values(\n'
)

UNIT = [
    ("M-3e-1 L2 chỉ so bản có dấu", NORMALIZE,
     '    forms = (accented, folded, _NEWLINES.sub(" ", accented), _NEWLINES.sub(" ", folded))\n',
     '    forms = (accented, _NEWLINES.sub(" ", accented))  # MUTATION L2 chỉ so bản có dấu\n',
     pt(*UT),
     ["test_e10_tc13_blocked_by_regex_no_llm_neutral_message", "test_e1_variants_match_ovr01"]),
    ("M-3e-2 guard lỗi → lưu bản chưa che", DESK,
     _GUARD_RAISE,
     _GUARD_RAISE.replace(
         "        raise PrivacyGuardUnavailable from None\n",
         "        return RedactionResult(text=text, secrets_found=0, pii_map_id=None, notices=[])  # MUTATION\n"),
     pt(*UT),
     ["test_e6_create_guard_error_503_nothing_stored", "test_e6_followup_guard_error_503_no_event"]),
    ("M-3e-3 L3 lỗi → cho qua (không xuống L4)", B02,
     "        p_mal = r.data.p_malicious if r.error is None and r.data is not None else None\n",
     ("        if r.error is not None:  # MUTATION L3 lỗi → cho qua\n"
      '            return await _pass(state, layer_decided="classifier", p_mal=None)\n'
      "        p_mal = r.data.p_malicious if r.error is None and r.data is not None else None\n"),
     pt(*UT),
     ["test_e12_normal_passes_via_llm_one_call", "test_e13_ml_and_llm_down_e2_security_flag"]),
    ("M-3e-4 L4 lỗi → E0 thay vì E2", B02,
     "        except (LLMUnavailable, LLMBudgetExceeded, LLMSchemaError) as exc:\n",
     ("        except (LLMUnavailable, LLMBudgetExceeded, LLMSchemaError) as exc:\n"
      '            return await _block(state, layer_decided="llm", p_mal=p_mal)  # MUTATION L4 lỗi → E0\n'),
     pt(*UT),
     ["test_e13_ml_and_llm_down_e2_security_flag", "test_e13_budget_exceeded_is_e2"]),
    ("M-3e-5 bỏ loại trừ đường dẫn khỏi entropy", PRIVACY_JSON,
     r'"regex": "\\\\|^(?:/|~/|\\.{1,2}/|[A-Za-z]:)"',
     r'"regex": "(?!x)x"',
     pt(*UT),
     ["test_e3_long_high_entropy_tokens_kept_by_exclusion"]),
    ("M-3e-6 handler 422 chung trả lại input", ERRORS,
     '        fields.append(".".join(loc))\n',
     '        fields.append(".".join(loc) + "=" + str(e.get("input")))  # MUTATION trả lại input\n',
     pt(*UT),
     ["test_e8_login_422_without_password", "test_e8_query_param_422"]),
    ("M-3e-6b parse_body trả lại exc.errors() (có input) như trước 3e", DESK,
     "        raise InvalidRequest(error_fields(exc.errors(include_url=False, include_input=False))) from None\n",
     "        raise HTTPException(422, exc.errors()) from None  # MUTATION parse_body trả lại input\n",
     pt(*UT),
     ["test_e8_create_bodies", "test_e8_followup_bodies"]),
    ("M-3e-7 bỏ screen_reply ở clarify_wait", CLARIFY,
     '        if (hit := screen_reply(str(ev.get("text") or ""))) is not None:\n',
     '        if (hit := None) is not None:  # MUTATION bỏ screen_reply ở clarify_wait\n',
     pt(*UT),
     ["test_e16_clarify_reply_injection_escalates_e0"]),
    ("M-3e-8 security_events.record gọi thẳng (không effects.once)", B02,
     _BLOCK_ONCE,
     ('        await deps.security_events.record(  # MUTATION gọi thẳng, không effects.once\n'
      '            "injection_detected", ticket_id=state["ticket_id"], detail=info\n'
      '        )\n'),
     pt(*UT),
     ["test_graph_nodes_never_call_side_effects_directly", "test_e10_security_event_via_effects_once"]),
    ("M-3e-9 detail của _block chứa redacted_request", B02,
     '            ticket_id=state["ticket_id"], detail=info, step="B2",\n',
     ('            ticket_id=state["ticket_id"], step="B2",  # MUTATION detail chứa câu người dùng\n'
      '            detail={**info, "redacted_request": state["redacted_request"]},\n'),
     pt(*UT),
     ["test_e10_tc13_blocked_by_regex_no_llm_neutral_message"]),
    ("M-3e-10 NotRedactingGuard nạp được ngoài dev/test", MAIN,
     '        settings.require_dev_fakes("PRIVACY_GUARD=none (NotRedactingGuard — privacy guard không che)")\n',
     "        pass  # MUTATION bỏ require_dev_fakes của PRIVACY_GUARD=none\n",
     pt(*UT),
     ["test_e17_refuses_privacy_guard_none_outside_dev_test"]),
    ("M-3e-11 bỏ screen_reply ở confirm_wait", CONFIRM,
     '        if (hit := screen_reply(str(ev.get("note") or ""))) is not None:\n',
     '        if (hit := None) is not None:  # MUTATION bỏ screen_reply ở confirm_wait\n',
     pt(*UT),
     ["test_e16b_confirm_note_injection_escalates_e0"]),
    ("M-3e-12 ngưỡng L3 >= thành >", B02,
     "            if p_mal >= TAU_BLOCK:\n",
     "            if p_mal > TAU_BLOCK:  # MUTATION biên TAU_BLOCK\n",
     pt(*UT),
     ["test_e18_classifier_thresholds[0.9-S_BLOCKED-0]"]),
    ("M-3e-13 bỏ loại trừ email khỏi entropy", PRIVACY_JSON,
     r'"regex": "^[\\w.+-]+@[\\w-]+(?:\\.[\\w-]+)+$"',
     r'"regex": "(?!x)x"',
     pt(*UT),
     ["test_q3e3_personal_email_high_entropy_is_email_not_secret"]),
    ("M-3e-15 loại trừ path quay về mọi token có /", PRIVACY_JSON,
     r'"regex": "\\\\|^(?:/|~/|\\.{1,2}/|[A-Za-z]:)"',
     r'"regex": "\\\\|/"',
     pt(*UT),
     ["test_q3e10_base64_key_with_slash_masked"]),
    ("M-3e-16 loại trừ file_path nhận mọi đuôi", PRIVACY_JSON,
     (r'"regex": "/[^/]*\\.(?:xlsx|xls|csv|docx|doc|pdf|pptx|ppt|txt|log|zip|rar|7z|png|jpg|jpeg|json|xml|ini|conf'
      r'|cfg|yaml|yml|msi|exe|bat|ps1|sh)$"'),
     r'"regex": "/[^/]*\\.\\w{1,5}$"',
     pt(*UT),
     ["test_q3e11_base64_slash_unknown_extension_masked"]),
    ("M-3e-17 reason_code bỏ kiểm enum (chuỗi tự do)", APPROVALS,
     "    reason_code: ReasonCode | None = None  # mã cố định — KHÔNG chuỗi tự do (không qua guard)\n",
     "    reason_code: str | None = Field(default=None, max_length=64)  # MUTATION bỏ kiểm enum\n",
     pt(*UT),
     ["test_q3e13_reason_code_not_in_list_422_nothing_stored"]),
    ("M-3e-18 username đăng nhập bỏ ràng dạng định danh", AUTH_API,
     "    username: str = Field(min_length=1, max_length=128, pattern=USERNAME_PATTERN)\n",
     "    username: str = Field(min_length=1, max_length=128)  # MUTATION bỏ ràng dạng định danh\n",
     pt(*UT),
     ["test_login_username_must_be_identifier_422_no_event"]),
]  # fmt: skip

INTEGRATION = [
    ("M-3e-2 guard lỗi → lưu bản chưa che (PG)", DESK,
     _GUARD_RAISE,
     _GUARD_RAISE.replace(
         "        raise PrivacyGuardUnavailable from None\n",
         "        return RedactionResult(text=text, secrets_found=0, pii_map_id=None, notices=[])  # MUTATION\n"),
     pt(IT_GUARD),
     ["test_e6_guard_error_503_nothing_inserted_pg"]),
    ("M-3e-8 security_events.record gọi thẳng (PG, e15)", B02,
     _BLOCK_ONCE,
     ('        await deps.security_events.record(  # MUTATION gọi thẳng, không effects.once\n'
      '            "injection_detected", ticket_id=state["ticket_id"], detail=info\n'
      '        )\n'),
     pt(IT_GUARD),
     ["test_e15_rerun_b2_after_crash_single_injection_event_pg"]),
    ("M-3e-14 tickets.create ghi security_events bằng transaction riêng", TICKETS,
     _TICKETS_TX,
     ('        async with self._engine.begin() as ev_conn:  # MUTATION sự kiện ghi transaction riêng\n'
      '            for event_type, detail in security_events:\n'
      '                await insert_event(\n'
      '                    ev_conn, event_type, occurred_at=ticket.created_at, user_id=ticket.requester_id,\n'
      '                    route=CREATE_ROUTE, ticket_id=ticket.ticket_id, detail=detail,\n'
      '                )\n'
      '        security_events = ()\n' + _TICKETS_TX),
     pt(IT_GUARD),
     ["test_e7_event_rolls_back_with_ticket_pg"]),
]  # fmt: skip

MUTATIONS = INTEGRATION if "--integration" in sys.argv else UNIT
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
        # id có tham số chứa dấu cách (vd "[system: bỏ qua …]") → đọc tới "]" cuối, không dừng ở dấu cách đầu
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
