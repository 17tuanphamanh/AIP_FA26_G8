"""Mutation chặng LLM-G (PLAN LLM-G DỪNG 1: `extra_body` của provider). Mỗi đột biến áp lên file thật, chạy bộ test, khôi phục
trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần
trước khi đột biến.

  uv run python scripts/mutation/mutate_llmg.py                    # cả 7 mã (unit backend, sandbox, không Docker)
  uv run python scripts/mutation/mutate_llmg.py --only M-LLMG-3

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


CONFIG = "backend/app/llm/config.py"
PROVIDER = "backend/app/llm/providers/openai_compat.py"
WIRING = "backend/app/llm/wiring.py"

UT = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in ("test_llm_config", "test_llm_client", "test_llm_security", "test_monitor_health")
])  # fmt: skip


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_PASS = '        extra: dict[str, Any] = {} if self._extra_body is None else {"extra_body": self._extra_body}\n'
_WIRE = "                                            json_mode=p.json_mode, extra_body=p.extra_body)  # fmt: skip\n"
_CLASH = "            clash = sorted(k for k in v if k.strip().lower() in EXTRA_BODY_FORBIDDEN)\n"
_COPY = "        self._extra_body = copy.deepcopy(extra_body)\n"
_HIDE = '_FROZEN = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)\n'
_JSON = "                json.dumps(v, allow_nan=False)\n"

# Danh sách khoá cấm chép độc lập với code (PLAN LLM-G, 3 nhóm) — M-LLMG-2 phải làm đỏ MỌI ca
FORBIDDEN = [
    "model", "messages", "max_tokens", "max_completion_tokens", "temperature", "response_format", "timeout",
    "stream", "stream_options", "n", "tools", "tool_choice", "functions", "function_call", "parallel_tool_calls",
    "logprobs", "top_logprobs", "modalities", "audio", "prediction",
    "stop", "top_p", "seed", "logit_bias", "presence_penalty", "frequency_penalty",
]  # fmt: skip
NORMALIZED = [" Model ", "MAX_TOKENS", "Stop"]
REJECT = "test_llmg_extra_body_rejects_gateway_keys"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-LLMG-1a provider bỏ truyền extra_body",
             [one(PROVIDER, _PASS, "        extra: dict[str, Any] = {}  # MUTATION M-LLMG-1a\n")],
             UT, ["test_llmg_extra_body_adds_thinking_and_keeps_gateway_fields", "test_llmg_extra_body_copied_not_shared",
                  "test_llmg_extra_body_through_gateway"]),
    Mutation("M-LLMG-1b wiring bỏ truyền p.extra_body",
             [one(WIRING, _WIRE, "                                            json_mode=p.json_mode)"
                                 "  # MUTATION M-LLMG-1b  # fmt: skip\n")],
             UT, ["test_llmg_wiring_passes_extra_body_and_json_mode"]),
    Mutation("M-LLMG-2 bỏ validator khoá cấm",
             [one(CONFIG, _CLASH, "            clash: list[str] = []  # MUTATION M-LLMG-2\n")],
             UT, [*(f"{REJECT}[{k}]" for k in FORBIDDEN + NORMALIZED),
                  "test_llmg_extra_body_rejects_forbidden_key_beside_allowed_one"]),
    Mutation("M-LLMG-3 mặc định vẫn gửi {thinking: {type: disabled}}",
             [one(PROVIDER, _COPY, '        self._extra_body = copy.deepcopy(extra_body) if extra_body is not None else '
                                   '{"thinking": {"type": "disabled"}}  # MUTATION M-LLMG-3\n')],
             UT, ["test_llmg_no_extra_body_sends_exact_gateway_keys[json_schema]",
                  "test_llmg_no_extra_body_sends_exact_gateway_keys[json_object]"]),
    Mutation("M-LLMG-4 bỏ strip/lower khi so khoá cấm",
             [one(CONFIG, _CLASH, _CLASH.replace("k.strip().lower() in", "k in").rstrip("\n") + "  # MUTATION M-LLMG-4\n")],
             UT, [f"{REJECT}[{k}]" for k in NORMALIZED]),
    Mutation("M-LLMG-5 bỏ hide_input_in_errors",
             [one(CONFIG, _HIDE, '_FROZEN = ConfigDict(extra="forbid", frozen=True)  # MUTATION M-LLMG-5\n')],
             UT, ["test_llmg_load_error_hides_input_values[gia-tri-dau]",
                  "test_llmg_load_error_hides_input_values[gia-tri-cuoi]"]),
    Mutation("M-LLMG-6 bỏ kiểm JSON lúc nạp",
             [one(CONFIG, _JSON, "                pass  # MUTATION M-LLMG-6\n")],
             UT, [f"test_llmg_extra_body_must_be_json_at_load[{k}]" for k in ("date", "nan", "inf")]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix)]


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
