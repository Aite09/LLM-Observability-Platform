"""
Logs router — HTTP handlers for LLM log ingestion and retrieval.

POST /logs  → ingest one LLM call record, enqueue embedding job
GET  /logs  → paginated list with optional filters
GET  /logs/{log_id} → single log by UUID

Handler rules (from CLAUDE.md):
  - No business logic here — call service functions
  - No DB queries directly — always through service layer
  - BackgroundTasks for embedding: response returns fast, embedding runs after

Why BackgroundTasks for embedding?
  OpenAI embedding call takes 100-500ms. Client shouldn't wait.
  FastAPI sends the 201 response, THEN runs the background task.
  Embedding is best-effort — log is already persisted regardless.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.llm_log import LLMLogCreate, LLMLogFilter, LLMLogResponse
from api.services import log_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/logs", tags=["logs"])


@router.post(
    "",
    response_model=LLMLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest one LLM call record",
)
async def ingest_log(
    payload: LLMLogCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> LLMLogResponse:
    """
    Record a single LLM API call.

    Returns the persisted log (with id + created_at) immediately.
    Embedding generation runs in the background after the response is sent.
    """
    log = await log_service.create_log(session, payload)

    # Lazy import avoids circular dependency at module load time.
    # Worker import triggers OpenAI client init — only pay that cost when needed.
    try:
        from workers.log_worker import enqueue_embedding_job
        background_tasks.add_task(enqueue_embedding_job, str(log.id))
        logger.debug("Embedding job enqueued for log_id=%s", log.id)
    except Exception as exc:  # noqa: BLE001
        # Worker unavailable (Redis down, missing dep) → log warning, don't fail request
        logger.warning("Could not enqueue embedding job for log_id=%s: %s", log.id, exc)

    return LLMLogResponse.model_validate(log)


@router.get(
    "",
    response_model=PaginatedResponse[LLMLogResponse],
    summary="List LLM logs (paginated, filterable)",
)
async def list_logs(
    application_id: str | None = Query(None, description="Filter by application"),
    model: str | None = Query(None, description="Filter by model name"),
    status_filter: str | None = Query(None, alias="status", description="success | error | timeout"),
    start_time: str | None = Query(None, description="ISO 8601 datetime lower bound on created_at"),
    end_time: str | None = Query(None, description="ISO 8601 datetime upper bound on created_at"),
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[LLMLogResponse]:
    """
    Paginated log listing. All filter params are optional.

    Why `alias="status"` on status_filter?
      `status` is a Python builtin — using it as a parameter name shadows it.
      FastAPI still exposes the query param as `?status=...` via alias.
    """
    from datetime import datetime

    # Parse datetime strings (Query params are strings; Pydantic handles if passed as model)
    parsed_start = datetime.fromisoformat(start_time) if start_time else None
    parsed_end = datetime.fromisoformat(end_time) if end_time else None

    filters = LLMLogFilter(
        application_id=application_id,
        model=model,
        status=status_filter,  # type: ignore[arg-type]
        start_time=parsed_start,
        end_time=parsed_end,
    )

    logs, total = await log_service.get_logs(session, filters, page, page_size)

    return PaginatedResponse[LLMLogResponse](
        total=total,
        page=page,
        page_size=page_size,
        items=[LLMLogResponse.model_validate(log) for log in logs],
    )


@router.get(
    "/{log_id}",
    response_model=LLMLogResponse,
    summary="Get single log by UUID",
)
async def get_log(
    log_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> LLMLogResponse:
    """Fetch a single LLM log by its UUID primary key."""
    log = await log_service.get_log(session, log_id)
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log {log_id} not found",
        )
    return LLMLogResponse.model_validate(log)
