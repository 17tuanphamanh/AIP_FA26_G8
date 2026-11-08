"""G2 — lock pool = 2 × GRAPH_CONCURRENCY + 2 (trước: GRAPH_CONCURRENCY + 2), và tổng số kết nối Postgres được ghi vào README.

Một lượt giữ MỘT kết nối lock pool suốt lượt (khoá advisory cấp session) và `GRAPH_CONCURRENCY` lượt chạy cùng lúc; ngoài ra API còn giữ
khoá để giao cho task nền (`resume_locked`, P1 mục 7) và `deliver_event` chờ khoá — pool bằng đúng `GRAPH_CONCURRENCY + 2` thì chỉ cần thêm
vài request chờ khoá là cạn. Công thức có MỘT nguồn: `Settings` (khi `LOCK_POOL_SIZE` trống). Compose và `.env.example` không ghim số.
"""

import re
from pathlib import Path
from typing import Any

import pytest
from app.db.session import create_engines
from app.settings import Settings

REPO = Path(__file__).resolve().parents[3]
DSN = "postgresql+psycopg://u:p@localhost:5432/d"


def settings(**over: Any) -> Settings:
    return Settings(_env_file=None, database_url=DSN, **over)  # type: ignore[call-arg]


def test_default_is_two_times_concurrency_plus_two() -> None:
    assert settings().graph_concurrency == 8 and settings().effective_lock_pool_size == 18
    assert settings(graph_concurrency=3).effective_lock_pool_size == 8
    assert settings(graph_concurrency=1).effective_lock_pool_size == 4


def test_explicit_lock_pool_size_still_wins() -> None:
    assert settings(graph_concurrency=8, lock_pool_size=4).effective_lock_pool_size == 4


@pytest.mark.asyncio
async def test_lock_engine_is_built_with_the_new_size_and_never_overflows() -> None:
    engines = create_engines(settings(graph_concurrency=5))
    try:
        assert engines.lock.pool.size() == 12  # type: ignore[attr-defined]
        assert engines.lock.pool._max_overflow == 0  # type: ignore[attr-defined]  # cạn thì chờ, không mở thêm kết nối
    finally:
        await engines.dispose()


def test_compose_does_not_pin_a_number_for_lock_pool() -> None:
    """Compose để TRỐNG (`${LOCK_POOL_SIZE:-}` → env_ignore_empty → công thức của Settings), không lặp lại công thức bằng một số."""
    line = next(ln for ln in (REPO / "docker-compose.yml").read_text(encoding="utf-8").splitlines() if "LOCK_POOL_SIZE" in ln)
    assert re.search(r"LOCK_POOL_SIZE:\s*\$\{LOCK_POOL_SIZE:-\}\s*(#.*)?$", line), line


def test_env_example_does_not_set_a_number_for_lock_pool() -> None:
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    assigned = [ln for ln in lines if re.match(r"\s*LOCK_POOL_SIZE\s*=\s*\S", ln)]
    assert assigned == []  # không ghim số: để Settings tính 2 × GRAPH_CONCURRENCY + 2
    assert any("LOCK_POOL_SIZE" in ln and ln.lstrip().startswith("#") for ln in lines)  # nhưng có chú thích


@pytest.mark.asyncio
async def test_readme_documents_total_connections_derived_from_defaults() -> None:
    """README ghi đúng số suy từ mặc định hiện tại (đổi mặc định mà quên sửa tài liệu → đỏ). 3 pool / tiến trình, 2 tiến trình
    (backend, worker): chính (`DB_POOL_SIZE` + overflow), khoá (không overflow), checkpoint (`CHECKPOINT_POOL_SIZE`)."""
    s = settings()
    engines = create_engines(s)
    try:
        main_cap = s.db_pool_size + engines.main.pool._max_overflow  # type: ignore[attr-defined]
    finally:
        await engines.dispose()
    steady = s.db_pool_size + s.effective_lock_pool_size + s.checkpoint_pool_size
    peak = main_cap + s.effective_lock_pool_size + s.checkpoint_pool_size
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "Số kết nối Postgres" in readme
    section = readme[readme.index("Số kết nối Postgres"):]
    for number in (steady, peak, 2 * steady, 2 * peak, 100):
        assert re.search(rf"\b{number}\b", section), f"README mục 'Số kết nối Postgres' thiếu số {number}"
    assert "3 pool" in section and "max_connections" in section
