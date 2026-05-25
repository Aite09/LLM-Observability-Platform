"""
Pydantic schemas for LLM log ingestion and querying.

Three distinct classes — never collapse them:
  LLMLogCreate   → API request body (what client sends)
  LLMLogResponse → API response (what client receives, includes id + created_at)
  LLMLogFilter   → validated query params for GET /logs

Why separate from ORM model?
  SQLAlchemy models map to DB columns.
  Pydantic schemas define the API contract.
  Merging them couples DB schema to API shape — bad when either needs to change.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMLogCreate(BaseModel):
    """Request body for POST /logs."""

    application_id: str = Field(..., max_length=255, description="Identifies the calling application")
    model: str = Field(..., max_length=100, description="e.g. gpt-4o, claude-3-5-sonnet")
    provider: str = Field(..., max_length=50, description="e.g. openai, anthropic, bedrock")
    prompt: str = Field(..., description="Full prompt text sent to the LLM")
    response: str | None = Field(None, description="LLM response text (None on error/timeout)")

    # Token counts
    prompt_tokens: int | None = Field(None, ge=0)
    completion_tokens: int | None = Field(None, ge=0)
    total_tokens: int | None = Field(None, ge=0)

    # Cost
    cost_usd: float | None = Field(None, ge=0, description="Inferred or reported cost in USD")

    # Latency
    latency_ms: int | None = Field(None, ge=0, description="Total round-trip latency in ms")
    time_to_first_token_ms: int | None = Field(None, ge=0, description="Time to first token (streaming)")

    # Status — Literal validates at API boundary, bad value → 422 before touching DB
    status: Literal["success", "error", "timeout"]

    # OpenTelemetry correlation IDs — 32-char trace_id, 16-char span_id
    otel_trace_id: str | None = Field(None, max_length=32)
    otel_span_id: str | None = Field(None, max_length=16)

    # Arbitrary key-value metadata
    tags: dict | None = None


class LLMLogResponse(LLMLogCreate):
    """Response body for POST /logs and items in GET /logs.

    Extends LLMLogCreate with server-generated fields.
    from_attributes=True: Pydantic reads from SQLAlchemy model attributes,
    not from a dict. Enables LLMLogResponse.model_validate(orm_instance).
    """

    id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LLMLogFilter(BaseModel):
    """Validated query parameters for GET /logs.

    All optional — only non-None values become WHERE clauses.
    Pydantic validates types/formats before they reach the service layer.
    """

    application_id: str | None = None
    model: str | None = None
    status: Literal["success", "error", "timeout"] | None = None
    start_time: datetime | None = Field(None, description="Inclusive lower bound on created_at")
    end_time: datetime | None = Field(None, description="Inclusive upper bound on created_at")
