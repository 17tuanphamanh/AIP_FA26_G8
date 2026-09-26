"""Khoá phiên bản schema checkpoint LangGraph (người yêu cầu khi duyệt 2a, 26/09/2026) + serde.

Bản integration (`test_graph_pg.py`) so thêm số dòng `checkpoint_migrations` trong DB thật.
"""

import importlib.util
import warnings
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from app.graph.checkpoint import CHECKPOINT_TABLES, make_serde
from app.graph.fakes import FAKE_ACTION, fake_requester, fake_risk
from langgraph.checkpoint.postgres import PostgresSaver

VERSIONS = Path(__file__).resolve().parents[2] / "app/db/alembic/versions"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installed_checkpoint_migrations_match_alembic() -> None:
    m = _load(VERSIONS / "0003_langgraph_checkpoint.py")
    assert len(PostgresSaver.MIGRATIONS) == m.KNOWN_CHECKPOINT_MIGRATIONS, (
        "langgraph-checkpoint-postgres đổi số migration checkpoint → cần migration Alembic mới "
        "gọi lại PostgresSaver.setup() (xem docstring 0003)"
    )


def test_checkpoint_table_lists_agree() -> None:
    m = _load(VERSIONS / "0003_langgraph_checkpoint.py")
    env_src = (VERSIONS.parent / "env.py").read_text(encoding="utf-8")
    assert tuple(m.CHECKPOINT_TABLES) == CHECKPOINT_TABLES
    assert all(f'"{t}"' in env_src for t in CHECKPOINT_TABLES)
    base_sql = "\n".join(PostgresSaver.MIGRATIONS)
    assert all(f"CREATE TABLE IF NOT EXISTS {t} " in base_sql for t in CHECKPOINT_TABLES)


def test_serde_roundtrips_domain_models_without_unregistered_warning() -> None:
    serde = make_serde()
    value = {
        "ctx": fake_requester("u1", datetime(2026, 9, 26, tzinfo=UTC)),
        "action": FAKE_ACTION,
        "risk": fake_risk("HITL"),
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert serde.loads_typed(serde.dumps_typed(value)) == value
