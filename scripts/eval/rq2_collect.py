"""RQ2 (Phase 11) — thu thập p của 3 cách trên các lá đi lớp LLM của lượt S1, ghi `results/rq2/<run_id>/` (xem backend/app/eval/rq2/README.md).

  EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/rq2_collect.py \\
      --s1-predictions <thư mục lượt S1>/predictions.jsonl --label D1 [--include-c] [--max-usd 2] [--only-b] [--allow-audit-pb]

- Dừng (mã 2) nếu `EVAL_MODE` ≠ true, `APP_ENV` (Settings) ngoài dev/test, `LLM_CACHE_MODE` ≠ eval, hoặc (khi gọi (a)/(c))
  `LLM_BACKEND` ≠ real.
- DB: chỉ đọc, qua `docker compose exec postgres psql` (`app.eval.stack.Shell`, transaction READ ONLY; `COMPOSE` đổi lệnh compose).
- (a) qua gateway (`LLMClient` + `FileLlmStore` trong thư mục run, cache eval); (c) đường httpx riêng (`--include-c`). Trần chi của run:
  `--max-usd` (mặc định 2) — KHÔNG cộng SUM(llm_calls) của PG.
- stdout chỉ có số đếm. Không in khoá, base_url, id lá, nội dung prompt.
"""

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
ENVS = ("dev", "test")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, capture_output=True,
                                    text=True, check=True).stdout.strip())  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return sha, dirty


