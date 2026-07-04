"""
Metrics aggregator — rolls llm_logs up into per-(app, model, period) rows.

One GROUP BY query computes counts, cost, tokens and latency percentiles
(percentile_cont inside the DB — no Python-side sorting), then upserts via
ON CONFLICT DO UPDATE on the (app, model, period_type, period_start) key.
Idempotent: re-running a window overwrites with fresh numbers.

Standalone package: no FastAPI imports.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.llm_log import LLMLog
from api.models.metric import Metric

logger = logging.getLogger(__name__)

_TRUNC = {"hourly": "hour", "daily": "day"}


async def aggregate_window(
    session: AsyncSession,
    period_type: str,
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Aggregate logs in [window_start, window_end) → upserted metric rows.

    Returns number of (app, model, period) rows written.
    """
    if period_type not in _TRUNC:
        raise ValueError(f"period_type must be 'hourly' or 'daily', got {period_type!r}")

    period_start = func.date_trunc(_TRUNC[period_type], LLMLog.created_at).label("period_start")
    lat = LLMLog.latency_ms

    query = (
        select(
            LLMLog.application_id,
            LLMLog.model,
            period_start,
            func.count().label("total_requests"),
            func.count().filter(LLMLog.status == "success").label("successful_requests"),
            func.count().filter(LLMLog.status != "success").label("failed_requests"),
            func.coalesce(func.sum(LLMLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LLMLog.cost_usd), 0).label("total_cost_usd"),
            func.avg(lat).label("avg_latency_ms"),
            cast(func.percentile_cont(0.5).within_group(lat.asc()), Integer).label("p50"),
            cast(func.percentile_cont(0.95).within_group(lat.asc()), Integer).label("p95"),
            cast(func.percentile_cont(0.99).within_group(lat.asc()), Integer).label("p99"),
        )
        .where(LLMLog.created_at >= window_start, LLMLog.created_at < window_end)
        .group_by(LLMLog.application_id, LLMLog.model, period_start)
    )

    rows = (await session.execute(query)).all()
    if not rows:
        logger.debug("aggregate_window: no logs in %s window %s–%s", period_type, window_start, window_end)
        return 0

    for r in rows:
        values = {
            "application_id": r.application_id,
            "model": r.model,
            "period_type": period_type,
            "period_start": r.period_start,
            "total_requests": r.total_requests,
            "successful_requests": r.successful_requests,
            "failed_requests": r.failed_requests,
            "total_tokens": int(r.total_tokens),
            "total_cost_usd": r.total_cost_usd,
            "avg_latency_ms": r.avg_latency_ms,
            "p50_latency_ms": r.p50,
            "p95_latency_ms": r.p95,
            "p99_latency_ms": r.p99,
        }
        stmt = pg_insert(Metric).values(**values).on_conflict_do_update(
            constraint="uq_metrics_app_model_period",
            set_={k: v for k, v in values.items() if k not in ("application_id", "model", "period_type", "period_start")}
            | {"updated_at": func.now()},
        )
        await session.execute(stmt)

    await session.commit()
    logger.info("aggregate_window: %s wrote %d rows for %s–%s", period_type, len(rows), window_start, window_end)
    return len(rows)
