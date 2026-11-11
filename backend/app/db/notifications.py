"""Nguồn thông báo trong app cho `GET /api/me/notifications` (P10 mục 3.1) — SUY RA từ dữ liệu sẵn có, không bảng mới, không
trạng thái "đã đọc" ở server.

Hai loại, một câu `UNION ALL`:
- `approval_decided`: phiếu `approvals` đã quyết (`approved`/`rejected`); `created_at` = `decided_at`;
- `escalation_closed`: ca L2 đã đóng; `created_at` = `escalations.closed_at`.

Chỉ ticket của CHÍNH người dùng (`tickets.requester_id = :user_id`) — điều kiện nằm ở CẢ HAI nhánh, trong SQL, trước khi
sắp xếp và phân trang (không lọc sau khi lấy). Ticket con trả `ticket_id` của CHA (D-31: con không tự nhắn người dùng).

Phân trang keyset trên `(created_at, id)`: `created_at` giảm dần rồi `id` giảm dần theo `COLLATE "C"` (thứ tự byte, không phụ
thuộc locale của Postgres). `id` là chuỗi `appr:<approval_id>` / `esc:<escalation_id>`. Con trỏ mờ cho FE: base64url của JSON
`{"t": <created_at ISO UTC>, "i": <id>}`.

Chỉ SELECT; engine `engines.main`. Bản giả (test): `tests/fakes/notifications.py`.
"""

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

ID_PATTERN = re.compile(r"(appr|esc):[0-9]{1,19}")


@dataclass(frozen=True)
class NotificationRow:
    """Dòng thô từ SQL — chưa có `text` (câu tiếng Việt dựng ở `api/notifications.py`)."""

    id: str
    kind: str  # approval_decided | escalation_closed
    ticket_id: str
    result: str  # approved | rejected | completed | confirmed_denial | reopened_as_new
    created_at: datetime
    note: str | None = None  # approvals.note (đã che lúc ghi) — chỉ nhánh phiếu duyệt
    exit_code: str | None = None  # escalations.exit_code — chỉ nhánh ca L2
    reason_detail: str | None = None  # escalations.reason_detail — chỉ nhánh ca L2


@dataclass(frozen=True)
class Cursor:
    at: datetime
    id: str


def encode_cursor(row: NotificationRow) -> str:
    raw = json.dumps({"t": row.created_at.astimezone(UTC).isoformat(), "i": row.id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value: str) -> Cursor:
    """Con trỏ sai bất kỳ kiểu nào → `ValueError` (route đổi thành 422 `query.after`)."""
    try:
        body = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        at, ident = body["t"], body["i"]
        if not isinstance(at, str) or not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident):
            raise ValueError("cursor")
        parsed = datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            raise ValueError("cursor")
        utc = parsed.astimezone(UTC)  # kiểm thử 12/11: "9999-12-31T23:59:59-14:00" tràn khi đổi sang UTC → OverflowError (từng 500)
    except (binascii.Error, KeyError, TypeError, ValueError, UnicodeDecodeError, OverflowError) as exc:
        raise ValueError("cursor") from exc
    return Cursor(utc, ident)


class NotificationSource(Protocol):
    async def page(self, user_id: str, limit: int, after: Cursor | None) -> list[NotificationRow]:
        """Tối đa `limit` dòng của `user_id`, đã sắp (created_at ↓, id ↓ theo "C"), sau con trỏ `after` (loại trừ)."""
        ...


# Điều kiện requester có ĐÚNG hai lần (mỗi nhánh một lần) — test đơn vị đếm chuỗi này, M-TB-1 bỏ nó.
REQUESTER_PREDICATE = "t.requester_id = :user_id"

_UNION = f"""
  SELECT 'appr:' || CAST(a.approval_id AS text) AS id, 'approval_decided' AS kind,
         COALESCE(t.parent_ticket_id, t.ticket_id) AS ticket_id, CAST(a.status AS text) AS result,
         a.decided_at AS created_at, a.note AS note,
         CAST(NULL AS text) AS exit_code, CAST(NULL AS text) AS reason_detail
  FROM approvals a JOIN tickets t ON t.ticket_id = a.ticket_id
  WHERE {REQUESTER_PREDICATE} AND a.status IN ('approved', 'rejected') AND a.decided_at IS NOT NULL
  UNION ALL
  SELECT 'esc:' || CAST(e.escalation_id AS text), 'escalation_closed',
         COALESCE(t.parent_ticket_id, t.ticket_id), CAST(e.close_result AS text),
         e.closed_at, CAST(NULL AS text), CAST(e.exit_code AS text), CAST(e.reason_detail AS text)
  FROM escalations e JOIN tickets t ON t.ticket_id = e.ticket_id
  WHERE {REQUESTER_PREDICATE} AND e.closed_at IS NOT NULL AND e.close_result IS NOT NULL
"""
_ORDER = 'ORDER BY n.created_at DESC, n.id COLLATE "C" DESC LIMIT :n'
FIRST_PAGE_SQL = f"SELECT n.* FROM ({_UNION}) n {_ORDER}"
NEXT_PAGE_SQL = f'SELECT n.* FROM ({_UNION}) n WHERE (n.created_at, n.id COLLATE "C") < (:c_at, :c_id) {_ORDER}'


class SqlNotificationSource:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def page(self, user_id: str, limit: int, after: Cursor | None) -> list[NotificationRow]:
        params: dict[str, object] = {"user_id": user_id, "n": limit}
        if after is None:
            sql = FIRST_PAGE_SQL
        else:
            sql = NEXT_PAGE_SQL
            params |= {"c_at": after.at, "c_id": after.id}
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(sql), params)).mappings().all()
        return [
            NotificationRow(
                r["id"], r["kind"], r["ticket_id"], r["result"], r["created_at"],
                note=r["note"], exit_code=r["exit_code"], reason_detail=r["reason_detail"],
            )
            for r in rows
        ]
