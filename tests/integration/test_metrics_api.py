"""Integration tests for metrics aggregation + API."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.llm_log import LLMLog
from api.models.metric import Metric
from monitor.metrics_aggregator import aggregate_window


def _log(app: str, model: str, ts: datetime, latency: int, cost: float, ok: bool = True) -> LLMLog:
    return LLMLog(
        application_id=app, model=model, provider="test", prompt="p",
        response="r" if ok else None, status="success" if ok else "error",
        latency_ms=latency, cost_usd=cost, total_tokens=100,
        created_at=ts,
    )


class TestAggregator:
    async def test_hourly_rollup_counts_and_percentiles(self, session: AsyncSession) -> None:
        base = datetime(2026, 7, 1, 14, 0, 0)
        latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        for lat in latencies:
            session.add(_log("app-x", "model-a", base + timedelta(minutes=5), lat, 0.01))
        session.add(_log("app-x", "model-a", base + timedelta(minutes=10), 999, 0.02, ok=False))
        await session.commit()

        await aggregate_window(session, "hourly", base, base + timedelta(hours=1))

        m = (await session.execute(
            select(Metric).where(Metric.application_id == "app-x", Metric.period_type == "hourly")
        )).scalar_one()
        assert m.total_requests == 11
        assert m.successful_requests == 10
        assert m.failed_requests == 1
        assert m.p50_latency_ms == pytest.approx(550, abs=60)
        assert m.p95_latency_ms >= 900
        assert float(m.total_cost_usd) == pytest.approx(0.12, abs=1e-6)

    async def test_rerun_is_idempotent_upsert(self, session: AsyncSession) -> None:
        base = datetime(2026, 7, 1, 9, 0, 0)
        session.add(_log("app-y", "model-b", base + timedelta(minutes=1), 100, 0.01))
        await session.commit()

        await aggregate_window(session, "hourly", base, base + timedelta(hours=1))
        session.add(_log("app-y", "model-b", base + timedelta(minutes=2), 300, 0.01))
        await session.commit()
        await aggregate_window(session, "hourly", base, base + timedelta(hours=1))

        rows = (await session.execute(
            select(Metric).where(Metric.application_id == "app-y")
        )).scalars().all()
        assert len(rows) == 1          # upsert, not duplicate
        assert rows[0].total_requests == 2


class TestMetricsAPI:
    async def test_list_metrics_filters(self, client: AsyncClient, session: AsyncSession) -> None:
        base = datetime(2026, 7, 1, 8, 0, 0)
        session.add(_log("app-m", "model-a", base, 100, 0.05))
        await session.commit()
        await aggregate_window(session, "hourly", base, base + timedelta(hours=1))

        resp = await client.get("/metrics", params={"application_id": "app-m", "period_type": "hourly"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["total_requests"] == 1

    async def test_summary_shape(self, client: AsyncClient, session: AsyncSession) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(_log("app-s", "model-a", now - timedelta(hours=1), 200, 0.10))
        session.add(_log("app-s", "model-a", now - timedelta(hours=2), 400, 0.20, ok=False))
        await session.commit()
        await aggregate_window(session, "hourly", now - timedelta(hours=3), now)

        resp = await client.get("/metrics/summary", params={"window": "24h"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_requests"] == 2
        assert body["total_cost_usd"] == pytest.approx(0.30, abs=1e-6)
        assert body["error_rate"] == pytest.approx(0.5)
        assert "p95_latency_ms" in body

    async def test_summary_rejects_bad_window(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics/summary", params={"window": "5y"})
        assert resp.status_code == 422
