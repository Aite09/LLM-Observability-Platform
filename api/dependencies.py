"""
FastAPI dependency providers — DB sessions, settings injection.

Pattern: FastAPI calls get_db() before each request via Depends(get_db).
The `yield` gives the handler a live session, then closes it after the
response is sent (even if an exception was raised).

Why async_sessionmaker instead of sessionmaker:
  - asyncpg is an async driver; sync session.execute() would deadlock.
  - expire_on_commit=False: after commit(), don't expire loaded objects.
    In async context you can't lazily reload (no implicit IO). Without
    this flag, accessing any attribute after commit raises DetachedInstanceError.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.config import get_settings

settings = get_settings()

# Connection pool config:
#   pool_size=10    → up to 10 persistent connections
#   max_overflow=20 → up to 20 extra connections under burst load
#   pool_pre_ping   → test connection before use (handles stale connections)
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,  # set True locally to log SQL; never True in prod
)

async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: yields an async DB session per request.

    Usage in a router:
        async def my_handler(session: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        yield session
