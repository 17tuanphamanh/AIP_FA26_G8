"""Cổng kiểm của ingest, bước 10 (thiết kế Phase 3 mục 5.8, 3-Q15; PLAN-3b mục 7.1, PLAN-3c mục 1; Q-3b-4).

Bộ kiểm tra `<kb_dir>/eval/retrieval_set.yaml` → Recall@5, tỉ lệ trả lời bừa (FG), MRR@5. Quyết định:
  (a) không có bộ: `--allow-unevaluated` (env đã qua bước 0) → đạt, `unevaluated`, số đo NULL; không cờ → KHÔNG đạt.
  (b) có bộ, chưa có alias (hoặc bản cũ lệch `pipeline_sha` — Q-3c-6, "ngoại lệ 3-Q15"): đạt ⇔ Recall ≥ 0,80 và
      FG ≤ 0,05.
  (c) có bộ, có alias, CÙNG `pipeline_sha`: đánh giá LẠI bản cũ bằng cùng bộ, cùng retriever; đạt ⇔ Recall không
      tụt quá 0,05 và FG không tăng quá 0,05.

3c: cổng kiểm dùng chung `Retriever` thật (BM25 + dense + rerank + lọc quyền) qua `RetrieveGateAdapter` — không
còn cosine dense-only (giới hạn đã biết của 3b, xem `01-kien-truc-project.md`/PROGRESS "spec cần sửa").
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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

from app.db.models import KB_REQUEST_TYPES
from app.domain.context import RequesterContext, Role
from app.domain.ticket_state import ChunkRef
from app.rag.ingest.config import (
    GATE_EPS,
    GATE_MAX_DELTA,
    GATE_MAX_FALSE_GROUNDING,
    GATE_MIN_RECALL,
    GATE_TOP_DOCS,
)
from app.rag.models import (
    IngestIssue,
    IngestMlError,
    RetrievalQuery,
    RetrievalSystemError,
)
from app.rag.ports import RagPort

RETRIEVAL_SET = Path("eval") / "retrieval_set.yaml"
_GATE_CTX_TIME = datetime(2026, 1, 1, tzinfo=UTC)  # ngữ cảnh tổng hợp cho cổng kiểm — chỉ role được đọc


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


# ---- Truy hồi (adapter quanh `retrieve()` thật, 3c) ---------------------------------------------


def gate_intent(intent: str) -> str | None:
    """Q-3c-7: cổng kiểm truyền `intent` của câu kiểm tra nếu ∈ `KB_REQUEST_TYPES`, ngược lại `None`."""
    return intent if intent in KB_REQUEST_TYPES else None


def gate_ctx(role: str) -> RequesterContext:
    """Ngữ cảnh tổng hợp cho cổng kiểm/eval — chỉ `role` có ý nghĩa (lọc quyền); các trường khác không được
    `retrieve()`/`expand_for_answer()` đọc tới."""
    return RequesterContext(
        user_id="gate", role=role, department="gate", manager_id=None, employment_status="active",  # type: ignore[arg-type]
        tenure_days=0, is_privileged_account=False, captured_at=_GATE_CTX_TIME,
    )  # fmt: skip


class Retriever(Protocol):
    async def top_docs(self, item: EvalItem, *, collection: str) -> tuple[list[str], float]:
        """(≤ 5 doc_id theo hạng, top_score); không có hit → ([], 0.0)."""
        ...


class RetrieveGateAdapter:
    """Bọc `RagPort` (Retriever thật, 3c) thành Protocol hẹp mà cổng kiểm cần — cùng đường lọc quyền, BM25,
    rerank với node B8. `RetrievalSystemError` (lỗi hệ thống khi đánh giá) → `IngestMlError` (mã thoát 1, như
    lỗi ml-service khi ingest — không phải lỗi cổng kiểm KHÔNG ĐẠT, mà là không đánh giá được)."""

    def __init__(self, retriever: RagPort) -> None:
        self._retriever = retriever

    async def top_docs(self, item: EvalItem, *, collection: str) -> tuple[list[str], float]:
        q = RetrievalQuery(text=item.query, intent=gate_intent(item.intent))
        try:
            res = await self._retriever.retrieve(q, gate_ctx(item.role), collection=collection)
        except RetrievalSystemError as e:
            raise IngestMlError(f"retrieve lỗi khi đánh giá (stage={e.stage}, sau {e.retries} lần thử lại)") from e
        return [c.doc_id for c in res.chunks][:GATE_TOP_DOCS], res.top_score


# ---- Chỉ số, quyết định ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateMetrics:
    """`recall_at5` KHÔNG xét ngưỡng (nghĩa cũ). R1 thêm hai trường MỚI — cổng ingest (`decide`) không đọc chúng; mặc định 0.0 để mọi chỗ
    dựng 5 đối số cũ vẫn chạy:
    - `p_at_1`: tỉ lệ câu có đáp án mà tài liệu hạng 1 ∈ `expected_doc_ids`;
    - `recall_at_threshold`: tỉ lệ câu có đáp án mà tài liệu đúng nằm trong top-5 VÀ `top_score ≥ threshold` (bằng ngưỡng thì trúng)."""

    recall_at5: float
    false_grounding_rate: float
    mrr: float
    positives: int
    negatives: int
    p_at_1: float = 0.0
    recall_at_threshold: float = 0.0


def metrics(results: list[tuple[EvalItem, list[str], float]], threshold: float) -> GateMetrics:
    """`results`: (câu, top-5 doc_id theo hạng, top_score). Hàm thuần."""
    pos = [(item, top, score) for item, top, score in results if item.expected_doc_ids]
    neg = [score for item, _, score in results if not item.expected_doc_ids]
    hit = 0
    hit_at_threshold = 0
    first = 0
    rr = 0.0
    for item, top, score in pos:
        top5 = top[:GATE_TOP_DOCS]
        expected = set(item.expected_doc_ids)
        if expected & set(top5):
            hit += 1
            rr += 1.0 / next(rank for rank, d in enumerate(top5, start=1) if d in expected)
            if score >= threshold:
                hit_at_threshold += 1
        if top5 and top5[0] in expected:
            first += 1
    recall = hit / len(pos) if pos else 0.0
    fg = sum(1 for s in neg if s >= threshold) / len(neg) if neg else 0.0
    return GateMetrics(
        recall, fg, rr / len(pos) if pos else 0.0, len(pos), len(neg),
        p_at_1=first / len(pos) if pos else 0.0,
        recall_at_threshold=hit_at_threshold / len(pos) if pos else 0.0,
    )  # fmt: skip


async def evaluate(
    rs: RetrievalSet, retriever: Retriever, collection: str, threshold: float
) -> GateMetrics:
    results = []
    for item in rs.items:
        top, score = await retriever.top_docs(item, collection=collection)
        results.append((item, top, score))
    return metrics(results, threshold)


class OnceSearcher(Protocol):
    """`rag.retriever.Retriever.search_once` — MỘT lần tìm, `use_intent` tường minh (không có bước D-23 thử lại không lọc)."""

    async def search_once(
        self, q: RetrievalQuery, ctx: RequesterContext, *, collection: str, use_intent: bool
    ) -> tuple[list[ChunkRef], float]: ...


async def evaluate_without_intent(
    rs: RetrievalSet, searcher: OnceSearcher, collection: str, threshold: float
) -> GateMetrics:
    """R1 — lượt chạy KHÔNG lọc intent: mỗi câu tìm một lần với `use_intent=False` (vẫn lọc quyền theo `role` của câu), cùng `metrics`.
    Chỉ để quan sát (`eval_cli`) — KHÔNG phải điều kiện của cổng ingest."""
    results = []
    for item in rs.items:
        q = RetrievalQuery(text=item.query, intent=gate_intent(item.intent))
        chunks, score = await searcher.search_once(q, gate_ctx(item.role), collection=collection, use_intent=False)
        results.append((item, [c.doc_id for c in chunks][:GATE_TOP_DOCS], score))
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


# ---- Quét ngưỡng (Q-3c-15, `eval_cli.py --sweep`) -------------------------------------------------

# 0,30 … 0,90, bước 0,05 = 13 điểm — chỉ để QUAN SÁT độ nhạy, KHÔNG dùng để chọn RETRIEVAL_THRESHOLD (D-22).
SWEEP_THRESHOLDS: tuple[float, ...] = tuple(round(0.30 + 0.05 * i, 2) for i in range(13))

type SearchPair = tuple[list[str], float]  # (doc_id theo hạng, top_score) — từ `Retriever.search_once`


@dataclass(frozen=True)
class SweepPoint:
    threshold: float
    metrics: GateMetrics


def sweep(
    rs: RetrievalSet,
    pairs: Mapping[str, tuple[SearchPair, SearchPair]],
    thresholds: Sequence[float] = SWEEP_THRESHOLDS,
) -> list[SweepPoint]:
    """Hàm THUẦN — không gọi mạng. `pairs[item.id] = (first, alt)`: `first` = `search_once(use_intent=True)`,
    `alt` = `search_once(use_intent=False)` (mô phỏng D-23 CHO TỪNG ngưỡng T, không phải ngưỡng thật đang chạy):
    `first.top_score ≥ T` → dùng `first`; ngược lại `alt.top_score ≥ T` → dùng `alt`; ngược lại vẫn `first`
    (đúng ngữ nghĩa D-23 thật: không bao giờ trả `alt` khi `alt` cũng dưới ngưỡng)."""
    out = []
    for t in thresholds:
        results: list[tuple[EvalItem, list[str], float]] = []
        for item in rs.items:
            first, alt = pairs[item.id]
            chosen = first if first[1] >= t else (alt if alt[1] >= t else first)
            results.append((item, chosen[0], chosen[1]))
        out.append(SweepPoint(t, metrics(results, t)))
    return out
