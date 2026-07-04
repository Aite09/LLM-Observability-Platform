"""Drift router — alert listing + acknowledge/resolve."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.drift_alert import DriftAlertResponse, DriftAlertUpdate
from api.services import drift_service

router = APIRouter(prefix="/drift", tags=["drift"])


@router.get("/alerts", response_model=PaginatedResponse[DriftAlertResponse])
async def list_alerts(
    status_filter: Literal["open", "acknowledged", "resolved"] | None = Query(None, alias="status"),
    severity: Literal["low", "medium", "high", "critical"] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DriftAlertResponse]:
    alerts, total = await drift_service.list_alerts(session, status_filter, severity, page, page_size)
    return PaginatedResponse[DriftAlertResponse](
        total=total, page=page, page_size=page_size,
        items=[DriftAlertResponse.model_validate(a) for a in alerts],
    )


@router.patch("/alerts/{alert_id}", response_model=DriftAlertResponse)
async def update_alert(
    alert_id: uuid.UUID,
    payload: DriftAlertUpdate,
    session: AsyncSession = Depends(get_db),
) -> DriftAlertResponse:
    alert = await drift_service.update_status(session, alert_id, payload.status)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found")
    return DriftAlertResponse.model_validate(alert)
