"""
Log worker — async embedding generation via OpenAI, enqueued via RQ.

Flow:
  POST /logs → create_log() → enqueue_embedding_job(log_id) → RQ queue
  RQ worker picks up → generate_embedding(log_id) → asyncio.run(async fn)
  → fetch log from DB → OpenAI embeddings.create → UPDATE prompt_embedding

Why asyncio.run() in generate_embedding?
  RQ calls sync functions. Our DB operations are async (asyncpg).
  asyncio.run() bridges sync → async for each job. Clean, no event loop leaks.

Why text-embedding-3-small?
  1536 dimensions (same as ada-002), cheaper, faster, matches Vector(1536) column.

Why UPDATE not fetch+modify+commit?
  Single SQL UPDATE = no re-read, no SQLAlchemy state tracking overhead.
  Background job just needs to set one column. Efficient.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from openai import AsyncOpenAI
from rq import Queue
from sqlalchemy import select, update

from api.config import get_settings
from api.dependencies import async_session_maker
from api.models.llm_log import LLMLog
from workers.base import get_redis_connection

logger = logging.getLogger(__name__)

# Module-level clients — instantiated once per worker process, not per job.
# get_settings() is lru_cache'd so repeated calls are free.
_settings = get_settings()
_openai_client = AsyncOpenAI(api_key=_settings.openai_api_key)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536  # must match Vector(1536) in LLMLog model


def enqueue_embedding_job(log_id: str) -> None:
    """
    Sync entry point called by FastAPI BackgroundTasks.

    Puts a generate_embedding job on the default RQ queue.
    Returns immediately — does not wait for embedding to complete.

    Why sync?
      FastAPI BackgroundTasks.add_task() calls the function in a thread pool.
      Keeping this sync avoids event loop nesting issues.
    """
    try:
        q = Queue(connection=get_redis_connection())
        job = q.enqueue(generate_embedding, log_id)
        logger.info("Embedding job enqueued: log_id=%s job_id=%s", log_id, job.id)
    except Exception as exc:  # noqa: BLE001
        # Redis unavailable → log and continue. Embedding is best-effort.
        logger.error("Failed to enqueue embedding job for log_id=%s: %s", log_id, exc)


def generate_embedding(log_id: str) -> None:
    """
    Sync RQ job entry point. RQ calls this function in a worker process.

    asyncio.run() creates a new event loop for each job.
    Safe: RQ worker is single-threaded per job. No loop conflict.
    """
    logger.info("Embedding job started: log_id=%s", log_id)
    asyncio.run(_generate_embedding_async(log_id))


async def _generate_embedding_async(log_id: str) -> None:
    """
    Async implementation:
      1. Fetch log row from DB
      2. Call OpenAI embeddings API
      3. UPDATE prompt_embedding column
    """
    log_uuid = uuid.UUID(log_id)

    async with async_session_maker() as session:
        # 1. Fetch prompt text
        result = await session.execute(
            select(LLMLog.id, LLMLog.prompt).where(LLMLog.id == log_uuid)
        )
        row = result.one_or_none()
        if row is None:
            logger.warning("Embedding job: log not found log_id=%s", log_id)
            return

        _, prompt_text = row

        # 2. Generate embedding
        try:
            resp = await _openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=prompt_text,
            )
            embedding: list[float] = resp.data[0].embedding
            assert len(embedding) == EMBEDDING_DIMS, f"Expected {EMBEDDING_DIMS} dims, got {len(embedding)}"
        except Exception as exc:
            logger.error("OpenAI embedding failed for log_id=%s: %s", log_id, exc)
            return  # leave prompt_embedding as NULL — job is done, no retry storm

        # 3. Persist embedding — single UPDATE, no re-fetch
        await session.execute(
            update(LLMLog)
            .where(LLMLog.id == log_uuid)
            .values(prompt_embedding=embedding)
        )
        await session.commit()
        logger.info("Embedding stored: log_id=%s dims=%d", log_id, len(embedding))
