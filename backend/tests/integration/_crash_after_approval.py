"""Tiến trình con cho P1 mục 11 "giết process ngay sau approvals.create, trước checkpoint".

`python _crash_after_approval.py <rw_url> <ticket_id>`: submit ticket; ngay khi `approval_create` đã
commit (phiếu + dòng side_effects nằm trong DB) thì `os._exit` — không finally, không checkpoint của
B15, không thông báo người duyệt. Test cha phục hồi bằng worker.
Đồng hồ giả cùng mốc với test cha để `turns.started_at` khớp.
"""

import asyncio
import os
import sys

from app.core.clock import FakeClock
from tests.integration.graph_pg import SESSION, open_pg_runtime

EXIT_CODE = 17


async def main(rw_url: str, ticket_id: str) -> None:
    async with open_pg_runtime(rw_url, clock=FakeClock()) as rt:
        rt.scenario.on(ticket_id, "after_approval_create", lambda _: os._exit(EXIT_CODE))
        await rt.runner.submit(ticket_id, session_id=SESSION, redacted_request="yêu cầu")
    sys.exit(0)  # không được tới đây


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