def guard() -> str | None:
    """Lý do dừng, hoặc None. Chạy TRƯỚC mọi import `app.eval` (import đó tự chặn khi thiếu EVAL_MODE)."""
    if os.environ.get("EVAL_MODE", "").strip().lower() != "true":
        return "EVAL_MODE phải là true"
    from app.settings import Settings

    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValueError:  # Settings từ chối EVAL_MODE ngoài dev/test/staging — không in giá trị
        return "APP_ENV phải là dev hoặc test (Settings từ chối cấu hình)"
    if settings.app_env not in ENVS:
        return "APP_ENV phải là dev hoặc test"
    if settings.llm_cache_mode != "eval":
        return "LLM_CACHE_MODE phải là eval"
    return None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rq2_collect.py", description="RQ2 — thu thập p (a)(b)(c) trên lá đi lớp LLM của S1")
    p.add_argument("--s1-predictions", type=Path, required=True, help="predictions.jsonl của lượt S1 (hybrid)")
    p.add_argument("--label", required=True, help="tên tập (vd main, D1, D2) — mỗi tập một run riêng, không gộp số")
    p.add_argument("--folds", type=Path, default=REPO / "eval" / "folds.csv")
    p.add_argument("--out", type=Path, default=REPO / "results" / "rq2")
    p.add_argument("--include-c", action="store_true", help="chạy (c) xác suất token (kiểm khả thi ở lá đầu tiên)")
    p.add_argument("--max-usd", type=float, default=2.0, help="trần chi của run rq2 (a + c), USD")
    p.add_argument("--only-b", action="store_true", help="chỉ đọc (b) từ DB, không gọi LLM")
    p.add_argument("--allow-audit-pb", action="store_true", help="thiếu phiếu trong llm_cache → p_b = raw_prob điểm log 4")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reason = guard()
    if reason is not None:
        print(f"DỪNG: {reason}", file=sys.stderr)
        return 2
    if args.only_b and args.include_c:
        print("DỪNG: --only-b không đi với --include-c", file=sys.stderr)
        return 2
    if not args.max_usd > 0:
        print("DỪNG: --max-usd phải > 0", file=sys.stderr)
        return 2
    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    from app.core.clock import SystemClock
    from app.eval.predictions import load_predictions
    from app.eval.rq2.collect import CRun, Deps, c_summary, collect, leaves, load_folds
    from app.eval.rq2.filestore import (
        SPEND_NOTE,
        FileLlmStore,
        SpendLedger,
        write_atomic,
    )
    from app.eval.rq2.logprob import TEMPERATURE as C_TEMPERATURE
    from app.eval.rq2.logprob import (
        TOP_LOGPROBS,
        HttpxTransport,
        LogprobClient,
        RequestCfg,
    )
    from app.eval.rq2.self_report import TEMPERATURE as A_TEMPERATURE
    from app.eval.rq2.source import B14_INPUT_METHOD, ESTIMATE_PROMPT, VOTE_PROMPT
    from app.eval.stack import Shell
    from app.llm.client import LLMClient
    from app.llm.config import load_llm_config, resolve
    from app.llm.providers.base import ProviderRequest
    from app.llm.providers.openai_compat import OpenAICompatProvider
    from app.llm.registry import load_prompts
    from app.llm.schemas import RiskVoteOut
    from app.risk.estimator import VOTE_TEMPERATURE, K
    from app.settings import Settings
    from pydantic import SecretStr

    settings = Settings()  # type: ignore[call-arg]
    records = load_predictions(args.s1_predictions)
    items = leaves(records, load_folds(args.folds))
    registry = load_prompts(settings.config_dir / "prompts")
    vote, estimate = registry.get(VOTE_PROMPT), registry.get(ESTIMATE_PROMPT)
    cfg = load_llm_config(settings.config_dir / "llm.yaml")
    strong = cfg.roles["strong"]
    commit, dirty = _commit()
    s1_run_id = records[0].run_id if records else None
    ident = {"label": args.label, "s1_run_id": s1_run_id, "s1_predictions_sha256": _sha256(args.s1_predictions), "commit": commit,
             "include_c": args.include_c, "only_b": args.only_b, "prompts": [estimate.sha256, vote.sha256]}  # fmt: skip
    run_id = hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:12]
    run_dir = args.out / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = SpendLedger(run_dir / "spend.jsonl")
    shell = Shell(shlex.split(os.environ.get("COMPOSE", "docker compose")))
    deps = Deps(sql=shell.sql, vote_prompt=vote, budget_in=strong.budget_in, model_version=strong.model_version,
                allow_audit=args.allow_audit_pb)  # fmt: skip
    store: FileLlmStore | None = None
    closers: list[Any] = []
    if not args.only_b:
        if settings.require_llm_backend() != "real":
            print("DỪNG: LLM_BACKEND phải là real để gọi (a)/(c) — hoặc dùng --only-b", file=sys.stderr)
            return 2
        runtime = resolve(cfg, settings, "real")
        runtime = replace(runtime, spend=runtime.spend.model_copy(update={"cap_usd": args.max_usd}))
        target = runtime.chains["strong"][0]
        pcfg = cfg.providers[target.provider]
        key = getattr(settings, pcfg.api_key_setting)
        base_url = getattr(settings, pcfg.base_url_setting)
        assert isinstance(key, SecretStr) and isinstance(base_url, str)  # resolve() đã từ chối nếu thiếu
        provider = OpenAICompatProvider(target.provider, base_url=base_url, api_key=key, json_mode=pcfg.json_mode,
                                        extra_body=pcfg.extra_body)  # fmt: skip
        closers.append(provider)
        store = FileLlmStore(run_dir, ledger)
        deps.llm = LLMClient(runtime=runtime, registry=registry, providers={target.provider: provider}, store=store,
                             clock=SystemClock(), eval_mode=True, cache_mode="eval")  # fmt: skip
        deps.model = target.model
        if args.include_c:
            assert target.price is not None  # resolve() đã từ chối model thiếu giá
            schema = RiskVoteOut.model_json_schema()
            fmt: dict[str, Any] = ({"type": "json_object"} if pcfg.json_mode == "json_object" else
                                   {"type": "json_schema", "json_schema": {"name": "RiskVoteOut", "schema": schema, "strict": False}})  # fmt: skip

            def wire(msgs: list[dict[str, str]]) -> list[dict[str, str]]:
                req = ProviderRequest(prompt_id=VOTE_PROMPT, model=target.model, messages=msgs, json_schema=schema,
                                      schema_name="RiskVoteOut", max_tokens=strong.max_tokens, temperature=C_TEMPERATURE,
                                      timeout_s=strong.timeout_s, attempt=0, variables={}, trace=None)  # fmt: skip
                return provider._messages(req)  # đúng phép biến đổi messages gateway gửi ở S1

            transport = HttpxTransport(base_url, key, timeout_s=strong.timeout_s)
            closers.append(transport)
            client = LogprobClient(transport, run_dir / "cache_c", ledger, target.price, args.max_usd)
            deps.c = CRun(client, RequestCfg(target.model, strong.max_tokens, fmt, pcfg.extra_body), wire)
    try:
        rows = await collect(deps, items)
    finally:
        for c in closers:
            await c.aclose()
    calls_a = store.calls() if store is not None else []
    models = sorted(deps.s1_models)
    manifest = {
        "rq2_run_id": run_id, **ident, "commit_dirty": dirty, "s1_predictions": args.s1_predictions.name,
        "folds_csv_sha256": _sha256(args.folds), "n_leaves": len(items),
        "model": models[0] if len(models) == 1 else None, "s1_models": dict(deps.s1_models),
        "configured_model": deps.model, "model_setting": strong.model_setting.upper(),
        "temperature": {"a": A_TEMPERATURE, "b": VOTE_TEMPERATURE, "c": C_TEMPERATURE}, "k_votes": K, "top_logprobs_c": TOP_LOGPROBS,
        "prompts": {p.id: {"version": p.version, "sha256": p.sha256} for p in (estimate, vote)},
        "b14_input_method": B14_INPUT_METHOD, "p_b_source": "llm_cache (mode eval) — đối chiếu raw_prob điểm log 4",
        "llm_cache_mode": "eval", "c": c_summary(deps.c),
        "a": {"network_calls": sum(1 for r in calls_a if not r["cache_hit"] and r["error"] is None),
              "cache_hits": sum(1 for r in calls_a if r["cache_hit"]), "errors": sum(1 for r in calls_a if r["error"])},
        "spend": {"total_usd": ledger.total(), "max_usd": args.max_usd, "note": SPEND_NOTE},
        "counts": dict(deps.counts),
    }  # fmt: skip
    write_atomic(run_dir / "collected.jsonl", "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    write_atomic(run_dir / "manifest_collect.json", json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
    n = len(rows)
    print(f"leaves={n} p_a={sum(r['p_a'] is not None for r in rows)} p_b={sum(r['p_b'] is not None for r in rows)} "
          f"p_c={sum(r.get('p_c') is not None for r in rows)} c_status={manifest['c']['status']}")  # fmt: skip
    print(f"a_network_calls={manifest['a']['network_calls']} c_network_calls={manifest['c'].get('network_calls', 0)} "
          f"spend_usd={ledger.total():.4f}")  # fmt: skip
    print(f"run_id={run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
