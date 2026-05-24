"""
Health check router — used by load balancers, Docker healthchecks, k8s probes.

GET /health  → checks DB connectivity, returns 200 if healthy
GET /health/live → lightweight liveness probe (no DB call)
GET /health/ready → readiness probe (checks DB + Redis)

Why hit the DB in /health?
  A process can be running but the DB connection pool exhausted or
  network partitioned. "Process alive" ≠ "can serve requests".
  Load balancers need to know the app is actually functional.
"""

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Full health check (DB connectivity)")
async def health_check(
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Confirms the API can reach the database."""
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/live", summary="Liveness probe (no DB)")
async def liveness() -> dict:
    """
    Lightweight probe — just confirms the process is responding.
    Use this for k8s livenessProbe (restarts container if it fails).
    """
    return {"status": "alive"}


@router.get("/ready", summary="Readiness probe (DB + Redis)")
async def readiness(
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Confirms both DB and Redis are reachable.
    Use this for k8s readinessProbe (removes pod from load balancer if it fails).
    """
    errors: list[str] = []

    # Check DB
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("DB health check failed: %s", exc)
        errors.append(f"database: {exc}")

    # Check Redis
    try:
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        errors.append(f"redis: {exc}")

    if errors:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "errors": errors},
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ready", "database": "connected", "redis": "connected"},
    )
