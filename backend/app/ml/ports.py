"""Port ml-service (3-Q7: ml-service KHÔNG phải tool — gọi qua `MlClient`, không qua ToolRegistry).

`MlResult` trả lỗi hạ tầng như GIÁ TRỊ, không raise (E2 ≠ E9): node/rag đọc `error` rồi quyết định
(B8 → E2 `rag_system_error`; B2/B3 → đường LLM khi `model_missing`). Lỗi hợp đồng (401/413/422/404,
response sai schema, văn bản quá lớn) là bug cấu hình/code → raise `MlContractError` → E9 ở boundary.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.ml.models import ClassifyOut, CountOut, EmbedOut, IntentOut, RerankOut

# Phase 5 gói 1 (D-52, phase5 §6.5 #10): `classify_failed` — ml-service bắt lỗi suy luận, trả 500 mã chung (không chữ đầu vào).
type MlError = Literal["timeout", "http_5xx", "connect", "model_missing", "too_many_windows", "classify_failed"]


class MlContractError(Exception):
    """Gọi ml-service sai hợp đồng — không retry, không đổi thành E2."""


@dataclass(frozen=True)
class MlResult[T]:
    data: T | None
    error: MlError | None
    # Số lần gọi LỖI trước khi xong — cùng nghĩa `ToolResult.attempts` / `call_with_retry` (Q-3a-2):
    # 500, 500, 200 → 2; hết lượt (3 lần lỗi) → 3; `model_missing` ngay lần đầu → 0. Nhiều lô → cộng dồn.
    attempts: int
    model_version: str | None = None  # header X-Model-Version → lineage (P4 mục 7)


class MlPort(Protocol):
    async def embed(self, texts: list[str]) -> MlResult[EmbedOut]: ...

    async def rerank(self, query: str, passages: list[str]) -> MlResult[RerankOut]: ...

    async def count_tokens(self, texts: list[str]) -> MlResult[CountOut]: ...

    async def classify(self, text: str) -> MlResult[ClassifyOut]: ...

    async def classify_intent(self, text: str) -> MlResult[IntentOut]: ...
