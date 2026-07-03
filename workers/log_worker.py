"""
Log worker — local embedding generation via fastembed, enqueued via RQ.

Flow:
  POST /logs → create_log() → enqueue_embedding_job(log_id) → RQ queue
  RQ worker picks up → generate_embedding(log_id) → asyncio.run(async fn)
  → fetch log from DB → fastembed encode (local, $0) → UPDATE prompt_embedding

Why asyncio.run() in generate_embedding?
  RQ calls sync functions. Our DB operations are async (asyncpg).
  asyncio.run() bridges sync → async for each job. Clean, no event loop leaks.

Why fastembed?
  Local ONNX model — no API key, no cost, self-hosted story intact.
  384 dims must match Vector(384) on LLMLog.prompt_embedding.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from rq import Queue
from sqlalchemy import select, update

from api.dependencies import async_session_maker
from api.models.llm_log import LLMLog
from workers.base import get_redis_connection

logger = logging.getLogger(__name__)


def enqueue_embedding_job(log_id: str) -> None:
    """
    Sync entry point called by FastAPI BackgroundTasks.

    Puts a generate_embedding job on the default RQ queue.
    Returns immediately — does not wait for embedding to complete.
    """
    try:
        q = Queue(connection=get_redis_connection())
        job = q.enqueue(generate_embedding, log_id)
        logger.info("Embedding job enqueued: log_id=%s job_id=%s", log_id, job.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to enqueue embedding job for log_id=%s: %s", log_id, exc)


def generate_embedding(log_id: str) -> None:
    """Sync RQ job entry point — bridges to async implementation."""
    logger.info("Embedding job started: log_id=%s", log_id)
    asyncio.run(_generate_embedding_async(log_id))


async def _generate_embedding_async(log_id: str) -> None:
    """Fetch prompt → embed locally → UPDATE prompt_embedding."""
    # Import here: loads ONNX model lazily, only in processes that embed.
    from eval.scorers.embedding_backend import embed_texts

    log_uuid = uuid.UUID(log_id)

    async with async_session_maker() as session:
        result = await session.execute(
            select(LLMLog.id, LLMLog.prompt).where(LLMLog.id == log_uuid)
        )
        row = result.one_or_none()
        if row is None:
            logger.warning("Embedding job: log not found log_id=%s", log_id)
            return

        _, prompt_text = row

        try:
            embedding: list[float] = embed_texts([prompt_text])[0].tolist()
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedding failed for log_id=%s: %s", log_id, exc)
            return  # leave NULL — best-effort
        await session.execute(
            update(LLMLog)
            .where(LLMLog.id == log_uuid)
            .values(prompt_embedding=embedding)
        )
        await session.commit()
        logger.info("Embedding stored: log_id=%s dims=%d", log_id, len(embedding))
