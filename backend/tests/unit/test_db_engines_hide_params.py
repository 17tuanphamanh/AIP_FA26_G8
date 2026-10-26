"""F15 (Việc treo 33): mọi engine của app có `hide_parameters=True` — lỗi DB (vd timeout lúc INSERT) không đưa tham số câu lệnh
(`note` đã che, chữ người dùng…) vào traceback/log. (a) dựng thật, không kết nối DB; (b) quét AST để engine mới không lọt.
"""

import ast
from pathlib import Path

import pytest
from app.db.session import create_engines
from app.settings import Settings

APP = Path(__file__).resolve().parents[2] / "app"
ENGINE_FACTORIES = {"create_async_engine", "create_engine", "engine_from_config", "async_engine_from_config"}
NO_DB = "postgresql+psycopg://x@127.0.0.1:1/khong_co"


@pytest.mark.asyncio
async def test_f15_a_main_lock_monitor_hide_parameters() -> None:
    settings = Settings(_env_file=None, database_url=NO_DB, monitor_database_url=NO_DB)  # type: ignore[call-arg]
    engines = create_engines(settings)
    try:
        assert engines.monitor is not None
        assert [e.sync_engine.hide_parameters for e in (engines.main, engines.lock, engines.monitor)] == [True] * 3
    finally:
        await engines.dispose()


def _engine_calls() -> list[tuple[str, int, ast.Call]]:
    found = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if name in ENGINE_FACTORIES:
                    found.append((str(path.relative_to(APP)), node.lineno, node))
    return found


def _hides(call: ast.Call) -> bool:
    return any(
        kw.arg == "hide_parameters" and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in call.keywords
    )


def test_f15_b_every_engine_in_app_hides_parameters() -> None:
    calls = _engine_calls()
    assert len(calls) >= 6, calls  # session ×3, audit/check, rag/ingest/cli, alembic/env — không xanh rỗng
    assert [(path, line) for path, line, call in calls if not _hides(call)] == []
