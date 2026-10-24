"""Hợp đồng HTTP của ml-service (thiết kế Phase 3 mục 4.3 — thay P4 mục 4 cho Phase 3).

Giới hạn số phần tử mỗi request là hằng ở đây; `backend/app/ml/client.py` chia lô theo cùng số
(test backend đọc file này bằng AST để hai bên không lệch).
"""

from pydantic import BaseModel, ConfigDict, Field

EMBED_MAX_ITEMS = 64
RERANK_MAX_PASSAGES = 32
COUNT_MAX_ITEMS = 256


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmbedIn(_In):
    texts: list[str] = Field(min_length=1, max_length=EMBED_MAX_ITEMS)


class EmbedOut(BaseModel):
    vectors: list[list[float]]
    dim: int
    model: str
    truncated: list[bool]  # True nếu văn bản dài hơn 512 token (model cắt phần đuôi)
    token_counts: list[int]


class RerankIn(_In):
    query: str
    passages: list[str] = Field(min_length=1, max_length=RERANK_MAX_PASSAGES)


class RerankOut(BaseModel):
    scores: list[float]  # sigmoid 0..1, cùng thứ tự passages
    truncated: list[bool]  # True nếu ĐOẠN TÀI LIỆU bị cắt — với chunker của P3 phải luôn False
    query_truncated: bool  # câu truy vấn bị cắt ở QUERY_MAX_TOKENS (3-Q12)
    model: str


class CountIn(_In):
    texts: list[str] = Field(min_length=1, max_length=COUNT_MAX_ITEMS)


class CountOut(BaseModel):
    counts: list[int]  # GỒM token đặc biệt (3-Q20)
    model: str


class ClassifyIn(_In):  # P4 mục 4 — model injection-clf (Phase 5)
    text: str = Field(min_length=1)


class ClassifyOut(BaseModel):  # khớp `backend/app/ml/models.py` ClassifyOut (test đọc bằng AST)
    p_malicious: float  # max trên mọi cửa sổ của xác suất lớp INJECTION
    windows: int
    model: str
    version: str


class IntentIn(_In):  # P4 mục 4 — model intent-clf (Phase 5, D-32)
    text: str = Field(min_length=1)


class IntentOut(BaseModel):  # khớp `backend/app/ml/models.py` IntentOut (test đọc bằng AST) — gói 2, D-53
    probs: dict[str, float]  # điểm trộn của gói, khoá theo đúng thứ tự `labels` của inference_config
    tau_hi: dict[str, float]  # thresholds.json
    tau_lo: dict[str, float]
    truncated: bool  # câu dài hơn max_len token (model chỉ thấy phần đầu)
    model: str
    version: str
