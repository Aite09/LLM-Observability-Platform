"""Integration tests for drift detection + drift API."""

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.drift_alert import DriftAlert
from api.models.llm_log import LLMLog
from monitor.drift_detector import detect_drift_for_app


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _embedded_log(app: str, ts: datetime, vec: list[float]) -> LLMLog:
    return LLMLog(
        application_id=app, model="m", provider="p", prompt="p", status="success",
        created_at=ts, prompt_embedding=vec,
    )


async def _seed_drifted_app(session: AsyncSession, app: str) -> None:
    rng = np.random.RandomState(42)
    now = _now()

    def unit(v: np.ndarray) -> list[float]:
        return (v / np.linalg.norm(v)).tolist()

    base_center = rng.normal(size=384)
    for i in range(60):  # baseline: 2-7 days ago, clustered
        vec = unit(base_center + rng.normal(scale=0.05, size=384))
        session.add(_embedded_log(app, now - timedelta(days=2, hours=i), vec))

    shifted_center = rng.normal(size=384)  # independent direction = far away
    for i in range(25):  # current: last 24h, different cluster
        vec = unit(shifted_center + rng.normal(scale=0.05, size=384))
        session.add(_embedded_log(app, now - timedelta(hours=i % 23), vec))
    await session.commit()


class TestDetector:
    async def test_detects_and_persists_alert(self, session: AsyncSession) -> None:
        app = f"drift-{uuid.uuid4().hex[:8]}"
        await _seed_drifted_app(session, app)

        alert = await detect_drift_for_app(session, app)

        assert alert is not None
        assert alert.severity in ("medium", "high", "critical")
        assert float(alert.drift_score) > 0.25
        assert alert.baseline_stats["sample_count"] == 60
        assert alert.current_stats["sample_count"] == 25

    async def test_dedup_same_severity_open_alert(self, session: AsyncSession) -> None:
        app = f"drift-{uuid.uuid4().hex[:8]}"
        await _seed_drifted_app(session, app)

        first = await detect_drift_for_app(session, app)
        second = await detect_drift_for_app(session, app)

        assert first is not None
        assert second is None  # deduped
        count = len((await session.execute(
            select(DriftAlert).where(DriftAlert.application_id == app)
        )).scalars().all())
        assert count == 1

    async def test_insufficient_baseline_skips(self, session: AsyncSession) -> None:
        app = f"tiny-{uuid.uuid4().hex[:8]}"
        session.add(_embedded_log(app, _now() - timedelta(days=3), [0.1] * 384))
        await session.commit()
        assert await detect_drift_for_app(session, app) is None
