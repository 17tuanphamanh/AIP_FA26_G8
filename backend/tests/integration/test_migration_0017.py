"""Migration 0017 (E12, soát 20 agent 12/11) trên Postgres 16 thật.

- `ix_llm_calls_span_id` ON llm_calls(span_id).
- `app_rw` không còn quyền DELETE trên `approvals` (SELECT, INSERT, UPDATE giữ nguyên — worker/route vẫn đóng phiếu bằng UPDATE).
- Lên 0017 → xuống 0016 → lên 0017: xuống trả đúng quyền của 0001, bỏ chỉ mục.
Mỗi test một database riêng (`fresh_database`).
"""

from typing import Any

from alembic import command
from sqlalchemy import Engine, create_engine, text
from tests.integration.pg import PgUrls, alembic_config, fresh_database

PRIVS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")


def _state(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rw = {p: conn.execute(text("SELECT has_table_privilege('app_rw', 'approvals', :p)"), {"p": p}).scalar() for p in PRIVS}
        index = conn.execute(text(
            "SELECT pg_get_indexdef(indexrelid) FROM pg_index WHERE indexrelid = to_regclass('public.ix_llm_calls_span_id')"
        )).scalar()  # fmt: skip
    return {"rw": rw, "index": index}


def test_0017_up_down_up(pg: PgUrls) -> None:
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        owner = create_engine(db.role("app_migrate"))
        try:
            command.upgrade(cfg, "0017")
            up = _state(owner)
            assert up["rw"] == {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False, "TRUNCATE": False}
            assert up["index"] is not None and "(span_id)" in up["index"]
            command.downgrade(cfg, "0016")
            down = _state(owner)
            assert down["rw"] == {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": True, "TRUNCATE": False}  # như 0001
            assert down["index"] is None
            command.upgrade(cfg, "0017")
            assert _state(owner) == up
        finally:
            owner.dispose()
