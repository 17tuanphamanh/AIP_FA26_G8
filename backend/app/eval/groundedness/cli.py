"""CLI groundedness: `EVAL_MODE=true python -m app.eval.groundedness <lệnh>`.

- `collect (--questions F | --from-run RUN --scenarios DIR | --from-probe KETQUA.json --families F) --out DIR [--since T --until T]`:
  dựng `answers.jsonl` + `collect_report.json` từ DB (chỉ đọc; xem `collect.py`). Mã thoát 3 nếu có ca bị bỏ vì lỗi hệ thống.
- `probe-input --retrieval-set kb/eval/retrieval_set.yaml --out DIR`: `probe.jsonl` (cho `make probe`) + `families.jsonl` [Đề xuất 22/10].
- `judge --answers F --out DIR --llm-factory pkg.mod:fn [--max-usd X]`: chấm. `fn(run_id[, max_usd=…])` trả `LlmPort` hoặc async context
  manager của nó — gateway thật: `app.eval.llm_factory:eval_gateway`. Mã thoát 3 nếu có ca lỗi.
- `score --run DIR`: tính lại `summary.json` từ `results.jsonl`.
- `sample --run DIR --answers F [--n 30] [--seed S] [--random]`: ghi `review_sample.jsonl` (mù), `review_key.jsonl`, `review_meta.json`.
  Mặc định phân tầng. `--answers` phải đúng file đã chấm (so sha256 với manifest).
- `agree --run DIR --labels F`: `agreement.json` từ `review_key.jsonl` + `review_sample.jsonl` đã điền; ghi thêm khối `human_agreement`
  (tỉ lệ khớp, κ, cờ `low_kappa` khi κ < 0,6) vào `summary.json`.
Lỗi đầu vào → thông điệp trên stderr, mã thoát 2.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.eval.dbread import open_reader
from app.eval.groundedness import collect as collecting
from app.eval.groundedness import probe_input, report, review
from app.eval.groundedness.judge import JudgeRun, judge_all
from app.eval.groundedness.models import (
    dump_jsonl,
    load_answers,
    load_results,
    sha256_file,
)
from app.eval.groundedness.scoring import score
from app.eval.llm_factory import open_port
from app.eval.stats import SEED

EXIT_INPUT = 2
EXIT_JUDGE_ERRORS = 3


def _default_run_id(sha: str, seed: int) -> str:
    return f"g11-{sha[:8]}-{seed}"


async def _judge(args: argparse.Namespace, rows: list, run_id: str) -> JudgeRun:  # type: ignore[type-arg]
    async with open_port(args.llm_factory, run_id, max_usd=args.max_usd) as llm:
        return await judge_all(llm, rows)


def cmd_judge(args: argparse.Namespace) -> int:
    rows = load_answers(args.answers)
    sha = sha256_file(args.answers)
    run_id = args.run_id or _default_run_id(sha, args.seed)
    run = asyncio.run(_judge(args, rows, run_id))
    report.write_results(args.out, run.answers)
    report.clear_review(args.out)
    summary = score(run.answers, seed=args.seed)
    report.write_json(args.out / report.SUMMARY, summary)
    manifest = report.build_manifest(
        run_id=run_id, answers_sha256=sha, n_rows=len(rows), metas=run.metas, seed=args.seed, commit=args.commit,
        now=datetime.now(UTC),
    )  # fmt: skip
    report.write_json(args.out / report.MANIFEST, manifest)
    print(json.dumps({k: summary[k] for k in ("n_judged", "n_errors", "supported_rate", "citation_precision")}))
    return EXIT_JUDGE_ERRORS if summary["n_errors"] else 0


def _when(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name}: không đọc được thời điểm ISO 8601") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{name}: phải có múi giờ")
    return parsed


async def _collect(args: argparse.Namespace) -> tuple[list[dict], dict]:  # type: ignore[type-arg]
    sources = [args.questions, args.from_run, args.from_probe]
    if sum(s is not None for s in sources) != 1:
        raise ValueError("chọn đúng MỘT trong --questions, --from-run, --from-probe")
    extra: dict[str, int] = {}
    if args.questions is not None:
        questions = collecting.load_questions(args.questions)
    elif args.from_run is not None:
        if args.scenarios is None:
            raise ValueError("--from-run cần --scenarios")
        questions, extra = collecting.questions_from_run(args.from_run, args.scenarios)
    else:
        if args.families is None:
            raise ValueError("--from-probe cần --families")
        questions, extra = collecting.questions_from_probe(args.from_probe, args.families)
    since, until = _when(args.since, "--since"), _when(args.until, "--until")
    async with open_reader() as reader:
        rows, rep = await collecting.collect(reader, questions, since=since, until=until)
    rep["skipped_before_db"] = extra
    return rows, rep


def cmd_collect(args: argparse.Namespace) -> int:
    rows, rep = asyncio.run(_collect(args))
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "answers.jsonl").open("x", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    report.write_json(args.out / "collect_report.json", rep)
    print(json.dumps({k: rep[k] for k in ("n_questions", "n_collected", "n_families", "n_cannot_answer", "skipped")}))
    return EXIT_JUDGE_ERRORS if collecting.has_system_skips(rep) else 0


def cmd_probe_input(args: argparse.Namespace) -> int:
    probe, families, rep = probe_input.build_probe_input(args.retrieval_set)
    probe_input.write_probe_input(args.out, probe, families)
    print(json.dumps(rep))
    return 0


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
    j.add_argument("--max-usd", type=float, default=None, help="trần chi riêng cho lượt này (cộng vào tổng chi lúc bắt đầu)")
    j.add_argument("--run-id")
    j.add_argument("--commit")
    j.add_argument("--seed", type=int, default=SEED)
    j.set_defaults(func=cmd_judge)
    c = sub.add_parser("collect")
    c.add_argument("--questions", type=Path)
    c.add_argument("--from-run", type=Path)
    c.add_argument("--scenarios", type=Path)
    c.add_argument("--from-probe", type=Path)
    c.add_argument("--families", type=Path)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--since")
    c.add_argument("--until")
    c.set_defaults(func=cmd_collect)
    pi = sub.add_parser("probe-input")
    pi.add_argument("--retrieval-set", type=Path, required=True)
    pi.add_argument("--out", type=Path, required=True)
    pi.set_defaults(func=cmd_probe_input)
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
    except SQLAlchemyError as e:  # chỉ tên lớp lỗi: thông điệp có thể chứa DSN
        print(f"lỗi DB: {type(e).__name__}", file=sys.stderr)
        return EXIT_INPUT
