"""Nạp model thật MỘT lần lúc khởi động (P4 mục 2, thiết kế 3a mục 4.4).

Kiểm lock + thư mục model TRƯỚC khi import torch: thiếu → `LockError` "chạy make models", service không
lên (fail-closed). `sentence_transformers`/`torch` import BÊN TRONG hàm → test dùng loader giả không cần
torch (nhóm uv `ml` không cài trong CI). Image đặt `HF_HUB_OFFLINE=1`: không tải gì lúc chạy.
"""

from typing import Any

from app.lock import model_dirs, read_lock
from app.models import Models, Tokenizer
from app.rerank import RERANK_MAX_LENGTH
from app.settings import MlSettings
from app.tokens import EMBED_MAX_TOKENS


class _StEmbedder:
    def __init__(self, model: Any) -> None:
        self._model = model

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts, normalize_embeddings=True, batch_size=16, convert_to_numpy=True
        )
        return [[float(x) for x in row] for row in vectors]


class _CeReranker:
    def __init__(self, model: Any) -> None:
        self._model = model

    def logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [float(x) for x in self._model.predict(pairs, batch_size=16, convert_to_numpy=True)]


def load_models(settings: MlSettings) -> Models:
    refs = read_lock(settings.models_lock)
    dirs = model_dirs(settings.models_dir, settings.models_lock)  # thiếu → LockError, chưa đụng torch

    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    torch.set_num_threads(settings.ml_threads)
    embedder = SentenceTransformer(str(dirs["embed"]), device="cpu", local_files_only=True)
    embedder.max_seq_length = EMBED_MAX_TOKENS  # bge-m3 khai 8192; P4 chốt 512 (khớp cờ truncated)
    reranker = CrossEncoder(
        str(dirs["rerank"]), device="cpu", local_files_only=True, max_length=RERANK_MAX_LENGTH,
        activation_fn=torch.nn.Identity(),  # lấy logit thô — sigmoid áp một lần ở rerank.py
    )  # fmt: skip
    dim = embedder.get_embedding_dimension()
    if dim is None:
        raise RuntimeError("không xác định được số chiều vector của model embed")
    tokenizer: Tokenizer = embedder.tokenizer
    rerank_tokenizer: Tokenizer = reranker.tokenizer
    return Models(
        tokenizer=tokenizer, rerank_tokenizer=rerank_tokenizer, embedder=_StEmbedder(embedder),
        reranker=_CeReranker(reranker), embed=refs["embed"], rerank=refs["rerank"], dim=dim,
    )  # fmt: skip
