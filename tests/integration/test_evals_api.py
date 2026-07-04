"""Integration tests for eval engine + eval API (real postgres)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.eval_result import EvalResult
from api.models.test_case import TestCase
from eval.engine import run_eval


async def _seed_suite(session: AsyncSession, suite: str) -> None:
    session.add_all([
        TestCase(
            suite_name=suite,
            input_prompt="What is the capital of France?",
            expected_output="Paris",
            eval_methods=["exact_match"],
        ),
        TestCase(
            suite_name=suite,
            input_prompt="Summarize: the sky is blue.",
            expected_output="The sky is blue",
            eval_methods=["embedding_similarity", "llm_judge"],
            similarity_threshold=0.5,
        ),
    ])
    await session.commit()


class TestEngine:
    async def test_run_eval_echo_target_passes_all(self, session: AsyncSession) -> None:
        suite = f"suite-{uuid.uuid4().hex[:8]}"
        await _seed_suite(session, suite)

        run = await run_eval(
            session, suite_name=suite, commit_sha="abc123", triggered_by="test",
            gate_threshold=0.8,
        )

        assert run.total_cases == 2
        assert run.passed_cases == 2
        assert float(run.pass_rate) == pytest.approx(1.0)
        assert run.gate_result == "pass"
        assert run.completed_at is not None

        results = (await session.execute(
            select(EvalResult).where(EvalResult.eval_run_id == run.id)
        )).scalars().all()
        assert len(results) == 2
        exact = next(r for r in results if r.exact_match_score is not None)
        assert float(exact.exact_match_score) == 1.0
        judged = next(r for r in results if r.llm_judge_score is not None)
        assert judged.llm_judge_reasoning  # mock judge writes reasoning

    async def test_unknown_suite_raises(self, session: AsyncSession) -> None:
        with pytest.raises(ValueError, match="No test cases"):
            await run_eval(session, suite_name="nope", commit_sha="x", triggered_by="test", gate_threshold=0.8)
