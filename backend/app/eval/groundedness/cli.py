"""CLI groundedness: `EVAL_MODE=true python -m app.eval.groundedness <lệnh>`.

- `judge --answers F --out DIR --llm-factory pkg.mod:fn`: chấm. `fn()` (không tham số) trả đối tượng `LlmPort` (gateway); đấu nối
  gateway thật ở mốc G (cần store không-DB cho gateway — chưa có trong `app/`). Mã thoát 3 nếu có ca lỗi.
- `score --run DIR`: tính lại `summary.json` từ `results.jsonl`.
- `sample --run DIR --answers F [--n 30] [--seed S] [--random]`: ghi `review_sample.jsonl` (mù), `review_key.jsonl`, `review_meta.json`.
  Mặc định phân tầng. `--answers` phải đúng file đã chấm (so sha256 với manifest).
- `agree --run DIR --labels F`: `agreement.json` từ `review_key.jsonl` + `review_sample.jsonl` đã điền; ghi thêm khối `human_agreement`
  (tỉ lệ khớp, κ, cờ `low_kappa` khi κ < 0,6) vào `summary.json`.
Lỗi đầu vào → thông điệp trên stderr, mã thoát 2.
"""

import argparse
import asyncio
import importlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.eval.groundedness import report, review
from app.eval.groundedness.judge import judge_all
from app.eval.groundedness.models import (
    dump_jsonl,
    load_answers,
    load_results,
    sha256_file,
)
from app.eval.groundedness.scoring import score
from app.eval.stats import SEED

EXIT_INPUT = 2
EXIT_JUDGE_ERRORS = 3


def _factory(spec: str) -> Any:
    module, _, name = spec.partition(":")
    if not module or not name:
        raise ValueError("--llm-factory phải có dạng pkg.mod:fn")
    return getattr(importlib.import_module(module), name)


def _default_run_id(sha: str, seed: int) -> str:
    return f"g11-{sha[:8]}-{seed}"


def cmd_judge(args: argparse.Namespace) -> int:
    rows = load_answers(args.answers)
    llm = _factory(args.llm_factory)()
    run = asyncio.run(judge_all(llm, rows))
    sha = sha256_file(args.answers)
    report.write_results(args.out, run.answers)
    report.clear_review(args.out)
    summary = score(run.answers, seed=args.seed)
    report.write_json(args.out / report.SUMMARY, summary)
    manifest = report.build_manifest(
        run_id=args.run_id or _default_run_id(sha, args.seed), answers_sha256=sha, n_rows=len(rows),
        metas=run.metas, seed=args.seed, commit=args.commit, now=datetime.now(UTC),
    )  # fmt: skip
    report.write_json(args.out / report.MANIFEST, manifest)
    print(json.dumps({k: summary[k] for k in ("n_judged", "n_errors", "supported_rate", "citation_precision")}))
    return EXIT_JUDGE_ERRORS if summary["n_errors"] else 0


def cmd_score(args: argparse.Namespace) -> int:
    answers = load_results(args.run / report.RESULTS)
    summary = score(answers, seed=args.seed)
    report.write_json(args.run / report.SUMMARY, summary)
    report.merge_agreement(args.run)
    print(json.dumps({k: summary[k] for k in ("n_judged", "n_errors", "supported_rate", "citation_precision")}))
    return EXIT_JUDGE_ERRORS if summary["n_errors"] else 0


def cmd_sample(args: argparse.Namespace) -> int:
    answers = load_results(args.run / report.RESULTS)
    manifest_path = args.run / report.MANIFEST
    if manifest_path.exists():
        recorded = json.loads(manifest_path.read_text(encoding="utf-8")).get("answers_sha256")
        if recorded != sha256_file(args.answers):
            raise ValueError("--answers khác file đã chấm (sha256 không khớp manifest.json)")
    rows = {r.scenario_id: r for r in load_answers(args.answers)}
    sample, meta = review.draw_sample(answers, n=args.n, seed=args.seed, stratify=not args.random)
    report.drop_agreement(args.run)
    dump_jsonl(args.run / report.REVIEW_SAMPLE, review.review_rows(sample, rows))
    dump_jsonl(args.run / report.REVIEW_KEY, review.key_rows(sample))
    report.write_json(args.run / report.REVIEW_META, meta)
    print(json.dumps({k: meta[k] for k in ("mode", "n_answers", "n_claims")}))
    return 0


def cmd_agree(args: argparse.Namespace) -> int:
    key = review.load_key(args.run / report.REVIEW_KEY)
    labels = review.load_labels(args.labels)
    result = review.agreement(key, labels, seed=args.seed)
    report.write_json(args.run / report.AGREEMENT, result)
    report.merge_agreement(args.run)
    print(json.dumps({k: result[k] for k in ("n_claims", "agreement", "kappa", "low_kappa")}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.eval.groundedness", description=__doc__.splitlines()[0] if __doc__ else "")
    sub = p.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--answers", type=Path, required=True)
    j.add_argument("--out", type=Path, required=True)
    j.add_argument("--llm-factory", required=True)
    j.add_argument("--run-id")
    j.add_argument("--commit")
    j.add_argument("--seed", type=int, default=SEED)
    j.set_defaults(func=cmd_judge)
    s = sub.add_parser("score")
    s.add_argument("--run", type=Path, required=True)
    s.add_argument("--seed", type=int, default=SEED)
    s.set_defaults(func=cmd_score)
    m = sub.add_parser("sample")
    m.add_argument("--run", type=Path, required=True)
    m.add_argument("--answers", type=Path, required=True)
    m.add_argument("--n", type=int, default=review.SAMPLE_N)
    m.add_argument("--seed", type=int, default=SEED)
    m.add_argument("--random", action="store_true", help="rút ngẫu nhiên thuần (mặc định: phân tầng)")
    m.set_defaults(func=cmd_sample)
    a = sub.add_parser("agree")
    a.add_argument("--run", type=Path, required=True)
    a.add_argument("--labels", type=Path, required=True)
    a.add_argument("--seed", type=int, default=SEED)
    a.set_defaults(func=cmd_agree)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, OSError) as e:
        print(f"lỗi: {e}", file=sys.stderr)
        return EXIT_INPUT
