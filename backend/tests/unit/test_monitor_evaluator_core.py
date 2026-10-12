"""M9-B0: `evaluate` — bắt lỗi theo từng luật, nguồn pending, loader, kiểm draft. Không DB: loader giả.
M9-B1: mỗi loader một savepoint (review #12) — kiểm bằng `FakeConn`; bản Postgres thật ở
`tests/integration/test_monitor_evaluator_savepoint_pg.py`.
M9-B2 GĐ1 cụm 3b: nhịp log traceback / Pending (#14 comment 5959974287: Q-M9-B2-9, Q-M9-B2-14 phương án A).

Nguồn: file chia việc M9 mục 3 (hợp đồng `EvalResult`), mục 6 (B0); kế hoạch chung M9 mục 3.3, 4.4.
"""

import asyncio
import dataclasses
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
    reset_log_pacing,
)
from app.monitor.rules import (
    REGISTRY,
    Audience,
    DuplicateRuleError,
    Every,
    RuleContext,
    rule,
)
from sqlalchemy.ext.asyncio import AsyncConnection

NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
CTX = RuleContext(now=NOW, tz=ZoneInfo("Asia/Ho_Chi_Minh"), cap_usd=38.0, warn_ratio=0.8)
AUD: tuple[Audience, ...] = ("dev",)


