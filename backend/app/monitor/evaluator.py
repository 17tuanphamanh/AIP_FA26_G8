"""Chạy các luật đến hạn (P9 mục 6, kế hoạch chung M9 mục 3.3) → `EvalResult`; KHÔNG ghi.

Dữ liệu của mỗi luật đi qua loader đăng ký theo `rule_id` (`@loader`, B1/B2 viết ở `queries/rules_data.py`,
chỉ SELECT qua engine monitor). Ghi cảnh báo là việc của worker (`audit.AlertWriter.raise_once`), không phải
của `app.monitor` [Chốt 17.9.2].

Bắt lỗi THEO TỪNG LUẬT: một luật (hoặc loader của nó) ném lỗi → vào `failed_rules`, luật khác vẫn chạy —
một luật hỏng không được làm mất cảnh báo của cả job (ưu tiên không bỏ sót). Luật thiếu loader cũng tính là
lỗi, không lặng lẽ bỏ qua. Draft của một luật chỉ được nhận khi CẢ luật chạy xong và qua `_check`.

SAVEPOINT THEO TỪNG LUẬT (review B0 ở #12): mọi loader dùng chung một `conn`; trên Postgres một câu SELECT lỗi đưa
cả transaction vào trạng thái *aborted* → mọi loader sau trên cùng `conn` cũng lỗi → mất cảnh báo cả job (FN). Mỗi
loader chạy trong `conn.begin_nested()`: lỗi chỉ ROLLBACK TO SAVEPOINT của luật đó, `conn` dùng tiếp được. Chưa có
transaction ngoài thì SQLAlchemy 2.x tự autobegin nó trước khi tạo SAVEPOINT (`Connection.begin_nested`) — worker chỉ
cần `engine.connect()`; đóng connection là rollback (M9 chỉ đọc). Hàm luật thuần chạy NGOÀI savepoint.

Message của exception (in nguyên traceback ở `log.exception`) chỉ mang tên luật/hằng, không mang dữ liệu đọc từ DB
(review #12 mục 3) — test AST `test_monitor_rules_event.py::test_error_messages_carry_no_data`.

NHỊP LOG THEO TỪNG LUẬT (#14, comment 5959974287): luật lỗi in traceback lần đầu, khi lớp lỗi đổi và mỗi giờ theo
`ctx.now` (Q-M9-B2-9); các lượt còn lại 1 dòng DEBUG tên lớp — worker đã báo WARNING "luật lỗi" theo nhịp IncidentLog.
Luật Pending in INFO lần đầu và khi lý do đổi, còn lại DEBUG (Q-M9-B2-14 phương án A). Luật chạy được → bỏ khoá: lỗi
hay Pending quay lại thì báo ngay (nghiêng về báo thừa). Trạng thái ở cấp module (giữ chữ ký `evaluate`), đặt lại
bằng `reset_log_pacing()`; mất khi worker khởi động lại → in lại một lần (Q-M9-B2-19). Đồng hồ lùi không có nhánh
riêng, giống IncidentLog (Q-M9-B2-18).
"""

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.alerts import SUBJECT_MAX, AlertDraft
from app.monitor.rules import REGISTRY, DuplicateRuleError, Every, RuleContext

log = logging.getLogger(__name__)


class Loader(Protocol):
    async def __call__(self, conn: AsyncConnection, ctx: RuleContext) -> object:
        """Đọc dữ liệu cho MỘT luật: chỉ SELECT trên `conn` (engine monitor), trả dataclass thuần mà hàm luật
        nhận làm `data`. Lookback do luật quyết (luật theo sự kiện quét lại 24 giờ, kế hoạch chung 4.4).
        Nguồn chưa có node ghi → trả `Pending(reason)`, không trả dữ liệu rỗng (rỗng = "đã đo, không có ca")."""
        ...


@dataclass(frozen=True)
class Pending:
    reason: str  # vd "cascade_not_enabled" (Q-M9-9) — ghi log, luật vào skipped_rules


@dataclass(frozen=True)
class EvalResult:
    drafts: list[AlertDraft]
    failed_rules: list[str]  # luật ném lỗi — log tên, không chặn luật khác
    skipped_rules: list[str]  # luật có nguồn pending


LOADERS: dict[str, Loader] = {}

