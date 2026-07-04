"""Pydantic schemas for per-case eval results."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.schemas.eval_run import EvalRunResponse


class EvalResultResponse(BaseModel):
    id: uuid.UUID
    eval_run_id: uuid.UUID
    test_case_id: uuid.UUID
    exact_match_score: float | None
    embedding_score: float | None
    llm_judge_score: float | None
    llm_judge_reasoning: str | None
    passed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvalRunDetail(BaseModel):
    """GET /evals/runs/{id} — run + nested results."""

    run: EvalRunResponse
    results: list[EvalResultResponse]
