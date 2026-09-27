"""P3 — RAG: ingest (3b), truy hồi + ghép đoạn liền kề (3c). Xem docs/spec/build/01-kien-truc-project.md mục 3."""

from app.rag.ingest.pipeline import IngestDeps, IngestOptions, run_ingest

__all__ = ["IngestDeps", "IngestOptions", "run_ingest"]