TRACEBACK_EVERY = timedelta(hours=1)  # Q-M9-B2-9 — cùng nhịp IncidentLog của worker (MONITOR_REMIND_EVERY)
# Khoá theo rule_id → tối đa một mục mỗi luật. Mỗi lượt chỉ sửa khoá của luật VỪA chạy (không thay cả dict): job
# phút/giờ/ngày dùng chung trạng thái nhưng tập luật của chúng tách rời.
_failing: dict[str, tuple[str, datetime]] = {}  # rule_id → (tên lớp lỗi, ctx.now lần in traceback gần nhất)
_pending: dict[str, str] = {}  # rule_id → lý do Pending đã in INFO


def reset_log_pacing() -> None:
    """Đặt lại nhịp log (chốt Q-M9-B2-9: "trạng thái giãn nhịp phải đặt lại được trong test")."""
    _failing.clear()
    _pending.clear()


def loader[L: Loader](rule_id: str) -> Callable[[L], L]:
    """Đăng ký loader cho luật `rule_id`; trả nguyên hàm. Trùng id / hàm không async → lỗi lúc import."""

    def register(fn: L) -> L:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"loader {rule_id}: phải là async def")
        if rule_id in LOADERS:
            raise DuplicateRuleError(f"loader {rule_id} đăng ký hai lần")
        LOADERS[rule_id] = fn
        return fn

    return register


class MissingLoaderError(LookupError):
    """Luật đã đăng ký mà chưa có loader (quên import `rules_data`?)."""


async def evaluate(every: Every, conn: AsyncConnection, ctx: RuleContext) -> EvalResult:
    drafts: list[AlertDraft] = []
    failed: list[str] = []
    skipped: list[str] = []
    for spec in [s for s in REGISTRY.values() if s.every == every]:
        try:
            load = LOADERS.get(spec.rule_id)
            if load is None:
                raise MissingLoaderError(spec.rule_id)
            async with conn.begin_nested():  # một luật một savepoint — lỗi SQL không làm hỏng luật sau
                data = await load(conn, ctx)
            if isinstance(data, Pending):
                level = logging.DEBUG if _pending.get(spec.rule_id) == data.reason else logging.INFO
                log.log(level, "luật %s bỏ qua: nguồn chưa có (%s)", spec.rule_id, data.reason)
                _pending[spec.rule_id] = data.reason
                _failing.pop(spec.rule_id, None)  # loader chạy được → luật không lỗi
                skipped.append(spec.rule_id)
                continue
            out = spec.fn(data, ctx)
            _check(spec.rule_id, out)
        except Exception as exc:  # CancelledError là BaseException → vẫn lan ra, hủy job không bị nuốt
            name = type(exc).__name__
            prev = _failing.get(spec.rule_id)
            if prev is None or prev[0] != name or ctx.now - prev[1] >= TRACEBACK_EVERY:
                _failing[spec.rule_id] = (name, ctx.now)
                log.exception("luật %s lỗi", spec.rule_id)  # chỉ tên luật, không log dữ liệu
            else:
                log.debug("luật %s lỗi: %s", spec.rule_id, name)  # không traceback, không str(exc)
            _pending.pop(spec.rule_id, None)
            failed.append(spec.rule_id)
            continue
        _failing.pop(spec.rule_id, None)
        _pending.pop(spec.rule_id, None)
        drafts.extend(out)
    return EvalResult(drafts=drafts, failed_rules=failed, skipped_rules=skipped)


def _check(rule_id: str, out: object) -> None:
    """Lỗi lập trình của luật phải lộ ra ở `failed_rules`, không để hỏng lúc worker INSERT `alerts`."""
    if not isinstance(out, list):
        raise TypeError(f"luật {rule_id} phải trả list[AlertDraft]")
    for d in out:
        if not isinstance(d, AlertDraft):
            raise TypeError(f"luật {rule_id} trả phần tử không phải AlertDraft")
        if d.rule_id != rule_id:
            raise ValueError(f"luật {rule_id} trả draft mang rule_id khác")
        if d.window_start.tzinfo is None:
            raise ValueError(f"luật {rule_id}: window_start thiếu múi giờ")
        if len(d.subject) > SUBJECT_MAX:
            raise ValueError(f"luật {rule_id}: subject dài hơn {SUBJECT_MAX}")
