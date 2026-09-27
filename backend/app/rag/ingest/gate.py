"""Cổng kiểm của ingest, bước 10 (thiết kế Phase 3 mục 5.8, 3-Q15; PLAN-3b mục 7.1; Q-3b-4).

Bộ kiểm tra `<kb_dir>/eval/retrieval_set.yaml` → Recall@5, tỉ lệ trả lời bừa (FG), MRR@5. Quyết định:
  (a) không có bộ: `--allow-unevaluated` (env đã qua bước 0) → đạt, `unevaluated`, số đo NULL; không cờ → KHÔNG đạt.
  (b) có bộ, chưa có alias: đạt ⇔ Recall ≥ 0,80 và FG ≤ 0,05.
  (c) có bộ, có alias: đánh giá LẠI bản cũ bằng cùng bộ, cùng retriever; đạt ⇔ Recall không tụt quá 0,05 và FG không
      tăng quá 0,05.

GIỚI HẠN ĐÃ BIẾT (3b): `DenseOnlyRetriever` chỉ có dense cosine — chưa BM25, rerank, lọc intent. Cosine khác thang
điểm rerank mà `RETRIEVAL_THRESHOLD` dành cho → với model thật, FG ở 3b vô nghĩa và `make ingest` có thể đỏ cổng; 3c
thay bằng adapter quanh `retrieve()`.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from qdrant_client.models import Filter

from app.db.models import KB_REQUEST_TYPES
from app.domain.context import Role
from app.ml.ports import MlPort
from app.rag.filters import base_filter
from app.rag.ingest.config import (
    DENSE_DIM,
    GATE_EPS,
    GATE_MAX_DELTA,
    GATE_MAX_FALSE_GROUNDING,
    GATE_MIN_RECALL,
    GATE_PREFETCH,
    GATE_TOP_DOCS,
)
from app.rag.models import IngestIssue, IngestMlError
from app.rag.vector_store import VectorIndex

RETRIEVAL_SET = Path("eval") / "retrieval_set.yaml"


class EvalItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    intent: str  # 3b không dùng
    role: Role
    expected_doc_ids: list[str]
    near_topic: bool | None = None
    note: str | None = None


class RetrievalSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    kb_scope: list[str]
    items: list[EvalItem]

    @field_validator("kb_scope")
    @classmethod
    def _scope(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in KB_REQUEST_TYPES]
        if bad:
            raise ValueError(f"kb_scope có request_type lạ {bad}")
        return v

    @model_validator(mode="after")
    def _items(self) -> "RetrievalSet":
        ids = [i.id for i in self.items]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"id trùng: {', '.join(dup)}")
        if not any(i.expected_doc_ids for i in self.items):
            raise ValueError("phải có ít nhất một câu có đáp án (expected_doc_ids không rỗng)")
        if all(i.expected_doc_ids for i in self.items):
            raise ValueError("phải có ít nhất một câu âm tính (expected_doc_ids: [])")
        return self


def load_retrieval_set(kb_dir: Path) -> tuple[RetrievalSet | None, list[IngestIssue]]:
    """(None, []) khi không có file — nhánh (a). File sai → lỗi, pipeline thoát 1."""
    path = kb_dir / RETRIEVAL_SET
    rel = f"{kb_dir.name}/{RETRIEVAL_SET.as_posix()}"
    if not path.is_file():
        return None, []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return RetrievalSet.model_validate(raw), []
    except yaml.YAMLError as e:
        return None, [IngestIssue(rel, None, f"YAML sai: {e}")]
    except ValidationError as e:
        return None, [
            IngestIssue(rel, None, err["msg"], ".".join(str(p) for p in err["loc"]) or None) for err in e.errors()
        ]


# ---- Truy hồi dense-only -----------------------------------------------------------------------


class Retriever(Protocol):
    async def top_docs(self, query: str, role: str, *, collection: str) -> tuple[list[str], float]:
        """(≤ 5 doc_id theo hạng, điểm của hit đầu); không có hit → ([], 0.0)."""
        ...


class DenseOnlyRetriever:
    """3b — CHƯA có BM25, rerank, lọc intent (3c thay bằng adapter quanh `retrieve()`)."""

    def __init__(self, index: VectorIndex, ml: MlPort) -> None:
        self._index = index
        self._ml = ml

    async def top_docs(self, query: str, role: str, *, collection: str) -> tuple[list[str], float]:
        result = await self._ml.embed([query])  # nhóm 1 (Q-3b-1)
        if result.error is not None or result.data is None:
            raise IngestMlError(f"ml-service /embed lỗi khi đánh giá: {result.error} sau {result.attempts} lần")
        if len(result.data.vectors) != 1 or result.data.dim != DENSE_DIM:
            raise IngestMlError(f"ml-service /embed trả {len(result.data.vectors)} vector, dim {result.data.dim}")
        hits = await self._index.query_dense(
            collection, result.data.vectors[0], Filter(must=list(base_filter(role))), GATE_PREFETCH
        )
        docs: list[str] = []
        for hit in hits:
            doc_id = str((hit.payload or {}).get("doc_id"))
            if doc_id not in docs:
                docs.append(doc_id)
        return docs[:GATE_TOP_DOCS], (float(hits[0].score) if hits else 0.0)


# ---- Chỉ số, quyết định ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateMetrics:
    recall_at5: float
    false_grounding_rate: float
    mrr: float
    positives: int
    negatives: int


def metrics(results: list[tuple[EvalItem, list[str], float]], threshold: float) -> GateMetrics:
    """`results`: (câu, top-5 doc_id theo hạng, top_score). Hàm thuần."""
    pos = [(item, top) for item, top, _ in results if item.expected_doc_ids]
    neg = [score for item, _, score in results if not item.expected_doc_ids]
    hit = 0
    rr = 0.0
    for item, top in pos:
        top5 = top[:GATE_TOP_DOCS]
        expected = set(item.expected_doc_ids)
        if expected & set(top5):
            hit += 1
            rr += 1.0 / next(rank for rank, d in enumerate(top5, start=1) if d in expected)
    recall = hit / len(pos) if pos else 0.0
    fg = sum(1 for s in neg if s >= threshold) / len(neg) if neg else 0.0
    return GateMetrics(recall, fg, rr / len(pos) if pos else 0.0, len(pos), len(neg))


async def evaluate(
    rs: RetrievalSet, retriever: Retriever, collection: str, threshold: float
) -> GateMetrics:
    results = []
    for item in rs.items:
        top, score = await retriever.top_docs(item.query, item.role, collection=collection)
        results.append((item, top, score))
    return metrics(results, threshold)


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    branch: Literal["a", "b", "c"]
    eval_status: Literal["evaluated", "unevaluated"]
    reason: str
    new: GateMetrics | None = None
    old: GateMetrics | None = None


def decide(
    *, has_set: bool, allow_unevaluated: bool, new: GateMetrics | None, old: GateMetrics | None
) -> GateDecision:
    if not has_set:
        if allow_unevaluated:
            return GateDecision(True, "a", "unevaluated", "không có bộ kiểm tra, --allow-unevaluated (dev/test)")
        return GateDecision(False, "a", "unevaluated",
                            f"không có {RETRIEVAL_SET.as_posix()} — thêm bộ kiểm tra hoặc dùng --allow-unevaluated "
                            "(chỉ APP_ENV dev/test)")  # fmt: skip
    assert new is not None
    if old is None:
        ok = new.recall_at5 >= GATE_MIN_RECALL - GATE_EPS and new.false_grounding_rate <= (
            GATE_MAX_FALSE_GROUNDING + GATE_EPS
        )
        reason = f"lần đầu: cần Recall@5 ≥ {GATE_MIN_RECALL:.2f} và trả lời bừa ≤ {GATE_MAX_FALSE_GROUNDING:.2f}"
        return GateDecision(ok, "b", "evaluated", reason, new)
    ok = new.recall_at5 >= old.recall_at5 - GATE_MAX_DELTA - GATE_EPS and new.false_grounding_rate <= (
        old.false_grounding_rate + GATE_MAX_DELTA + GATE_EPS
    )
    reason = (f"so với bản đang chạy: Recall@5 không tụt quá {GATE_MAX_DELTA:.2f}, "
              f"trả lời bừa không tăng quá {GATE_MAX_DELTA:.2f}")  # fmt: skip
    return GateDecision(ok, "c", "evaluated", reason, new, old)
