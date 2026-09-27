"""Đếm token cho chunker (thiết kế Phase 3 mục 5.5; PLAN-3b mục 4.4). Số đếm GỒM token đặc biệt (3-Q20).

- `MlTokenCounter` — qua ml-service `/count_tokens` (tokenizer bge-m3 thật). CLI ingest CHỈ dùng cái này.
- `LocalTokenizerCounter` — tokenizer bge-m3 nạp từ file, CHỈ cho test (`tokenizer_real`, Q-3b-11): image backend
  không có gói `tokenizers`, nên import muộn trong `__init__`.
"""

from pathlib import Path
from typing import Any, Protocol

from app.ml.ports import MlPort
from app.rag.ingest.config import COUNT_BATCH
from app.rag.models import IngestMlError


class TokenCounter(Protocol):
    async def count(self, texts: list[str]) -> list[int]: ...


class MlTokenCounter:
    def __init__(self, ml: MlPort) -> None:
        self._ml = ml

    async def count(self, texts: list[str]) -> list[int]:
        out: list[int] = []
        for i in range(0, len(texts), COUNT_BATCH):  # MlClient tự chia thêm theo byte
            batch = texts[i : i + COUNT_BATCH]
            result = await self._ml.count_tokens(batch)
            if result.error is not None or result.data is None:
                raise IngestMlError(f"ml-service /count_tokens lỗi: {result.error} sau {result.attempts} lần")
            if len(result.data.counts) != len(batch):
                raise IngestMlError(
                    f"ml-service /count_tokens trả {len(result.data.counts)} số cho {len(batch)} văn bản"
                )
            out.extend(result.data.counts)
        return out


class LocalTokenizerCounter:
    """Chỉ dùng trong test (tokenizer_real). Image backend không có gói `tokenizers`."""

    def __init__(self, tokenizer_json: Path) -> None:
        from tokenizers import Tokenizer  # import muộn — gói chỉ có ở nhóm dev

        self._tok: Any = Tokenizer.from_file(str(tokenizer_json))

    async def count(self, texts: list[str]) -> list[int]:
        if not texts:
            return []
        return [len(e.ids) for e in self._tok.encode_batch(texts, add_special_tokens=True)]
