"""Alembic environment for calc-engine's own DDL history.

Connection string comes from the DATABASE_URL environment variable only — never hardcoded,
never read from alembic.ini (see alembic.ini's comment). Migrations run as the migration
role (`metrion_migrate`, auth.md §7.3), which owns these tables; the runtime role
(`metrion_app`) never runs DDL and has no BYPASSRLS.

This package writes migrations as raw SQL (`op.execute(...)`) rather than declarative ORM
models, because Alembic's autogenerate has no support for `FORCE ROW LEVEL SECURITY` or
policy definitions — those are exactly the lines that matter here, so hand-written SQL is the
honest choice, not an autogenerate diff that would silently omit them.
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
        "DATABASE_URL is not set. calc-engine migrations require an explicit connection "
        "string (see .env.example) — there is no default and none is committed to alembic.ini."
    )
config.set_main_option("sqlalchemy.url", database_url)

# No ORM metadata: this history is hand-written SQL, so autogenerate is not used.
target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
