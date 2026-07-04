"""
Drift detector — flags shifts in prompt-embedding distribution.

Method: cosine distance between the baseline centroid (window: 8d→1d ago)
and the current centroid (last 24h). Centroid distance catches mean shift;
the spread ratio in stats surfaces variance change for human review.

Severity ladder (cosine distance): 0.15 low · 0.25 medium · 0.35 high · 0.50 critical.
Dedup: while an `open` alert exists for the app at the same-or-higher
severity, no new alert is inserted (no alert spam on every tick).

Standalone package: no FastAPI imports; plain exceptions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.models.drift_alert import DriftAlert
from api.models.llm_log import LLMLog

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = ["low", "medium", "high", "critical"]
_SEVERITY_THRESHOLDS = [(0.50, "critical"), (0.35, "high"), (0.25, "medium"), (0.15, "low")]


def severity_for(score: float) -> str | None:
    """Map drift score → severity; None when below alerting floor."""
    for threshold, name in _SEVERITY_THRESHOLDS:
        if score >= threshold:
            return name
    return None


def _centroid(vectors: np.ndarray) -> np.ndarray:
    c = vectors.mean(axis=0)
    norm = np.linalg.norm(c)
    return c / norm if norm > 0 else c


def _avg_pairwise_spread(vectors: np.ndarray, sample: int = 100) -> float:
    """Mean cosine distance of a sample of vectors to their centroid — cheap spread proxy."""
    if len(vectors) == 0:
        return 0.0
    take = vectors[: min(sample, len(vectors))]
    c = _centroid(vectors)
    sims = take @ c / (np.linalg.norm(take, axis=1) * np.linalg.norm(c) + 1e-12)
    return float(np.mean(1.0 - sims))


def compute_drift_score(baseline: np.ndarray, current: np.ndarray) -> float:
    """Cosine distance between window centroids ∈ [0, 2]."""
    cb, cc = _centroid(baseline), _centroid(current)
    denom = float(np.linalg.norm(cb) * np.linalg.norm(cc))
    if denom == 0.0:
        return 0.0
    return float(1.0 - (np.dot(cb, cc) / denom))


async def _embeddings_between(
    session: AsyncSession, app: str, start: datetime, end: datetime
) -> np.ndarray:
    rows = (
        await session.execute(
            select(LLMLog.prompt_embedding).where(
                LLMLog.application_id == app,
                LLMLog.prompt_embedding.is_not(None),
                LLMLog.created_at >= start,
                LLMLog.created_at < end,
            )
        )
    ).scalars().all()
    return np.array([np.asarray(r, dtype=np.float32) for r in rows]) if rows else np.empty((0,))


async def detect_drift_for_app(session: AsyncSession, application_id: str) -> DriftAlert | None:
    """Run detection for one app. Returns the created alert, or None (no drift / skipped / deduped)."""
    settings = get_settings()
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive-UTC to match columns

    baseline = await _embeddings_between(
        session, application_id,
        now - timedelta(days=settings.drift_baseline_days + 1), now - timedelta(days=1),
    )
    if len(baseline) < settings.drift_min_baseline:
        logger.debug("drift[%s]: baseline too small (%d)", application_id, len(baseline))
        return None

    current = await _embeddings_between(session, application_id, now - timedelta(days=1), now)
    if len(current) < settings.drift_min_current:
        logger.debug("drift[%s]: current window too small (%d)", application_id, len(current))
        return None

    score = compute_drift_score(baseline, current)
    severity = severity_for(score)
    if severity is None:
        logger.info("drift[%s]: score %.4f below floor — ok", application_id, score)
        return None

    # Dedup: an open alert at same-or-higher severity suppresses a new one
    open_alerts = (
        await session.execute(
            select(DriftAlert.severity).where(
                DriftAlert.application_id == application_id, DriftAlert.status == "open"
            )
        )
    ).scalars().all()
    if any(_SEVERITY_ORDER.index(s) >= _SEVERITY_ORDER.index(severity) for s in open_alerts):
        logger.info("drift[%s]: open %s alert exists — dedup", application_id, severity)
        return None

    alert = DriftAlert(
        application_id=application_id,
        drift_type="embedding_distribution",
        severity=severity,
        drift_score=round(score, 4),
        baseline_stats={
            "sample_count": int(len(baseline)),
            "window_days": [settings.drift_baseline_days + 1, 1],
            "spread": round(_avg_pairwise_spread(baseline), 4),
        },
        current_stats={
            "sample_count": int(len(current)),
            "window_hours": 24,
            "spread": round(_avg_pairwise_spread(current), 4),
        },
        detected_at=now,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)

    from api.observability import drift_alerts_total

    drift_alerts_total.labels(application_id, severity).inc()

    logger.warning("drift[%s]: %s alert, score=%.4f", application_id, severity, score)
    return alert
