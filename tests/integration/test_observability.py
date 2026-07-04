"""Prometheus endpoint + custom metric registration."""

from httpx import AsyncClient


async def test_prometheus_endpoint_exposes_custom_metrics(client: AsyncClient) -> None:
    # Ingest one log so the counter has a sample
    await client.post("/logs", json={
        "application_id": "obs-app", "model": "m", "provider": "p",
        "prompt": "x", "status": "success", "cost_usd": 0.01,
    })
    resp = await client.get("/prometheus-metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "llm_logs_ingested_total" in body
    assert "llm_cost_usd_total" in body
    assert "eval_runs_total" in body
    assert "drift_alerts_total" in body
