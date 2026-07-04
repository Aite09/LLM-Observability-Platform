"""Pydantic schemas for metrics endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MetricResponse(BaseModel):
    id: uuid.UUID
    application_id: str
    model: str
    period_type: Literal["hourly", "daily"]
    period_start: datetime
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float | None
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    p99_latency_ms: int | None

    model_config = ConfigDict(from_attributes=True)


class MetricsSummary(BaseModel):
    """Dashboard KPI block — computed across rollups for a time window."""

    window: Literal["24h", "7d", "30d"]
    total_requests: int
    total_cost_usd: float
    error_rate: float                 # failed / total, 0 when no traffic
    p50_latency_ms: int | None        # request-weighted approximations
    p95_latency_ms: int | None
    p99_latency_ms: int | None
    cost_prev_window_usd: float       # same-length window immediately before
    open_drift_alerts: int
