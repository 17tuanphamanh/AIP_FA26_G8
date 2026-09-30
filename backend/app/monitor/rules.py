"""Khung luật cảnh báo M9 (P9 mục 6) — đăng ký luật và tiện ích thuần; KHÔNG I/O.

Luật là hàm thuần `(data, ctx) -> list[AlertDraft]`: `data` do loader (`evaluator.loader`, chỉ SELECT qua
engine monitor) đọc sẵn; hàm luật không truy vấn, không ghi, không đọc đồng hồ — mốc "bây giờ" duy nhất là
`ctx.now`, worker lấy từ `Clock` của app (một nguồn đồng hồ, chạy lại ra đúng khoá cũ). Hàm `async def` bị từ
chối ngay lúc đăng ký: không có `await` thì không có I/O lọt vào luật.

Đăng ký trùng `rule_id` → `DuplicateRuleError` lúc import: hai luật cùng id ghi chung khoá chống trùng
`(rule_id, subject, window_start)` → cảnh báo của luật này che mất cảnh báo của luật kia (bỏ sót).
"""

import inspect
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, get_args
from zoneinfo import ZoneInfo

from app.domain.alerts import AlertDraft

type Every = Literal["minute", "hourly", "daily", "weekly"]
EVERY_VALUES: tuple[str, ...] = get_args(Every.__value__)

type RuleFn = Callable[[Any, RuleContext], list[AlertDraft]]

HOURS_7D = 168  # trung vị theo giờ của 7 ngày trước giờ đang xét (luật 4, 6)


class DuplicateRuleError(ValueError):
    """Hai luật (hoặc hai loader) cùng id."""


@dataclass(frozen=True)
class RuleContext:
    now: datetime  # từ Clock của app — một nguồn đồng hồ
    tz: ZoneInfo  # VN_TZ (Q-M9-2)
    cap_usd: float  # config/llm.yaml spend.cap_usd — worker đọc, truyền vào
    warn_ratio: float  # spend.warn_ratio

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("RuleContext.now cần datetime có múi giờ")


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    every: Every
    fn: RuleFn


REGISTRY: dict[str, RuleSpec] = {}  # thứ tự đăng ký = thứ tự chạy


def rule[F: RuleFn](rule_id: str, every: Every) -> Callable[[F], F]:
    """Đăng ký luật vào `REGISTRY`; trả nguyên hàm (test gọi thẳng được). Sai → lỗi ngay lúc import."""
    if not rule_id:
        raise ValueError("rule_id rỗng")
    if every not in EVERY_VALUES:
        raise ValueError(f"every không hợp lệ: {every!r}")

    def register(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            raise TypeError(f"luật {rule_id}: hàm luật phải thuần (không async) — I/O đi qua loader")
        if rule_id in REGISTRY:
            raise DuplicateRuleError(f"luật {rule_id} đăng ký hai lần")
        REGISTRY[rule_id] = RuleSpec(rule_id, every, fn)
        return fn

    return register


def hourly_median(counts_168h: Sequence[int]) -> float:
    """Trung vị số ca theo giờ trong 168 giờ; giờ không có ca = 0.

    Nhận số ca của các giờ CÓ ca (SQL `GROUP BY` giờ bỏ qua giờ trống) — tự đệm 0 cho đủ 168 giờ. Truyền đủ
    168 phần tử (có số 0) cũng ra cùng kết quả. Bỏ giờ trống thì trung vị bị đẩy lên → spike thật bị che (FN).
    """
    if len(counts_168h) > HOURS_7D:
        raise ValueError(f"quá {HOURS_7D} giờ: {len(counts_168h)}")
    if any(c < 0 for c in counts_168h):
        raise ValueError("số ca âm")
    return float(statistics.median([*counts_168h, *[0] * (HOURS_7D - len(counts_168h))]))


def spike(count: int, median: float, factor: float = 3, minimum: int = 3) -> bool:
    """`count > factor × median AND count ≥ minimum` (kế hoạch chung mục 6; P9 luật 4).

    Đúng bằng ngưỡng → không báo. `minimum` chặn báo nhiễu khi trung vị = 0 (1 ca đã vượt 3 × 0).
    """
    return count > factor * median and count >= minimum