class FakeConn:
    """Giả `AsyncConnection` vừa đủ cho `evaluate`: chỉ có `begin_nested()`. Ghi lại từng savepoint — mở, đóng bằng
    RELEASE hay ROLLBACK (kèm tên lỗi) — và đang lồng bao nhiêu tầng."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str | None]] = []
        self.depth = 0

    def begin_nested(self) -> "_Savepoint":
        return _Savepoint(self)


class _Savepoint:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        self._conn.depth += 1
        self._conn.events.append(("savepoint", None))

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: object, tb: object) -> bool:
        self._conn.depth -= 1
        self._conn.events.append(("rollback", exc_type.__name__) if exc_type else ("release", None))
        return False  # không nuốt lỗi — evaluate tự bắt theo từng luật


CONN = cast(AsyncConnection, FakeConn())  # evaluate mở savepoint rồi chuyển tiếp cho loader


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    saved_rules, saved_loaders = dict(REGISTRY), dict(LOADERS)
    REGISTRY.clear()
    LOADERS.clear()
    reset_log_pacing()  # nhịp log là trạng thái cấp module — test không thấy lượt của test trước
    yield
    reset_log_pacing()
    REGISTRY.clear()
    REGISTRY.update(saved_rules)
    LOADERS.clear()
    LOADERS.update(saved_loaders)


def _draft(rule_id: str, subject: str = "t-1", window_start: datetime = NOW) -> AlertDraft:
    return AlertDraft(rule_id=rule_id, subject=subject, window_start=window_start, severity="warning")


def _returns(rule_id: str, every: Every, drafts: list[AlertDraft]) -> None:
    """Đăng ký luật + loader: loader trả `None`, luật trả `drafts`."""

    @rule(rule_id, every, audience=AUD)
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
    @rule("A", "minute", audience=AUD)
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


@pytest.mark.asyncio
async def test_each_loader_runs_in_its_own_savepoint() -> None:
    """Review #12: loader A lỗi SQL làm transaction Postgres *aborted* → mọi loader sau cùng `conn` lỗi theo. Mỗi
    loader phải chạy BÊN TRONG savepoint riêng; savepoint của A rollback, của B mở SAU khi A đã đóng."""
    fake = FakeConn()
    depth_seen: dict[str, int] = {}

    @rule("A", "minute", audience=AUD)
    def rule_a(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return [_draft("A")]

    @loader("A")
    async def load_a(conn: AsyncConnection, ctx: RuleContext) -> object:
        depth_seen["A"] = fake.depth
        raise Boom("lỗi SQL giả")

    b = _draft("B")

    @rule("B", "minute", audience=AUD)
    def rule_b(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        assert fake.depth == 0  # hàm luật thuần chạy NGOÀI savepoint
        return [b]

    @loader("B")
    async def load_b(conn: AsyncConnection, ctx: RuleContext) -> object:
        depth_seen["B"] = fake.depth
        return None

    result = await evaluate("minute", cast(AsyncConnection, fake), CTX)
    assert result == EvalResult(drafts=[b], failed_rules=["A"], skipped_rules=[])
    assert fake.events == [("savepoint", None), ("rollback", "Boom"), ("savepoint", None), ("release", None)]
    assert depth_seen == {"A": 1, "B": 1}


@pytest.mark.asyncio
async def test_cancelled_error_propagates_through_savepoint() -> None:
    """X1: hủy job (`CancelledError` là BaseException) phải LAN RA qua savepoint, không bị nuốt thành `failed_rules`
    — `except Exception` trong evaluate. Savepoint của luật bị hủy rollback; luật sau không chạy."""
    fake = FakeConn()
    called: list[str] = []

    @rule("A", "minute", audience=AUD)
    def rule_a(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return []

    @loader("A")
    async def load_a(conn: AsyncConnection, ctx: RuleContext) -> object:
        raise asyncio.CancelledError

    @rule("B", "minute", audience=AUD)
    def rule_b(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return []

    @loader("B")
    async def load_b(conn: AsyncConnection, ctx: RuleContext) -> object:
        called.append("B")
        return None

    with pytest.raises(asyncio.CancelledError):
        await evaluate("minute", cast(AsyncConnection, fake), CTX)
    assert fake.events == [("savepoint", None), ("rollback", "CancelledError")]
    assert called == []


# ---- nguồn pending, thiếu loader -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_source_goes_to_skipped() -> None:
    called: list[str] = []

    @rule("pend", "daily", audience=AUD)
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
    @rule("no_loader", "minute", audience=AUD)
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

    @rule("pass", "hourly", audience=AUD)
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


# ---- nhịp log (#14 comment 5959974287: Q-M9-B2-9 traceback, Q-M9-B2-14 phương án A Pending) -------------------
#
# Mọi kỳ vọng là HẰNG viết tay theo hai bảng nhịp của plan cụm 3b. "Phút" = `ctx.now = NOW + phút`; mỗi lượt một lần
# `evaluate`, chỉ xét log của logger evaluator.

EV_LOGGER = "app.monitor.evaluator"
ERR, INF, DBG = logging.ERROR, logging.INFO, logging.DEBUG
Outcome = type[Exception] | Exception | Pending | None  # lớp/thực thể lỗi → loader ném; Pending; None → chạy được
Log = tuple[int, str, bool]  # (mức, message, có exc_info)


def _scripted(rule_id: str, every: Every = "minute") -> dict[str, Outcome]:
    """Đăng ký luật + loader điều khiển được: gán `script["next"]` trước mỗi lượt. Chạy được → 1 draft."""
    script: dict[str, Outcome] = {"next": None}

    @rule(rule_id, every, audience=AUD)
    def fn(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return [_draft(rule_id)]

    @loader(rule_id)
    async def load(conn: AsyncConnection, ctx: RuleContext) -> object:
        nxt = script["next"]
        if isinstance(nxt, type):
            raise nxt("lỗi giả")
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    return script


def _at(minute: int) -> RuleContext:
    return dataclasses.replace(CTX, now=NOW + timedelta(minutes=minute))


def _take(caplog: pytest.LogCaptureFixture) -> list[Log]:
    out = [(r.levelno, r.getMessage(), r.exc_info is not None) for r in caplog.records if r.name == EV_LOGGER]
    caplog.clear()
    return out


def _expected(rule_id: str, kind: str) -> EvalResult:
    """F = luật lỗi, S = bỏ qua (Pending), D = chạy được, ra 1 draft."""
    return {
        "F": EvalResult(drafts=[], failed_rules=[rule_id], skipped_rules=[]),
        "S": EvalResult(drafts=[], failed_rules=[], skipped_rules=[rule_id]),
        "D": EvalResult(drafts=[_draft(rule_id)], failed_rules=[], skipped_rules=[]),
    }[kind]


async def _run_table(
    rule_id: str, table: list[tuple[int, Outcome, str, list[Log]]], caplog: pytest.LogCaptureFixture
) -> None:  # fmt: skip
    script = _scripted(rule_id)
    for step, (minute, outcome, kind, logs) in enumerate(table, start=1):
        script["next"] = outcome
        result = await evaluate("minute", CONN, _at(minute))
        assert result == _expected(rule_id, kind), f"lượt {step}"
        assert _take(caplog) == logs, f"lượt {step}"


X_TB = "luật X lỗi"  # dòng traceback — giữ nguyên chữ cũ (integration savepoint_pg ghim)

# Bảng nhịp (a): (phút, kết cục, F/S/D, log mong đợi)
TRACEBACK_TABLE: list[tuple[int, Outcome, str, list[Log]]] = [
    (0, Boom, "F", [(ERR, X_TB, True)]),  # 1 lần đầu
    (1, Boom, "F", [(DBG, "luật X lỗi: Boom", False)]),  # 2 cùng lớp, < 1 giờ
    (59, Boom, "F", [(DBG, "luật X lỗi: Boom", False)]),  # 3 59 phút — sát ngưỡng, chưa đủ
    (60, Boom, "F", [(ERR, X_TB, True)]),  # 4 đúng bằng 1 giờ
    (61, Boom, "F", [(DBG, "luật X lỗi: Boom", False)]),  # 5 mốc mới là phút 60
    (62, KeyError, "F", [(ERR, X_TB, True)]),  # 6 lớp đổi
    (63, KeyError, "F", [(DBG, "luật X lỗi: KeyError", False)]),  # 7 cùng lớp
    (64, None, "D", []),  # 8 chạy được → bỏ khoá
    (65, KeyError, "F", [(ERR, X_TB, True)]),  # 9 lỗi quay lại sau lượt chạy được
    (66, Pending("r"), "S", [(INF, "luật X bỏ qua: nguồn chưa có (r)", False)]),  # 10 Pending → bỏ khoá lỗi
    (67, KeyError, "F", [(ERR, X_TB, True)]),  # 11 lỗi quay lại sau Pending
]

P_A = "luật P bỏ qua: nguồn chưa có (a)"
P_B = "luật P bỏ qua: nguồn chưa có (b)"

# Bảng nhịp (b)
PENDING_TABLE: list[tuple[int, Outcome, str, list[Log]]] = [
    (0, Pending("a"), "S", [(INF, P_A, False)]),  # 1 lần đầu
    (1, Pending("a"), "S", [(DBG, P_A, False)]),  # 2 cùng lý do
    (120, Pending("a"), "S", [(DBG, P_A, False)]),  # 3 qua 2 giờ — KHÔNG nhắc mỗi giờ
    (121, Pending("b"), "S", [(INF, P_B, False)]),  # 4 lý do đổi
    (122, Pending("b"), "S", [(DBG, P_B, False)]),  # 5 cùng lý do mới
    (123, None, "D", []),  # 6 chạy được → bỏ khoá
    (124, Pending("b"), "S", [(INF, P_B, False)]),  # 7 Pending quay lại sau lượt chạy được
    (125, Boom, "F", [(ERR, "luật P lỗi", True)]),  # 8 lỗi → bỏ khoá Pending; traceback lần đầu
    (126, Pending("b"), "S", [(INF, P_B, False)]),  # 9 Pending quay lại sau lỗi
]


@pytest.mark.asyncio
async def test_traceback_pacing_table(caplog: pytest.LogCaptureFixture) -> None:
    """Q-M9-B2-9: traceback lần đầu, khi lớp lỗi đổi, mỗi giờ theo `ctx.now`; còn lại 1 dòng DEBUG tên lớp."""
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)
    await _run_table("X", TRACEBACK_TABLE, caplog)


@pytest.mark.asyncio
async def test_pending_pacing_table(caplog: pytest.LogCaptureFixture) -> None:
    """Q-M9-B2-14 phương án A: Pending INFO lần đầu và khi lý do đổi, còn lại DEBUG.
    Chữ "nguồn chưa có" (luật cứng 7)."""
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)
    await _run_table("P", PENDING_TABLE, caplog)


@pytest.mark.asyncio
async def test_two_rules_same_error_two_tracebacks(caplog: pytest.LogCaptureFixture) -> None:
    """Khoá theo rule_id: hai luật cùng lớp lỗi trong cùng lượt → hai traceback."""
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)
    _scripted("X")["next"] = Boom
    _scripted("Y")["next"] = Boom
    result = await evaluate("minute", CONN, _at(0))
    assert result.failed_rules == ["X", "Y"]
    assert _take(caplog) == [(ERR, "luật X lỗi", True), (ERR, "luật Y lỗi", True)]
    await evaluate("minute", CONN, _at(1))
    assert _take(caplog) == [(DBG, "luật X lỗi: Boom", False), (DBG, "luật Y lỗi: Boom", False)]


@pytest.mark.asyncio
async def test_two_rules_same_pending_reason_two_infos(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)
    _scripted("P")["next"] = Pending("a")
    _scripted("Q")["next"] = Pending("a")
    result = await evaluate("minute", CONN, _at(0))
    assert result.skipped_rules == ["P", "Q"]
    assert _take(caplog) == [(INF, P_A, False), (INF, "luật Q bỏ qua: nguồn chưa có (a)", False)]
    await evaluate("minute", CONN, _at(1))
    assert _take(caplog) == [(DBG, P_A, False), (DBG, "luật Q bỏ qua: nguồn chưa có (a)", False)]


@pytest.mark.asyncio
async def test_repeat_line_has_no_exception_text(caplog: pytest.LogCaptureFixture) -> None:
    """Dòng lặp chỉ tên luật + tên lớp: không `str(exc)`, không traceback. Lượt đầu giữ mức lộ cũ (`exc_info` đúng
    exception đó) — không thêm, không bớt."""
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)
    script = _scripted("X")
    first = Boom("CANARY-du-lieu")
    script["next"] = first
    await evaluate("minute", CONN, _at(0))
    [rec] = [r for r in caplog.records if r.name == EV_LOGGER]
    assert (rec.levelno, rec.getMessage()) == (ERR, "luật X lỗi")
    assert rec.exc_info is not None and rec.exc_info[1] is first
    caplog.clear()
    script["next"] = Boom("CANARY-du-lieu")
    await evaluate("minute", CONN, _at(1))
    [rec] = [r for r in caplog.records if r.name == EV_LOGGER]
    assert (rec.levelno, rec.getMessage(), rec.exc_info) == (DBG, "luật X lỗi: Boom", None)
    assert "CANARY" not in caplog.text


@pytest.mark.asyncio
async def test_reset_log_pacing(caplog: pytest.LogCaptureFixture) -> None:
    """Chốt Q-M9-B2-9: trạng thái giãn nhịp đặt lại được — sau `reset_log_pacing()` cùng lỗi / cùng lý do báo lại."""
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)
    _scripted("X")["next"] = Boom
    _scripted("P")["next"] = Pending("a")
    await evaluate("minute", CONN, _at(0))
    assert _take(caplog) == [(ERR, "luật X lỗi", True), (INF, P_A, False)]
    await evaluate("minute", CONN, _at(0))
    assert _take(caplog) == [(DBG, "luật X lỗi: Boom", False), (DBG, P_A, False)]
    reset_log_pacing()
    await evaluate("minute", CONN, _at(0))
    assert _take(caplog) == [(ERR, "luật X lỗi", True), (INF, P_A, False)]


@pytest.mark.asyncio
async def test_pacing_isolated_per_every(caplog: pytest.LogCaptureFixture) -> None:
    """Job giờ chạy giữa hai lượt job phút không xoá khoá của luật phút (chỉ sửa khoá của luật vừa chạy)."""
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)
    _scripted("X")["next"] = Boom
    _scripted("H", "hourly")["next"] = None
    await evaluate("minute", CONN, _at(0))
    assert _take(caplog) == [(ERR, "luật X lỗi", True)]
    assert await evaluate("hourly", CONN, _at(1)) == _expected("H", "D")
    assert _take(caplog) == []
    await evaluate("minute", CONN, _at(2))
    assert _take(caplog) == [(DBG, "luật X lỗi: Boom", False)]


@pytest.mark.asyncio
async def test_missing_loader_paced_like_failure(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=EV_LOGGER)

    @rule("N", "minute", audience=AUD)
    def fn(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return []

    await evaluate("minute", CONN, _at(0))
    assert _take(caplog) == [(ERR, "luật N lỗi", True)]
    result = await evaluate("minute", CONN, _at(1))
    assert result.failed_rules == ["N"]
    assert _take(caplog) == [(DBG, "luật N lỗi: MissingLoaderError", False)]
