"""Schema kết quả của ml-service phía backend (thiết kế Phase 3 mục 4.3; P4 mục 4 cho classify).

Bỏ qua trường thừa (ml-service thêm trường không làm gãy backend), nhưng thiếu trường / sai kiểu là lỗi
hợp đồng → `MlContractError` (như output tool, P5 mục 6.1).
"""

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class EmbedOut(_Out):
    vectors: list[list[float]]
    dim: int
    model: str
    truncated: list[bool]  # văn bản > 512 token (D-21) — B8/ingest ghi số lần vào span, M9 cảnh báo
    token_counts: list[int]


class RerankOut(_Out):
    scores: list[float]  # sigmoid 0..1, cùng thứ tự passages
    truncated: list[bool]  # ĐOẠN TÀI LIỆU bị cắt — phải luôn False với chunker P3
    query_truncated: bool  # câu truy vấn bị cắt ở 128 token (3-Q12)
    model: str


class CountOut(_Out):
    counts: list[int]  # GỒM token đặc biệt (3-Q20)
    model: str


class ClassifyOut(_Out):  # injection-clf (Phase 5) — Phase 3 luôn model_missing
    # Phase 5 gói 1 (phase5 §6.5 #8): ngoài [0, 1] hoặc NaN/inf → sai schema → MlContractError → E9 (bảng 4.2 #10)
    p_malicious: float = Field(ge=0, le=1, allow_inf_nan=False)
    windows: int
    model: str
    version: str


class IntentOut(_Out):  # intent-clf đa nhãn (Phase 5, D-32) — Phase 3 luôn model_missing
    probs: dict[str, float]
    tau_hi: dict[str, float]
    tau_lo: dict[str, float]
    truncated: bool
    model: str
    version: str
