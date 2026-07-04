"""Pydantic schemas for test-case CRUD (API contract only — no Column())."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvalMethod = Literal["exact_match", "embedding_similarity", "llm_judge"]


class TestCaseCreate(BaseModel):
    suite_name: str = Field(..., max_length=255)
    input_prompt: str
    expected_output: str
    eval_methods: list[EvalMethod] = Field(..., min_length=1)
    similarity_threshold: float = Field(0.85, ge=0.0, le=1.0)


class TestCaseResponse(TestCaseCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
