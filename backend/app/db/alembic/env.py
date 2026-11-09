"""Alembic env — chạy bằng role app_migrate (owner schema, P7 mục 3), không superuser.

URL: `sqlalchemy.url` do test đặt, nếu không có thì MIGRATE_DATABASE_URL.
"""

import os
from logging.config import fileConfig

from alembic import context
from app.db.models import Base
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Bảng checkpoint LangGraph do migration 0003 tạo bằng `PostgresSaver.setup()`, không nằm trong
# models.py — autogenerate/compare_metadata phải bỏ qua, không thì đề xuất DROP chúng.
CHECKPOINT_TABLES = frozenset(
    {"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"}
)


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    if type_ == "table":
        return name not in CHECKPOINT_TABLES
    table = getattr(obj, "table", None)
    return getattr(table, "name", None) not in CHECKPOINT_TABLES


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get(
        "MIGRATE_DATABASE_URL"
    )
    if not url:
        raise RuntimeError("Thiếu MIGRATE_DATABASE_URL (role app_migrate) cho Alembic")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
