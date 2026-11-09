"""Mutation gói 1 — B2 `review` (D-52; `dac-ta-bat-2-model.md` mục 8; PLAN-B2REVIEW 5.4). Khuôn `mutate_t23a.py`: mỗi đột biến áp lên
file thật, chạy bộ test, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ
`MUTATION` → dừng; mốc xanh một lần cho mỗi lệnh test trước khi đột biến.

  uv run python scripts/mutation/mutate_b2review.py                 # 10 mã ĐT mục 8 + 8 mã phụ X (sandbox, không Docker)
  uv run python scripts/mutation/mutate_b2review.py --only M-B2R-7

10 mã M-B2R-1…10 = đúng danh sách ĐT mục 8 (phải đỏ hết). Mã phụ M-B2R-X1…X8 (duyệt MẪU B1, 18/10): chứng minh 12 test DỪNG 2 từng
"xpassed" trên commit 1 KHÔNG rỗng — chúng kiểm hành vi có sẵn mà DỪNG 2 không được phá (không chặn quá tay), và mỗi test đỏ khi
code bị sửa quá tay theo đúng hướng đó.
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


B2_REVIEW = "backend/app/guard/b2_review.py"
B02 = "backend/app/graph/nodes/b02_screen.py"
B20 = "backend/app/graph/nodes/b20_audit.py"
STATES = "backend/app/domain/states.py"
SETTINGS = "backend/app/settings.py"
CLIENT = "backend/app/ml/client.py"
MODELS = "backend/app/ml/models.py"
ML_MAIN = "ml_service/app/main.py"
ML_GUARD = "ml_service/app/guard.py"

BE = pt(*[
    f"backend/tests/unit/{name}.py"
    for name in ("test_b02_review", "test_b2_review_decision", "test_b02_screen", "test_settings_b2_review",
                 "test_ml_client_classify_failed", "test_ml_client", "test_turn_deadline")
])  # fmt: skip
ML = pt("ml_service/tests", "-o", "pythonpath=ml_service", "-m", "not ml_real")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_TAU = "        if (p_mal is not None and p_mal >= tau) or ml_error == TOO_MANY_WINDOWS:\n"
_E1 = '            return Verdict("E1", "classifier")\n'
_CAT = '    if is_attack or category != "none":\n'
_L4 = "        try:  # L4: mọi câu ở `shadow`/`review`; vùng giữa HOẶC L3 lỗi ở `active` — L4 nhận bản CHƯA thay nhãn\n"
_SUSPECT = "        # gói 1 (#4, #5): chuyển L2, KHÔNG security_event, KHÔNG security_flag; S_SCREENING → S_ESCALATED theo quy tắc 2 (D-29)\n"
_JUDGE_TEXT = '                "fast", "b02_injection_judge", {"text": text}, InjectionJudgeOut, cache_policy="bypass"\n'
_PASS = "    async def _pass(state: Any, **info: Any) -> dict[str, Any]:\n"
_MSG = 'SUSPECTED_MESSAGE_CODE = {"injection_suspected": "E0"}\n'
_QUEUE = "    classify_limiter = asyncio.Semaphore(settings.ml_classify_concurrency)\n"
_MANIFEST = "    hashes = _check_manifest(d, settings)  # gói 1 #9 — băm mỗi file MỘT lần (trọng số ~1,1 GB)\n"
_F5 = "        and to not in {S_CLASSIFYING, S_BLOCKED, S_ESCALATED},\n"
_ACTIVE_ENV = '        if self.b2_classifier_mode == "active" and self.app_env not in B2_ACTIVE_ENVS:\n'
_FAILED_500 = '        return endpoint in CLASSIFY_ENDPOINTS and _error_code(response) == "classify_failed"\n'
_NO_RETRY = 'NO_TIMEOUT_RETRY = frozenset({"classify"})  # gói 1 (ĐT 4.6): timeout không thử lại\n'
_CONNECT = '            except httpx.ConnectError:\n                kind = "connect"\n                raise\n'
_L3_RETURN = "            if _is_l3_error(endpoint, response):\n"
_BOUNDS = "    p_malicious: float = Field(ge=0, le=1, allow_inf_nan=False)\n"
_SET_EQ = "    if extra or missing:\n"

E1_ROW4 = "test_row4_high_p_llm_no_is_e1"
CLIENT_RETRY = "test_classify_connect_and_other_5xx_retried"

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-B2R-1 ≥ τ thành > τ",
             [one(B2_REVIEW, _TAU, _TAU.replace("p_mal >= tau", "p_mal > tau").replace(":\n", ":  # MUTATION M-B2R-1\n"))],
             BE, ["test_a3_review_p_equal_tau_is_e1_classifier"]),
    Mutation("M-B2R-2 bỏ gọi LLM khi p cao",
             [one(B02, _L4, "        if clf_mode == \"review\" and p_mal is not None and tau is not None and p_mal >= tau:"
                            "  # MUTATION M-B2R-2\n            return await _suspect(state, layer_decided=\"classifier\", **base)\n"
                            + _L4)],
             BE, [E1_ROW4]),
    Mutation("M-B2R-3 cho qua khi p cao",
             [one(B2_REVIEW, _E1, '            return Verdict("pass", "llm")  # MUTATION M-B2R-3\n')],
             BE, ["test_a4b_review_high_p_e1", E1_ROW4]),
    Mutation("M-B2R-4 ghi security_event ở #4",
             [one(B02, _SUSPECT, _SUSPECT + '        await effects.once(state, "security_event", deps.security_events.record,'
                                  ' "injection_detected", ticket_id=state["ticket_id"], detail=info, step="B2")  # MUTATION M-B2R-4\n')],
             BE, [E1_ROW4]),
    Mutation("M-B2R-5 dùng tin E1 cho injection_suspected",
             [one(B20, _MSG, "SUSPECTED_MESSAGE_CODE: dict[str, str] = {}  # MUTATION M-B2R-5\n")],
             BE, [E1_ROW4]),
    Mutation("M-B2R-6 bỏ category ≠ none",
             [one(B2_REVIEW, _CAT, "    if is_attack:  # MUTATION M-B2R-6\n")],
             BE, ["test_a2_review_category_not_none_e0_llm_row3", "test_row3_old_modes_also_e0"]),
    Mutation("M-B2R-7 thay nhãn che cả ở bản gửi LLM",
             [one(B02, _JUDGE_TEXT, _JUDGE_TEXT.replace('{"text": text}', '{"text": model_text}').replace(
                 "\n", "  # MUTATION M-B2R-7\n"))],
             BE, ["test_c_mask_replace_only_in_review"]),
    Mutation("M-B2R-8 bỏ ml_error ở nhánh qua",
             [one(B02, _PASS, _PASS + '        info = {k: v for k, v in info.items() if k != "ml_error"}  # MUTATION M-B2R-8\n')],
             BE, ["test_row7_infra_error_passes_with_ml_error"]),
    Mutation("M-B2R-9 classify dùng chung hàng chờ",
             [one(ML_MAIN, _QUEUE, "    classify_limiter = limiter  # MUTATION M-B2R-9\n")],
             ML, ["test_classify_not_queued_behind_running_rerank"]),
    Mutation("M-B2R-10 bỏ kiểm manifest",
             [one(ML_GUARD, _MANIFEST, "    hashes = {WEIGHTS_FILE: sha256_file(d / WEIGHTS_FILE)}  # MUTATION M-B2R-10\n")],
             ML, ["test_manifest_missing_a_file_refused", "test_extra_file_in_dir_refused", "test_one_file_sha_wrong_refused"]),
    # ---- mã phụ: 12 test từng xpassed trên commit 1 không rỗng --------------------------------------------------------------
    Mutation("M-B2R-X1 F5 cấm S_SCREENING → S_ESCALATED",
             [one(STATES, _F5, "        and to not in {S_CLASSIFYING, S_BLOCKED},  # MUTATION M-B2R-X1\n")],
             BE, ["test_e1_transition_not_forbidden"]),
    Mutation("M-B2R-X2 active bị từ chối cả ở dev/test",
             [one(SETTINGS, _ACTIVE_ENV, '        if self.b2_classifier_mode == "active":  # MUTATION M-B2R-X2\n')],
             BE, ["test_active_in_dev_test_accepted[dev]", "test_active_in_dev_test_accepted[test]"]),
    Mutation("M-B2R-X3 mọi 500 của classify thành classify_failed",
             [one(CLIENT, _FAILED_500, "        return endpoint in CLASSIFY_ENDPOINTS  # MUTATION M-B2R-X3\n")],
             BE, ["test_plain_500_classify_still_retried"]),
    Mutation("M-B2R-X4 không thử lại timeout cả ở embed",
             [one(CLIENT, _NO_RETRY, 'NO_TIMEOUT_RETRY = frozenset({"classify", "embed"})  # MUTATION M-B2R-X4\n')],
             BE, ["test_embed_timeout_still_retried"]),
    Mutation("M-B2R-X5 classify mất kết nối không thử lại",
             [one(CLIENT, _CONNECT, '            except httpx.ConnectError:\n                kind = "connect"\n'
                                    "                if endpoint in NO_TIMEOUT_RETRY:  # MUTATION M-B2R-X5\n"
                                    "                    raise _TimeoutNoRetry from None\n                raise\n")],
             BE, [f"{CLIENT_RETRY}[step0-connect]"]),
    Mutation("M-B2R-X6 5xx khác của classify không thử lại",
             [one(CLIENT, _L3_RETURN, "            if endpoint in NO_TIMEOUT_RETRY and response.status_code >= 500:"
                                      "  # MUTATION M-B2R-X6\n                return response\n" + _L3_RETURN)],
             BE, [f"{CLIENT_RETRY}[step1-http_5xx]", f"{CLIENT_RETRY}[step2-http_5xx]"]),
    Mutation("M-B2R-X7 biên p_malicious mở (0 và 1 bị loại)",
             [one(MODELS, _BOUNDS, "    p_malicious: float = Field(gt=0, lt=1, allow_inf_nan=False)  # MUTATION M-B2R-X7\n")],
             BE, ["test_p_malicious_bounds_accepted[0.0]", "test_p_malicious_bounds_accepted[1.0]"]),
    Mutation("M-B2R-X8 manifest đúng vẫn bị từ chối",
             [one(ML_GUARD, _SET_EQ, "    if True:  # MUTATION M-B2R-X8\n")],
             ML, ["test_valid_dir_accepted"]),
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
