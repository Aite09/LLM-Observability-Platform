"""
Eval worker — runs eval suites enqueued from POST /evals/run.

RQ job: sync entry, asyncio.run bridge, own session (worker process ≠ API).
"""

from __future__ import annotations

import asyncio
import logging

from rq import Queue

from api.config import get_settings
from api.dependencies import async_session_maker
from eval.engine import run_eval
from workers.base import get_redis_connection

logger = logging.getLogger(__name__)


def enqueue_eval_run(suite_name: str, commit_sha: str) -> str:
    """Called by the API. Returns the RQ job id."""
    q = Queue("evals", connection=get_redis_connection())
    job = q.enqueue(execute_eval_run, suite_name, commit_sha)
    logger.info("Eval job enqueued: suite=%s job_id=%s", suite_name, job.id)
    return job.id


def execute_eval_run(suite_name: str, commit_sha: str) -> None:
    """RQ job body."""
    asyncio.run(_execute(suite_name, commit_sha))


async def _execute(suite_name: str, commit_sha: str) -> None:
    settings = get_settings()
    async with async_session_maker() as session:
        try:
            await run_eval(
                session,
                suite_name=suite_name,
                commit_sha=commit_sha,
                triggered_by="api",
                gate_threshold=settings.eval_gate_threshold,
            )
        except ValueError as exc:
            logger.error("Eval job failed: %s", exc)
