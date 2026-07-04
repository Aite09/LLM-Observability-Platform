"""
Eval runner — CLI entry point for the CI/CD gate.

    python -m eval.runner --suite core --commit-sha $GITHUB_SHA [--threshold 0.8]

Exit codes: 0 = gate pass, 1 = gate fail or error. CI blocks merge on non-zero.
Builds its own async engine from settings — no FastAPI app involved.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.config import get_settings
from api.models.eval_result import EvalResult
from api.models.test_case import TestCase
from eval.engine import run_eval

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eval.runner", description="Run an eval suite and gate on pass rate")
    p.add_argument("--suite", required=True, help="Suite name (test_cases.suite_name)")
    p.add_argument("--commit-sha", required=True, help="Git SHA being evaluated")
    p.add_argument("--threshold", type=float, default=None, help="Gate threshold (default: settings.eval_gate_threshold)")
    p.add_argument("--triggered-by", default="ci", help="Recorded on the run (default: ci)")
    return p


async def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    threshold = args.threshold if args.threshold is not None else settings.eval_gate_threshold

    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            run = await run_eval(
                session,
                suite_name=args.suite,
                commit_sha=args.commit_sha,
                triggered_by=args.triggered_by,
                gate_threshold=threshold,
            )
            results = (
                await session.execute(select(EvalResult, TestCase).join(TestCase, EvalResult.test_case_id == TestCase.id).where(EvalResult.eval_run_id == run.id))
            ).all()

        # Human-readable summary table for the CI log
        print(f"\nEval run {run.id} — suite {args.suite} @ {args.commit_sha[:12]}")
        print(f"{'case':<50} {'exact':>6} {'embed':>6} {'judge':>6} {'pass':>5}")
        for result, case in results:
            fmt = lambda v: "-" if v is None else f"{float(v):.2f}"  # noqa: E731
            prompt_short = (case.input_prompt[:47] + "...") if len(case.input_prompt) > 50 else case.input_prompt
            print(f"{prompt_short:<50} {fmt(result.exact_match_score):>6} {fmt(result.embedding_score):>6} {fmt(result.llm_judge_score):>6} {str(result.passed):>5}")
        print(f"\n{run.passed_cases}/{run.total_cases} passed · rate {float(run.pass_rate):.4f} · threshold {threshold} → gate {run.gate_result.upper()}")

        return 0 if run.gate_result == "pass" else 1
    except ValueError as exc:
        print(f"eval.runner error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    sys.exit(asyncio.run(main()))
