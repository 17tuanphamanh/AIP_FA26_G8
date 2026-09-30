"""P6 (phase4 4.1; Việc treo 16) — phần THUẦN của `tests/stack/bench_checkpoint.py` (không cần Docker): cỡ state tổng hợp đúng
mục tiêu (đo bằng serde thật), percentile nearest-rank, dòng in khớp mẫu `make verify` bước 7 đọc; module không đọc `.env`.
Số đo thật: `make verify BENCH=1` (Postgres testcontainers)."""

import re
from pathlib import Path

import pytest
from tests.stack.bench_checkpoint import (
    SIZES_KB,
    format_line,
    percentile,
    state_bytes,
    synthetic_state,
)

SRC = Path(__file__).resolve().parents[1] / "stack" / "bench_checkpoint.py"


@pytest.mark.parametrize("kb", SIZES_KB)
def test_synthetic_state_reaches_target_size_without_overshooting(kb: int) -> None:
    size = state_bytes(synthetic_state(kb))
    assert kb * 1024 <= size < kb * 1024 + 1024  # thêm từng tin ~0,5 KB → vượt mục tiêu < 1 KB


def test_percentile_nearest_rank() -> None:
    samples = [float(i) for i in range(1, 201)]
    assert (percentile(samples, 50), percentile(samples, 95)) == (100.0, 190.0)
    assert percentile([3.0], 95) == 3.0


def test_format_line_matches_verify_grep() -> None:
    line = format_line(20, 20 * 1024 + 300, [1.0, 2.0, 3.0])
    assert re.match(r"^(5|20|50) KB", line) and "p50=2.00ms" in line and "p95=3.00ms" in line and "n=3" in line


def test_bench_never_touches_env_file_or_stack_db() -> None:
    src = SRC.read_text(encoding="utf-8")
    assert ".env" not in src.replace("KHÔNG đọc `.env`", "") and "DATABASE_URL" not in src and "get_settings" not in src
