"""Alembic environment for competitor-intelligence's own DDL history.

Connection string comes from the DATABASE_URL environment variable only, same convention as
packages/calc-engine/migrations/env.py. Runs as metrion_migrate (auth.md §7.3).

`version_table="alembic_version_competitor_intelligence"` — this package shares one Postgres
database with calc-engine, data-foundation and backend but is a structurally separate,
independently versioned migration history. Using Alembic's default `alembic_version` table
name here would collide with calc-engine's own history in the same database (each package's
revision graph would corrupt the other's version-tracking row). A distinct version table
keeps the histories independent, matching how the packages are otherwise fully decoupled (no
shared ORM metadata, no cross-package migration dependency).

Migrations are hand-written SQL (`op.execute(...)`), not declarative ORM models, for the same
reason as calc-engine's: autogenerate has no support for RLS policies, which are exactly the
lines that matter here.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. competitor-intelligence migrations require an explicit "
        "connection string (see .env.example) — there is no default and none is committed "
        "to alembic.ini."
    )
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = None
_VERSION_TABLE = "alembic_version_competitor_intelligence"


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, version_table=_VERSION_TABLE)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
