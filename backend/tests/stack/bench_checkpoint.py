"""Đo `AsyncPostgresSaver.aput` (phase4 4.1 P6; Việc treo 16 — thời gian thêm của `durability="sync"`, ước tính +10–50 ms/lượt).

Chạy: `make verify BENCH=1` (bước 7) hoặc `PYTHONPATH=backend uv run python -m tests.stack.bench_checkpoint`.

- Postgres **testcontainers** riêng (`postgres:16`, cùng image stack, cùng colima — Makefile export `DOCKER_HOST`/
  `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`): không cần mật khẩu stack, không làm bẩn DB stack, KHÔNG đọc `.env`.
- Cùng đường ghi của runtime: `graph.checkpoint.open_postgres_saver` (pool psycopg, `autocommit`, `make_serde()` có kiểu domain).
  Bảng checkpoint tạo bằng `setup()` dưới superuser của container (runtime: migration 0003).
- State TỔNG HỢP ~5 / 20 / 50 KB (đo bằng chính serde): `RequesterContext` + 5 `ChunkRef` (excerpt 600 ký tự) + `conversation`
  tin 500 ký tự tới đủ cỡ; mỗi khoá là một channel, MỌI channel đổi phiên bản mỗi lần (trường hợp xấu: ghi mọi blob). 10 lần
  khởi động bỏ đi + 200 lần đo mỗi cỡ, mỗi lần một checkpoint mới nối cha. In p50/p95 (ms) — KHÔNG in nội dung checkpoint.
- p95 > 50 ms → in dòng "Q" (phase4 P6: ghi PROGRESS, hỏi Tuấn Anh). Mã thoát 0 khi đo xong (số đo, không phải cổng).
"""

import asyncio
import math
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.domain.context import RequesterContext
from app.domain.ticket_state import ChunkRef
from app.graph.checkpoint import make_serde, open_postgres_saver
from langgraph.checkpoint.base import empty_checkpoint

SIZES_KB = (5, 20, 50)
RUNS = 200
WARMUP = 10
P95_LIMIT_MS = 50.0
IMAGE = "postgres:16"
_FILLER = "Nội dung mô phỏng tin nhắn đã che trong hội thoại ticket VPN. "  # không phải dữ liệu thật


def _text(n: int) -> str:
    return (_FILLER * (n // len(_FILLER) + 1))[:n]


def state_bytes(state: dict[str, Any]) -> int:
    """Tổng byte serde của mọi channel — đúng cỡ blob `checkpoint_blobs`/`checkpoints` sẽ ghi."""
    serde = make_serde()
    return sum(len(serde.dumps_typed(v)[1]) for v in state.values())


def synthetic_state(target_kb: int) -> dict[str, Any]:
    """State giống `TicketState` giữa lượt (không dữ liệu thật): thêm tin 500 ký tự tới khi ≥ `target_kb` KB."""
    ctx = RequesterContext(
        user_id="nv001", role="employee", department="it", manager_id=None, employment_status="active",
        tenure_days=365, is_privileged_account=False, captured_at=datetime(2026, 9, 30, tzinfo=UTC),
    )  # fmt: skip
    chunks = [
        ChunkRef(chunk_id=f"KB-VPN-00{i}#v1#0", doc_id=f"KB-VPN-00{i}", version=1, seq=0, title="Tài liệu VPN",
                 heading_path="Mục", score=0.5, excerpt=_text(600))
        for i in range(1, 6)
    ]  # fmt: skip
    state: dict[str, Any] = {
        "ticket_id": str(uuid.uuid4()), "status": "S_RETRIEVING", "redacted_request": _text(300), "intent": "vpn",
        "requester_context": ctx, "retrieved": chunks, "retrieval_score": 0.05, "kb_version": "b" * 64,
        "slots": {"device_id": "LAP-0342", "action": "renew_vpn_cert"}, "conversation": [],
    }  # fmt: skip
    while state_bytes(state) < target_kb * 1024:
        state["conversation"].append({"role": "assistant", "kind": "answer", "text": _text(500), "ref": "m1"})
    return state


def percentile(samples: Sequence[float], q: float) -> float:
    """Nearest-rank (không nội suy): p95 của 200 mẫu = mẫu thứ 190 sau khi sắp."""
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def format_line(kb: int, actual_bytes: int, samples: Sequence[float]) -> str:
    return (f"{kb} KB (thực {actual_bytes / 1024:.1f} KB) p50={percentile(samples, 50):.2f}ms "
            f"p95={percentile(samples, 95):.2f}ms n={len(samples)}")  # fmt: skip


async def measure(url: str, *, runs: int = RUNS, warmup: int = WARMUP) -> list[tuple[int, int, list[float]]]:
    out: list[tuple[int, int, list[float]]] = []
    async with open_postgres_saver(url, max_size=2) as saver:
        await saver.setup()
        for kb in SIZES_KB:
            state = synthetic_state(kb)
            thread = f"bench-{kb}-{uuid.uuid4().hex[:8]}"
            parent: str | None = None
            samples: list[float] = []
            for i in range(warmup + runs):
                versions: dict[str, str | int | float] = {k: str(i + 1) for k in state}
                cp = empty_checkpoint()
                cp["channel_values"] = state
                cp["channel_versions"] = versions
                configurable: dict[str, Any] = {"thread_id": thread, "checkpoint_ns": ""}
                if parent is not None:
                    configurable["checkpoint_id"] = parent
                t0 = time.perf_counter()
                saved = await saver.aput({"configurable": configurable}, cp, {"source": "loop", "step": i, "parents": {}},
                                         versions)  # fmt: skip
                elapsed_ms = (time.perf_counter() - t0) * 1000
                parent = saved["configurable"]["checkpoint_id"]
                if i >= warmup:
                    samples.append(elapsed_ms)
            out.append((kb, state_bytes(state), samples))
    return out


def main(argv: Sequence[str] = ()) -> int:
    from testcontainers.community.postgres import (
        PostgresContainer,  # nạp muộn: unit test hàm thuần không cần Docker
    )

    print(f"bench aput AsyncPostgresSaver — {IMAGE} testcontainers, {RUNS} lần/cỡ (+{WARMUP} khởi động)")
    with PostgresContainer(IMAGE, username="postgres", password="bench-only", dbname="bench", driver="psycopg") as pg:
        url = f"postgresql+psycopg://postgres:bench-only@{pg.get_container_host_ip()}:{pg.get_exposed_port(5432)}/bench"
        results = asyncio.run(measure(url))
    worst = 0.0
    for kb, size, samples in results:
        print(format_line(kb, size, samples))
        worst = max(worst, percentile(samples, 95))
    if worst > P95_LIMIT_MS:
        print(f"Q: p95 lớn nhất {worst:.2f} ms > {P95_LIMIT_MS:.0f} ms — ghi PROGRESS, hỏi Tuấn Anh (phase4 P6)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
