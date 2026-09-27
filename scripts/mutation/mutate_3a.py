"""Mutation chặng 3a (ml-service): áp từng đột biến, chạy test, KHÔI PHỤC, so md5; in test đỏ của mỗi đột biến.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_3a.py          # 13 đột biến, test loader giả (không cần model)
  uv run python scripts/mutation/mutate_3a.py --real   # M-3a-2/3/6, M9, M14 với model thật (cần make models)
  uv run python scripts/mutation/mutate_3a.py --only M15   # chỉ các đột biến có tên bắt đầu bằng "M15"

Không đọc `.env`: pytest chạy qua `conftest.py` gốc (`APP_ENV_FILE=""`, token ngẫu nhiên). Mã thoát 1 nếu có
đột biến sống hoặc không áp được. File luôn được khôi phục trong `finally`, cuối cùng so md5 với lúc đầu.
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ML = ["uv", "run", "pytest", "ml_service/tests", "-o", "pythonpath=ml_service", "-m", "not ml_real",
      "-q", "-p", "no:cacheprovider",
      "--deselect", "ml_service/tests/test_lock.py::test_repo_lock_pins_40_hex_revisions"]


def be(*files: str) -> list[str]:
    return ["uv", "run", "pytest", *files, "-q", "-p", "no:cacheprovider"]


MUTATIONS = [
    ("M-3a-1 bỏ kiểm token", "ml_service/app/main.py",
     "api = APIRouter(dependencies=[Depends(require_token)])", "api = APIRouter()  # MUTATION", ML,
     "test_missing_token_401"),
    ("M-3a-2 truncated luôn False", "ml_service/app/embed.py",
     "truncated=[n > EMBED_MAX_TOKENS for n in counts]", "truncated=[False for n in counts]", ML,
     "test_a4f_embed_truncated_over_512"),
    ("M-3a-3 đếm không token đặc biệt", "ml_service/app/tokens.py",
     "return len(tokenizer(text, add_special_tokens=True)", "return len(tokenizer(text, add_special_tokens=False)", ML,
     "test_a3f_count_includes_special_tokens"),
    ("M-3a-4 retry cả model_missing", "backend/app/ml/client.py",
     "if response.status_code == 503 and _is_model_missing(response):",
     "if response.status_code == 503 and _is_model_missing(response) and False:  # MUTATION",
     be("backend/tests/unit/test_ml_client.py", "backend/tests/unit/test_fake_ml.py"),
     "test_a11_model_missing_single_call_no_retry"),
    ("M-3a-5 nuốt 5xx thành rỗng", "backend/app/ml/client.py",
     "            return MlResult(None, kind, attempts)\n",
     "            return MlResult(None, None, attempts)  # MUTATION\n",
     be("backend/tests/unit/test_ml_client.py"), "test_a10_500_forever_is_value_not_exception"),
    ("M-3a-6 không cắt câu truy vấn", "ml_service/app/rerank.py",
     "if len(ids) <= QUERY_MAX_TOKENS:", "if True:  # MUTATION", ML, "test_a6f_rerank_cuts_query_not_passage"),
    ("M7 TransportError không đổi thành connect", "backend/app/ml/client.py",
     ("            except httpx.TransportError as e:  # Q-3a-3: đứt giữa chừng = mất kết nối, có retry\n"
      "                kind = \"connect\"\n"
      "                raise httpx.ConnectError(f\"{type(e).__name__}: {e}\") from e\n"),
     "            # MUTATION bỏ nhánh TransportError\n",
     be("backend/tests/unit/test_ml_client.py"), "test_infra_errors_retried_then_returned"),
    ("M8 không chia lô theo byte", "backend/app/ml/client.py",
     "if current and (len(current) == max_items or size + n > budget):",
     "if current and (len(current) == max_items):  # MUTATION",
     be("backend/tests/unit/test_ml_client.py"), "test_batches_split_by_bytes_too"),
    ("M9 không sigmoid", "ml_service/app/rerank.py",
     "scores=[sigmoid(x) for x in logits]", "scores=list(logits)", ML,
     "test_a5_rerank_scores_in_order_and_unit_interval"),
    ("M10 bỏ giới hạn body", "ml_service/app/main.py",
     "    app.add_middleware(BodyLimitMiddleware)", "    pass  # MUTATION", ML,
     "test_chunked_body_over_limit_413_handler_not_run"),
    ("M11 health bỏ check ml", "backend/app/main.py",
     'return {"db": db, "qdrant": qdrant, "mock": mock, "ml": ml}',
     'return {"db": db, "qdrant": qdrant, "mock": mock}  # MUTATION',
     be("backend/tests/unit/test_health.py"), "test_default_checks_are_db_qdrant_mock_ml"),
    ("M12 worker không kiểm token", "backend/app/graph/wiring.py",
     "    ml_token = settings.require_ml_token()  # như trên (3-Q21)\n",
     "    ml_token = settings.ml_service_token or __import__('pydantic').SecretStr('x')  # MUTATION\n",
     be("backend/tests/unit/test_app_env.py"), "test_worker_runtime_refuses_without_ml_token"),
    ("M15 timeout rerank 30 s (Q-3a-16)", "backend/app/ml/client.py",
     '"rerank": 10.0,', '"rerank": 30.0,',
     be("backend/tests/unit/test_ml_timeouts.py"), "test_worst_case_call_under_half_stale_turn[rerank]"),
    ("M13 422 vọng lại input", "ml_service/app/main.py",
     "    @app.exception_handler(RequestValidationError)\n", "    # MUTATION bỏ handler 422\n", ML,
     "test_logs_never_contain_text"),
]


REAL = ["uv", "run", "--group", "ml", "pytest", "ml_service/tests", "-o", "pythonpath=ml_service",
        "-m", "ml_real", "-q", "-p", "no:cacheprovider"]
REAL_EXPECT = {  # --real: cùng đột biến, test ml_real với model thật (cần make models)
    "M-3a-2 truncated luôn False": "test_a4_embed_truncated_over_512",
    "M-3a-3 đếm không token đặc biệt": "test_a3_count_includes_special_tokens",
    "M-3a-6 không cắt câu truy vấn": "test_a6_query_cut_passage_kept",
    "M9 không sigmoid": "test_a5_real_scores_sigmoid_once",
}
if "--only" in sys.argv:  # --only <tiền tố tên>: chỉ chạy các đột biến có tên bắt đầu bằng tiền tố đó
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS if m[0].startswith(prefix)]
if "--real" in sys.argv:
    MUTATIONS = [(n, f, o, w, REAL, REAL_EXPECT[n]) for n, f, o, w, _, _ in MUTATIONS if n in REAL_EXPECT]
    MUTATIONS.append((  # chỉ bắt được với model thật: sigmoid của thư viện + sigmoid của ta = hai lần
        "M14 sigmoid hai lần (bỏ activation identity)", "ml_service/app/loader.py",
        "        activation_fn=torch.nn.Identity(),  # lấy logit thô — sigmoid áp một lần ở rerank.py\n",
        "", REAL, "test_a5_real_scores_sigmoid_once"))


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    before = {m[1]: md5(REPO / m[1]) for m in MUTATIONS}
    bad = 0
    for name, rel, old, new, cmd, expect in MUTATIONS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if original.count(old) != 1:
            print(f"!! {name}: chuỗi gốc xuất hiện {original.count(old)} lần — bỏ qua")
            bad += 1
            continue
        if name == "M13 422 vọng lại input":  # bỏ cả hàm handler (decorator + 3 dòng thân)
            mutated = re.sub(r"    @app\.exception_handler\(RequestValidationError\)\n(    .*\n){3}",
                             new, original, count=1)
        else:
            mutated = original.replace(old, new)
        if mutated == original:
            print(f"!! {name}: đột biến không áp được")
            bad += 1
            continue
        try:
            path.write_text(mutated, encoding="utf-8")
            out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True,
                                 timeout=600, check=False)
        finally:
            path.write_text(original, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?)(?: - |$)", out.stdout, re.MULTILINE)))
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        hit = any(expect in f for f in failed)
        status = "ĐỎ đúng dự đoán" if hit else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        if not hit:
            bad += 1
        print(f"{name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
    after = {rel: md5(REPO / rel) for rel in before}
    assert after == before, "md5 khác sau khôi phục!"
    print("md5 sau khôi phục: khớp")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
