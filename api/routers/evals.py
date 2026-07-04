"""Eval routers — test-case CRUD + eval run trigger/listing. No business logic."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.eval_result import EvalResultResponse, EvalRunDetail
from api.schemas.eval_run import EvalRunQueued, EvalRunResponse, EvalRunTrigger
from api.schemas.test_case import TestCaseCreate, TestCaseResponse
from api.services import eval_service

logger = logging.getLogger(__name__)

test_cases_router = APIRouter(prefix="/test-cases", tags=["test-cases"])
evals_router = APIRouter(prefix="/evals", tags=["evals"])


@test_cases_router.post("", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    payload: TestCaseCreate,
    session: AsyncSession = Depends(get_db),
) -> TestCaseResponse:
    case = await eval_service.create_test_case(session, payload)
    return TestCaseResponse.model_validate(case)


@test_cases_router.get("", response_model=PaginatedResponse[TestCaseResponse])
async def list_test_cases(
    suite_name: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TestCaseResponse]:
    cases, total = await eval_service.list_test_cases(session, suite_name, page, page_size)
    return PaginatedResponse[TestCaseResponse](
        total=total, page=page, page_size=page_size,
        items=[TestCaseResponse.model_validate(c) for c in cases],
    )


@evals_router.post("/run", response_model=EvalRunQueued, status_code=status.HTTP_202_ACCEPTED)
async def trigger_eval_run(payload: EvalRunTrigger) -> EvalRunQueued:
    """Enqueue an eval run. Worker executes it; poll GET /evals/runs for the result."""
    try:
        from workers.eval_worker import enqueue_eval_run

        job_id = enqueue_eval_run(payload.suite_name, payload.commit_sha)
    except Exception as exc:  # Redis down → 503, honest signal
        logger.error("Could not enqueue eval run: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Eval queue unavailable")
    return EvalRunQueued(job_id=job_id)


@evals_router.get("/runs", response_model=PaginatedResponse[EvalRunResponse])
async def list_runs(
    suite_name: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EvalRunResponse]:
    runs, total = await eval_service.list_eval_runs(session, suite_name, page, page_size)
    return PaginatedResponse[EvalRunResponse](
        total=total, page=page, page_size=page_size,
        items=[EvalRunResponse.model_validate(r) for r in runs],
    )


@evals_router.get("/runs/{run_id}", response_model=EvalRunDetail)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> EvalRunDetail:
    pair = await eval_service.get_run_with_results(session, run_id)
    if pair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Eval run {run_id} not found")
    run, results = pair
    return EvalRunDetail(
        run=EvalRunResponse.model_validate(run),
        results=[EvalResultResponse.model_validate(r) for r in results],
    )
