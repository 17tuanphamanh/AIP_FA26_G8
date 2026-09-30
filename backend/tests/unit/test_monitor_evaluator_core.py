"""M9-B0: `evaluate` — bắt lỗi theo từng luật, nguồn pending, loader, kiểm draft. Không DB: loader giả.

Nguồn: file chia việc M9 mục 3 (hợp đồng `EvalResult`), mục 6 (B0); kế hoạch chung M9 mục 3.3, 4.4.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from app.domain.alerts import AlertDraft
from app.monitor.evaluator import (
    LOADERS,
    EvalResult,
    Pending,
    evaluate,
    loader,
)
from app.monitor.rules import REGISTRY, DuplicateRuleError, Every, RuleContext, rule
from sqlalchemy.ext.asyncio import AsyncConnection

NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
CTX = RuleContext(now=NOW, tz=ZoneInfo("Asia/Ho_Chi_Minh"), cap_usd=38.0, warn_ratio=0.8)
CONN = cast(AsyncConnection, object())  # sentinel: evaluate chỉ chuyển tiếp cho loader, không dùng


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


def _draft(rule_id: str, subject: str = "t-1", window_start: datetime = NOW) -> AlertDraft:
    return AlertDraft(rule_id=rule_id, subject=subject, window_start=window_start, severity="warning")


def _returns(rule_id: str, every: Every, drafts: list[AlertDraft]) -> None:
    """Đăng ký luật + loader: loader trả `None`, luật trả `drafts`."""

    @rule(rule_id, every)
    def fn(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return drafts

    @loader(rule_id)
    async def load(conn: AsyncConnection, ctx: RuleContext) -> object:
        return None


class Boom(RuntimeError):
    pass


# ---- một luật lỗi không chặn luật khác -----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["loader", "rule"])
async def test_failing_rule_does_not_block_others(where: str) -> None:
    @rule("A", "minute")
    def rule_a(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        raise Boom("luật A hỏng")

    @loader("A")
    async def load_a(conn: AsyncConnection, ctx: RuleContext) -> object:
        if where == "loader":
            raise Boom("loader A hỏng")
        return None

    b = _draft("B")
    _returns("B", "minute", [b])

    result = await evaluate("minute", CONN, CTX)
    assert result == EvalResult(drafts=[b], failed_rules=["A"], skipped_rules=[])


@pytest.mark.asyncio
async def test_failed_rule_contributes_no_partial_drafts() -> None:
    """Luật trả 1 draft đúng + 1 draft mang rule_id khác → cả luật lỗi, không nhận draft nửa chừng."""
    _returns("half", "minute", [_draft("half"), _draft("other_id")])
    result = await evaluate("minute", CONN, CTX)
    assert result.drafts == []
    assert result.failed_rules == ["half"]


@pytest.mark.asyncio
async def test_draft_checks_naive_window_and_long_subject() -> None:
    _returns("naive", "minute", [_draft("naive", window_start=datetime(2026, 9, 30, 8, 0))])  # noqa: DTZ001 — cố ý naive
    _returns("long", "minute", [_draft("long", subject="x" * 65)])
    _returns("ok64", "minute", [_draft("ok64", subject="x" * 64)])
    result = await evaluate("minute", CONN, CTX)
    assert result.failed_rules == ["naive", "long"]
    assert [d.rule_id for d in result.drafts] == ["ok64"]


# ---- nguồn pending, thiếu loader -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_source_goes_to_skipped() -> None:
    called: list[str] = []

    @rule("pend", "daily")
    def fn(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        called.append("pend")
        return [_draft("pend")]

    @loader("pend")
    async def load(conn: AsyncConnection, ctx: RuleContext) -> object:
        return Pending("cascade_not_enabled")

    result = await evaluate("daily", CONN, CTX)
    assert result == EvalResult(drafts=[], failed_rules=[], skipped_rules=["pend"])
    assert called == []  # hàm luật không được gọi khi nguồn pending


@pytest.mark.asyncio
async def test_missing_loader_is_failed_not_silent() -> None:
    @rule("no_loader", "minute")
    def fn(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return [_draft("no_loader")]

    _returns("with_loader", "minute", [_draft("with_loader")])
    result = await evaluate("minute", CONN, CTX)
    assert result.failed_rules == ["no_loader"]
    assert [d.rule_id for d in result.drafts] == ["with_loader"]


# ---- chọn luật theo chu kỳ, truyền tham số -------------------------------------------------------


@pytest.mark.asyncio
async def test_only_rules_of_requested_every_run() -> None:
    _returns("m1", "minute", [_draft("m1")])
    _returns("d1", "daily", [_draft("d1")])
    _returns("m2", "minute", [_draft("m2")])
    minute = await evaluate("minute", CONN, CTX)
    assert [d.rule_id for d in minute.drafts] == ["m1", "m2"]  # đúng thứ tự đăng ký
    daily = await evaluate("daily", CONN, CTX)
    assert [d.rule_id for d in daily.drafts] == ["d1"]
    assert await evaluate("weekly", CONN, CTX) == EvalResult(drafts=[], failed_rules=[], skipped_rules=[])


@pytest.mark.asyncio
async def test_conn_and_ctx_passed_through() -> None:
    seen: dict[str, object] = {}
    payload = object()

    @rule("pass", "hourly")
    def fn(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        seen["data"], seen["rule_ctx"] = data, ctx
        return []

    @loader("pass")
    async def load(conn: AsyncConnection, ctx: RuleContext) -> object:
        seen["conn"], seen["load_ctx"] = conn, ctx
        return payload

    await evaluate("hourly", CONN, CTX)
    assert seen["conn"] is CONN
    assert seen["load_ctx"] is CTX and seen["rule_ctx"] is CTX
    assert seen["data"] is payload


# ---- đăng ký loader ------------------------------------------------------------------------------


def test_duplicate_loader_and_sync_loader_rejected() -> None:
    async def load(conn: AsyncConnection, ctx: RuleContext) -> object:
        return None

    loader("dup")(load)
    with pytest.raises(DuplicateRuleError):
        loader("dup")(load)

    def sync_load(conn: AsyncConnection, ctx: RuleContext) -> object:
        return None

    with pytest.raises(TypeError):
        loader("sync")(sync_load)  # type: ignore[type-var]
    assert list(LOADERS) == ["dup"]
