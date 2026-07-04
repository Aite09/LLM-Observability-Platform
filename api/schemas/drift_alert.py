"""Pydantic schemas for drift alerts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DriftAlertResponse(BaseModel):
    id: uuid.UUID
    application_id: str
    drift_type: str
    severity: Literal["low", "medium", "high", "critical"]
    drift_score: float
    baseline_stats: dict
    current_stats: dict
    status: Literal["open", "acknowledged", "resolved"]
    detected_at: datetime
    resolved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriftAlertUpdate(BaseModel):
    """PATCH body — lifecycle transitions only."""

    status: Literal["acknowledged", "resolved"]
