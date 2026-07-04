"""Integration tests for /logs API (needs running postgres via docker compose)."""

import pytest
from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_ingest_and_fetch_log(client: AsyncClient) -> None:
    payload = {
        "application_id": "test-app",
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
        "prompt": "What is 2+2?",
        "response": "4",
        "prompt_tokens": 8,
        "completion_tokens": 1,
        "total_tokens": 9,
        "cost_usd": 0.0001,
        "latency_ms": 220,
        "status": "success",
    }
    resp = await client.post("/logs", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]

    resp2 = await client.get(f"/logs/{body['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["prompt"] == "What is 2+2?"


async def test_list_logs_filters(client: AsyncClient) -> None:
    for app_id in ("app-a", "app-a", "app-b"):
        await client.post("/logs", json={
            "application_id": app_id, "model": "m", "provider": "p",
            "prompt": "x", "status": "success",
        })
    resp = await client.get("/logs", params={"application_id": "app-a"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
