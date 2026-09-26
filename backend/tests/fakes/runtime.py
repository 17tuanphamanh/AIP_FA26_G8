"""`no_runtime`: factory runtime luôn lỗi — `create_app(runtime=no_runtime)` lên với `"runtime": "down"`,
route ticket/duyệt 503, và KHÔNG mở pool Postgres thật (test auth, health không cần graph)."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from app.graph.wiring import Runtime


def no_runtime(*_: Any) -> AbstractAsyncContextManager[Runtime]:
    @asynccontextmanager
    async def fail() -> AsyncIterator[Runtime]:
        raise RuntimeError("không có runtime trong test này")
        yield  # pragma: no cover

    return fail()
