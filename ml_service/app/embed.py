"""POST /embed — vector dense bge-m3 (P4, thiết kế 3a mục 4.4).

`truncated` tính TRƯỚC khi encode (3-Q20), từ số token gồm token đặc biệt: > 512 → model chỉ thấy
phần đầu. Không raise khi cắt — chỉ báo cờ, backend ghi vào span và M9 cảnh báo (D-21).
Hàm đồng bộ: chạy trong threadpool (`main.py`), không chặn event loop.
"""

from app.models import Models
from app.schemas import EmbedOut
from app.tokens import EMBED_MAX_TOKENS, count


def embed_sync(models: Models, texts: list[str]) -> EmbedOut:
    counts = [count(models.tokenizer, text) for text in texts]
    vectors = models.embedder.encode(texts)
    return EmbedOut(
        vectors=vectors, dim=models.dim, model=models.embed.repo,
        truncated=[n > EMBED_MAX_TOKENS for n in counts], token_counts=counts,
    )  # fmt: skip
