"""Circuit breaker theo hệ thống ngoài [Chốt 17.3, P5 mục 6].

Tham số chỉ có một nguồn: `Settings.breaker_*` (giá trị [Chốt] ghi ở P5 mục 6).

- closed → open: `failure_threshold` lỗi liên tiếp trong `window_seconds`.
- open: mọi lời gọi bị từ chối ngay trong `open_seconds` — ticket đi E2 ngay, không mất
  3 giây retry.
- half-open: cho qua đúng 1 lời gọi thử; thành công → đóng, lỗi → mở tiếp.

Một "lỗi" = một lần gọi registry kết thúc bằng lỗi hệ thống **sau retry**, không phải từng HTTP
attempt [Suy luận — P5 không nói rõ]. Trạng thái trong bộ nhớ process, không lưu DB [Chốt]. Mở/đóng
chỉ ghi log (span + metric ở Phase 2, P1 mục 9), KHÔNG ghi security_events — đây là sự cố hạ tầng.
"""

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Literal

from app.core.clock import Clock

log = logging.getLogger(__name__)

State = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        clock: Clock,
        failure_threshold: int,
        window_seconds: float,
        open_seconds: float,
    ) -> None:
        self.name = name
        self._clock = clock
        self._threshold = failure_threshold
        self._window = timedelta(seconds=window_seconds)
        self._open_for = timedelta(seconds=open_seconds)
        self._failures: deque[datetime] = deque()  # lỗi liên tiếp kể từ lần thành công gần nhất
        self._state: State = "closed"
        self._opened_at: datetime | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> State:
        return self._state

    def allow(self) -> bool:
        """Được gọi hệ thống ngoài không? Gọi xong PHẢI báo `record_success`/`record_failure`."""
        if self._state == "closed":
            return True
        if self._state == "open":
            assert self._opened_at is not None
            if self._clock.now() - self._opened_at < self._open_for:
                return False
            self._state = "half_open"
            self._probe_in_flight = False
            log.info("breaker %s: half-open", self.name)
        if self._probe_in_flight:
            return False  # half-open chỉ cho đúng 1 lời gọi thử
        self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        if self._state != "closed":
            log.info("breaker %s: đóng lại", self.name)
        self._state = "closed"
        self._failures.clear()
        self._probe_in_flight = False

    def record_neutral(self) -> None:
        """Kết quả không tính vào breaker (tool ghi 404/409 — P5 mục 6.1): chuỗi lỗi liên tiếp giữ
        nguyên. Riêng lượt thử half-open: hệ thống đã trả lời nên coi như thử thành công."""
        if self._state == "half_open":
            self.record_success()

    def record_failure(self) -> None:
        now = self._clock.now()
        if self._state == "half_open":
            self._open(now)
            return
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self._window:
            self._failures.popleft()
        if len(self._failures) >= self._threshold:
            self._open(now)

    def _open(self, now: datetime) -> None:
        self._state = "open"
        self._opened_at = now
        self._probe_in_flight = False
        self._failures.clear()
        log.warning("breaker %s: mở %.0f giây", self.name, self._open_for.total_seconds())


class BreakerBoard:
    """Một breaker cho mỗi `target_system`, tạo khi cần. Tham số lấy từ Settings (`breaker_*`)."""

    def __init__(
        self,
        clock: Clock,
        failure_threshold: int,
        window_seconds: float,
        open_seconds: float,
    ) -> None:
        self._clock = clock
        self._params = (failure_threshold, window_seconds, open_seconds)
        self._breakers: dict[str, CircuitBreaker] = {}

    def __getitem__(self, system: str) -> CircuitBreaker:
        if system not in self._breakers:
            threshold, window, open_for = self._params
            self._breakers[system] = CircuitBreaker(system, self._clock, threshold, window, open_for)
        return self._breakers[system]
