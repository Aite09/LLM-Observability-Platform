"""
Demo data seeder — realistic 7-day traffic, drift event, eval history. $0.

    python -m scripts.seed [--reset]

Generates:
  ~3000 llm_logs across 3 apps / 4 models — lognormal latency, per-model
    cost curves, 6% error rate, REAL local embeddings (fastembed) so drift
    detection works on seeded data
  Topic shift on day 6-7 for chatbot-prod → the drift detector genuinely fires
  Eval suite "core" (10 cases) + 3 eval runs with per-case results (2 pass, 1 fail)
  Hourly + daily metric rollups (calls the real aggregator)
  One open drift alert (via the real detector — severity reflects the genuine
    embedding-cluster distance, typically low/medium for real text)

Idempotent: --reset truncates all tables first; without it, re-running adds data.
Runtime: <2 min on a laptop (embeddings batched).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from api.dependencies import async_session_maker, engine
from api.models.base import Base
from api.models.eval_result import EvalResult
from api.models.eval_run import EvalRun
from api.models.llm_log import LLMLog
from api.models.test_case import TestCase
from eval.scorers.embedding_backend import embed_texts
from monitor.drift_detector import detect_drift_for_app
from monitor.metrics_aggregator import aggregate_window

logger = logging.getLogger(__name__)
rng = random.Random(1337)


def _now() -> datetime:
    """Naive-UTC now — matches the DB's timezone-naive timestamp columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


APPS = ["chatbot-prod", "support-bot", "summarizer"]
MODELS = [
    # (model, provider, cost per 1k total tokens, latency median ms)
    ("claude-sonnet-5", "anthropic", 0.009, 900),
    ("claude-haiku-4-5", "anthropic", 0.003, 350),
    ("gpt-4o", "openai", 0.0125, 800),
    ("gpt-4o-mini", "openai", 0.000375, 300),
]

BASE_PROMPTS = [
    "How do I reset my password?",
    "What is the refund policy for annual plans?",
    "Summarize this support ticket about login failures",
    "My invoice shows a duplicate charge, can you help?",
    "How do I export my data to CSV?",
    "What are the API rate limits on the pro tier?",
    "The mobile app crashes when I open settings",
    "How do I add a team member to my workspace?",
    "Can I change my subscription from monthly to annual?",
    "Where do I find my API keys?",
]

# Day 6-7 topic shift for chatbot-prod — different domain = embedding drift
DRIFT_PROMPTS = [
    "Compare the nutritional value of quinoa and brown rice",
    "What is the best training plan for a first marathon?",
    "Explain how mortgage interest deduction works",
    "Recommend a beginner woodworking project",
    "How do solar panels perform in cloudy climates?",
    "What vaccinations does a puppy need in year one?",
]


def _make_log(app: str, ts: datetime, prompt: str, embedding: list[float]) -> LLMLog:
    model, provider, cost_per_1k, lat_median = rng.choice(MODELS)
    status = rng.choices(["success", "error", "timeout"], weights=[94, 4, 2])[0]
    prompt_toks = rng.randint(50, 600)
    completion_toks = rng.randint(20, 800) if status == "success" else 0
    total = prompt_toks + completion_toks
    latency = int(rng.lognormvariate(0, 0.45) * lat_median)
    if status == "timeout":
        latency = 30_000
    return LLMLog(
        application_id=app,
        model=model,
        provider=provider,
        prompt=prompt,
        response=f"[seeded response for: {prompt[:40]}…]" if status == "success" else None,
        prompt_tokens=prompt_toks,
        completion_tokens=completion_toks,
        total_tokens=total,
        cost_usd=round(total / 1000 * cost_per_1k, 6),
        latency_ms=latency,
        time_to_first_token_ms=int(latency * rng.uniform(0.1, 0.4)),
        status=status,
        otel_trace_id=uuid.uuid4().hex,
        otel_span_id=uuid.uuid4().hex[:16],
        tags={"seed": True, "env": "demo"},
        created_at=ts,
        prompt_embedding=embedding,
    )


