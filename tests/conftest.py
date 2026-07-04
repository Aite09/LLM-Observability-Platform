"""
Shared test fixtures.

Unit tests (tests/unit): pure logic, no fixtures from here needed.
Integration tests (tests/integration): real Postgres via TEST_DATABASE_URL
(defaults to the docker-compose Postgres with a _test database).

Strategy: one engine per session; each test runs in a fresh schema state
by truncating all tables after the test. Truncate > drop/create: faster,
keeps Alembic-applied schema intact.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Test DB URL — same postgres container, dedicated database.
# CI overrides via env. The _test DB is created by the integration bootstrap
# fixture below if missing. Credentials mirror docker-compose (llmobs/llmobs_secret).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://llmobs:llmobs_secret@localhost:5432/llm_observability_test",
)

# Name of the dedicated test database, parsed from the URL's last path segment.
TEST_DB_NAME = TEST_DATABASE_URL.rsplit("/", 1)[1]

# Make the app under test read the test DB before api.config is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Session-scoped engine. Creates llm_obs_test DB + schema if needed."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    from sqlalchemy import text

    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name").bindparams(
                name=TEST_DB_NAME
            )
        )
        if not exists:
            # Identifier can't be bound as a param; TEST_DB_NAME is developer-set.
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    await admin_engine.dispose()

    eng = create_async_engine(TEST_DATABASE_URL)
    # Apply schema: pgvector extension + all tables from ORM metadata.
    # (Alembic runs against the dev DB; tests build equivalent schema directly.)
    from api.models.base import Base
    import api.models.llm_log  # noqa: F401 — register all models on Base.metadata
    import api.models.test_case  # noqa: F401
    import api.models.eval_run  # noqa: F401
    import api.models.eval_result  # noqa: F401
    import api.models.drift_alert  # noqa: F401
    import api.models.metric  # noqa: F401

    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session; truncates all tables after each test."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s

    from sqlalchemy import text
    from api.models.base import Base

    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client against the real app, DB dependency overridden to test DB."""
    from api.dependencies import get_db
    from api.main import create_app

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _test_db() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_db] = _test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    from sqlalchemy import text
    from api.models.base import Base

    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
