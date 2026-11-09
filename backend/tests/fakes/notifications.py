"""Nguồn thông báo giả (`app.state.notifications`) — cùng ngữ nghĩa `db/notifications.SqlNotificationSource`: lọc requester TRƯỚC khi
sắp, sắp `created_at` ↓ rồi `id` ↓ (so chuỗi byte = `COLLATE "C"` với ASCII), keyset loại trừ con trỏ."""

from dataclasses import dataclass
from typing import Any

from app.db.notifications import Cursor, NotificationRow


@dataclass(frozen=True)
class StoredNotification:
    requester_id: str
    row: NotificationRow


class MemoryNotifications:
    def __init__(self, *items: StoredNotification) -> None:
        self.items = list(items)
        self.calls: list[dict[str, Any]] = []

    async def page(self, user_id: str, limit: int, after: Cursor | None) -> list[NotificationRow]:
        self.calls.append({"user_id": user_id, "limit": limit, "after": after})
        mine = [i.row for i in self.items if i.requester_id == user_id]
        ordered = sorted(mine, key=lambda r: (r.created_at, r.id), reverse=True)
        if after is not None:
            ordered = [r for r in ordered if (r.created_at, r.id) < (after.at, after.id)]
        return ordered[:limit]
