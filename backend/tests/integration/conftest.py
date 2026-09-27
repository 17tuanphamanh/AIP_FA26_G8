"""Postgres 16 thật qua testcontainers, khởi tạo bằng CHÍNH script init của compose
(docker/postgres/init-roles.sh) — 3 role có mật khẩu, app_migrate làm owner schema.

Alembic chạy bằng app_migrate (không superuser), đúng như `make up`.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.qdrant import QdrantContainer
from tests.integration.pg import DB, INIT_DIR, PASSWORDS, PgUrls, alembic_config
from tests.integration.qdrant import QDRANT_IMAGE, wipe_kb


@pytest.fixture(scope="session")
def pg() -> Iterator[PgUrls]:
    container = (
        PostgresContainer(
            "postgres:16", username="postgres", password="test-super", dbname=DB, driver="psycopg"
        )
        .with_env("PG_MIGRATE_PASSWORD", PASSWORDS["app_migrate"])
        .with_env("PG_RW_PASSWORD", PASSWORDS["app_rw"])
        .with_env("PG_MONITOR_PASSWORD", PASSWORDS["app_monitor"])
        .with_volume_mapping(str(INIT_DIR), "/docker-entrypoint-initdb.d", mode="ro")
    )
    with container:
        yield PgUrls(container.get_container_host_ip(), int(container.get_exposed_port(5432)))


@pytest.fixture(scope="session")
def migrated(pg: PgUrls) -> PgUrls:
    """DB đã `alembic upgrade head` một lần cho cả phiên test."""
    command.upgrade(alembic_config(pg), "head")
    return pg


def _engine(url: str) -> Iterator[Engine]:
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def owner(migrated: PgUrls) -> Iterator[Engine]:
    yield from _engine(migrated.role("app_migrate"))


@pytest.fixture
def rw(migrated: PgUrls) -> Iterator[Engine]:
    yield from _engine(migrated.role("app_rw"))


@pytest.fixture
def monitor(migrated: PgUrls) -> Iterator[Engine]:
    yield from _engine(migrated.role("app_monitor"))


# ---- Qdrant (Phase 3 chặng 3b — RAG ingest) ------------------------------------------------------


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    with QdrantContainer(QDRANT_IMAGE) as container:
        yield f"http://{container.rest_host_address}"


@pytest.fixture
def clean_qdrant(qdrant_url: str, rw: Engine) -> str:
    """Qdrant không có alias/collection `kb_*`, bảng `kb_documents`/`kb_versions` trống (ghi bằng app_rw)."""
    wipe_kb(qdrant_url)
    with rw.begin() as conn:
        conn.execute(text("DELETE FROM kb_documents"))
        conn.execute(text("DELETE FROM kb_versions"))
    return qdrant_url
