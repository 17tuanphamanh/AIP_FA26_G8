"""CLI ingest KB (thiết kế Phase 3 mục 5.8; PLAN-3b mục 7.2) — `make ingest` chạy trong container backend:

    python -m app.rag.ingest.cli [--kb-dir kb] [--dry-run] [--allow-unevaluated]

Điểm nối (composition root) riêng như `app.auth.mfa`: tự dựng `MlClient` → `MlTokenCounter` (LUÔN đếm token qua
ml-service — không có tuỳ chọn chọn bộ đếm khác, Q-3b-11), `QdrantIndex`, `KbRepo` (role app_rw), đồng hồ hệ thống.
Không in nội dung tài liệu ngoài ngữ cảnh lỗi (file, dòng, trường).
"""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import httpx
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.clock import SystemClock
from app.db.kb import KbRepo
from app.ml import MlClient
from app.rag.ingest.pipeline import STEP_NOTE, IngestDeps, IngestOptions, run_ingest
from app.rag.retriever import RagConfig
from app.rag.token_counter import MlTokenCounter
from app.rag.vector_store import QdrantIndex
from app.settings import Settings, get_policy

type DepsFactory = Callable[[Settings], AbstractAsyncContextManager[IngestDeps]]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.rag.ingest.cli", description="Nạp KB vào Qdrant (make ingest)")
    p.add_argument("--kb-dir", type=Path, default=Path("kb"), help="thư mục KB (mặc định: kb)")
    p.add_argument("--dry-run", action="store_true", help="chỉ kiểm + chia đoạn (bước 1–6), không ghi gì")
    p.add_argument("--allow-unevaluated", action="store_true",
                   help="cho nạp khi chưa có kb/eval/retrieval_set.yaml — chỉ APP_ENV dev/test")  # fmt: skip
    return p


@asynccontextmanager
async def _build_deps(settings: Settings) -> AsyncIterator[IngestDeps]:
    token = settings.require_ml_token()
    http = httpx.AsyncClient(base_url=settings.ml_service_url)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=60)
    engine = create_async_engine(settings.database_url, pool_size=2, hide_parameters=True)
    try:
        ml = MlClient(http, token.get_secret_value())
        yield IngestDeps(
            index=QdrantIndex(qdrant), ml=ml, counter=MlTokenCounter(ml), repo=KbRepo(engine), clock=SystemClock(),
            app_env=settings.app_env, retrieval_threshold=get_policy().constants.RETRIEVAL_THRESHOLD,
            keep_old=settings.rag_keep_old_collections, config_dir=settings.config_dir,
            rag=RagConfig.from_settings(settings),
        )  # fmt: skip
    finally:
        await http.aclose()
        await qdrant.close()
        await engine.dispose()


def _failed_step(e: BaseException) -> str:
    prefix = STEP_NOTE.format("")
    notes = [n for n in getattr(e, "__notes__", []) if n.startswith(prefix)]
    return notes[-1].removeprefix(prefix) if notes else "?"


def main(argv: Sequence[str] | None = None, *, deps_factory: DepsFactory | None = None) -> int:
    args = _parser().parse_args(argv)
    opts = IngestOptions(kb_dir=args.kb_dir, dry_run=args.dry_run, allow_unevaluated=args.allow_unevaluated)
    factory = deps_factory or _build_deps

    async def _go() -> int:
        async with factory(Settings()) as deps:
            return await run_ingest(opts, deps)

    try:
        return asyncio.run(_go())
    except Exception as e:  # noqa: BLE001 — không lường trước: in gọn, không traceback chứa nội dung tài liệu
        step = _failed_step(e)
        print(f"lỗi ở bước {step}: {type(e).__name__}: {e}", file=sys.stderr)
        if step.isdigit() and int(step) >= 12:  # alias đã đổi (Q-3b-12)
            print("alias đã đổi nhưng DB có thể chưa ghi — chạy lại `make ingest` để ghi bù (3-Q16)", file=sys.stderr)
            return 2
        return 1


if __name__ == "__main__":
    sys.exit(main())
