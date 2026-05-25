"""
Worker base utilities — shared setup for all RQ workers.

Why a separate base module?
  Multiple workers (log_worker, drift_worker, etc.) need the same
  Redis connection + async session setup. DRY.

Why RQ (Redis Queue)?
  FastAPI BackgroundTasks runs in the same process as the API.
  If embedding takes 500ms, it's fine — but if it crashes, it's silent.
  RQ = separate worker process, retries, job visibility, dead-letter queue.
  Simple to operate: `rq worker` command, no Celery complexity.
"""

from __future__ import annotations

import logging

import redis as sync_redis

from api.config import get_settings

logger = logging.getLogger(__name__)


def get_redis_connection() -> sync_redis.Redis:
    """Sync Redis connection for RQ (RQ uses sync redis, not aioredis)."""
    settings = get_settings()
    return sync_redis.from_url(settings.redis_url, decode_responses=False)
