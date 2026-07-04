"""Integration tests for eval engine + eval API (real postgres)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.eval_result import EvalResult
from api.models.test_case import TestCase
from eval.engine import run_eval
from eval.runner import main as runner_main


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


class TestRunner:
    async def test_exit_zero_on_pass(self, session: AsyncSession, capsys: pytest.CaptureFixture[str]) -> None:
        suite = f"runner-{uuid.uuid4().hex[:8]}"
        await _seed_suite(session, suite)

        code = await runner_main(["--suite", suite, "--commit-sha", "deadbeef", "--threshold", "0.5"])
        assert code == 0
        out = capsys.readouterr().out
        assert "gate PASS" in out and suite in out

    async def test_exit_one_on_unknown_suite(self) -> None:
        code = await runner_main(["--suite", "does-not-exist", "--commit-sha", "x"])
        assert code == 1


class TestEvalAPI:
    async def test_create_and_list_test_cases(self, client: AsyncClient) -> None:
        payload = {
            "suite_name": "api-suite",
            "input_prompt": "2+2?",
            "expected_output": "4",
            "eval_methods": ["exact_match"],
        }
        resp = await client.post("/test-cases", json=payload)
        assert resp.status_code == 201
        assert resp.json()["similarity_threshold"] == 0.85

        listing = await client.get("/test-cases", params={"suite_name": "api-suite"})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

    async def test_invalid_method_rejected(self, client: AsyncClient) -> None:
        resp = await client.post("/test-cases", json={
            "suite_name": "s", "input_prompt": "p", "expected_output": "o",
            "eval_methods": ["vibes"],
        })
        assert resp.status_code == 422

    async def test_run_listing_and_detail(self, client: AsyncClient, session: AsyncSession) -> None:
        suite = f"api-{uuid.uuid4().hex[:8]}"
        await _seed_suite(session, suite)
        run = await run_eval(session, suite_name=suite, commit_sha="c0ffee", triggered_by="test", gate_threshold=0.8)

        listing = await client.get("/evals/runs", params={"suite_name": suite})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

        detail = await client.get(f"/evals/runs/{run.id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["run"]["gate_result"] == "pass"
        assert len(body["results"]) == 2

    async def test_run_detail_404(self, client: AsyncClient) -> None:
        resp = await client.get(f"/evals/runs/{uuid.uuid4()}")
        assert resp.status_code == 404
