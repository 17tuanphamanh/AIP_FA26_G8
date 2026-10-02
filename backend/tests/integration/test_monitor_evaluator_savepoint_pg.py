"""M9-B1 GĐ1 — savepoint theo từng luật trên Postgres thật (review B0 ở #12, tiêu chí đạt bắt buộc).

Trên Postgres, một câu SELECT lỗi đưa cả transaction vào trạng thái *aborted*: mọi câu sau trên cùng connection
đều lỗi `InFailedSqlTransaction` → nếu không có savepoint, một loader hỏng làm mất cảnh báo của cả job (FN).
Chạy bằng role `app_monitor` như worker thật. Bỏ `begin_nested` trong `evaluate` → test này đỏ (`failed_rules`
thành `["A", "B"]`).
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from app.domain.alerts import AlertDraft
from app.monitor.evaluator import LOADERS, evaluate, loader
from app.monitor.rules import REGISTRY, RuleContext, rule
from app.monitor.window import VN_TZ
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from tests.integration.pg import PgUrls

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
CTX = RuleContext(now=NOW, tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    saved_rules, saved_loaders = dict(REGISTRY), dict(LOADERS)
    REGISTRY.clear()
    LOADERS.clear()
    yield
    REGISTRY.clear()
    REGISTRY.update(saved_rules)
    LOADERS.clear()
    LOADERS.update(saved_loaders)


def _register_a_fails_then_b() -> None:
    """A (đăng ký trước, chạy trước) đọc bảng không tồn tại → lỗi SQL thật; B đọc `alerts` rồi ra một draft."""

    @rule("A", "minute", audience=("dev",))
    def rule_a(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return [AlertDraft(rule_id="A", subject="", window_start=NOW, severity="warning")]

    @loader("A")
    async def load_a(conn: AsyncConnection, ctx: RuleContext) -> object:
        await conn.execute(text("SELECT * FROM bang_khong_ton_tai"))
        return None

    @rule("B", "minute", audience=("dev",))
    def rule_b(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return [AlertDraft(rule_id="B", subject="", window_start=NOW, severity="warning", value=data)]

    @loader("B")
    async def load_b(conn: AsyncConnection, ctx: RuleContext) -> object:
        return (await conn.execute(text("SELECT count(*) FROM alerts"))).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize("outer", ["autobegin", "explicit_begin"])
async def test_sql_error_in_one_loader_does_not_abort_others(
    migrated: PgUrls, outer: str, caplog: pytest.LogCaptureFixture
) -> None:
    _register_a_fails_then_b()
    engine = create_async_engine(migrated.role("app_monitor"))
    try:
        async with engine.connect() as conn:
            if outer == "explicit_begin":  # transaction ngoài có sẵn → savepoint lồng bên trong
                async with conn.begin():
                    result = await evaluate("minute", conn, CTX)
            else:  # worker chỉ `connect()` — SQLAlchemy tự autobegin transaction ngoài
                result = await evaluate("minute", conn, CTX)
            # sau job, connection vẫn dùng được (không kẹt ở trạng thái aborted)
            assert (await conn.execute(text("SELECT current_user"))).scalar_one() == "app_monitor"
    finally:
        await engine.dispose()

    assert result.failed_rules == ["A"]
    assert [d.rule_id for d in result.drafts] == ["B"]
    assert result.skipped_rules == []
    failed_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in failed_logs] == ["luật A lỗi"]  # chỉ tên luật
    assert failed_logs[0].exc_info is not None
    assert "bang_khong_ton_tai" in str(failed_logs[0].exc_info[1])  # đúng lỗi SQL thật, không phải lỗi giả
