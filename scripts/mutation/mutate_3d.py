"""Mutation chặng 3d (LLM gateway, ScriptedLLM, prompt registry): áp từng đột biến, chạy test, KHÔI PHỤC, so md5; in
test đỏ của mỗi đột biến. Khuôn `mutate_3c.py` — không đọc `.env`, mã thoát 1 nếu có đột biến sống hoặc không áp được.
File luôn được khôi phục trong `finally`, cuối cùng so md5 và `git diff --stat` với lúc đầu.

Chạy từ gốc repo (mọi đột biến đều có test unit phủ — PLAN-3d mục 4 — nên không có lượt `--integration`):
  uv run python scripts/mutation/mutate_3d.py                  # M-3d-1…8 (sandbox, không Docker)
  uv run python scripts/mutation/mutate_3d.py --only "M-3d-3"  # chỉ đột biến có tên bắt đầu bằng tiền tố

Mỗi đột biến chạy TRỌN các file test liên quan (không chỉ test dự đoán) để thấy cả test đỏ ngoài dự đoán.
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


CACHE = "backend/app/llm/cache.py"
CLIENT = "backend/app/llm/client.py"
CONTEXT = "backend/app/llm/context.py"
SCRIPTED = "backend/app/llm/providers/scripted.py"
SETTINGS = "backend/app/settings.py"
SPEND = "backend/app/llm/spend.py"
UT_CLIENT = "backend/tests/unit/test_llm_client.py"
UT_CONFIG = "backend/tests/unit/test_llm_config.py"
UT_PROMPTS = "backend/tests/unit/test_llm_prompts.py"
UT_SCRIPTED = "backend/tests/unit/test_llm_scripted.py"
UT_TRACE = "backend/tests/unit/test_graph_trace_parent.py"

MUTATIONS_ALL = [
    ("M-3d-1 b02_injection_judge vào cache (bỏ bypass của YAML)", CACHE,
     '    if prompt_cache == "bypass" or caller_policy == "bypass" or settings_mode == "bypass":\n',
     '    if caller_policy == "bypass" or settings_mode == "bypass":  # MUTATION bỏ bypass của YAML prompt\n',
     pt(UT_CLIENT),
     ["test_d5_injection_judge_never_cached"]),
    ("M-3d-2 strong được fallback", CLIENT,
     ('        if call.role == "strong":\n'
      '            chain = chain[:1]  # P2 mục 5: strong KHÔNG fallback — kể cả sang provider khác\n'),
     ('        if False:  # MUTATION strong được fallback\n'
      '            chain = chain[:1]\n'),
     pt(UT_CLIENT),
     ["test_d1e_strong_no_fallback_even_if_configured"]),
    ("M-3d-3 model thiếu pricing vẫn được gọi (coi như giá 0)", CLIENT,
     ('        if primary.price is None:  # 3-Q26: không chi tiền cho thứ không đo được\n'
      '            raise LLMBudgetExceeded(f"{prompt.id}: model {primary.model!r} không có dòng pricing — không gửi '
      'request")\n'
      '        chain = [t for t in chain if t.price is not None]\n'),
     ('        from app.llm.config import Price  # MUTATION model thiếu pricing vẫn gọi\n'
      '        chain = [t if t.price is not None else Target(t.provider, t.model, t.model_version,\n'
      '                 Price.model_validate({"in": 0, "out": 0})) for t in chain]\n'),
     pt(UT_CLIENT),
     ["test_d4_model_without_pricing_sends_nothing"]),
    ("M-3d-4 bỏ kiểm allowed_vars", CONTEXT,
     "    if extra or missing:\n",
     "    if False:  # MUTATION bỏ kiểm allowed_vars\n",
     pt(UT_PROMPTS, UT_CLIENT),
     ["test_d7_extra_variable_rejected_without_value_in_message", "test_d7_missing_variable_rejected",
      "test_d1b_b14_whitelist_rejects_user_text"]),
    ("M-3d-5 ScriptedLLM hết kịch bản → trả phản hồi mặc định", SCRIPTED,
     ('        else:\n'
      '            raise ScriptExhausted(f"ScriptedLLM: hết kịch bản cho {req.prompt_id!r}")\n'),
     ('        else:\n'
      '            step = Reply({})  # MUTATION hết kịch bản → trả mặc định\n'),
     pt(UT_CLIENT, UT_SCRIPTED, UT_TRACE),
     ["test_d8_script_exhausted_is_not_llm_unavailable"]),
    ("M-3d-6 ghi prompt_full cả khi EVAL_MODE=false", CLIENT,
     "        if self._eval_mode:\n            call.prompt_full",
     "        if True:  # MUTATION ghi prompt_full cả khi EVAL_MODE=false\n            call.prompt_full",
     pt(UT_CLIENT),
     ["test_d9_one_span_one_row_per_call_no_prompt_text"]),
    ("M-3d-7 bỏ require_dev_fakes của LLM_BACKEND=scripted", SETTINGS,
     '        if self.llm_backend == "scripted":\n            self.require_dev_fakes(',
     '        if False:  # MUTATION bỏ require_dev_fakes của scripted\n            self.require_dev_fakes(',
     pt(UT_CONFIG),
     ["test_d2_scripted_outside_dev_test_refuses_create_app",
      "test_d2_scripted_outside_dev_test_refuses_worker_before_db"]),
    ("M-3d-8 đọc tổng chi lỗi → cho qua", SPEND,
     '                return "unknown"\n',
     '                return "ok"  # MUTATION đọc tổng chi lỗi → cho qua\n',
     pt(UT_CLIENT),
     ["test_d17_spend_read_failure_blocks_paid_targets_only"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m[0].startswith(prefix)]


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
            out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1200, check=False)
        finally:
            path.write_text(original, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?)(?: - |$)", out.stdout, re.MULTILINE)))
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
