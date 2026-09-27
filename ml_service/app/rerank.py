"""POST /rerank — bge-reranker-v2-m3 (P4, thiết kế 3a mục 4.4, 3-Q12).

Cắt **câu truy vấn** ở `QUERY_MAX_TOKENS` (cờ `query_truncated`), cửa sổ cặp `RERANK_MAX_LENGTH`: với
đoạn ≤ 480 token của chunker P3 thì 128 + 480 + 4 < 640 → đoạn tài liệu không bao giờ bị cắt. Câu người
dùng dài không được âm thầm cắt mất phần cuối đoạn tài liệu — phần quyết định câu trả lời đủ bước (D-21).

Điểm = sigmoid(logit), áp ĐÚNG MỘT LẦN ở đây: loader nạp CrossEncoder với activation identity
(mặc định của thư viện là sigmoid — áp thêm lần nữa sẽ dồn mọi điểm về khoảng 0,5–0,73).
"""

import math

from app.models import Models, Tokenizer
from app.schemas import RerankOut
from app.tokens import count_pair

QUERY_MAX_TOKENS = 128
RERANK_MAX_LENGTH = 640  # truyền vào CrossEncoder(max_length=…) ở loader


def cut_query(tokenizer: Tokenizer, query: str) -> tuple[str, bool]:
    ids = tokenizer(query, add_special_tokens=False)["input_ids"]
    if len(ids) <= QUERY_MAX_TOKENS:
        return query, False
    return tokenizer.decode(ids[:QUERY_MAX_TOKENS]), True


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def rerank_sync(models: Models, query: str, passages: list[str]) -> RerankOut:
    tok = models.rerank_tokenizer
    q, query_truncated = cut_query(tok, query)
    truncated = [count_pair(tok, q, p) > RERANK_MAX_LENGTH for p in passages]
    logits = models.reranker.logits([(q, p) for p in passages])
    return RerankOut(
        scores=[sigmoid(x) for x in logits], truncated=truncated,
        query_truncated=query_truncated, model=models.rerank.repo,
    )  # fmt: skip
