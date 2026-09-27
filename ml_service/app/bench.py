"""`make ml-bench` — đo độ trễ ml-service ngay trong container (cổng 8200 không bind ra máy).

`docker compose exec -T ml-service python -m app.bench`: embed 1 câu × 50, rerank 20 đoạn × 20, rerank
32 đoạn (một lô đầy) × 20; in p50/p95 (ms) và RSS của process uvicorn (PID 1). Mục tiêu P4 mục 9: embed
p95 < 300 ms, rerank 20 đoạn p95 < 2 s. Timeout rerank của backend chỉnh ≥ 2 × p95 lô 32 (3a).
Văn bản đo là câu tiếng Việt tổng hợp — không có dữ liệu thật.
"""

import os
import statistics
import time
from collections.abc import Mapping
from pathlib import Path

import httpx

URL = "http://127.0.0.1:8200"
QUERY = "máy tính của tôi không kết nối được VPN, báo lỗi chứng chỉ hết hạn"
SENTENCE = "Để gia hạn chứng chỉ VPN, mở ứng dụng kết nối, chọn mục cài đặt rồi làm theo hướng dẫn. "
PASSAGE = SENTENCE * 12  # ~ 300 âm tiết — cỡ đoạn lớn của chunker P3


def _time(client: httpx.Client, path: str, body: Mapping[str, object], n: int) -> list[float]:
    client.post(path, json=dict(body)).raise_for_status()  # lượt làm nóng, không tính
    samples = []
    for _ in range(n):
        started = time.perf_counter()
        client.post(path, json=dict(body)).raise_for_status()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def _report(name: str, samples: list[float]) -> None:
    p95 = statistics.quantiles(samples, n=20)[18]
    print(f"{name:<22} n={len(samples):<3} p50={statistics.median(samples):8.1f} ms  p95={p95:8.1f} ms")


def _rss_mb(pid: int = 1) -> str:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return f"{int(line.split()[1]) / 1024:.0f} MB"
    return "không đọc được"


def main() -> None:
    headers = {"X-Service-Token": os.environ["ML_SERVICE_TOKEN"]}
    with httpx.Client(base_url=URL, headers=headers, timeout=120) as client:
        _report("embed 1 câu", _time(client, "/embed", {"texts": [QUERY]}, 50))
        for k in (20, 32):
            body = {"query": QUERY, "passages": [PASSAGE] * k}
            _report(f"rerank {k} đoạn", _time(client, "/rerank", body, 20))
    print(f"RSS ml-service (PID 1): {_rss_mb()}")


if __name__ == "__main__":
    main()
