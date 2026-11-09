"""Intent chỉ-trả-lời (D-76, ĐP chốt 09/11, bản demo lo-0811 — lô Q12). Một nguồn cho hằng `it_help`.

`it_help` = câu HỎI cách làm / BÁO hiện tượng IT ngoài 4 loại hành động mà KB `general` hướng dẫn được (máy in, Wi-Fi, Outlook…). KHÔNG có
slot, KHÔNG có hành động: B3 → B6 (0 tool) → B8 (lọc `request_type ∈ ["general"]`) → B10 ép `info` → `S_CONFIRMING`. Không bao giờ tới
B11/B12/M5/B15/B17 (B11, B12 gặp intent này → `ValueError` → E9). KHÔNG thuộc `ENABLED_INTENTS` (không slot/roster/plan) và KHÔNG thuộc
`db.models.INTENTS` (4 loại hành động mà eval/monitor/policy dùng) — chỉ vào CHECK của `tickets`/`audit_logs` (`TICKET_INTENTS`, migration 0015).
"""

from typing import Final

IT_HELP: Final = "it_help"
ANSWER_ONLY_INTENTS: Final[frozenset[str]] = frozenset({IT_HELP})
