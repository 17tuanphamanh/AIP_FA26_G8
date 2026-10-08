"""Giao diện của model đã nạp — `loader.load_models` dựng bản thật (sentence-transformers, transformers), test tiêm
bản giả (không cần torch). Code xử lý (`tokens`, `embed`, `rerank`, `guard`) chỉ biết các Protocol này."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.lock import ModelRef

EMBED_LABEL = "bge-m3"  # tên trong header X-Model-Version (P4 mục 7, thiết kế 3a mục 4.3)
RERANK_LABEL = "reranker"
GUARD_LABEL = "injection-clf"  # trường `model` của /classify (P11 mục 4.3, backend `ClassifyOut`)


class Tokenizer(Protocol):
    """Tập con của tokenizer HF (XLM-RoBERTa của bge-m3) mà ml-service dùng."""

    def __call__(
        self, text: str, text_pair: str | None = None, *, add_special_tokens: bool = True
    ) -> Mapping[str, Any]: ...

    def decode(self, token_ids: Sequence[int]) -> str: ...


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]:
        """Vector dense đã chuẩn hoá L2, cùng thứ tự `texts`."""
        ...


class Reranker(Protocol):
    def logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Điểm THÔ (logit) của cross-encoder — ml-service tự áp sigmoid đúng một lần."""
        ...


class GuardScorer(Protocol):
    def logits(self, windows: list[list[int]]) -> list[list[float]]:
        """Logit THÔ mỗi cửa sổ (id đã có cls/sep), một hàng mỗi lớp theo `id2label` — softmax áp ở `guard.py`."""
        ...


@dataclass(frozen=True)
class Guard:
    """Model chặn tấn công (injection-clf, B2 L3) đã nạp."""

    tokenizer: Tokenizer  # XLM-R của model: tách id KHÔNG thêm token đặc biệt, không cắt
    scorer: GuardScorer
    cls_id: int
    sep_id: int
    injection_index: int  # vị trí lớp "INJECTION" trong hàng logit — lấy từ config.json `id2label`
    version: str  # tên thư mục phiên bản, vd "v3-seed123"


@dataclass(frozen=True)
class Models:
    tokenizer: Tokenizer  # bge-m3: đếm token, cờ truncated của /embed
    rerank_tokenizer: Tokenizer  # reranker: cắt câu truy vấn, độ dài cặp
    embedder: Embedder
    reranker: Reranker
    embed: ModelRef
    rerank: ModelRef
    dim: int
    guard: Guard | None = None  # None = GUARD_MODEL_DIR không đặt → /classify 503 model_missing

    @property
    def version(self) -> str:
        return f"{EMBED_LABEL}@{self.embed.short};{RERANK_LABEL}@{self.rerank.short}"
