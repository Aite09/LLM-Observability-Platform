"""Integration tests for drift detection + drift API."""

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from httpx import AsyncClient
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


class TestDriftAPI:
    async def _make_alert(self, session: AsyncSession, app: str = "app-d") -> DriftAlert:
        alert = DriftAlert(
            application_id=app, drift_type="embedding_distribution", severity="high",
            drift_score=0.41, baseline_stats={}, current_stats={}, detected_at=_now(),
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
        return alert

    async def test_list_filters_by_status(self, client: AsyncClient, session: AsyncSession) -> None:
        await self._make_alert(session)
        resp = await client.get("/drift/alerts", params={"status": "open"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_acknowledge_then_resolve(self, client: AsyncClient, session: AsyncSession) -> None:
        alert = await self._make_alert(session)

        ack = await client.patch(f"/drift/alerts/{alert.id}", json={"status": "acknowledged"})
        assert ack.status_code == 200
        assert ack.json()["status"] == "acknowledged"
        assert ack.json()["resolved_at"] is None

        res = await client.patch(f"/drift/alerts/{alert.id}", json={"status": "resolved"})
        assert res.status_code == 200
        assert res.json()["resolved_at"] is not None

    async def test_patch_unknown_404(self, client: AsyncClient) -> None:
        resp = await client.patch(f"/drift/alerts/{uuid.uuid4()}", json={"status": "resolved"})
        assert resp.status_code == 404

    async def test_patch_invalid_status_422(self, client: AsyncClient, session: AsyncSession) -> None:
        alert = await self._make_alert(session)
        resp = await client.patch(f"/drift/alerts/{alert.id}", json={"status": "closed"})
        assert resp.status_code == 422
