"""Nạp model thật MỘT lần lúc khởi động (P4 mục 2, thiết kế 3a mục 4.4).

Kiểm lock + thư mục model TRƯỚC khi import torch: thiếu → `LockError` "chạy make models", service không
lên (fail-closed). `sentence_transformers`/`torch` import BÊN TRONG hàm → test dùng loader giả không cần
torch (nhóm uv `ml` không cài trong CI). Image đặt `HF_HUB_OFFLINE=1`: không tải gì lúc chạy.

Model chặn tấn công (ML-GAN phần 1, `GUARD_MODEL_DIR`): `guard.check_guard` (file, SHA-256, `id2label`) cũng chạy TRƯỚC
torch. Nạp bằng `AutoTokenizer` + `AutoModelForSequenceClassification` với `local_files_only=True`,
`use_safetensors=True`, `trust_remote_code=False` (không pickle, không chạy mã trong thư mục model); CPU, `eval()`,
`no_grad`. Tự kiểm tokenizer (không tự cắt, cls/sep như khi train) rồi mới nhận.
"""

import logging
import time
from typing import Any

from app.guard import (
    INJECTION_LABEL,
    WINDOW_BODY,
    GuardLoadError,
    GuardSpec,
    check_guard,
)
from app.lock import model_dirs, read_lock
from app.models import Guard, Models, Tokenizer
from app.rerank import RERANK_MAX_LENGTH
from app.settings import MlSettings
from app.tokens import EMBED_MAX_TOKENS

log = logging.getLogger(__name__)

GUARD_BATCH = 16  # cửa sổ mỗi lượt forward (≤ 48 cửa sổ/câu → ≤ 3 lượt)
_SELF_CHECK_TEXT = "vpn không vào được"


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


class _HfGuardScorer:
    def __init__(self, model: Any, pad_id: int) -> None:
        self._model = model
        self._pad = pad_id

    def logits(self, windows: list[list[int]]) -> list[list[float]]:
        import torch

        rows: list[list[float]] = []
        for start in range(0, len(windows), GUARD_BATCH):
            batch = windows[start : start + GUARD_BATCH]
            width = max(len(w) for w in batch)
            ids = torch.tensor([w + [self._pad] * (width - len(w)) for w in batch])
            mask = torch.tensor([[1] * len(w) + [0] * (width - len(w)) for w in batch])
            with torch.no_grad():
                out = self._model(input_ids=ids, attention_mask=mask).logits
            rows.extend([float(x) for x in row] for row in out.tolist())
        return rows


def _load_guard(spec: GuardSpec) -> Guard:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    started = time.perf_counter()
    path = str(spec.dir)
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(
        path, local_files_only=True, use_safetensors=True, trust_remote_code=False
    )
    model.to("cpu")
    model.eval()
    labels = {int(k): v for k, v in (model.config.id2label or {}).items()}
    if labels.get(spec.injection_index) != INJECTION_LABEL:
        raise GuardLoadError(f"id2label của model đã nạp ({labels}) khác config.json đã kiểm")
    cls_id, sep_id, pad_id = tokenizer.cls_token_id, tokenizer.sep_token_id, tokenizer.pad_token_id
    if not all(isinstance(i, int) for i in (cls_id, sep_id, pad_id)):
        raise GuardLoadError("tokenizer của model chặn tấn công thiếu cls/sep/pad")
    _self_check(tokenizer, cls_id, sep_id)
    log.info(
        "đã nạp injection-clf %s (SHA-256 %s, lớp INJECTION = %d) trong %.1f s",
        spec.version, "đã kiểm" if spec.sha_checked else "KHÔNG kiểm", spec.injection_index,
        time.perf_counter() - started,
    )  # fmt: skip
    return Guard(
        tokenizer=tokenizer, scorer=_HfGuardScorer(model, pad_id), cls_id=cls_id, sep_id=sep_id,
        injection_index=spec.injection_index, version=spec.version,
    )  # fmt: skip


def _self_check(tokenizer: Tokenizer, cls_id: int, sep_id: int) -> None:
    """Cửa sổ tự cắt chỉ đúng nếu tokenizer KHÔNG tự cắt và câu ngắn = cls + id + sep như lúc train (ML-KIEM)."""
    long_ids = tokenizer(" ".join([_SELF_CHECK_TEXT] * 60), add_special_tokens=False)["input_ids"]
    if len(long_ids) <= WINDOW_BODY:
        raise GuardLoadError(f"tokenizer của model chặn tấn công tự cắt văn bản dài ({len(long_ids)} id)")
    short = list(tokenizer(_SELF_CHECK_TEXT, add_special_tokens=False)["input_ids"])
    if [cls_id, *short, sep_id] != list(tokenizer(_SELF_CHECK_TEXT, add_special_tokens=True)["input_ids"]):
        raise GuardLoadError("tokenizer: cls + id + sep khác kết quả tokenizer có token đặc biệt")


def load_models(settings: MlSettings) -> Models:
    refs = read_lock(settings.models_lock)
    dirs = model_dirs(settings.models_dir, settings.models_lock)  # thiếu → LockError, chưa đụng torch
    guard_spec = check_guard(settings)  # sai file/SHA/id2label → GuardLoadError, chưa đụng torch

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
    guard = _load_guard(guard_spec) if guard_spec is not None else None
    return Models(
        tokenizer=tokenizer, rerank_tokenizer=rerank_tokenizer, embedder=_StEmbedder(embedder),
        reranker=_CeReranker(reranker), embed=refs["embed"], rerank=refs["rerank"], dim=dim, guard=guard,
    )  # fmt: skip
