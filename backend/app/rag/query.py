"""Dựng câu truy hồi RAG (thiết kế Phase 3 mục 6.4, 3-Q13).

Không nối `device_id` (vô nghĩa với KB) hay tên intent — chỉ `query_slots` (`config/slots.yaml`, hiện chỉ có
`error_code`). Câu dài để ml-service tự cắt khi rerank (3-Q12). Thẻ `[fake:…]` (dev/test) bị bỏ — `core.fake_tag`.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.fake_tag import strip_fake_tag
from app.rag.models import RetrievalQuery


def build_query(
    redacted_request: str, intent: str | None, slots: Mapping[str, Any], *, query_slots: Sequence[str]
) -> RetrievalQuery:
    base = strip_fake_tag(redacted_request).strip()  # thẻ preset dev/test không vào câu truy hồi (Q-3h-11 a)
    extra = [
        str(slots[k]).strip()
        for k in query_slots
        if k in slots and str(slots[k]).strip() and str(slots[k]).strip().casefold() not in base.casefold()
    ]
    return RetrievalQuery(text=" ".join([base, *extra]).strip(), intent=intent)
