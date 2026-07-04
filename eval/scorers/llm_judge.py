"""
LLM-judge scorer — rates actual output against expected, 0.0–1.0.

Two providers, selected per call (default from settings):
  mock       Deterministic token-overlap heuristic (Jaccard). $0, repeatable.
             The default everywhere: demo, tests, CI.
  anthropic  Claude judge (judge_model setting). Only used when the user
             explicitly sets JUDGE_PROVIDER=anthropic + ANTHROPIC_API_KEY.
             Retries x3 with exponential backoff.

No FastAPI imports. Plain exceptions only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from api.config import get_settings

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are an impartial evaluator. Compare the ACTUAL output to the EXPECTED output.
Score how well ACTUAL preserves the meaning and key facts of EXPECTED.

EXPECTED:
{expected}

ACTUAL:
{actual}

Respond with ONLY a JSON object: {{"score": <float 0.0-1.0>, "reasoning": "<one sentence>"}}"""


@dataclass(frozen=True)
class JudgeResult:
    score: float
    reasoning: str


def _get_anthropic_client():  # noqa: ANN202 — anthropic types not imported at module load
    """Lazy client factory — patchable in tests, never constructed in mock mode."""
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(api_key=get_settings().anthropic_api_key)


def _mock_judge(expected: str, actual: str) -> JudgeResult:
    """Deterministic heuristic: Jaccard overlap of lowercase word sets."""
    tok = lambda s: set(re.findall(r"[a-z0-9']+", s.lower()))  # noqa: E731
    e, a = tok(expected), tok(actual)
    if not e and not a:
        return JudgeResult(1.0, "mock judge: both outputs empty")
    if not e or not a:
        return JudgeResult(0.0, "mock judge: one output empty")
    jaccard = len(e & a) / len(e | a)
    return JudgeResult(round(jaccard, 3), f"mock judge: token overlap {jaccard:.2f}")


async def _anthropic_judge(expected: str, actual: str) -> JudgeResult:
    settings = get_settings()
    client = _get_anthropic_client()
    prompt = _JUDGE_PROMPT.format(expected=expected, actual=actual)

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            msg = await client.messages.create(
                model=settings.judge_model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text
            try:
                data = json.loads(text)
                return JudgeResult(
                    score=max(0.0, min(1.0, float(data["score"]))),
                    reasoning=str(data.get("reasoning", "")),
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as parse_exc:
                logger.warning("Judge response unparseable: %s", parse_exc)
                return JudgeResult(0.0, f"could not parse judge response: {text[:100]}")
        except Exception as exc:  # noqa: BLE001 — network/API errors retry
            last_error = exc
            wait = 2**attempt
            logger.warning("Judge attempt %d failed (%s); retrying in %ds", attempt + 1, exc, wait)
            await asyncio.sleep(wait)

    raise RuntimeError(f"LLM judge failed after 3 attempts: {last_error}")


async def judge(expected: str, actual: str, provider: str | None = None) -> JudgeResult:
    """Score actual vs expected. provider=None → settings.judge_provider."""
    selected = provider or get_settings().judge_provider
    if selected == "anthropic":
        return await _anthropic_judge(expected, actual)
    return _mock_judge(expected, actual)