async def seed_logs() -> None:
    """~3000 logs over 7 days; chatbot-prod drifts on days 6-7."""
    now = _now()
    texts: list[str] = []
    slots: list[tuple[str, datetime]] = []

    for day in range(7, 0, -1):
        for app in APPS:
            n = rng.randint(120, 170)
            for _ in range(n):
                ts = now - timedelta(days=day) + timedelta(seconds=rng.randint(0, 86_399))
                # Only the current 24h window (day 1) drifts, and fully — this keeps
                # the baseline (days 2-7) a clean support-topic cluster so the shift
                # is unambiguous and the real detector clears its alerting floor.
                drifting = app == "chatbot-prod" and day == 1
                pool = DRIFT_PROMPTS if drifting else BASE_PROMPTS
                texts.append(rng.choice(pool) + f" (ref #{rng.randint(1000, 9999)})")
                slots.append((app, ts))

    logger.info("Embedding %d prompts locally (batched)…", len(texts))
    embeddings = embed_texts(texts)  # one batched pass — the slow step, ~60s

    async with async_session_maker() as session:
        for (app, ts), text_, vec in zip(slots, texts, embeddings, strict=True):
            session.add(_make_log(app, ts, text_, vec.tolist()))
        await session.commit()
    logger.info("Seeded %d logs", len(texts))


async def seed_evals() -> None:
    """Suite 'core' + 3 historical runs (pass, pass, fail)."""
    async with async_session_maker() as session:
        cases = [
            TestCase(
                suite_name="core",
                input_prompt=p,
                expected_output=f"Expected answer for: {p}",
                eval_methods=["exact_match", "embedding_similarity"],
                similarity_threshold=0.80,
            )
            for p in BASE_PROMPTS
        ]
        session.add_all(cases)
        await session.commit()
        for c in cases:
            await session.refresh(c)

        now = _now()
        run_specs = [  # (age_days, passed_of_10, gate)
            (3, 10, "pass"),
            (2, 9, "pass"),
            (1, 6, "fail"),
        ]
        for age, passed, gate in run_specs:
            run = EvalRun(
                suite_name="core",
                commit_sha=uuid.uuid4().hex[:12],
                triggered_by="seed",
                total_cases=10,
                passed_cases=passed,
                pass_rate=passed / 10,
                gate_threshold=0.8,
                gate_result=gate,
                started_at=now - timedelta(days=age, minutes=5),
                completed_at=now - timedelta(days=age),
                created_at=now - timedelta(days=age),
            )
            session.add(run)
            await session.flush()
            for i, c in enumerate(cases):
                ok = i < passed
                session.add(EvalResult(
                    eval_run_id=run.id,
                    test_case_id=c.id,
                    exact_match_score=1.0 if ok else 0.0,
                    embedding_score=round(rng.uniform(0.86, 0.99) if ok else rng.uniform(0.35, 0.7), 3),
                    passed=ok,
                    created_at=now - timedelta(days=age),
                ))
        await session.commit()
    logger.info("Seeded eval suite 'core' + 3 runs")


async def seed_rollups_and_drift() -> None:
    """Run the REAL aggregator + detector over seeded data."""
    now = _now()
    async with async_session_maker() as session:
        await aggregate_window(session, "hourly", now - timedelta(days=8), now)
        await aggregate_window(session, "daily", now - timedelta(days=8), now)
        alert = await detect_drift_for_app(session, "chatbot-prod")
        if alert is None:
            logger.warning("Drift alert did not fire — check DRIFT_* thresholds")
        else:
            logger.info("Drift alert seeded: %s score=%.4f", alert.severity, float(alert.drift_score))


async def reset_db() -> None:
    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    logger.info("All tables truncated")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.seed")
    parser.add_argument("--reset", action="store_true", help="truncate all tables first")
    args = parser.parse_args(argv)

    if args.reset:
        await reset_db()
    await seed_logs()
    await seed_evals()
    await seed_rollups_and_drift()
    await engine.dispose()
    print("Seed complete → open http://localhost:5173")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    sys.exit(asyncio.run(main()))
