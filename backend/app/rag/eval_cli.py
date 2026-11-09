"""CLI đo chất lượng truy hồi trên bản KB ĐANG CHẠY (thiết kế Phase 3 mục 6, Q-3c-15) — `make eval-rag`:

    python -m app.rag.eval_cli [--kb-dir kb] [--sweep] [--csv]

Không sửa gì (chỉ đọc Qdrant qua alias `kb_current` hiện tại — không ingest lại). Mặc định in Recall@5/FG/MRR ở
đúng `RETRIEVAL_THRESHOLD` đang cấu hình (giống cổng kiểm ingest bước 10, dùng `RetrieveGateAdapter`). R1: kèm P@1 và Recall@5 ở
ngưỡng (đúng tài liệu trong top-5 VÀ top_score ≥ ngưỡng) và một dòng "Không lọc intent" (mỗi câu thêm một `search_once(use_intent=False)`);
`recall_at5` giữ nghĩa cũ, cổng ingest không đọc chỉ số mới. `--sweep`
in thêm bảng 13 ngưỡng (`gate.sweep`, Q-3c-15) — CHỈ để quan sát độ nhạy, KHÔNG dùng để chọn ngưỡng thật (D-22:
chọn ngưỡng làm trên model thật, có kiểm định, ở mốc riêng). `--csv` in bảng sweep dạng CSV ra stdout thay bảng
người đọc (người chuyển hướng `> eval/reports/…`), không vẽ hình.

Điểm nối (composition root) riêng, như `rag/ingest/cli.py`.
"""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from qdrant_client import AsyncQdrantClient

from app.core.clock import SystemClock
from app.ml import MlClient
from app.rag.bm25 import load_lexicon
from app.rag.ingest.config import ALIAS
from app.rag.ingest.gate import (
    GateMetrics,
    RetrieveGateAdapter,
    SweepPoint,
    evaluate,
    evaluate_without_intent,
    gate_ctx,
    gate_intent,
    load_retrieval_set,
    sweep,
)
from app.rag.ingest.kbversion import pipeline_sha
from app.rag.models import IngestMlError, RetrievalQuery, RetrievalSystemError
from app.rag.retriever import RagConfig, Retriever
from app.rag.vector_store import QdrantIndex, VectorIndex
from app.settings import Settings, get_policy


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.rag.eval_cli",
                                description="Đo Recall@5/FG/MRR của bản KB đang chạy (alias kb_current)")  # fmt: skip
    p.add_argument("--kb-dir", type=Path, default=Path("kb"), help="thư mục KB có eval/retrieval_set.yaml")
    p.add_argument("--sweep", action="store_true", help="in thêm bảng 13 ngưỡng 0,30–0,90 (Q-3c-15) — không "
                                                         "dùng để chọn ngưỡng thật")  # fmt: skip
    p.add_argument("--csv", action="store_true", help="in bảng sweep dạng CSV (chỉ có nghĩa cùng --sweep)")
    return p


@dataclass
class EvalDeps:
    retriever: Retriever
    index: VectorIndex
    threshold: float  # get_policy().constants.RETRIEVAL_THRESHOLD — một nguồn, đọc ở composition root


@asynccontextmanager
async def _build_deps(settings: Settings) -> AsyncIterator[EvalDeps]:
    token = settings.require_ml_token()
    http = httpx.AsyncClient(base_url=settings.ml_service_url)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=int(settings.rag_qdrant_timeout_s),
                               check_compatibility=False)  # fmt: skip
    async with AsyncExitStack() as stack:
        stack.push_async_callback(http.aclose)
        stack.push_async_callback(qdrant.close)
        ml = MlClient(http, token.get_secret_value())
        index = QdrantIndex(qdrant)
        threshold = get_policy().constants.RETRIEVAL_THRESHOLD
        retriever = Retriever(
            index, ml, RagConfig.from_settings(settings), threshold=threshold,
            pipeline_sha=pipeline_sha(settings.config_dir), lexicon=load_lexicon(settings.config_dir),
            clock=SystemClock(),
        )  # fmt: skip
        yield EvalDeps(retriever=retriever, index=index, threshold=threshold)


