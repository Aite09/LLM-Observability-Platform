"""Drift service — alert listing + lifecycle transitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.drift_alert import DriftAlert

logger = logging.getLogger(__name__)


async def list_alerts(
    session: AsyncSession,
    status: str | None,
    severity: str | None,
    page: int,
    page_size: int,
) -> tuple[list[DriftAlert], int]:
    query = select(DriftAlert)
    if status is not None:
        query = query.where(DriftAlert.status == status)
    if severity is not None:
        query = query.where(DriftAlert.severity == severity)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(DriftAlert.detected_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def update_status(
    session: AsyncSession, alert_id: uuid.UUID, new_status: str
) -> DriftAlert | None:
    alert = (
        await session.execute(select(DriftAlert).where(DriftAlert.id == alert_id))
    ).scalar_one_or_none()
    if alert is None:
        return None
    alert.status = new_status
    alert.resolved_at = (
        datetime.now(timezone.utc).replace(tzinfo=None) if new_status == "resolved" else None
    )
    await session.commit()
    await session.refresh(alert)
    logger.info("Drift alert %s → %s", alert_id, new_status)
    return alert
