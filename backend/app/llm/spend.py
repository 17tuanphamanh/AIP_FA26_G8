"""Trần chi tiêu (P2 mục 5, N1; PLAN-3d Q-3d-14, S9).

`SUM(llm_calls.cost_usd)` đọc lại mỗi `refresh_s` giây; giữa hai lần đọc, chi phí mỗi lời gọi được CỘNG DỒN ngay vào
bộ đệm (không đợi lần đọc sau mới thấy). Chỉ áp cho đích trả phí (giá > 0): `over` → bỏ đích; đọc tổng lỗi →
`unknown` → bỏ đích (fail-closed, gateway ném `LLMUnavailable` nếu không còn đích nào). ≥ `warn_ratio` → log cảnh báo
(cảnh báo M9 luật 14 làm ở P9).

Giữ chỗ (S9): trước MỖI request tới đích trả phí (kể cả lần thử lại, lần sửa schema), gateway giữ chỗ bằng chi phí xấu
nhất ước tính (`Price.cost(token vào ước tính, max_tokens)`); đã chi + đang giữ + phần mới > trần → từ chối, không
gửi. Nhờ vậy N lời gọi song song gần trần không cùng lọt qua một lần kiểm. Chỗ được nhả khi request kết thúc (dù lỗi).
Token vào là ƯỚC TÍNH (ceil(ký tự/3), Q-3d-8) — provider báo nhiều hơn thì một request có thể vượt phần giữ chỗ;
phần vượt tối đa = sai số ước tính của các request đang bay.

Lần đọc tổng không làm mất chi phí: chi phí phát sinh nhưng dòng `llm_calls` chưa ghi xong lúc BẮT ĐẦU đọc được cộng
thêm (có thể đếm hai lần nếu dòng ghi xong trong lúc đọc — lệch về phía an toàn, lần đọc sau tự khớp); chi phí phát
sinh sau lúc bắt đầu đọc được cộng dồn như thường. Dòng ghi hỏng (`recorded` không được gọi) được tính mãi trong
process này.
"""

import logging
from datetime import datetime
from typing import Literal

from app.core.clock import Clock
from app.llm.config import SpendCfg
from app.llm.ports import LlmStore

log = logging.getLogger(__name__)

type SpendStatus = Literal["ok", "over", "unknown"]


class SpendTracker:
    def __init__(self, cfg: SpendCfg, store: LlmStore, clock: Clock) -> None:
        self._cfg = cfg
        self._store = store
        self._clock = clock
        self._base: float | None = None  # SUM đọc được + chi phí chưa ghi lúc bắt đầu đọc
        self._mark = 0.0  # `_added` lúc bắt đầu lần đọc đó
        self._added = 0.0  # tổng chi phí process này đã cộng (tăng đơn điệu)
        self._unrecorded = 0.0  # đã phát sinh, dòng llm_calls chưa ghi xong
        self._reserved = 0.0  # giữ chỗ của các request trả phí đang bay
        self._read_at: datetime | None = None

    def _spent(self) -> float:
        assert self._base is not None
        return self._base + (self._added - self._mark)

    async def check(self) -> SpendStatus:
        now = self._clock.now()
        stale = self._read_at is None or (now - self._read_at).total_seconds() >= self._cfg.refresh_s
        if stale:
            mark, unrecorded = self._added, self._unrecorded
            try:
                total = await self._store.spend_total()
            except Exception as e:  # noqa: BLE001 — DB lỗi: không biết đã chi bao nhiêu → không chi thêm
                log.warning("không đọc được tổng chi LLM (%s) — chặn đích trả phí", type(e).__name__)
                return "unknown"
            self._base, self._mark, self._read_at = total + unrecorded, mark, now
            if self._spent() >= self._cfg.cap_usd * self._cfg.warn_ratio:
                log.warning("chi LLM %.4f USD ≥ %.0f%% trần %.2f USD", self._spent(), self._cfg.warn_ratio * 100,
                            self._cfg.cap_usd)  # fmt: skip
        return "over" if self._spent() + self._reserved >= self._cfg.cap_usd else "ok"

    def reserve(self, amount: float) -> bool:
        """Giữ chỗ cho một request trả phí. Đồng bộ (không `await`) → không lời gọi song song nào chen giữa lúc kiểm
        và lúc cộng. Chưa từng đọc được tổng → từ chối (fail-closed)."""
        if self._base is None or self._spent() + self._reserved + amount > self._cfg.cap_usd:
            return False
        self._reserved += amount
        return True

    def release(self, amount: float) -> None:
        self._reserved -= amount

    def add(self, cost_usd: float) -> None:
        self._added += cost_usd
        self._unrecorded += cost_usd

    def recorded(self, cost_usd: float) -> None:
        """Dòng `llm_calls` mang chi phí này đã ghi xong — từ lần đọc sau, SUM đã chứa nó."""
        self._unrecorded -= cost_usd
