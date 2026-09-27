"""Lọc quyền khi truy hồi (thiết kế Phase 3 mục 6.5, 3-Q5; kéo sớm ở 3b — Q-3b-6).

`base_filter(role)` — điều kiện BẮT BUỘC của mọi truy vấn Qdrant: chỉ tài liệu enabled (phòng thủ hai lớp — ingest đã
không đưa tài liệu disabled vào collection) và độ nhạy mà role được xem. Role lạ → ít quyền nhất (fail-closed).
Cổng kiểm của ingest (3b) và `retrieve` (3c) cùng dùng hàm này.
"""

from qdrant_client.models import FieldCondition, MatchAny, MatchValue

_ALLOWED = {
    "employee": ["public", "internal"],
    "l1": ["public", "internal", "restricted"],
    "l2": ["public", "internal", "restricted"],
    "manager": ["public", "internal", "restricted"],
}


def allowed_sensitivity(role: str) -> list[str]:
    return list(_ALLOWED.get(role, ["public"]))


def base_filter(role: str) -> list[FieldCondition]:
    return [
        FieldCondition(key="enabled", match=MatchValue(value=True)),
        FieldCondition(key="sensitivity", match=MatchAny(any=allowed_sensitivity(role))),
    ]
