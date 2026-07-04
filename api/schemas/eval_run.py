"""Pydantic schemas for eval runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvalRunTrigger(BaseModel):
    """Request body for POST /evals/run."""

    suite_name: str = Field(..., max_length=255)
    commit_sha: str = Field("manual", max_length=40)


class EvalRunResponse(BaseModel):
    id: uuid.UUID
    suite_name: str
    commit_sha: str
    triggered_by: str
    total_cases: int
    passed_cases: int
    pass_rate: float | None
    gate_threshold: float
    gate_result: Literal["pass", "fail"] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvalRunQueued(BaseModel):
    """Response for POST /evals/run — job accepted, not yet complete."""

    job_id: str
    status: Literal["queued"] = "queued"
