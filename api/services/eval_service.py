"""Eval service — business logic for test cases and eval runs."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.eval_result import EvalResult
from api.models.eval_run import EvalRun
from api.models.test_case import TestCase
from api.schemas.test_case import TestCaseCreate

logger = logging.getLogger(__name__)


async def create_test_case(session: AsyncSession, data: TestCaseCreate) -> TestCase:
    case = TestCase(**data.model_dump())
    session.add(case)
    await session.commit()
    await session.refresh(case)
    logger.info("Test case created: id=%s suite=%s", case.id, case.suite_name)
    return case


async def list_test_cases(
    session: AsyncSession, suite_name: str | None, page: int, page_size: int
) -> tuple[list[TestCase], int]:
    query = select(TestCase)
    if suite_name is not None:
        query = query.where(TestCase.suite_name == suite_name)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(TestCase.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def list_eval_runs(
    session: AsyncSession, suite_name: str | None, page: int, page_size: int
) -> tuple[list[EvalRun], int]:
    query = select(EvalRun)
    if suite_name is not None:
        query = query.where(EvalRun.suite_name == suite_name)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(EvalRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def get_run_with_results(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[EvalRun, list[EvalResult]] | None:
    run = (await session.execute(select(EvalRun).where(EvalRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return None
    results = (
        await session.execute(
            select(EvalResult).where(EvalResult.eval_run_id == run_id).order_by(EvalResult.created_at)
        )
    ).scalars().all()
    return run, list(results)
