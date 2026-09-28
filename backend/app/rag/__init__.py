"""P3 — RAG: ingest (3b), truy hồi + ghép đoạn liền kề (3c). Xem docs/spec/build/01-kien-truc-project.md mục 3."""

from app.rag.ingest.pipeline import IngestDeps, IngestOptions, run_ingest
from app.rag.models import (
    EvidenceBlock,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSystemError,
)
from app.rag.query import build_query

__all__ = [
    "EvidenceBlock",
    "IngestDeps",
    "IngestOptions",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalSystemError",
    "build_query",
    "run_ingest",
]
