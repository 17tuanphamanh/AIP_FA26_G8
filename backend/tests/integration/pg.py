"""Tiện ích Postgres cho test integration — dùng chung bởi conftest và các file test."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[3]
INIT_DIR = REPO / "docker" / "postgres"
PASSWORDS = {"app_migrate": "test-migrate", "app_rw": "test-rw", "app_monitor": "test-monitor"}
DB = "servicedesk"


@dataclass(frozen=True)
class PgUrls:
    host: str
    port: int
    db: str = DB

    def url(self, role: str, password: str) -> str:
        return f"postgresql+psycopg://{role}:{password}@{self.host}:{self.port}/{self.db}"

    @property
    def superuser(self) -> str:
        return self.url("postgres", "test-super")

    def role(self, role: str) -> str:
        return self.url(role, PASSWORDS[role])


def alembic_config(pg: PgUrls) -> Config:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", pg.role("app_migrate"))
    cfg.attributes["configure_logger"] = False
    return cfg


# Phần "theo database" của docker/postgres/init-roles.sh (role đã có sẵn trong cluster).
_PER_DB_SETUP = (
    'REVOKE ALL ON DATABASE "{db}" FROM PUBLIC',
    'GRANT CONNECT ON DATABASE "{db}" TO app_migrate, app_rw, app_monitor',
    "REVOKE ALL ON SCHEMA public FROM PUBLIC",
    "ALTER SCHEMA public OWNER TO app_migrate",
    "GRANT USAGE ON SCHEMA public TO app_rw, app_monitor",
)


@contextmanager
def fresh_database(pg: PgUrls) -> Iterator[PgUrls]:
    """Database TRỐNG riêng trong cùng container (chưa migrate). Dùng cho test ghi `mfa_enrolled`/
    `mfa_reset`: bảng append-only không xoá được, ghi vào DB chung thì test downgrade về base đỏ."""
    fresh = replace(pg, db=f"t_{uuid.uuid4().hex[:12]}")
    admin = create_engine(pg.superuser, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{fresh.db}"'))
        setup = create_engine(fresh.superuser, isolation_level="AUTOCOMMIT")
        with setup.connect() as conn:
            for stmt in _PER_DB_SETUP:
                conn.execute(text(stmt.format(db=fresh.db)))
        setup.dispose()
        yield fresh
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{fresh.db}" WITH (FORCE)'))
        admin.dispose()
