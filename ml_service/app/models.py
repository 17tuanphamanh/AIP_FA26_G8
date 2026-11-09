"""Giao diện của model đã nạp — `loader.load_models` dựng bản thật (sentence-transformers, transformers), test tiêm
bản giả (không cần torch). Code xử lý (`tokens`, `embed`, `rerank`, `guard`) chỉ biết các Protocol này."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.lock import ModelRef

EMBED_LABEL = "bge-m3"  # tên trong header X-Model-Version (P4 mục 7, thiết kế 3a mục 4.3)
RERANK_LABEL = "reranker"
GUARD_LABEL = "injection-clf"  # trường `model` của /classify (P11 mục 4.3, backend `ClassifyOut`)
INTENT_LABEL = "intent-clf"  # trường `model` của /classify_intent (gói 2, D-53; backend `IntentOut`)


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
class IntentRaw:
    """Đầu ra THÔ của model intent cho một câu — trộn điểm, lọc token, cờ cắt làm ở `intent.py` (không torch)."""

    seq_logits: list[float]  # một logit mỗi nhãn, theo `labels` của inference_config
    tok_probs: list[list[float]]  # softmax đầu gắn thẻ, một hàng mỗi token (đã cắt ở max_len), một cột mỗi tag
    offsets: list[tuple[int, int]]  # offset ký tự (a, b) của từng token; token đặc biệt (0, 0)
    full_len: int  # số id của câu KHÔNG cắt (gồm token đặc biệt) — cờ `truncated`


class IntentScorer(Protocol):
    def score(self, text: str) -> IntentRaw: ...


@dataclass(frozen=True)
class Intent:
    """Model intent (intent-clf, B3 — gói 2, D-53) đã nạp."""

    scorer: IntentScorer
    labels: tuple[str, ...]  # đúng thứ tự `labels` của inference_config — thứ tự khoá `probs`
    b_req: tuple[int, ...]  # cột tag `B-REQ:<nhãn>` trong `tok_probs`, theo `labels`
    i_req: tuple[int, ...]  # cột tag `I-REQ:<nhãn>`
    mix: tuple[float, float]  # mix_weights[0] (sigmoid seq), mix_weights[1] (p_span); mix_weights[2] = 0 đã kiểm lúc nạp
    max_len: int
    tau_lo: dict[str, float]  # thresholds.json
    tau_hi: dict[str, float]
    version: str  # tên thư mục phiên bản, vd "v3.1-seed42-st"


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
    intent: Intent | None = None  # None = INTENT_MODEL_DIR không đặt → /classify_intent 503 model_missing

    @property
    def version(self) -> str:
        return f"{EMBED_LABEL}@{self.embed.short};{RERANK_LABEL}@{self.rerank.short}"
