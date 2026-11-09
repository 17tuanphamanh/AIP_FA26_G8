"""Lọc quyền khi truy hồi (thiết kế Phase 3 mục 6.5, 3-Q5; kéo sớm ở 3b — Q-3b-6).

`base_filter(role)` — điều kiện BẮT BUỘC của mọi truy vấn Qdrant: chỉ tài liệu enabled (phòng thủ hai lớp — ingest đã
không đưa tài liệu disabled vào collection) và độ nhạy mà role được xem. Role lạ → ít quyền nhất (fail-closed).
Cổng kiểm của ingest (3b) và `retrieve` (3c) cùng dùng hàm này.

`query_filter(role, *extra)` là chỗ DUY NHẤT trong `app/rag/` được gọi `Filter(` — cả 3 đường truy hồi (lần 1, lần
chạy lại D-23, `expand_for_answer` D-24) đi qua đây nên không đường nào dựng filter thiếu `base_filter` (c36).
`procedure_filter` (Phase 4 S0-P10) — kiểm tài liệu quy trình ở B11 — cũng đi qua `query_filter`.
"""

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.domain.intents import ANSWER_ONLY_INTENTS

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


def intent_filter(intent: str) -> FieldCondition:
    """Lần truy hồi đầu: tài liệu của intent + `general`. D-76: intent chỉ-trả-lời (`it_help`) → CHỈ `general` (không có tài liệu loại
    `it_help` — `KB_REQUEST_TYPES`). Lần chạy lại D-23 không lọc intent — không đổi."""
    types = ["general"] if intent in ANSWER_ONLY_INTENTS else [intent, "general"]
    return FieldCondition(key="request_type", match=MatchAny(any=types))


def query_filter(role: str, *extra: FieldCondition) -> Filter:
    return Filter(must=[*base_filter(role), *extra])


def procedure_filter(role: str, doc_id: str) -> Filter:
    """Tài liệu quy trình `doc_id` mà `role` được xem: `base_filter` (enabled + độ nhạy) + đúng `doc_id` (S0-P10)."""
    return query_filter(role, FieldCondition(key="doc_id", match=MatchValue(value=doc_id)))
