"""Mutation gói 2 — nạp `intent-clf` vào ml-service (D-53; `dac-ta-bat-2-model.md` 6.2, mục 8 "Mutation gói 2"; MẪU A g2-intent
đã duyệt). Khuôn `mutate_b2review.py`: mỗi đột biến áp lên file thật, chạy bộ test, khôi phục trong `finally`, so md5 + `git diff
--stat` trước/sau. Luật N3 (`n3.py`): file đích còn chữ `MUTATION` → dừng; mốc xanh một lần cho mỗi lệnh test trước khi đột biến.

  uv run python scripts/mutation/mutate_g2intent.py
  uv run python scripts/mutation/mutate_g2intent.py --only M-G2I-5

Hai bộ test: ML (không torch, như `make test`) và TORCH (marker `ml_torch`: B3Model giả nhỏ, safetensors, script chuyển). Lệnh
TORCH mặc định `uv run --group ml pytest`; đặt `ML_TORCH_PYTHON=<python có torch>` để chạy bằng interpreter khác (máy không tải
được torch từ index CPU). Thiếu torch → DỪNG (test `ml_torch` tự bỏ qua, đột biến sẽ "sống" giả).

Nhóm theo điểm của đặc tả: 1 = nạp (thư mục, SHA, manifest, safetensors strict, script chuyển), 2 = điểm trộn / thứ tự nhãn /
ngưỡng / truncated, 3 = hàng chờ và bọc lỗi (`classify_failed`), 4 = không đặt INTENT_MODEL_DIR → 503.
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
QUIET = ["-q", "-p", "no:cacheprovider"]
ML_TESTS = ["ml_service/tests", "-o", "pythonpath=ml_service"]


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, *QUIET]


def pt_torch(*args: str) -> list[str]:
    py = os.environ.get("ML_TORCH_PYTHON")
    head = [py, "-m", "pytest"] if py else ["uv", "run", "--group", "ml", "pytest"]
    return [*head, *args, *QUIET]


INTENT = "ml_service/app/intent.py"
MODEL = "ml_service/app/intent_model.py"
MAIN = "ml_service/app/main.py"
LOADER = "ml_service/app/loader.py"
CONVERT = "scripts/ml/convert_intent_pt.py"

ML = pt(*ML_TESTS, "-m", "not ml_real")
TORCH = pt_torch(*ML_TESTS, "-m", "ml_torch")


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    cmd: list[str]
    expect: list[str]  # test PHẢI đỏ


def one(rel: str, old: str, new: str) -> tuple[str, str, str, int]:
    return (rel, old, new, 1)


def off(rel: str, cond: str, tag: str) -> tuple[str, str, str, int]:
    """`<thụt>if <điều kiện>:` → `<thụt>if False:  # MUTATION <tag>` (bỏ một phép kiểm)."""
    indent = cond[: len(cond) - len(cond.lstrip())]
    return one(rel, cond, f"{indent}if False:  # MUTATION {tag}\n")


# ---- chuỗi đích ------------------------------------------------------------------------------------------------------

_FORBID = '    forbidden = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.suffix.lower() in FORBIDDEN_SUFFIXES)\n'
_W_SHA = "    if weights_sha != settings.intent_model_sha256:\n"
_MANIFEST = '    hashes = verify_manifest(d, settings.intent_manifest_sha256, "INTENT_MANIFEST_SHA256", IntentLoadError)\n'
_M_REQ = "    if settings.intent_manifest_sha256 is None:\n"
_STRICT = "        model.load_state_dict(state, strict=True, assign=True)\n"
_FP32_FILE = "    odd = sorted(k for k, v in state.items() if v.dtype != torch.float32)\n"
_FP32_PARAM = "    wrong = [n for n, p in model.named_parameters() if p.dtype != torch.float32]\n"
_RESET = "    _reset_unsaved_buffers(model, spec)\n"
_CHECK = "    intent_spec = check_intent(settings)  # gói 2: sai file/SHA/manifest/config/ngưỡng → IntentLoadError, chưa đụng torch\n"
_THREADS = "    torch.set_num_threads(settings.ml_threads)\n"
_WEIGHTS_ONLY = '        state = torch.load(pt, map_location="cpu", weights_only=True)  # tường minh: không unpickle đối tượng tuỳ ý\n'
_PT_SHA = "    if actual != expected_sha:\n"
_GELU = "            nn.Dropout(dropout), nn.Linear(3 * h, h), nn.GELU(), nn.Dropout(dropout), nn.Linear(h, n_labels)\n"
_CAT = "        seq_logits = self.seq_head(torch.cat([h[:, 0], att_pool, req_pool], -1))\n"
_MIX2 = "    if mix[2] != 0:\n"
_MIX = "    w_seq, w_span = intent.mix\n"
_PROBS = "        probs=dict(zip(intent.labels, probs, strict=True)), tau_hi=dict(intent.tau_hi), tau_lo=dict(intent.tau_lo),\n"
_KS = "    ks = [t for t, (a, b) in enumerate(offsets) if b > a and anchor(text, a, b) >= 0]\n"
_TRUNC = "        truncated=raw.full_len > intent.max_len, model=INTENT_LABEL, version=intent.version,\n"
_LO_HI = "        if lo > hi:\n"
_LABELS = "    if not isinstance(labels, list) or tuple(labels) != LABELS:\n"
_REQ = "    if [float(v) for v in req_mask] != want:\n"
_FINITE = "    if not all(math.isfinite(p) for p in probs):  # NaN lọt vào JSON/audit là sai lặng lẽ — ném → classify_failed\n"
_QUEUE = "            out = await run_classify(classify_intent_sync, intent, body.text)\n"
_EXCEPT = "        except Exception as e:  # noqa: BLE001 — lỗi suy luận / điểm NaN → 500 mã chung; log TÊN lớp lỗi, không thông điệp/chữ\n"
_MISSING = "        if intent is None:\n            return intent_missing()\n"

T_INTENT = "test_intent.py"
NAN = "test_nan_or_inf_score_classify_failed"
REF = "test_scores_match_reference"

MUTATIONS_ALL: list[Mutation] = [
    # ---- 1. nạp --------------------------------------------------------------------------------------------------------
    Mutation("M-G2I-1 cho phép .pt trong thư mục nạp",
             [one(INTENT, _FORBID, _FORBID.replace("in FORBIDDEN_SUFFIXES)", 'in FORBIDDEN_SUFFIXES - {".pt"})').replace(
                 "\n", "  # MUTATION M-G2I-1\n"))],
             ML, ["test_pickle_or_code_file_refused[seed_42.pt]"]),
    Mutation("M-G2I-2 bỏ kiểm SHA trọng số", [off(INTENT, _W_SHA, "M-G2I-2")], ML, ["test_weights_sha_mismatch_refused"]),
    Mutation("M-G2I-3 bỏ kiểm manifest",
             [one(INTENT, _MANIFEST, "    hashes = {WEIGHTS_FILE: __import__('hashlib').sha256((d / WEIGHTS_FILE).read_bytes())"
                                     ".hexdigest()}  # MUTATION M-G2I-3\n")],
             ML, ["test_manifest_sha_mismatch_refused", "test_extra_file_not_in_manifest_refused",
                  "test_file_changed_after_manifest_refused"]),
    Mutation("M-G2I-4 INTENT_MANIFEST_SHA256 không bắt buộc", [off(INTENT, _M_REQ, "M-G2I-4")],
             ML, ["test_sha_vars_required[intent_manifest_sha256]"]),
    Mutation("M-G2I-5 strict=False", [one(MODEL, _STRICT, _STRICT.replace("strict=True", "strict=False").replace(
                 "\n", "  # MUTATION M-G2I-5\n"))], TORCH, ["test_extra_key_refused"]),
    Mutation("M-G2I-6 nạp trọng số fp16 không từ chối",
             [one(MODEL, _FP32_FILE, "    odd: list[str] = []  # MUTATION M-G2I-6\n"),
              one(MODEL, _FP32_PARAM, "    wrong: list[str] = []  # MUTATION M-G2I-6\n")],
             TORCH, ["test_fp16_weights_refused"]),
    Mutation("M-G2I-7 không dựng lại buffer không lưu", [one(MODEL, _RESET, "    pass  # MUTATION M-G2I-7\n")],
             TORCH, ["test_load_valid_package"]),
    Mutation("M-G2I-8 kiểm thư mục intent SAU khi import torch",
             [one(LOADER, _CHECK, "    # MUTATION M-G2I-8: check_intent dời xuống sau import torch\n"),
              one(LOADER, _THREADS, _THREADS + "    intent_spec = check_intent(settings)  # MUTATION M-G2I-8\n")],
             ML, ["test_intent_dir_blocks_startup_before_torch"]),
    Mutation("M-G2I-9 script chuyển: weights_only=False",
             [one(CONVERT, _WEIGHTS_ONLY, _WEIGHTS_ONLY.replace("weights_only=True)", "weights_only=False)").replace(
                 "\n", "  # MUTATION M-G2I-9\n"))],
             TORCH, ["test_weights_only_blocks_pickled_code", "test_weights_only_passed_explicitly"]),
    Mutation("M-G2I-10 script chuyển: bỏ kiểm SHA trước torch.load", [off(CONVERT, _PT_SHA, "M-G2I-10")],
             TORCH, ["test_sha_mismatch_stops_before_torch_load"]),
    Mutation("M-G2I-11 seq_head dùng ReLU thay GELU",
             [one(MODEL, _GELU, _GELU.replace("nn.GELU()", "nn.ReLU()").replace("\n", "  # MUTATION M-G2I-11\n"))],
             TORCH, [REF]),
    Mutation("M-G2I-12 đảo att_pool / req_pool",
             [one(MODEL, _CAT, _CAT.replace("att_pool, req_pool", "req_pool, att_pool").replace("\n", "  # MUTATION M-G2I-12\n"))],
             TORCH, [REF]),
    # ---- 2. điểm, thứ tự nhãn, ngưỡng, truncated -------------------------------------------------------------------------
    Mutation("M-G2I-13 bỏ kiểm mix_weights[2]", [off(INTENT, _MIX2, "M-G2I-13")], ML, ["test_mix_weights_2_nonzero_refused"]),
    Mutation("M-G2I-14 đảo trọng số 0,4/0,6",
             [one(INTENT, _MIX, "    w_span, w_seq = intent.mix  # MUTATION M-G2I-14\n")],
             ML, ["test_mixed_score_04_sigmoid_06_span"]),
    Mutation("M-G2I-15 probs xếp theo chữ cái",
             [one(INTENT, _PROBS, _PROBS.replace("probs=dict(zip(intent.labels, probs, strict=True))",
                                                 "probs=dict(sorted(zip(intent.labels, probs, strict=True)))").replace(
                 "\n", "  # MUTATION M-G2I-15\n"))],
             ML, ["test_probs_follow_config_label_order", "test_probs_order_over_http"]),
    Mutation("M-G2I-16 bỏ lọc token (offset, _anchor)",
             [one(INTENT, _KS, "    ks = list(range(len(offsets)))  # MUTATION M-G2I-16\n")],
             ML, ["test_special_tokens_ignored_in_span", "test_whitespace_only_token_ignored_by_anchor"]),
    Mutation("M-G2I-17 bỏ _anchor (giữ b > a)",
             [one(INTENT, _KS, _KS.replace(" and anchor(text, a, b) >= 0", "").replace("\n", "  # MUTATION M-G2I-17\n"))],
             ML, ["test_whitespace_only_token_ignored_by_anchor"]),
    Mutation("M-G2I-18 truncated ≥ thay >",
             [one(INTENT, _TRUNC, _TRUNC.replace("full_len > intent", "full_len >= intent").replace("\n", "  # MUTATION M-G2I-18\n"))],
             ML, ["test_truncated_flag_boundary[160-False]"]),
    Mutation("M-G2I-19 tau_hi cố định 0,75",
             [one(INTENT, _PROBS, _PROBS.replace("tau_hi=dict(intent.tau_hi)", "tau_hi=dict.fromkeys(intent.labels, 0.75)").replace(
                 "\n", "  # MUTATION M-G2I-19\n"))],
             ML, ["test_tau_from_thresholds"]),
    Mutation("M-G2I-20 bỏ kiểm tau_lo ≤ tau_hi", [off(INTENT, _LO_HI, "M-G2I-20")], ML, ["test_thresholds_lo_above_hi_refused"]),
    Mutation("M-G2I-21 labels không kiểm thứ tự",
             [one(INTENT, _LABELS, _LABELS.replace("tuple(labels) != LABELS", "sorted(labels) != sorted(LABELS)").replace(
                 "\n", "  # MUTATION M-G2I-21\n"))],
             ML, ["test_labels_wrong_refused[labels0]", "test_labels_wrong_refused[labels1]"]),
    Mutation("M-G2I-22 bỏ kiểm req_mask đúng tag REQ", [off(INTENT, _REQ, "M-G2I-22")], ML, ["test_req_mask_not_on_req_tags_refused"]),
    # ---- 3. hàng chờ, bọc lỗi ----------------------------------------------------------------------------------------------
    Mutation("M-G2I-23 classify_intent dùng hàng chung embed/rerank",
             [one(MAIN, _QUEUE, _QUEUE.replace("run_classify(", "run(").replace("\n", "  # MUTATION M-G2I-23\n"))],
             ML, ["test_classify_intent_not_queued_behind_running_rerank"]),
    Mutation("M-G2I-24 bỏ kiểm NaN/inf", [off(INTENT, _FINITE, "M-G2I-24")],
             ML, [f"{NAN}[nan-0.0]", f"{NAN}[0.0-inf]", f"{NAN}[0.0-nan]", "test_nan_score_raises_value_error"]),
    Mutation("M-G2I-25 chỉ bọc ValueError (lỗi model lọt ra)",
             [one(MAIN, _EXCEPT, "        except ValueError as e:  # MUTATION M-G2I-25\n")],
             ML, ["test_model_error_classify_failed", "test_wrong_logit_count_classify_failed"]),
    # ---- 4. không đặt INTENT_MODEL_DIR → 503 ----------------------------------------------------------------------------
    Mutation("M-G2I-26 bỏ nhánh 503 model_missing",
             [one(MAIN, _MISSING, "        pass  # MUTATION M-G2I-26\n")],
             ML, ["test_no_intent_model_503_and_health_missing", "test_a7_classifiers_model_missing[/classify_intent]"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.split(" ")[0] == prefix or m.name.startswith(prefix + " ")]


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


def _torch_ok(env: dict[str, str]) -> bool:
    probe = [*TORCH[: TORCH.index("pytest")], "python", "-c", "import torch, transformers, safetensors"]
    if TORCH[0] != "uv":  # ML_TORCH_PYTHON: <python> -m pytest …
        probe = [TORCH[0], "-c", "import torch, transformers, safetensors"]
    return subprocess.run(probe, cwd=REPO, env=env, capture_output=True, check=False).returncode == 0


def main() -> int:
    env = test_env()
    if any(m.cmd is TORCH for m in MUTATIONS) and not _torch_ok(env):
        print("DỪNG: lệnh TORCH không import được torch/transformers/safetensors — test ml_torch sẽ tự bỏ qua, đột biến"
              " sống giả. Cài nhóm uv `ml` hoặc đặt ML_TORCH_PYTHON.")
        return 2
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
    print(f"{len(MUTATIONS) - bad}/{len(MUTATIONS)} đột biến bị giết đúng dự đoán")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
