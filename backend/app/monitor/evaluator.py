"""Chạy các luật đến hạn (P9 mục 6, kế hoạch chung M9 mục 3.3) → `EvalResult`; KHÔNG ghi.

Dữ liệu của mỗi luật đi qua loader đăng ký theo `rule_id` (`@loader`, B1/B2 viết ở `queries/rules_data.py`,
chỉ SELECT qua engine monitor). Ghi cảnh báo là việc của worker (`audit.AlertWriter.raise_once`), không phải
của `app.monitor` [Chốt 17.9.2].

Bắt lỗi THEO TỪNG LUẬT: một luật (hoặc loader của nó) ném lỗi → vào `failed_rules`, luật khác vẫn chạy —
một luật hỏng không được làm mất cảnh báo của cả job (ưu tiên không bỏ sót). Luật thiếu loader cũng tính là
lỗi, không lặng lẽ bỏ qua. Draft của một luật chỉ được nhận khi CẢ luật chạy xong và qua `_check`.
"""

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
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
            data = await load(conn, ctx)
            if isinstance(data, Pending):
                log.info("luật %s bỏ qua: nguồn pending (%s)", spec.rule_id, data.reason)
                skipped.append(spec.rule_id)
                continue
            out = spec.fn(data, ctx)
            _check(spec.rule_id, out)
        except Exception:  # CancelledError là BaseException → vẫn lan ra, hủy job không bị nuốt
            log.exception("luật %s lỗi", spec.rule_id)  # chỉ tên luật, không log dữ liệu
            failed.append(spec.rule_id)
            continue
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
