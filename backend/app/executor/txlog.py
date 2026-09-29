"""`transaction_log` (bảng có từ 0001; P7) — lớp truy cập của B17 (phase3 11.4 bước 4). Không thêm bảng, không thêm trạng thái.

- `begin`: INSERT `begun` (`step_name` = tên tool) trong transaction RIÊNG, commit NGAY — TRƯỚC khi gọi tool ghi. Không đi qua
  `effects.once`/`current_tx()`: dòng này phải còn lại kể cả khi process chết ngay sau lời gọi ghi (đó là bằng chứng duy nhất).
- `has_begun(ticket_id)`: ticket đã có dòng `begun` ở BẤT KỲ lượt nào (chốt DỪNG 2, NGHI-2 — mỗi ticket tới B17 tối đa một lần,
  không nhánh nào quay lại B17 sau khi đã ghi). B17 hỏi TRƯỚC mọi bước kiểm lại; executor hỏi lại trước `begin` → E7, 0 ghi.
- Hoàn tác thành công → `undone`; thất bại → `undo_failed` + `detail` (chỉ mã lỗi thuộc tập đóng — P6).
"""

from typing import Protocol

from sqlalchemy import Table, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import Clock
from app.db.models import TransactionLogEntry

_TABLE: Table = TransactionLogEntry.__table__  # type: ignore[assignment]


class TxLog(Protocol):
    async def has_begun(self, ticket_id: str) -> bool: ...
    async def begin(self, ticket_id: str, turn_id: str, step_name: str) -> None: ...
    async def undone(self, ticket_id: str, turn_id: str, step_name: str) -> None: ...
    async def undo_failed(self, ticket_id: str, turn_id: str, step_name: str, detail: str) -> None: ...


class SqlTxLog:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def has_begun(self, ticket_id: str) -> bool:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(_TABLE.c.log_id).where(_TABLE.c.ticket_id == ticket_id, _TABLE.c.status == "begun").limit(1)
                )
            ).first()
        return row is not None

    async def _insert(self, ticket_id: str, turn_id: str, step_name: str, status: str, detail: str | None) -> None:
        async with self._engine.begin() as conn:  # transaction riêng, commit khi ra khỏi khối
            await conn.execute(
                insert(_TABLE).values(
                    ticket_id=ticket_id, turn_id=turn_id, step_name=step_name, status=status, detail=detail,
                    created_at=self._clock.now(),
                )
            )

    async def begin(self, ticket_id: str, turn_id: str, step_name: str) -> None:
        await self._insert(ticket_id, turn_id, step_name, "begun", None)

    async def undone(self, ticket_id: str, turn_id: str, step_name: str) -> None:
        await self._insert(ticket_id, turn_id, step_name, "undone", None)

    async def undo_failed(self, ticket_id: str, turn_id: str, step_name: str, detail: str) -> None:
        await self._insert(ticket_id, turn_id, step_name, "undo_failed", detail)
