"""Metric service — rollup queries + KPI summary for the dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.drift_alert import DriftAlert
from api.models.metric import Metric
from api.schemas.metric import MetricsSummary

logger = logging.getLogger(__name__)

_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


async def list_metrics(
    session: AsyncSession,
    application_id: str | None,
    model: str | None,
    period_type: str | None,
    start: datetime | None,
    end: datetime | None,
    page: int,
    page_size: int,
) -> tuple[list[Metric], int]:
    query = select(Metric)
    if application_id is not None:
        query = query.where(Metric.application_id == application_id)
    if model is not None:
        query = query.where(Metric.model == model)
    if period_type is not None:
        query = query.where(Metric.period_type == period_type)
    if start is not None:
        query = query.where(Metric.period_start >= start)
    if end is not None:
        query = query.where(Metric.period_start <= end)

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(Metric.period_start.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def _window_totals(session: AsyncSession, start: datetime, end: datetime) -> tuple[int, int, float]:
    """(total_requests, failed_requests, total_cost) over hourly rollups in window."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(Metric.total_requests), 0),
                func.coalesce(func.sum(Metric.failed_requests), 0),
                func.coalesce(func.sum(Metric.total_cost_usd), 0),
            ).where(
                Metric.period_type == "hourly",
                Metric.period_start >= start,
                Metric.period_start < end,
            )
        )
    ).one()
    return int(row[0]), int(row[1]), float(row[2])


async def summary(session: AsyncSession, window: str) -> MetricsSummary:
    """KPIs across all apps. Percentiles: request-weighted percentile-of-rollups
    approximation (documented tradeoff — exact percentiles would need raw logs)."""
    span = _WINDOWS[window]
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive-UTC to match columns
    start = now - span

    total, failed, cost = await _window_totals(session, start, now)
    prev_total_cost = (await _window_totals(session, start - span, start))[2]

    pct_row = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(Metric.p50_latency_ms.asc()),
                func.percentile_cont(0.5).within_group(Metric.p95_latency_ms.asc()),
                func.percentile_cont(0.5).within_group(Metric.p99_latency_ms.asc()),
            ).where(
                Metric.period_type == "hourly",
                Metric.period_start >= start,
                Metric.p50_latency_ms.is_not(None),
            )
        )
    ).one()

    open_alerts = (
        await session.execute(
            select(func.count()).select_from(DriftAlert).where(DriftAlert.status == "open")
        )
    ).scalar_one()

    return MetricsSummary(
        window=window,  # type: ignore[arg-type]
        total_requests=total,
        total_cost_usd=round(cost, 6),
        error_rate=round(failed / total, 4) if total else 0.0,
        p50_latency_ms=int(pct_row[0]) if pct_row[0] is not None else None,
        p95_latency_ms=int(pct_row[1]) if pct_row[1] is not None else None,
        p99_latency_ms=int(pct_row[2]) if pct_row[2] is not None else None,
        cost_prev_window_usd=round(prev_total_cost, 6),
        open_drift_alerts=int(open_alerts),
    )
