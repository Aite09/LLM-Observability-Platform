"""
Log service — business logic for LLM log CRUD.

Why a service layer?
  Routers handle HTTP concerns (status codes, query params, response models).
  Services handle business logic (DB queries, data transforms, validation rules).
  Keeping them separate = service is testable without HTTP, mockable in router tests.

All functions are async — they await DB operations via AsyncSession.
No FastAPI imports here — this is pure async Python + SQLAlchemy.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.llm_log import LLMLog
from api.schemas.llm_log import LLMLogCreate, LLMLogFilter

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def create_log(session: AsyncSession, data: LLMLogCreate) -> LLMLog:
    """Insert one LLM log row and return the persisted ORM instance.

    Steps:
      1. model_dump() → dict → unpack into LLMLog constructor
      2. add to session (not yet committed)
      3. commit → DB write, triggers server_default for created_at
      4. refresh → reload from DB so id + created_at are populated in Python

    Why refresh? SQLAlchemy async doesn't lazy-load after commit.
    Without refresh, log.id may be unset if the DB generates it.
    """
    log = LLMLog(**data.model_dump())
    session.add(log)
    await session.commit()
    await session.refresh(log)
    logger.info("Log created: id=%s application=%s model=%s status=%s", log.id, log.application_id, log.model, log.status)
    return log


async def get_log(session: AsyncSession, log_id: uuid.UUID) -> LLMLog | None:
    """Fetch single log by primary key. Returns None if not found."""
    result = await session.execute(select(LLMLog).where(LLMLog.id == log_id))
    return result.scalar_one_or_none()


async def get_logs(
    session: AsyncSession,
    filters: LLMLogFilter,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[LLMLog], int]:
    """Paginated log listing with optional filters.

    Returns (logs, total_count).
    total_count is the untruncated count (for pagination UI).

    Why build conditions list then and_(*conditions)?
      Avoids "WHERE application_id = NULL" — only add clauses for non-None values.
      and_() with no args = no WHERE clause = return all rows.

    Why count via subquery?
      SELECT COUNT(*) on the filtered base query gives the correct total.
      Simple COUNT(*) without filters gives wrong pagination math.
    """
    base_query = select(LLMLog)

    conditions: list = []
    if filters.application_id is not None:
        conditions.append(LLMLog.application_id == filters.application_id)
    if filters.model is not None:
        conditions.append(LLMLog.model == filters.model)
    if filters.status is not None:
        conditions.append(LLMLog.status == filters.status)
    if filters.start_time is not None:
        conditions.append(LLMLog.created_at >= filters.start_time)
    if filters.end_time is not None:
        conditions.append(LLMLog.created_at <= filters.end_time)

    if conditions:
        base_query = base_query.where(and_(*conditions))

    # Count total matching rows
    count_result = await session.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total: int = count_result.scalar_one()

    # Fetch page
    logs_result = await session.execute(
        base_query
        .order_by(LLMLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = list(logs_result.scalars().all())

    logger.debug("get_logs: total=%d page=%d page_size=%d filters=%s", total, page, page_size, filters.model_dump(exclude_none=True))
    return logs, total
