"""Báo trùng yêu cầu (M1) — phần THUẦN: chọn ticket đang mở trùng và dựng tin cố định. Không đọc DB, không gọi LLM.

B3 (sau khi có intent của ticket lá) hỏi store `open_candidates(requester_id, since=…)` — store trả TẬP CHA có thể thừa — rồi
`pick_duplicate` MỚI là nơi quyết định (mọi điều kiện lọc nằm ở đây để unit test + mutation bắt được, không cần Postgres):
cùng người gửi, cùng intent, ticket lá còn mở (`final_state IS NULL` — chưa qua B20), tạo từ `since` (gồm mốc), không phải chính
ticket này, không phải cha hay anh em của nó (cùng một câu gốc, không phải yêu cầu chồng).

`intent` của ticket còn mở lấy từ dòng audit B3 `intent_classified` — `tickets.intent` chỉ được ghi ở B20.
Kết quả chỉ đi vào audit điểm log 1 (`duplicate_of`) và một tin cố định; KHÔNG vào state/ctx/M5 (`test_dedup_isolation_ast.py`).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.domain.messages import INTENT_LABELS


@dataclass(frozen=True)
class OpenCandidate:
    """Một ticket do store trả — chưa lọc. `intent`/`final_state` None = chưa qua B3 / chưa qua B20."""

    ticket_id: str
    requester_id: str
    intent: str | None
    final_state: str | None
    is_parent: bool
    parent_ticket_id: str | None
    created_at: datetime


def pick_duplicate(
    candidates: Iterable[OpenCandidate],
    *,
    ticket_id: str,
    parent_ticket_id: str | None,
    requester_id: str,
    intent: str,
    since: datetime,
) -> str | None:
    """`ticket_id` của yêu cầu trùng MỚI NHẤT (hoà thì mã lớn hơn), hoặc None."""
    best: OpenCandidate | None = None
    for c in candidates:
        if c.requester_id != requester_id or c.intent != intent:
            continue
        if c.final_state is not None or c.is_parent or c.created_at < since:
            continue
        if c.ticket_id == ticket_id or c.ticket_id == parent_ticket_id:
            continue
        if parent_ticket_id is not None and c.parent_ticket_id == parent_ticket_id:
            continue
        if best is None or (c.created_at, c.ticket_id) > (best.created_at, best.ticket_id):
            best = c
    return None if best is None else best.ticket_id


def intent_phrase(intent: str) -> str:
    """Tên loại yêu cầu trong câu: nhãn có sẵn của `INTENT_LABELS`, hạ chữ đầu ("Tài khoản" → "tài khoản"; "VPN" giữ nguyên).
    Intent lạ → `KeyError` (lỗi lập trình, không đoán nhãn)."""
    label = INTENT_LABELS[intent]
    return label if label.isupper() else label[0].lower() + label[1:]


def duplicate_text(template: str, intent: str, duplicate_id: str) -> str:
    """Tin cố định từ mẫu trong `config/dedup.yaml` — chỉ ghép loại và mã ticket, không chữ nào khác."""
    return template.format(loai=intent_phrase(intent), ma=duplicate_id)
