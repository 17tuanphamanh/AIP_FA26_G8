"""Tiến trình con cho 2b-3 chốt (g): "giết process thật giữa commit INSERT và submit".

`python _crash_after_ticket_create.py <rw_url> <ticket_id> <turn_id>`: ghi `tickets` + lượt `submit`
bằng CHÍNH `SqlTicketStore.create` của API (một transaction, đã commit) rồi `os._exit` — task nền
`run_new` chưa từng chạy, chưa có checkpoint nào. Test cha phục hồi bằng worker.
Đồng hồ giả cùng mốc với test cha để `turns.started_at` khớp.
"""

import asyncio
import os
import sys

from app.core.clock import FakeClock
from app.db.tickets import NewTicket, SqlTicketStore
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration.graph_pg import REQUESTER, SESSION

EXIT_CODE = 19


async def main(rw_url: str, ticket_id: str, turn_id: str) -> None:
    engine = create_async_engine(rw_url)
    await SqlTicketStore(engine).create(
        NewTicket(ticket_id=ticket_id, requester_id=REQUESTER, requester_role="employee",
                  requester_dept="it", session_id=SESSION, redacted_request="VPN lỗi",
                  created_at=FakeClock().now()),
        turn_id=turn_id,
    )  # fmt: skip
    os._exit(EXIT_CODE)  # ngay sau commit: không run_new, không dispose


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
    sys.exit(0)  # không được tới đây
