"""Giao diện của model đã nạp — `loader.load_models` dựng bản thật (sentence-transformers), test tiêm
bản giả (không cần torch). Code xử lý (`tokens`, `embed`, `rerank`) chỉ biết các Protocol này."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.lock import ModelRef

EMBED_LABEL = "bge-m3"  # tên trong header X-Model-Version (P4 mục 7, thiết kế 3a mục 4.3)
RERANK_LABEL = "reranker"


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


@dataclass(frozen=True)
class Models:
    tokenizer: Tokenizer  # bge-m3: đếm token, cờ truncated của /embed
    rerank_tokenizer: Tokenizer  # reranker: cắt câu truy vấn, độ dài cặp
    embedder: Embedder
    reranker: Reranker
    embed: ModelRef
    rerank: ModelRef
    dim: int

    @property
    def version(self) -> str:
        return f"{EMBED_LABEL}@{self.embed.short};{RERANK_LABEL}@{self.rerank.short}"
