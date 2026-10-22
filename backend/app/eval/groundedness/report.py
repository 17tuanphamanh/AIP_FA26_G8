"""Ghi kết quả một lượt chạy groundedness vào một thư mục (mặc định `eval/reports/<run_id>/groundedness/`).

- `results.jsonl`: một dòng/ca (ý lồng bên trong) — nguồn duy nhất cho `score`, `sample`, `agree`.
- `errors.jsonl`: các ca `status="error"` (đã nằm trong results; tách ra để thấy ngay).
- `summary.json`: chỉ số + khoảng tin cậy — KHÔNG có giờ/đường dẫn → chạy lại cùng đầu vào + cùng phản hồi LLM ra file giống hệt.
- `manifest.json`: run_id, sha256 đầu vào, prompt (id, version, sha256), model chấm, seed, số lời gọi/token/chi phí, giờ tạo. P8 5.1:
  không có manifest thì không đưa số vào báo cáo.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from app.eval.groundedness.judge import PROMPT_ID, ROLE
from app.eval.groundedness.models import JudgedAnswer, dump_jsonl
from app.eval.stats import BOOTSTRAP_N, LEVEL, SEED
from app.llm.ports import LLMMeta

RESULTS = "results.jsonl"
ERRORS = "errors.jsonl"
SUMMARY = "summary.json"
MANIFEST = "manifest.json"
REVIEW_SAMPLE = "review_sample.jsonl"
REVIEW_KEY = "review_key.jsonl"
REVIEW_META = "review_meta.json"
AGREEMENT = "agreement.json"


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


AGREEMENT_KEYS = ("n_claims", "n_answers", "agreement", "kappa", "kappa_threshold", "low_kappa")


def merge_agreement(run: Path) -> None:
    """Nếu có cả `summary.json` và `agreement.json`: ghi khối `human_agreement` (tỉ lệ khớp + κ + cờ `low_kappa`) vào summary, để
    con số groundedness luôn đi cùng độ tin cậy của người chấm (P8 v1.5 6.3.1)."""
    summary_path, agreement_path = run / SUMMARY, run / AGREEMENT
    if not (summary_path.exists() and agreement_path.exists()):
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    agreement = json.loads(agreement_path.read_text(encoding="utf-8"))
    summary["human_agreement"] = {k: agreement[k] for k in AGREEMENT_KEYS}
    write_json(summary_path, summary)


def drop_agreement(run: Path) -> None:
    """Mẫu mới → `agreement.json` cũ và khối `human_agreement` trong summary không còn khớp: bỏ cả hai."""
    (run / AGREEMENT).unlink(missing_ok=True)
    summary_path = run / SUMMARY
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.pop("human_agreement", None) is not None:
            write_json(summary_path, summary)


def clear_review(out: Path) -> None:
    """Chấm lại vào thư mục cũ → bỏ mẫu soát/đồng thuận của lần trước (không còn khớp với `results.jsonl`)."""
    for name in (REVIEW_SAMPLE, REVIEW_KEY, REVIEW_META, AGREEMENT):
        (out / name).unlink(missing_ok=True)


def write_results(out: Path, answers: Sequence[JudgedAnswer]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    dump_jsonl(out / RESULTS, list(answers))
    dump_jsonl(out / ERRORS, [a for a in answers if a.status == "error"])


def build_manifest(
    *, run_id: str, answers_sha256: str, n_rows: int, metas: Sequence[LLMMeta], seed: int = SEED,
    commit: str | None = None, now: datetime,
) -> dict[str, Any]:
    return {
        "kind": "groundedness", "run_id": run_id, "answers_sha256": answers_sha256, "n_rows": n_rows,
        "prompt": {"id": PROMPT_ID, "role": ROLE, "versions": sorted({m.prompt_version for m in metas}),
                   "sha256": sorted({m.prompt_hash for m in metas})},
        "judge": {"providers": sorted({m.provider for m in metas}), "models": sorted({m.model for m in metas}),
                  "model_versions": sorted({m.model_version for m in metas if m.model_version})},
        "llm_calls": {"n": len(metas), "cache_hits": sum(m.cache_hit for m in metas),
                      "tokens_in": sum(m.tokens_in for m in metas), "tokens_out": sum(m.tokens_out for m in metas),
                      "cost_usd": sum(m.cost_usd for m in metas)},
        "stats": {"seed": seed, "bootstrap_n": BOOTSTRAP_N, "level": LEVEL},
        "commit": commit,
        "generated_at": now.isoformat(),
        "limitations": [
            "tách ý bằng code (câu ghép là một ý; ý xã giao bị chấm như ý thường)",
            "người chấm cùng model với người viết (cấu hình A) — mẫu người soát là phép kiểm",
            "chỉ chấm trên đoạn đã dẫn", "cách đo là [Đề xuất 22/10]; yêu cầu đo là [Chốt 17.4]",
        ],
    }
