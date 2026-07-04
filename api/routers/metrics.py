"""Metrics router — rollup listing + dashboard summary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.metric import MetricResponse, MetricsSummary
from api.services import metric_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummary)
async def get_summary(
    window: Literal["24h", "7d", "30d"] = Query("24h"),
    session: AsyncSession = Depends(get_db),
) -> MetricsSummary:
    return await metric_service.summary(session, window)


@router.get("", response_model=PaginatedResponse[MetricResponse])
async def list_metrics(
    application_id: str | None = Query(None),
    model: str | None = Query(None),
    period_type: Literal["hourly", "daily"] | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MetricResponse]:
    rows, total = await metric_service.list_metrics(
        session, application_id, model, period_type, start, end, page, page_size
    )
    return PaginatedResponse[MetricResponse](
        total=total, page=page, page_size=page_size,
        items=[MetricResponse.model_validate(m) for m in rows],
    )
