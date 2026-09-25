"""Tiện ích Postgres cho test integration — dùng chung bởi conftest và các file test."""

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config

REPO = Path(__file__).resolve().parents[3]
INIT_DIR = REPO / "docker" / "postgres"
PASSWORDS = {"app_migrate": "test-migrate", "app_rw": "test-rw", "app_monitor": "test-monitor"}
DB = "servicedesk"


@dataclass(frozen=True)
class PgUrls:
    host: str
    port: int

    def url(self, role: str, password: str) -> str:
        return f"postgresql+psycopg://{role}:{password}@{self.host}:{self.port}/{DB}"

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
