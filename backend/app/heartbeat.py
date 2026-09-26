"""Heartbeat của worker — file, không bảng (không thêm bảng ngoài P7).

Worker ghi thời điểm hiện tại vào `WORKER_HEARTBEAT_PATH` định kỳ bằng chính APScheduler chạy các job
(`app/worker.py`), nên file còn mới nghĩa là event loop + scheduler còn chạy. Healthcheck của compose gọi
`python -m app.heartbeat`: thiếu file, nội dung hỏng, hoặc cũ hơn `WORKER_HEARTBEAT_MAX_AGE` (60 giây)
→ thoát 1 = unhealthy. Module nhẹ (chỉ nạp settings) vì healthcheck chạy vài giây một lần.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

from app.core.clock import SystemClock
from app.settings import Settings


def write(path: Path, now: datetime) -> None:
    """Ghi nguyên tử (file tạm + rename) để healthcheck không bao giờ đọc phải file dở."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(now.isoformat(), encoding="utf-8")
    os.replace(tmp, path)


def age_seconds(path: Path, now: datetime) -> float | None:
    """Tuổi của heartbeat; None nếu chưa có file hoặc nội dung không đọc được."""
    try:
        beat = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if beat.tzinfo is None:
        return None
    return (now - beat).total_seconds()


def is_fresh(path: Path, now: datetime, max_age: float) -> bool:
    age = age_seconds(path, now)
    return age is not None and age <= max_age


def main(settings: Settings | None = None, now: datetime | None = None) -> int:
    settings = settings or Settings()
    now = now or SystemClock().now()
    path, max_age = settings.worker_heartbeat_path, settings.worker_heartbeat_max_age
    age = age_seconds(path, now)
    if age is None or age > max_age:
        why = "không có/không đọc được" if age is None else f"cũ {age:.0f} giây > {max_age:.0f}"
        print(f"worker heartbeat {path}: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
