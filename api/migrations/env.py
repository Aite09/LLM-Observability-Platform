"""
Alembic migration environment — async configuration.

Key points:
  1. `import api.models` triggers __init__.py which imports every model,
     registering all tables with Base.metadata. Without this, autogenerate
     produces empty migrations.

  2. We override sqlalchemy.url from get_settings() so credentials never
     live in alembic.ini (which is committed to git).

  3. NullPool for migrations: migrations run once, a connection pool is
     wasteful. NullPool creates a connection, uses it, destroys it.

  4. run_sync(do_run_migrations): Alembic's migration runner is synchronous.
     We bridge async → sync with connection.run_sync().
"""

import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Crucial: import all models so Base.metadata knows every table ────────────
import api.models  # noqa: F401 — side-effect import, registers models
from api.config import get_settings
from api.models.base import Base

logger = logging.getLogger(__name__)

# Alembic Config object — access to values in alembic.ini
config = context.config

# Configure Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject database_url from env — never hardcode credentials in alembic.ini
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Point autogenerate at our models
target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    """Synchronous migration runner — called via connection.run_sync()."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Compare server defaults so Alembic detects server_default changes
        compare_server_default=True,
        # Include schemas if you use PostgreSQL schemas (we don't — kept for reference)
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Async migration runner for asyncpg driver.

    NullPool: no connection pooling for migrations — create, use, destroy.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_offline() -> None:
    """
    Offline mode: generate SQL script without connecting to DB.
    Useful for reviewing what a migration will do before applying it.
    Run: alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