def _print_current(threshold: float, m: GateMetrics) -> None:
    print(
        f"Recall@5 {m.recall_at5:.3f}  trả lời bừa {m.false_grounding_rate:.3f}  MRR {m.mrr:.3f}  "
        f"(câu có đáp án={m.positives}, câu âm tính={m.negatives}, ngưỡng={threshold:.2f})"
    )
    # R1: chỉ số MỚI, dòng riêng — dòng trên giữ nguyên chữ. Recall@5 ở ngưỡng = đúng tài liệu trong top-5 VÀ top_score ≥ ngưỡng.
    print(f"  P@1 {m.p_at_1:.3f}  Recall@5 ở ngưỡng {m.recall_at_threshold:.3f}")


def _print_without_intent(m: GateMetrics) -> None:
    """R1 — lượt chạy không lọc intent (`search_once(use_intent=False)`), cùng bộ chỉ số, cùng ngưỡng."""
    print(
        f"Không lọc intent: Recall@5 {m.recall_at5:.3f}  trả lời bừa {m.false_grounding_rate:.3f}  MRR {m.mrr:.3f}  "
        f"P@1 {m.p_at_1:.3f}  Recall@5 ở ngưỡng {m.recall_at_threshold:.3f}"
    )


async def _run(deps: EvalDeps, kb_dir: Path, *, do_sweep: bool, csv: bool) -> int:
    rs, issues = load_retrieval_set(kb_dir)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    if rs is None:
        print(f"không có {kb_dir / 'eval' / 'retrieval_set.yaml'}", file=sys.stderr)
        return 1
    coll = await deps.index.alias_target(ALIAS)
    if coll is None:
        print(f"alias {ALIAS} chưa trỏ collection nào — chạy `make ingest` trước", file=sys.stderr)
        return 1
    adapter = RetrieveGateAdapter(deps.retriever)
    m = await evaluate(rs, adapter, coll, deps.threshold)
    print(f"collection={coll}")
    _print_current(deps.threshold, m)
    _print_without_intent(await evaluate_without_intent(rs, deps.retriever, coll, deps.threshold))
    if not do_sweep:
        return 0
    pairs: dict[str, tuple[tuple[list[str], float], tuple[list[str], float]]] = {}
    for item in rs.items:
        q = RetrievalQuery(text=item.query, intent=gate_intent(item.intent))
        ctx = gate_ctx(item.role)
        first_chunks, first_score = await deps.retriever.search_once(q, ctx, collection=coll, use_intent=True)
        alt_chunks, alt_score = await deps.retriever.search_once(q, ctx, collection=coll, use_intent=False)
        pairs[item.id] = (
            ([c.doc_id for c in first_chunks], first_score),
            ([c.doc_id for c in alt_chunks], alt_score),
        )
    _print_sweep(sweep(rs, pairs), csv=csv)
    return 0


def _print_sweep(points: Sequence[SweepPoint], *, csv: bool) -> None:
    if csv:
        print("threshold,recall_at5,false_grounding_rate,mrr,positives,negatives,p_at_1,recall_at_threshold")
        for p in points:
            m = p.metrics
            print(f"{p.threshold},{m.recall_at5},{m.false_grounding_rate},{m.mrr},{m.positives},{m.negatives},"
                  f"{m.p_at_1},{m.recall_at_threshold}")  # fmt: skip
        return
    print(f"\n{'T':>5} {'Recall@5':>9} {'trả lời bừa':>12} {'MRR':>6} {'P@1':>6} {'R@5 ở T':>8}")
    for p in points:
        m = p.metrics
        print(f"{p.threshold:>5.2f} {m.recall_at5:>9.3f} {m.false_grounding_rate:>12.3f} {m.mrr:>6.3f} "
              f"{m.p_at_1:>6.3f} {m.recall_at_threshold:>8.3f}")  # fmt: skip
    print("(bảng sweep chỉ để quan sát — KHÔNG dùng để chọn RETRIEVAL_THRESHOLD, D-22)")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings()

    async def _go() -> int:
        async with _build_deps(settings) as deps:
            return await _run(deps, args.kb_dir, do_sweep=args.sweep, csv=args.csv)

    try:
        return asyncio.run(_go())
    except (IngestMlError, RetrievalSystemError) as e:
        print(f"lỗi khi đánh giá: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
