"""
Eval engine — orchestrates one full eval run for a suite.

Flow:
  load test cases → for each: generate candidate output (target fn)
  → run each configured scorer → case passes iff ALL its methods pass
  → persist EvalRun + EvalResults in one transaction → return the run.

Target function: the system-under-test. Production integrations pass a
real async generate_fn(prompt) -> str. The default EchoTarget returns the
expected output — deterministic plumbing-proof for demo and CI. This is
intentional and documented: the gate demonstrates the full machinery;
plugging a real target is a one-liner.

Standalone package: no FastAPI imports; raises plain ValueError.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.eval_result import EvalResult
from api.models.eval_run import EvalRun
from api.models.test_case import TestCase
from eval.scorers import exact_match
from eval.scorers.llm_judge import judge

logger = logging.getLogger(__name__)

# Judge pass bar (spec): fixed 0.7. Embedding bar is per-case similarity_threshold.
JUDGE_PASS_THRESHOLD = 0.7

TargetFn = Callable[[str], Awaitable[str]]


async def echo_target_factory(expected: str) -> str:
    """See module docstring — demo target echoes the expected output."""
    return expected


async def run_eval(
    session: AsyncSession,
    suite_name: str,
    commit_sha: str,
    triggered_by: str,
    gate_threshold: float,
    generate_fn: TargetFn | None = None,
) -> EvalRun:
    """Execute the suite and persist run + per-case results. Returns the run."""
    cases = (
        await session.execute(select(TestCase).where(TestCase.suite_name == suite_name))
    ).scalars().all()
    if not cases:
        raise ValueError(f"No test cases found for suite {suite_name!r}")

    started = datetime.now(timezone.utc).replace(tzinfo=None)  # columns are naive-UTC
    run = EvalRun(
        suite_name=suite_name,
        commit_sha=commit_sha,
        triggered_by=triggered_by,
        total_cases=len(cases),
        gate_threshold=gate_threshold,
        started_at=started,
    )
    session.add(run)
    await session.flush()  # populate run.id for FK references, still uncommitted

    passed_count = 0
    for case in cases:
        # 1. Candidate output from the target under test
        if generate_fn is not None:
            actual = await generate_fn(case.input_prompt)
        else:
            actual = await echo_target_factory(case.expected_output)

        # 2. Run configured scorers; a scorer crash fails the case, not the run
        result = EvalResult(eval_run_id=run.id, test_case_id=case.id, passed=False)
        method_passes: list[bool] = []
        try:
            for method in case.eval_methods:
                if method == "exact_match":
                    s = exact_match.score(case.expected_output, actual)
                    result.exact_match_score = s
                    method_passes.append(s == 1.0)
                elif method == "embedding_similarity":
                    # Import here: keeps engine importable without ONNX model
                    from eval.scorers import embedding_similarity

                    s = embedding_similarity.score(case.expected_output, actual)
                    result.embedding_score = s
                    method_passes.append(s >= float(case.similarity_threshold))
                elif method == "llm_judge":
                    jr = await judge(case.expected_output, actual)
                    result.llm_judge_score = jr.score
                    result.llm_judge_reasoning = jr.reasoning
                    method_passes.append(jr.score >= JUDGE_PASS_THRESHOLD)
                else:
                    logger.warning("Unknown eval method %r on case %s — counted as fail", method, case.id)
                    method_passes.append(False)
        except Exception as exc:  # noqa: BLE001 — scorer failure = case failure
            logger.error("Scorer error on case %s: %s", case.id, exc)
            method_passes.append(False)

        result.passed = bool(method_passes) and all(method_passes)
        if result.passed:
            passed_count += 1
        session.add(result)

    run.passed_cases = passed_count
    run.pass_rate = round(passed_count / len(cases), 4)
    run.gate_result = "pass" if run.pass_rate >= gate_threshold else "fail"
    run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await session.commit()
    await session.refresh(run)

    from api.observability import eval_runs_total

    eval_runs_total.labels(suite_name, run.gate_result).inc()

    logger.info(
        "Eval run %s: suite=%s %d/%d passed rate=%.4f gate=%s",
        run.id, suite_name, passed_count, len(cases), run.pass_rate, run.gate_result,
    )
    return run
