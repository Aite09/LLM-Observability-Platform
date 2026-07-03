# Weeks 3–8 Platform Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the LLM Observability Platform: eval engine + CI gate, metrics aggregation, drift detection + webhooks, React dashboard, Prometheus/OTEL, seed + README — at $0 total cost.

**Architecture:** FastAPI async backend (routers→services→ORM), standalone `eval/` + `monitor/` packages (no FastAPI imports), RQ + loop-daemon workers, React 18 + Vite dashboard with "linen terminal" design system. Embeddings local via fastembed (384-dim). LLM judge defaults to a free deterministic mock provider.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async + asyncpg, pgvector, Redis+RQ, fastembed, anthropic (mock-default), React 18, TypeScript, Vite, Tailwind, Recharts, TanStack Query, Prometheus, OTEL, Alembic.

**Spec:** `docs/superpowers/specs/2026-07-02-weeks-3-8-platform-completion-design.md`

**Hard rules (from CLAUDE.md — apply to every task):** all DB ops async; models≠schemas; eval/ + monitor/ import no FastAPI; config via `get_settings()`; type hints everywhere; Alembic for schema changes; `logging` not print; thin routers.

**Zero-cost rule:** no code path in demo/tests/CI may call a paid API. `JUDGE_PROVIDER=mock` default; fastembed local; no hosted services.

**Design tokens (frontend, from spec):** bg `oklch(0.955 0.015 78)`; sidebar `oklch(0.925 0.018 76)`; hairline `oklch(0.855 0.02 75)`; rule-strong `oklch(0.815 0.022 73)`; ink `oklch(0.36 0.06 48)`; secondary `oklch(0.48 0.048 56)`; faint `oklch(0.60 0.04 62)`; accent `oklch(0.60 0.125 42)`; sage `oklch(0.52 0.085 135)`; rust `oklch(0.55 0.15 30)`. Fonts: Jersey 25 (display), IBM Plex Sans (UI), IBM Plex Mono (data).

---

## Phase 0 — Foundation

### Task 1: Dependencies + config additions

**Files:**
- Modify: `pyproject.toml`
- Modify: `api/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add Python deps to `pyproject.toml`**

In the `dependencies = [` list, replace the line `"openai>=1.30.0",` with:

```toml
    "anthropic>=0.34.0",
    "fastembed>=0.3.0",
```

(openai is removed — embeddings go local, judge goes anthropic/mock.) Then add below the otel lines:

```toml
    "opentelemetry-instrumentation-sqlalchemy>=0.45b0",
```

- [ ] **Step 2: Install**

Run: `source .venv/bin/activate && pip install -e ".[dev]" 2>&1 | tail -3`
Expected: `Successfully installed ...` (fastembed pulls onnxruntime — ~100MB, one time)

- [ ] **Step 3: Extend `api/config.py` Settings**

Replace the `# ── OpenAI ──...` block (`openai_api_key: str = ""`) with:

```python
    # ── LLM Judge (eval scorer) ────────────────────────────────────────────────
    # "mock" = free deterministic heuristic (default — $0 guarantee)
    # "anthropic" = real Claude judge; requires anthropic_api_key
    judge_provider: str = "mock"
    judge_model: str = "claude-haiku-4-5"
    anthropic_api_key: str = ""

    # ── Embeddings (local, free) ───────────────────────────────────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX via fastembed
    embedding_dims: int = 384

    # ── Workers ────────────────────────────────────────────────────────────────
    metrics_interval_seconds: int = 300
    drift_check_interval_seconds: int = 3600

    # ── Drift detection ────────────────────────────────────────────────────────
    drift_baseline_days: int = 7
    drift_min_baseline: int = 50
    drift_min_current: int = 20

    # ── Webhook signing ────────────────────────────────────────────────────────
    webhook_secret: str = ""

    # ── OTEL ───────────────────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = ""
```

Add a validator after `must_be_async`:

```python
    @field_validator("judge_provider")
    @classmethod
    def judge_provider_known(cls, v: str) -> str:
        if v not in ("mock", "anthropic"):
            raise ValueError(f"judge_provider must be 'mock' or 'anthropic', got {v!r}")
        return v
```

- [ ] **Step 4: Add model-level cross-check for anthropic key**

After the validators, add:

```python
    @model_validator(mode="after")
    def anthropic_needs_key(self) -> "Settings":
        if self.judge_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError(
                "judge_provider=anthropic requires ANTHROPIC_API_KEY. "
                "Use judge_provider=mock for free operation."
            )
        return self
```

Update the pydantic import line to: `from pydantic import field_validator, model_validator`

- [ ] **Step 5: Update `.env.example`** — remove `OPENAI_API_KEY`, add (with comments matching existing file style):

```bash
# LLM judge: mock (free, default) or anthropic (needs key, costs pennies/run)
JUDGE_PROVIDER=mock
JUDGE_MODEL=claude-haiku-4-5
ANTHROPIC_API_KEY=

# Local embeddings (fastembed, free)
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5

# Worker intervals (seconds)
METRICS_INTERVAL_SECONDS=300
DRIFT_CHECK_INTERVAL_SECONDS=3600

# Drift detection windows
DRIFT_BASELINE_DAYS=7
DRIFT_MIN_BASELINE=50
DRIFT_MIN_CURRENT=20

# HMAC secret for signing drift webhooks
WEBHOOK_SECRET=change-me

# OTEL OTLP endpoint (empty = tracing no-op)
OTEL_EXPORTER_OTLP_ENDPOINT=
```

- [ ] **Step 6: Verify config loads**

Run: `source .venv/bin/activate && python -c "from api.config import get_settings; s=get_settings(); print(s.judge_provider, s.embedding_dims)"`
Expected: `mock 384`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml api/config.py .env.example
git commit -m "feat: config + deps for eval/drift/metrics — mock judge default, local embeddings"
```

### Task 2: Embedding singleton + migrate vector(1536)→vector(384) + rewrite log_worker

**Files:**
- Create: `eval/scorers/embedding_backend.py` (shared by scorer, drift, log worker)
- Modify: `api/models/llm_log.py:59` (Vector dim)
- Modify: `workers/log_worker.py` (OpenAI → fastembed)
- Create: `api/migrations/versions/<autogen>_prompt_embedding_384.py`
- Test: `tests/unit/test_embedding_backend.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_embedding_backend.py`:

```python
"""Embedding backend — lazy singleton around fastembed.

Unit tests use the real model (small, local, free). First call downloads
~66MB to ~/.cache — CI caches this. If offline, test is skipped.
"""

import numpy as np
import pytest

from eval.scorers.embedding_backend import embed_texts, cosine_similarity


def test_embed_returns_384_dim_unit_vectors() -> None:
    vecs = embed_texts(["hello world", "goodbye world"])
    assert vecs.shape == (2, 384)
    # bge models emit L2-normalized vectors → norms ≈ 1
    np.testing.assert_allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-3)


def test_cosine_similarity_bounds() -> None:
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    c = np.array([-1.0, 0.0, 0.0])
    assert cosine_similarity(a, b) == pytest.approx(1.0)
    assert cosine_similarity(a, c) == pytest.approx(-1.0)


def test_similar_texts_score_higher_than_different() -> None:
    vecs = embed_texts([
        "The cat sat on the mat",
        "A cat is sitting on a mat",
        "Quarterly revenue grew 40 percent",
    ])
    sim_close = cosine_similarity(vecs[0], vecs[1])
    sim_far = cosine_similarity(vecs[0], vecs[2])
    assert sim_close > sim_far
    assert sim_close > 0.8
```

- [ ] **Step 2: Run to verify failure**

Run: `source .venv/bin/activate && pytest tests/unit/test_embedding_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.scorers.embedding_backend'`

- [ ] **Step 3: Implement `eval/scorers/embedding_backend.py`**

```python
"""
Shared local embedding backend — fastembed (ONNX, no torch, no API, $0).

One lazy singleton per process. Used by:
  - eval/scorers/embedding_similarity.py (scoring)
  - monitor/drift_detector.py (via stored embeddings)
  - workers/log_worker.py (embedding generation on ingest)

Why lazy? Model load reads ~66MB from disk (first run: downloads).
Workers that never embed (metrics_worker) shouldn't pay that cost.
No FastAPI imports — this module is part of the standalone eval package.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
from fastembed import TextEmbedding

from api.config import get_settings

logger = logging.getLogger(__name__)

_model: TextEmbedding | None = None
_lock = threading.Lock()


def _get_model() -> TextEmbedding:
    """Lazy, thread-safe singleton. Double-checked locking: fast path no lock."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                settings = get_settings()
                logger.info("Loading embedding model %s", settings.embedding_model)
                _model = TextEmbedding(model_name=settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts → (len(texts), 384) float32 array.

    fastembed returns a generator of arrays; stack once for vector math.
    """
    model = _get_model()
    return np.stack(list(model.embed(texts)))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two 1-D vectors, safe against zero vectors."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/unit/test_embedding_backend.py -v`
Expected: 3 PASS (first run downloads model ~30s; later runs fast)

- [ ] **Step 5: Change model column to 384**

In `api/models/llm_log.py`: replace `prompt_embedding: Mapped[list | None] = mapped_column(Vector(1536))` with `prompt_embedding: Mapped[list | None] = mapped_column(Vector(384))`. Update the docstring lines that mention 1536/OpenAI to say `384-dim local embedding (fastembed bge-small-en-v1.5)`.

- [ ] **Step 6: Generate migration**

Run: `docker compose up -d postgres && sleep 3 && alembic upgrade head && alembic revision --autogenerate -m "prompt_embedding 1536 to 384"`
Expected: new file in `api/migrations/versions/`. Open it; ensure upgrade contains a drop/recreate (ALTER TYPE on vector dims isn't supported):

```python
def upgrade() -> None:
    op.drop_column("llm_logs", "prompt_embedding")
    op.add_column("llm_logs", sa.Column("prompt_embedding", Vector(dim=384), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_logs", "prompt_embedding")
    op.add_column("llm_logs", sa.Column("prompt_embedding", Vector(dim=1536), nullable=True))
```

(Import `from pgvector.sqlalchemy import Vector` at top of the migration. If autogenerate emitted `alter_column`, replace with the above — dim change requires drop/add.)

- [ ] **Step 7: Apply**

Run: `alembic upgrade head`
Expected: `Running upgrade ... prompt_embedding 1536 to 384`

- [ ] **Step 8: Rewrite `workers/log_worker.py` embedding section**

Replace the OpenAI import/client/constants block (`from openai import AsyncOpenAI`, `_openai_client = ...`, `EMBEDDING_MODEL`, `EMBEDDING_DIMS`) and `_generate_embedding_async` body so the module reads:

```python
"""
Log worker — local embedding generation via fastembed, enqueued via RQ.

Flow:
  POST /logs → create_log() → enqueue_embedding_job(log_id) → RQ queue
  RQ worker picks up → generate_embedding(log_id) → asyncio.run(async fn)
  → fetch log from DB → fastembed encode (local, $0) → UPDATE prompt_embedding

Why asyncio.run() in generate_embedding?
  RQ calls sync functions. Our DB operations are async (asyncpg).
  asyncio.run() bridges sync → async for each job. Clean, no event loop leaks.

Why fastembed?
  Local ONNX model — no API key, no cost, self-hosted story intact.
  384 dims must match Vector(384) on LLMLog.prompt_embedding.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from rq import Queue
from sqlalchemy import select, update

from api.config import get_settings
from api.dependencies import async_session_maker
from api.models.llm_log import LLMLog
from workers.base import get_redis_connection

logger = logging.getLogger(__name__)

_settings = get_settings()


def enqueue_embedding_job(log_id: str) -> None:
    """
    Sync entry point called by FastAPI BackgroundTasks.

    Puts a generate_embedding job on the default RQ queue.
    Returns immediately — does not wait for embedding to complete.
    """
    try:
        q = Queue(connection=get_redis_connection())
        job = q.enqueue(generate_embedding, log_id)
        logger.info("Embedding job enqueued: log_id=%s job_id=%s", log_id, job.id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to enqueue embedding job for log_id=%s: %s", log_id, exc)


def generate_embedding(log_id: str) -> None:
    """Sync RQ job entry point — bridges to async implementation."""
    logger.info("Embedding job started: log_id=%s", log_id)
    asyncio.run(_generate_embedding_async(log_id))


async def _generate_embedding_async(log_id: str) -> None:
    """Fetch prompt → embed locally → UPDATE prompt_embedding."""
    # Import here: loads ONNX model lazily, only in processes that embed.
    from eval.scorers.embedding_backend import embed_texts

    log_uuid = uuid.UUID(log_id)

    async with async_session_maker() as session:
        result = await session.execute(
            select(LLMLog.id, LLMLog.prompt).where(LLMLog.id == log_uuid)
        )
        row = result.one_or_none()
        if row is None:
            logger.warning("Embedding job: log not found log_id=%s", log_id)
            return

        _, prompt_text = row

        try:
            embedding: list[float] = embed_texts([prompt_text])[0].tolist()
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedding failed for log_id=%s: %s", log_id, exc)
            return  # leave NULL — best-effort

        await session.execute(
            update(LLMLog)
            .where(LLMLog.id == log_uuid)
            .values(prompt_embedding=embedding)
        )
        await session.commit()
        logger.info("Embedding stored: log_id=%s dims=%d", log_id, len(embedding))
```

- [ ] **Step 9: Verify imports + full unit suite**

Run: `python -c "import workers.log_worker" && pytest tests/unit -v`
Expected: import OK; all unit tests pass.

- [ ] **Step 10: Commit**

```bash
git add eval/scorers/embedding_backend.py api/models/llm_log.py workers/log_worker.py api/migrations/versions/ tests/unit/test_embedding_backend.py
git commit -m "feat: local fastembed embeddings (384-dim) replace OpenAI — migration + worker rewrite"
```

### Task 3: Test infrastructure (conftest)

**Files:**
- Modify: `tests/conftest.py` (currently empty)
- Modify: `pyproject.toml` (pytest config)

- [ ] **Step 1: pytest config in `pyproject.toml`** — add (or extend existing `[tool.pytest.ini_options]`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write `tests/conftest.py`**

```python
"""
Shared test fixtures.

Unit tests (tests/unit): pure logic, no fixtures from here needed.
Integration tests (tests/integration): real Postgres via TEST_DATABASE_URL
(defaults to the docker-compose Postgres with a _test database).

Strategy: one engine per session; each test runs in a fresh schema state
by truncating all tables after the test. Truncate > drop/create: faster,
keeps Alembic-applied schema intact.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Test DB URL — same postgres container, dedicated database.
# CI overrides via env. The _test DB is created by the integration bootstrap
# fixture below if missing.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://llm_obs:llm_obs_password@localhost:5432/llm_obs_test",
)

# Make the app under test read the test DB before api.config is imported.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Session-scoped engine. Creates llm_obs_test DB + schema if needed."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    from sqlalchemy import text

    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname='llm_obs_test'")
        )
        if not exists:
            await conn.execute(text("CREATE DATABASE llm_obs_test"))
    await admin_engine.dispose()

    eng = create_async_engine(TEST_DATABASE_URL)
    # Apply schema: pgvector extension + all tables from ORM metadata.
    # (Alembic runs against the dev DB; tests build equivalent schema directly.)
    from api.models.base import Base
    import api.models.llm_log  # noqa: F401 — register all models on Base.metadata
    import api.models.test_case  # noqa: F401
    import api.models.eval_run  # noqa: F401
    import api.models.eval_result  # noqa: F401
    import api.models.drift_alert  # noqa: F401
    import api.models.metric  # noqa: F401

    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session; truncates all tables after each test."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s

    from sqlalchemy import text
    from api.models.base import Base

    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client against the real app, DB dependency overridden to test DB."""
    from api.dependencies import get_db
    from api.main import create_app

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _test_db() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_db] = _test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    from sqlalchemy import text
    from api.models.base import Base

    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
```

- [ ] **Step 3: Smoke-test the fixtures**

Append to `tests/integration/test_logs_api.py` (currently empty):

```python
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
```

- [ ] **Step 4: Run**

Run: `docker compose up -d postgres redis && pytest tests/integration/test_logs_api.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/integration/test_logs_api.py pyproject.toml
git commit -m "test: async test infrastructure — test DB bootstrap, session + client fixtures"
```

---

## Phase 1 — Eval Engine (Week 3)

### Task 4: exact_match scorer

**Files:**
- Create: `eval/scorers/exact_match.py` (0-byte stub exists)
- Test: `tests/unit/test_scorers.py` (0-byte stub exists)

- [ ] **Step 1: Failing test** — start `tests/unit/test_scorers.py`:

```python
"""Unit tests for eval scorers — pure logic, no DB, no network."""

import pytest

from eval.scorers.exact_match import score as exact_score


class TestExactMatch:
    @pytest.mark.parametrize(
        ("expected", "actual", "want"),
        [
            ("Paris", "Paris", 1.0),
            ("Paris", "paris", 1.0),            # case-insensitive
            ("  Paris ", "Paris", 1.0),          # strip
            ("New  York", "new york", 1.0),      # whitespace collapse
            ("Paris", "London", 0.0),
            ("Paris", "", 0.0),
            ("", "", 1.0),                        # both empty = match
        ],
    )
    def test_normalized_comparison(self, expected: str, actual: str, want: float) -> None:
        assert exact_score(expected, actual) == want
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/unit/test_scorers.py -v`
Expected: FAIL — `ImportError` (module empty)

- [ ] **Step 3: Implement `eval/scorers/exact_match.py`**

```python
"""
Exact-match scorer — binary comparison after normalization.

Normalization: strip outer whitespace, lowercase, collapse internal
whitespace runs to single spaces. "New  York " == "new york" → 1.0.
No FastAPI imports (standalone eval package rule).
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text.strip().lower())


def score(expected: str, actual: str) -> float:
    """1.0 if normalized strings are identical, else 0.0."""
    return 1.0 if _normalize(expected) == _normalize(actual) else 0.0
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/unit/test_scorers.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/scorers/exact_match.py tests/unit/test_scorers.py
git commit -m "feat: exact_match scorer with normalization"
```

### Task 5: embedding_similarity scorer

**Files:**
- Create: `eval/scorers/embedding_similarity.py` (stub exists)
- Test: append to `tests/unit/test_scorers.py`

- [ ] **Step 1: Failing test** — append to `tests/unit/test_scorers.py`:

```python
from eval.scorers.embedding_similarity import score as embedding_score


class TestEmbeddingSimilarity:
    def test_identical_texts_near_one(self) -> None:
        s = embedding_score("The capital of France is Paris", "The capital of France is Paris")
        assert s == pytest.approx(1.0, abs=1e-3)

    def test_paraphrase_above_unrelated(self) -> None:
        para = embedding_score("The cat sat on the mat", "A cat is sitting on a mat")
        unrel = embedding_score("The cat sat on the mat", "Revenue grew 40% quarter over quarter")
        assert para > unrel

    def test_clamped_to_unit_interval(self) -> None:
        s = embedding_score("alpha", "omega")
        assert 0.0 <= s <= 1.0
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/unit/test_scorers.py::TestEmbeddingSimilarity -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement `eval/scorers/embedding_similarity.py`**

```python
"""
Embedding-similarity scorer — cosine similarity of local embeddings.

Uses the shared fastembed backend (384-dim bge-small). Raw cosine for
bge-normalized vectors lands in [-1, 1]; we clamp to [0, 1] because
scores below 0 carry no ranking meaning for eval pass/fail.
"""

from __future__ import annotations

from eval.scorers.embedding_backend import cosine_similarity, embed_texts


def score(expected: str, actual: str) -> float:
    """Cosine similarity of expected vs actual, clamped to [0, 1]."""
    vecs = embed_texts([expected, actual])
    raw = cosine_similarity(vecs[0], vecs[1])
    return max(0.0, min(1.0, raw))
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/unit/test_scorers.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add eval/scorers/embedding_similarity.py tests/unit/test_scorers.py
git commit -m "feat: embedding_similarity scorer on local fastembed backend"
```

### Task 6: llm_judge scorer (mock default + anthropic optional)

**Files:**
- Create: `eval/scorers/llm_judge.py` (stub exists)
- Test: append to `tests/unit/test_scorers.py`

- [ ] **Step 1: Failing tests** — append:

```python
from unittest.mock import AsyncMock, MagicMock

from eval.scorers.llm_judge import JudgeResult, judge


class TestLLMJudgeMock:
    async def test_identical_scores_high(self) -> None:
        r = await judge("Paris is the capital", "Paris is the capital", provider="mock")
        assert isinstance(r, JudgeResult)
        assert r.score == pytest.approx(1.0)
        assert "mock" in r.reasoning.lower()

    async def test_disjoint_scores_low(self) -> None:
        r = await judge("Paris is the capital", "bananas grow on trees", provider="mock")
        assert r.score < 0.3

    async def test_deterministic(self) -> None:
        a = await judge("some expected", "some actual output", provider="mock")
        b = await judge("some expected", "some actual output", provider="mock")
        assert a.score == b.score


class TestLLMJudgeAnthropic:
    async def test_parses_json_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_msg = MagicMock()
        fake_msg.content = [MagicMock(text='{"score": 0.9, "reasoning": "matches key facts"}')]
        fake_client = MagicMock()
        fake_client.messages.create = AsyncMock(return_value=fake_msg)
        monkeypatch.setattr("eval.scorers.llm_judge._get_anthropic_client", lambda: fake_client)

        r = await judge("expected", "actual", provider="anthropic")
        assert r.score == pytest.approx(0.9)
        assert r.reasoning == "matches key facts"

    async def test_malformed_json_returns_zero_with_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_msg = MagicMock()
        fake_msg.content = [MagicMock(text="not json at all")]
        fake_client = MagicMock()
        fake_client.messages.create = AsyncMock(return_value=fake_msg)
        monkeypatch.setattr("eval.scorers.llm_judge._get_anthropic_client", lambda: fake_client)

        r = await judge("expected", "actual", provider="anthropic")
        assert r.score == 0.0
        assert "parse" in r.reasoning.lower()
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/unit/test_scorers.py -k Judge -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement `eval/scorers/llm_judge.py`**

```python
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
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/unit/test_scorers.py -v`
Expected: all PASS (anthropic path fully mocked — zero API calls)

- [ ] **Step 5: Commit**

```bash
git add eval/scorers/llm_judge.py tests/unit/test_scorers.py
git commit -m "feat: llm_judge scorer — free deterministic mock default, optional Claude provider"
```

### Task 7: Eval Pydantic schemas

**Files:**
- Modify: `api/schemas/test_case.py`, `api/schemas/eval_run.py`, `api/schemas/eval_result.py` (0-byte stubs)

- [ ] **Step 1: `api/schemas/test_case.py`**

```python
"""Pydantic schemas for test-case CRUD (API contract only — no Column())."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvalMethod = Literal["exact_match", "embedding_similarity", "llm_judge"]


class TestCaseCreate(BaseModel):
    suite_name: str = Field(..., max_length=255)
    input_prompt: str
    expected_output: str
    eval_methods: list[EvalMethod] = Field(..., min_length=1)
    similarity_threshold: float = Field(0.85, ge=0.0, le=1.0)


class TestCaseResponse(TestCaseCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: `api/schemas/eval_run.py`**

```python
"""Pydantic schemas for eval runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvalRunTrigger(BaseModel):
    """Request body for POST /evals/run."""

    suite_name: str = Field(..., max_length=255)
    commit_sha: str = Field("manual", max_length=40)


class EvalRunResponse(BaseModel):
    id: uuid.UUID
    suite_name: str
    commit_sha: str
    triggered_by: str
    total_cases: int
    passed_cases: int
    pass_rate: float | None
    gate_threshold: float
    gate_result: Literal["pass", "fail"] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvalRunQueued(BaseModel):
    """Response for POST /evals/run — job accepted, not yet complete."""

    job_id: str
    status: Literal["queued"] = "queued"
```

- [ ] **Step 3: `api/schemas/eval_result.py`**

```python
"""Pydantic schemas for per-case eval results."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EvalResultResponse(BaseModel):
    id: uuid.UUID
    eval_run_id: uuid.UUID
    test_case_id: uuid.UUID
    exact_match_score: float | None
    embedding_score: float | None
    llm_judge_score: float | None
    llm_judge_reasoning: str | None
    passed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvalRunDetail(BaseModel):
    """GET /evals/runs/{id} — run + nested results."""

    # imported here to avoid circular import at module top
    from api.schemas.eval_run import EvalRunResponse  # noqa: PLC0415

    run: EvalRunResponse
    results: list[EvalResultResponse]
```

Note: the inline import inside a class body is invalid — instead put `from api.schemas.eval_run import EvalRunResponse` at the top of the file (no circularity exists: eval_run.py does not import eval_result.py). Final file has the import at top and `run: EvalRunResponse`.

- [ ] **Step 4: Verify**

Run: `python -c "from api.schemas.test_case import TestCaseCreate; from api.schemas.eval_run import EvalRunResponse; from api.schemas.eval_result import EvalRunDetail; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add api/schemas/test_case.py api/schemas/eval_run.py api/schemas/eval_result.py
git commit -m "feat: eval API schemas — test cases, runs, results"
```

### Task 8: Eval engine

**Files:**
- Create: `eval/engine.py` (stub exists)
- Test: `tests/integration/test_evals_api.py` (stub exists — engine section)

- [ ] **Step 1: Failing integration test** — start `tests/integration/test_evals_api.py`:

```python
"""Integration tests for eval engine + eval API (real postgres)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.eval_result import EvalResult
from api.models.test_case import TestCase
from eval.engine import run_eval


async def _seed_suite(session: AsyncSession, suite: str) -> None:
    session.add_all([
        TestCase(
            suite_name=suite,
            input_prompt="What is the capital of France?",
            expected_output="Paris",
            eval_methods=["exact_match"],
        ),
        TestCase(
            suite_name=suite,
            input_prompt="Summarize: the sky is blue.",
            expected_output="The sky is blue",
            eval_methods=["embedding_similarity", "llm_judge"],
            similarity_threshold=0.5,
        ),
    ])
    await session.commit()


class TestEngine:
    async def test_run_eval_echo_target_passes_all(self, session: AsyncSession) -> None:
        suite = f"suite-{uuid.uuid4().hex[:8]}"
        await _seed_suite(session, suite)

        run = await run_eval(
            session, suite_name=suite, commit_sha="abc123", triggered_by="test",
            gate_threshold=0.8,
        )

        assert run.total_cases == 2
        assert run.passed_cases == 2
        assert float(run.pass_rate) == pytest.approx(1.0)
        assert run.gate_result == "pass"
        assert run.completed_at is not None

        results = (await session.execute(
            select(EvalResult).where(EvalResult.eval_run_id == run.id)
        )).scalars().all()
        assert len(results) == 2
        exact = next(r for r in results if r.exact_match_score is not None)
        assert float(exact.exact_match_score) == 1.0
        judged = next(r for r in results if r.llm_judge_score is not None)
        assert judged.llm_judge_reasoning  # mock judge writes reasoning

    async def test_unknown_suite_raises(self, session: AsyncSession) -> None:
        with pytest.raises(ValueError, match="No test cases"):
            await run_eval(session, suite_name="nope", commit_sha="x", triggered_by="test", gate_threshold=0.8)
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/integration/test_evals_api.py -v`
Expected: FAIL — ImportError `run_eval`

- [ ] **Step 3: Implement `eval/engine.py`**

```python
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
    logger.info(
        "Eval run %s: suite=%s %d/%d passed rate=%.4f gate=%s",
        run.id, suite_name, passed_count, len(cases), run.pass_rate, run.gate_result,
    )
    return run
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/integration/test_evals_api.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/engine.py tests/integration/test_evals_api.py
git commit -m "feat: eval engine — scorer orchestration, transactional run persistence"
```

### Task 9: Eval runner CLI (CI gate entry)

**Files:**
- Create: `eval/runner.py` (stub exists)
- Test: append `TestRunner` to `tests/integration/test_evals_api.py`

- [ ] **Step 1: Failing test** — append:

```python
from eval.runner import main as runner_main


class TestRunner:
    async def test_exit_zero_on_pass(self, session: AsyncSession, capsys: pytest.CaptureFixture[str]) -> None:
        suite = f"runner-{uuid.uuid4().hex[:8]}"
        await _seed_suite(session, suite)

        code = await runner_main(["--suite", suite, "--commit-sha", "deadbeef", "--threshold", "0.5"])
        assert code == 0
        out = capsys.readouterr().out
        assert "gate PASS" in out and suite in out

    async def test_exit_one_on_unknown_suite(self) -> None:
        code = await runner_main(["--suite", "does-not-exist", "--commit-sha", "x"])
        assert code == 1
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/integration/test_evals_api.py::TestRunner -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement `eval/runner.py`**

```python
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
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/integration/test_evals_api.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add eval/runner.py tests/integration/test_evals_api.py
git commit -m "feat: eval runner CLI — CI gate with exit codes and summary table"
```

### Task 10: Eval service + routers + worker + registration

**Files:**
- Modify: `api/services/eval_service.py` (stub), `api/routers/evals.py` (stub), `workers/eval_worker.py` (stub), `api/main.py:61-65`
- Test: append `TestEvalAPI` to `tests/integration/test_evals_api.py`

- [ ] **Step 1: Failing tests** — append:

```python
from httpx import AsyncClient


class TestEvalAPI:
    async def test_create_and_list_test_cases(self, client: AsyncClient) -> None:
        payload = {
            "suite_name": "api-suite",
            "input_prompt": "2+2?",
            "expected_output": "4",
            "eval_methods": ["exact_match"],
        }
        resp = await client.post("/test-cases", json=payload)
        assert resp.status_code == 201
        assert resp.json()["similarity_threshold"] == 0.85

        listing = await client.get("/test-cases", params={"suite_name": "api-suite"})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

    async def test_invalid_method_rejected(self, client: AsyncClient) -> None:
        resp = await client.post("/test-cases", json={
            "suite_name": "s", "input_prompt": "p", "expected_output": "o",
            "eval_methods": ["vibes"],
        })
        assert resp.status_code == 422

    async def test_run_listing_and_detail(self, client: AsyncClient, session: AsyncSession) -> None:
        suite = f"api-{uuid.uuid4().hex[:8]}"
        await _seed_suite(session, suite)
        run = await run_eval(session, suite_name=suite, commit_sha="c0ffee", triggered_by="test", gate_threshold=0.8)

        listing = await client.get("/evals/runs", params={"suite_name": suite})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

        detail = await client.get(f"/evals/runs/{run.id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["run"]["gate_result"] == "pass"
        assert len(body["results"]) == 2

    async def test_run_detail_404(self, client: AsyncClient) -> None:
        resp = await client.get(f"/evals/runs/{uuid.uuid4()}")
        assert resp.status_code == 404
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/integration/test_evals_api.py::TestEvalAPI -v`
Expected: FAIL — 404s (routers not registered)

- [ ] **Step 3: Implement `api/services/eval_service.py`**

```python
"""Eval service — business logic for test cases and eval runs."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.eval_result import EvalResult
from api.models.eval_run import EvalRun
from api.models.test_case import TestCase
from api.schemas.test_case import TestCaseCreate

logger = logging.getLogger(__name__)


async def create_test_case(session: AsyncSession, data: TestCaseCreate) -> TestCase:
    case = TestCase(**data.model_dump())
    session.add(case)
    await session.commit()
    await session.refresh(case)
    logger.info("Test case created: id=%s suite=%s", case.id, case.suite_name)
    return case


async def list_test_cases(
    session: AsyncSession, suite_name: str | None, page: int, page_size: int
) -> tuple[list[TestCase], int]:
    query = select(TestCase)
    if suite_name is not None:
        query = query.where(TestCase.suite_name == suite_name)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(TestCase.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def list_eval_runs(
    session: AsyncSession, suite_name: str | None, page: int, page_size: int
) -> tuple[list[EvalRun], int]:
    query = select(EvalRun)
    if suite_name is not None:
        query = query.where(EvalRun.suite_name == suite_name)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(EvalRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def get_run_with_results(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[EvalRun, list[EvalResult]] | None:
    run = (await session.execute(select(EvalRun).where(EvalRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return None
    results = (
        await session.execute(
            select(EvalResult).where(EvalResult.eval_run_id == run_id).order_by(EvalResult.created_at)
        )
    ).scalars().all()
    return run, list(results)
```

- [ ] **Step 4: Implement `workers/eval_worker.py`**

```python
"""
Eval worker — runs eval suites enqueued from POST /evals/run.

RQ job: sync entry, asyncio.run bridge, own session (worker process ≠ API).
"""

from __future__ import annotations

import asyncio
import logging

from rq import Queue

from api.config import get_settings
from api.dependencies import async_session_maker
from eval.engine import run_eval
from workers.base import get_redis_connection

logger = logging.getLogger(__name__)


def enqueue_eval_run(suite_name: str, commit_sha: str) -> str:
    """Called by the API. Returns the RQ job id."""
    q = Queue("evals", connection=get_redis_connection())
    job = q.enqueue(execute_eval_run, suite_name, commit_sha)
    logger.info("Eval job enqueued: suite=%s job_id=%s", suite_name, job.id)
    return job.id


def execute_eval_run(suite_name: str, commit_sha: str) -> None:
    """RQ job body."""
    asyncio.run(_execute(suite_name, commit_sha))


async def _execute(suite_name: str, commit_sha: str) -> None:
    settings = get_settings()
    async with async_session_maker() as session:
        try:
            await run_eval(
                session,
                suite_name=suite_name,
                commit_sha=commit_sha,
                triggered_by="api",
                gate_threshold=settings.eval_gate_threshold,
            )
        except ValueError as exc:
            logger.error("Eval job failed: %s", exc)
```

- [ ] **Step 5: Implement `api/routers/evals.py`**

```python
"""Eval routers — test-case CRUD + eval run trigger/listing. No business logic."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.eval_result import EvalResultResponse, EvalRunDetail
from api.schemas.eval_run import EvalRunQueued, EvalRunResponse, EvalRunTrigger
from api.schemas.test_case import TestCaseCreate, TestCaseResponse
from api.services import eval_service

logger = logging.getLogger(__name__)

test_cases_router = APIRouter(prefix="/test-cases", tags=["test-cases"])
evals_router = APIRouter(prefix="/evals", tags=["evals"])


@test_cases_router.post("", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    payload: TestCaseCreate,
    session: AsyncSession = Depends(get_db),
) -> TestCaseResponse:
    case = await eval_service.create_test_case(session, payload)
    return TestCaseResponse.model_validate(case)


@test_cases_router.get("", response_model=PaginatedResponse[TestCaseResponse])
async def list_test_cases(
    suite_name: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TestCaseResponse]:
    cases, total = await eval_service.list_test_cases(session, suite_name, page, page_size)
    return PaginatedResponse[TestCaseResponse](
        total=total, page=page, page_size=page_size,
        items=[TestCaseResponse.model_validate(c) for c in cases],
    )


@evals_router.post("/run", response_model=EvalRunQueued, status_code=status.HTTP_202_ACCEPTED)
async def trigger_eval_run(payload: EvalRunTrigger) -> EvalRunQueued:
    """Enqueue an eval run. Worker executes it; poll GET /evals/runs for the result."""
    try:
        from workers.eval_worker import enqueue_eval_run

        job_id = enqueue_eval_run(payload.suite_name, payload.commit_sha)
    except Exception as exc:  # Redis down → 503, honest signal
        logger.error("Could not enqueue eval run: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Eval queue unavailable")
    return EvalRunQueued(job_id=job_id)


@evals_router.get("/runs", response_model=PaginatedResponse[EvalRunResponse])
async def list_runs(
    suite_name: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EvalRunResponse]:
    runs, total = await eval_service.list_eval_runs(session, suite_name, page, page_size)
    return PaginatedResponse[EvalRunResponse](
        total=total, page=page, page_size=page_size,
        items=[EvalRunResponse.model_validate(r) for r in runs],
    )


@evals_router.get("/runs/{run_id}", response_model=EvalRunDetail)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> EvalRunDetail:
    pair = await eval_service.get_run_with_results(session, run_id)
    if pair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Eval run {run_id} not found")
    run, results = pair
    return EvalRunDetail(
        run=EvalRunResponse.model_validate(run),
        results=[EvalResultResponse.model_validate(r) for r in results],
    )
```

- [ ] **Step 6: Register in `api/main.py`** — replace the commented router lines with:

```python
    from api.routers import evals

    app.include_router(evals.test_cases_router)
    app.include_router(evals.evals_router)
    # Week 4+: app.include_router(metrics.router)
    # Week 5+: app.include_router(drift.router)
```

(Adjust the top import to `from api.routers import health, logs` unchanged; evals imported inside create_app or at top — top preferred: `from api.routers import evals, health, logs`.)

- [ ] **Step 7: Verify pass**

Run: `pytest tests/integration/test_evals_api.py -v && pytest tests/unit -v`
Expected: all PASS

- [ ] **Step 8: Commit — Week 3 boundary**

```bash
git add api/services/eval_service.py api/routers/evals.py workers/eval_worker.py api/main.py tests/integration/test_evals_api.py
git commit -m "Week 3: eval engine — scorers, engine, runner CLI, eval API + worker"
```

---

## Phase 2 — Metrics (Week 4)

### Task 11: Metrics aggregator

**Files:**
- Create: `monitor/metrics_aggregator.py` (stub exists)
- Test: `tests/unit/test_metrics.py` (stub — becomes integration-style but lives with real DB via fixtures; put DB tests in `tests/integration/test_metrics_api.py` instead, keep unit file for pure helpers)
- Create: `tests/integration/test_metrics_api.py`

- [ ] **Step 1: Failing test** — create `tests/integration/test_metrics_api.py`:

```python
"""Integration tests for metrics aggregation + API."""

from datetime import datetime, timedelta

import pytest
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
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/integration/test_metrics_api.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement `monitor/metrics_aggregator.py`**

```python
"""
Metrics aggregator — rolls llm_logs up into per-(app, model, period) rows.

One GROUP BY query computes counts, cost, tokens and latency percentiles
(percentile_cont inside the DB — no Python-side sorting), then upserts via
ON CONFLICT DO UPDATE on the (app, model, period_type, period_start) key.
Idempotent: re-running a window overwrites with fresh numbers.

Standalone package: no FastAPI imports.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.llm_log import LLMLog
from api.models.metric import Metric

logger = logging.getLogger(__name__)

_TRUNC = {"hourly": "hour", "daily": "day"}


async def aggregate_window(
    session: AsyncSession,
    period_type: str,
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Aggregate logs in [window_start, window_end) → upserted metric rows.

    Returns number of (app, model, period) rows written.
    """
    if period_type not in _TRUNC:
        raise ValueError(f"period_type must be 'hourly' or 'daily', got {period_type!r}")

    period_start = func.date_trunc(_TRUNC[period_type], LLMLog.created_at).label("period_start")
    lat = LLMLog.latency_ms

    query = (
        select(
            LLMLog.application_id,
            LLMLog.model,
            period_start,
            func.count().label("total_requests"),
            func.count().filter(LLMLog.status == "success").label("successful_requests"),
            func.count().filter(LLMLog.status != "success").label("failed_requests"),
            func.coalesce(func.sum(LLMLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LLMLog.cost_usd), 0).label("total_cost_usd"),
            func.avg(lat).label("avg_latency_ms"),
            cast(func.percentile_cont(0.5).within_group(lat.asc()), Integer).label("p50"),
            cast(func.percentile_cont(0.95).within_group(lat.asc()), Integer).label("p95"),
            cast(func.percentile_cont(0.99).within_group(lat.asc()), Integer).label("p99"),
        )
        .where(LLMLog.created_at >= window_start, LLMLog.created_at < window_end)
        .group_by(LLMLog.application_id, LLMLog.model, period_start)
    )

    rows = (await session.execute(query)).all()
    if not rows:
        logger.debug("aggregate_window: no logs in %s window %s–%s", period_type, window_start, window_end)
        return 0

    for r in rows:
        values = {
            "application_id": r.application_id,
            "model": r.model,
            "period_type": period_type,
            "period_start": r.period_start,
            "total_requests": r.total_requests,
            "successful_requests": r.successful_requests,
            "failed_requests": r.failed_requests,
            "total_tokens": int(r.total_tokens),
            "total_cost_usd": r.total_cost_usd,
            "avg_latency_ms": r.avg_latency_ms,
            "p50_latency_ms": r.p50,
            "p95_latency_ms": r.p95,
            "p99_latency_ms": r.p99,
        }
        stmt = pg_insert(Metric).values(**values).on_conflict_do_update(
            constraint="uq_metrics_app_model_period",
            set_={k: v for k, v in values.items() if k not in ("application_id", "model", "period_type", "period_start")}
            | {"updated_at": func.now()},
        )
        await session.execute(stmt)

    await session.commit()
    logger.info("aggregate_window: %s wrote %d rows for %s–%s", period_type, len(rows), window_start, window_end)
    return len(rows)
```

- [ ] **Step 4: Verify pass**

Run: `pytest tests/integration/test_metrics_api.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/metrics_aggregator.py tests/integration/test_metrics_api.py
git commit -m "feat: metrics aggregator — DB-side percentiles, idempotent upsert"
```

### Task 12: Metrics worker + service + router + schemas

**Files:**
- Create: `workers/metrics_worker.py` (new), `api/services/metric_service.py` (stub), `api/routers/metrics.py` (stub), `api/schemas/metric.py` (stub)
- Modify: `api/main.py` (register router), `docker-compose.yml` (worker command note — check existing worker service first)
- Test: append `TestMetricsAPI` to `tests/integration/test_metrics_api.py`

- [ ] **Step 1: Failing tests** — append:

```python
from httpx import AsyncClient


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
        now = datetime.utcnow()
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
```

- [ ] **Step 2: Verify fail** — `pytest tests/integration/test_metrics_api.py::TestMetricsAPI -v` → 404s.

- [ ] **Step 3: `api/schemas/metric.py`**

```python
"""Pydantic schemas for metrics endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MetricResponse(BaseModel):
    id: uuid.UUID
    application_id: str
    model: str
    period_type: Literal["hourly", "daily"]
    period_start: datetime
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float | None
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    p99_latency_ms: int | None

    model_config = ConfigDict(from_attributes=True)


class MetricsSummary(BaseModel):
    """Dashboard KPI block — computed across rollups for a time window."""

    window: Literal["24h", "7d", "30d"]
    total_requests: int
    total_cost_usd: float
    error_rate: float                 # failed / total, 0 when no traffic
    p50_latency_ms: int | None        # request-weighted approximations
    p95_latency_ms: int | None
    p99_latency_ms: int | None
    cost_prev_window_usd: float       # same-length window immediately before
    open_drift_alerts: int
```

- [ ] **Step 4: `api/services/metric_service.py`**

```python
"""Metric service — rollup queries + KPI summary for the dashboard."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.drift_alert import DriftAlert
from api.models.metric import Metric
from api.schemas.metric import MetricsSummary

logger = logging.getLogger(__name__)

_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


async def list_metrics(
    session: AsyncSession,
    application_id: str | None,
    model: str | None,
    period_type: str | None,
    start: datetime | None,
    end: datetime | None,
    page: int,
    page_size: int,
) -> tuple[list[Metric], int]:
    query = select(Metric)
    if application_id is not None:
        query = query.where(Metric.application_id == application_id)
    if model is not None:
        query = query.where(Metric.model == model)
    if period_type is not None:
        query = query.where(Metric.period_type == period_type)
    if start is not None:
        query = query.where(Metric.period_start >= start)
    if end is not None:
        query = query.where(Metric.period_start <= end)

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(Metric.period_start.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def _window_totals(session: AsyncSession, start: datetime, end: datetime) -> tuple[int, int, float]:
    """(total_requests, failed_requests, total_cost) over hourly rollups in window."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(Metric.total_requests), 0),
                func.coalesce(func.sum(Metric.failed_requests), 0),
                func.coalesce(func.sum(Metric.total_cost_usd), 0),
            ).where(
                Metric.period_type == "hourly",
                Metric.period_start >= start,
                Metric.period_start < end,
            )
        )
    ).one()
    return int(row[0]), int(row[1]), float(row[2])


async def summary(session: AsyncSession, window: str) -> MetricsSummary:
    """KPIs across all apps. Percentiles: request-weighted percentile-of-rollups
    approximation (documented tradeoff — exact percentiles would need raw logs)."""
    span = _WINDOWS[window]
    now = datetime.utcnow()
    start = now - span

    total, failed, cost = await _window_totals(session, start, now)
    prev_total_cost = (await _window_totals(session, start - span, start))[2]

    pct_row = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(Metric.p50_latency_ms.asc()),
                func.percentile_cont(0.5).within_group(Metric.p95_latency_ms.asc()),
                func.percentile_cont(0.5).within_group(Metric.p99_latency_ms.asc()),
            ).where(
                Metric.period_type == "hourly",
                Metric.period_start >= start,
                Metric.p50_latency_ms.is_not(None),
            )
        )
    ).one()

    open_alerts = (
        await session.execute(
            select(func.count()).select_from(DriftAlert).where(DriftAlert.status == "open")
        )
    ).scalar_one()

    return MetricsSummary(
        window=window,  # type: ignore[arg-type]
        total_requests=total,
        total_cost_usd=round(cost, 6),
        error_rate=round(failed / total, 4) if total else 0.0,
        p50_latency_ms=int(pct_row[0]) if pct_row[0] is not None else None,
        p95_latency_ms=int(pct_row[1]) if pct_row[1] is not None else None,
        p99_latency_ms=int(pct_row[2]) if pct_row[2] is not None else None,
        cost_prev_window_usd=round(prev_total_cost, 6),
        open_drift_alerts=int(open_alerts),
    )
```

- [ ] **Step 5: `api/routers/metrics.py`**

```python
"""Metrics router — rollup listing + dashboard summary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.metric import MetricResponse, MetricsSummary
from api.services import metric_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummary)
async def get_summary(
    window: Literal["24h", "7d", "30d"] = Query("24h"),
    session: AsyncSession = Depends(get_db),
) -> MetricsSummary:
    return await metric_service.summary(session, window)


@router.get("", response_model=PaginatedResponse[MetricResponse])
async def list_metrics(
    application_id: str | None = Query(None),
    model: str | None = Query(None),
    period_type: Literal["hourly", "daily"] | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MetricResponse]:
    rows, total = await metric_service.list_metrics(
        session, application_id, model, period_type, start, end, page, page_size
    )
    return PaginatedResponse[MetricResponse](
        total=total, page=page, page_size=page_size,
        items=[MetricResponse.model_validate(m) for m in rows],
    )
```

Note: `/metrics/summary` is declared BEFORE `/{anything}` routes (none here) and prefix `/metrics` will later share a path with Prometheus scrape endpoint — Prometheus instrumentator will mount its own `/metrics` on a different route in Task 21; when Task 21 arrives, the Prometheus endpoint moves to `/prometheus-metrics` via instrumentator config. This is recorded here so neither task is surprised.

- [ ] **Step 6: `workers/metrics_worker.py`**

```python
"""
Metrics worker — loop daemon aggregating logs into rollups.

Not an RQ job: aggregation is periodic, not event-driven. A plain asyncio
loop with SIGTERM-aware shutdown keeps operational surface minimal
(no scheduler dependency).

Run: python -m workers.metrics_worker
"""

from __future__ import annotations

import asyncio
import logging
import random
import signal
from datetime import datetime, timedelta

from api.config import get_settings
from api.dependencies import async_session_maker
from monitor.metrics_aggregator import aggregate_window

logger = logging.getLogger(__name__)


async def run_once() -> None:
    """One aggregation tick: current + previous hour (hourly), today (daily)."""
    now = datetime.utcnow()
    hour = now.replace(minute=0, second=0, microsecond=0)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_maker() as session:
        await aggregate_window(session, "hourly", hour - timedelta(hours=1), hour + timedelta(hours=1))
        await aggregate_window(session, "daily", day, day + timedelta(days=1))


async def main() -> None:
    settings = get_settings()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("metrics_worker started; interval=%ds", settings.metrics_interval_seconds)
    while not stop.is_set():
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001 — worker never dies from one tick
            logger.error("metrics tick failed: %s", exc)
        # jitter ±10% avoids thundering-herd with drift worker on shared DB
        delay = settings.metrics_interval_seconds * random.uniform(0.9, 1.1)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
    logger.info("metrics_worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    asyncio.run(main())
```

- [ ] **Step 7: Register router in `api/main.py`** — replace `# Week 4+: app.include_router(metrics.router)` with `app.include_router(metrics.router)` and extend the import to `from api.routers import evals, health, logs, metrics`.

- [ ] **Step 8: Verify**

Run: `pytest tests/integration/test_metrics_api.py -v && python -c "import workers.metrics_worker"`
Expected: all PASS; import OK.

- [ ] **Step 9: Commit — Week 4 boundary**

```bash
git add workers/metrics_worker.py api/services/metric_service.py api/routers/metrics.py api/schemas/metric.py api/main.py tests/integration/test_metrics_api.py
git commit -m "Week 4: metrics — aggregation worker, GET /metrics + /metrics/summary"
```

---

## Phase 3 — Drift Detection (Week 5)

### Task 13: Drift detector

**Files:**
- Create: `monitor/drift_detector.py` (stub exists)
- Test: `tests/unit/test_drift_detector.py` (pure math parts) + `tests/integration/test_drift_api.py` (detector against DB)

- [ ] **Step 1: Failing unit tests** — `tests/unit/test_drift_detector.py`:

```python
"""Unit tests for drift math — injected vectors, no DB."""

import numpy as np

from monitor.drift_detector import compute_drift_score, severity_for


class TestDriftMath:
    def test_identical_distributions_score_zero(self) -> None:
        vecs = np.random.RandomState(7).normal(size=(50, 8))
        score = compute_drift_score(vecs, vecs)
        assert score < 0.01

    def test_shifted_distribution_scores_higher(self) -> None:
        rng = np.random.RandomState(7)
        baseline = rng.normal(loc=0.0, size=(60, 8))
        shifted = rng.normal(loc=3.0, size=(30, 8))
        assert compute_drift_score(baseline, shifted) > compute_drift_score(baseline, baseline)

    def test_severity_thresholds(self) -> None:
        assert severity_for(0.10) is None
        assert severity_for(0.15) == "low"
        assert severity_for(0.25) == "medium"
        assert severity_for(0.35) == "high"
        assert severity_for(0.50) == "critical"
```

- [ ] **Step 2: Failing integration test** — start `tests/integration/test_drift_api.py`:

```python
"""Integration tests for drift detection + drift API."""

import uuid
from datetime import datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.drift_alert import DriftAlert
from api.models.llm_log import LLMLog
from monitor.drift_detector import detect_drift_for_app


def _embedded_log(app: str, ts: datetime, vec: list[float]) -> LLMLog:
    return LLMLog(
        application_id=app, model="m", provider="p", prompt="p", status="success",
        created_at=ts, prompt_embedding=vec,
    )


async def _seed_drifted_app(session: AsyncSession, app: str) -> None:
    rng = np.random.RandomState(42)
    now = datetime.utcnow()

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
        session.add(_embedded_log(app, datetime.utcnow() - timedelta(days=3), [0.1] * 384))
        await session.commit()
        assert await detect_drift_for_app(session, app) is None
```

- [ ] **Step 3: Verify fail**

Run: `pytest tests/unit/test_drift_detector.py tests/integration/test_drift_api.py -v`
Expected: FAIL — ImportError

- [ ] **Step 4: Implement `monitor/drift_detector.py`**

```python
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
from datetime import datetime, timedelta

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
    now = datetime.utcnow()

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
    logger.warning("drift[%s]: %s alert, score=%.4f", application_id, severity, score)
    return alert
```

- [ ] **Step 5: Verify pass**

Run: `pytest tests/unit/test_drift_detector.py tests/integration/test_drift_api.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add monitor/drift_detector.py tests/unit/test_drift_detector.py tests/integration/test_drift_api.py
git commit -m "feat: drift detector — centroid cosine distance, severity ladder, dedup"
```

### Task 14: Webhooks

**Files:**
- Create: `monitor/webhooks.py` (stub exists)
- Test: `tests/unit/test_webhooks.py` (new)

- [ ] **Step 1: Failing tests** — `tests/unit/test_webhooks.py`:

```python
"""Unit tests for webhook dispatch — httpx mocked, no network."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from monitor.webhooks import dispatch_drift_alert, sign_payload


class TestSigning:
    def test_hmac_sha256_hex(self) -> None:
        body = b'{"a":1}'
        sig = sign_payload(body, "secret")
        expected = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        assert sig == expected


class TestDispatch:
    @pytest.fixture
    def alert_payload(self) -> dict:
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "application_id": "app-1",
            "severity": "high",
            "drift_score": 0.41,
        }

    async def test_posts_with_signature(self, alert_payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DRIFT_WEBHOOK_URL", "https://example.test/hook")
        monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")
        from api.config import get_settings
        get_settings.cache_clear()

        sent = {}

        async def fake_post(self, url, content=None, headers=None):  # noqa: ANN001
            sent["url"], sent["content"], sent["headers"] = url, content, headers
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch("httpx.AsyncClient.post", new=fake_post):
            ok = await dispatch_drift_alert(alert_payload)

        assert ok is True
        assert sent["url"] == "https://example.test/hook"
        body = sent["content"]
        assert json.loads(body)["severity"] == "high"
        assert sent["headers"]["X-Signature"] == sign_payload(body, "s3cr3t")
        get_settings.cache_clear()

    async def test_no_url_configured_skips(self, alert_payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DRIFT_WEBHOOK_URL", raising=False)
        from api.config import get_settings
        get_settings.cache_clear()
        ok = await dispatch_drift_alert(alert_payload)
        assert ok is False
        get_settings.cache_clear()

    async def test_retries_then_gives_up(self, alert_payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DRIFT_WEBHOOK_URL", "https://example.test/hook")
        from api.config import get_settings
        get_settings.cache_clear()

        calls = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("httpx.AsyncClient.post", new=calls), patch("asyncio.sleep", new=AsyncMock()):
            ok = await dispatch_drift_alert(alert_payload)

        assert ok is False
        assert calls.await_count == 3
        get_settings.cache_clear()
```

- [ ] **Step 2: Verify fail** — `pytest tests/unit/test_webhooks.py -v` → ImportError.

- [ ] **Step 3: Implement `monitor/webhooks.py`**

```python
"""
Webhook dispatch — POSTs drift alerts to the configured URL.

Security: body signed with HMAC-SHA256 (X-Signature: sha256=<hex>).
Receivers verify with their copy of WEBHOOK_SECRET — prevents spoofed alerts.

Failure policy: 3 attempts, exponential backoff, then give up and log.
Never raises to the caller — a dead webhook must not break drift detection.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging

import httpx

from api.config import get_settings

logger = logging.getLogger(__name__)


def sign_payload(body: bytes, secret: str) -> str:
    """HMAC-SHA256 signature header value: sha256=<hexdigest>."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def dispatch_drift_alert(alert_data: dict) -> bool:
    """POST alert JSON to DRIFT_WEBHOOK_URL. True on 2xx, False otherwise/skip."""
    settings = get_settings()
    if not settings.drift_webhook_url:
        logger.debug("No DRIFT_WEBHOOK_URL configured — webhook skipped")
        return False

    body = json.dumps(alert_data, default=str).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": sign_payload(body, settings.webhook_secret),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(settings.drift_webhook_url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    logger.info("Webhook delivered: %s → %d", settings.drift_webhook_url, resp.status_code)
                    return True
                logger.warning("Webhook non-2xx (%d), attempt %d", resp.status_code, attempt + 1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Webhook attempt %d failed: %s", attempt + 1, exc)
            await asyncio.sleep(2**attempt)

    logger.error("Webhook delivery failed after 3 attempts: %s", settings.drift_webhook_url)
    return False
```

- [ ] **Step 4: Verify pass** — `pytest tests/unit/test_webhooks.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add monitor/webhooks.py tests/unit/test_webhooks.py
git commit -m "feat: drift webhooks — HMAC-signed dispatch with retries"
```

### Task 15: Drift worker + service + router + schemas

**Files:**
- Create: `workers/drift_worker.py` (stub), `api/services/drift_service.py` (stub), `api/routers/drift.py` (stub), `api/schemas/drift_alert.py` (stub)
- Modify: `api/main.py` (register)
- Test: append `TestDriftAPI` to `tests/integration/test_drift_api.py`

- [ ] **Step 1: Failing tests** — append:

```python
from httpx import AsyncClient


class TestDriftAPI:
    async def _make_alert(self, session: AsyncSession, app: str = "app-d") -> DriftAlert:
        alert = DriftAlert(
            application_id=app, drift_type="embedding_distribution", severity="high",
            drift_score=0.41, baseline_stats={}, current_stats={}, detected_at=datetime.utcnow(),
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
```

- [ ] **Step 2: Verify fail** — `pytest tests/integration/test_drift_api.py::TestDriftAPI -v` → 404s.

- [ ] **Step 3: `api/schemas/drift_alert.py`**

```python
"""Pydantic schemas for drift alerts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DriftAlertResponse(BaseModel):
    id: uuid.UUID
    application_id: str
    drift_type: str
    severity: Literal["low", "medium", "high", "critical"]
    drift_score: float
    baseline_stats: dict
    current_stats: dict
    status: Literal["open", "acknowledged", "resolved"]
    detected_at: datetime
    resolved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriftAlertUpdate(BaseModel):
    """PATCH body — lifecycle transitions only."""

    status: Literal["acknowledged", "resolved"]
```

- [ ] **Step 4: `api/services/drift_service.py`**

```python
"""Drift service — alert listing + lifecycle transitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.drift_alert import DriftAlert

logger = logging.getLogger(__name__)


async def list_alerts(
    session: AsyncSession,
    status: str | None,
    severity: str | None,
    page: int,
    page_size: int,
) -> tuple[list[DriftAlert], int]:
    query = select(DriftAlert)
    if status is not None:
        query = query.where(DriftAlert.status == status)
    if severity is not None:
        query = query.where(DriftAlert.severity == severity)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(
            query.order_by(DriftAlert.detected_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def update_status(
    session: AsyncSession, alert_id: uuid.UUID, new_status: str
) -> DriftAlert | None:
    alert = (
        await session.execute(select(DriftAlert).where(DriftAlert.id == alert_id))
    ).scalar_one_or_none()
    if alert is None:
        return None
    alert.status = new_status
    alert.resolved_at = datetime.utcnow() if new_status == "resolved" else None
    await session.commit()
    await session.refresh(alert)
    logger.info("Drift alert %s → %s", alert_id, new_status)
    return alert
```

- [ ] **Step 5: `api/routers/drift.py`**

```python
"""Drift router — alert listing + acknowledge/resolve."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.schemas.common import PaginatedResponse
from api.schemas.drift_alert import DriftAlertResponse, DriftAlertUpdate
from api.services import drift_service

router = APIRouter(prefix="/drift", tags=["drift"])


@router.get("/alerts", response_model=PaginatedResponse[DriftAlertResponse])
async def list_alerts(
    status_filter: Literal["open", "acknowledged", "resolved"] | None = Query(None, alias="status"),
    severity: Literal["low", "medium", "high", "critical"] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DriftAlertResponse]:
    alerts, total = await drift_service.list_alerts(session, status_filter, severity, page, page_size)
    return PaginatedResponse[DriftAlertResponse](
        total=total, page=page, page_size=page_size,
        items=[DriftAlertResponse.model_validate(a) for a in alerts],
    )


@router.patch("/alerts/{alert_id}", response_model=DriftAlertResponse)
async def update_alert(
    alert_id: uuid.UUID,
    payload: DriftAlertUpdate,
    session: AsyncSession = Depends(get_db),
) -> DriftAlertResponse:
    alert = await drift_service.update_status(session, alert_id, payload.status)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found")
    return DriftAlertResponse.model_validate(alert)
```

- [ ] **Step 6: `workers/drift_worker.py`**

```python
"""
Drift worker — periodic detection across all active applications.

Loop daemon (same shape as metrics_worker). Each tick: distinct app ids
seen in the last baseline+1 days → detect per app → webhook on new alerts.

Run: python -m workers.drift_worker
"""

from __future__ import annotations

import asyncio
import logging
import random
import signal
from datetime import datetime, timedelta

from sqlalchemy import select

from api.config import get_settings
from api.dependencies import async_session_maker
from api.models.llm_log import LLMLog
from monitor.drift_detector import detect_drift_for_app
from monitor.webhooks import dispatch_drift_alert

logger = logging.getLogger(__name__)


async def run_once() -> None:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(days=settings.drift_baseline_days + 1)

    async with async_session_maker() as session:
        app_ids = (
            await session.execute(
                select(LLMLog.application_id).where(LLMLog.created_at >= cutoff).distinct()
            )
        ).scalars().all()

        for app_id in app_ids:
            try:
                alert = await detect_drift_for_app(session, app_id)
            except Exception as exc:  # noqa: BLE001 — one bad app never stops the sweep
                logger.error("drift detection failed for %s: %s", app_id, exc)
                continue
            if alert is not None:
                await dispatch_drift_alert({
                    "id": str(alert.id),
                    "application_id": alert.application_id,
                    "drift_type": alert.drift_type,
                    "severity": alert.severity,
                    "drift_score": float(alert.drift_score),
                    "detected_at": alert.detected_at.isoformat(),
                    "baseline_stats": alert.baseline_stats,
                    "current_stats": alert.current_stats,
                })


async def main() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("drift_worker started; interval=%ds", settings.drift_check_interval_seconds)
    while not stop.is_set():
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001
            logger.error("drift tick failed: %s", exc)
        delay = settings.drift_check_interval_seconds * random.uniform(0.9, 1.1)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
    logger.info("drift_worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    asyncio.run(main())
```

- [ ] **Step 7: Register in `api/main.py`** — replace `# Week 5+: app.include_router(drift.router)` with `app.include_router(drift.router)`; import becomes `from api.routers import drift, evals, health, logs, metrics`.

- [ ] **Step 8: Verify** — `pytest tests/ -v` → ALL tests green (full suite).

- [ ] **Step 9: Commit — Week 5 boundary**

```bash
git add workers/drift_worker.py api/services/drift_service.py api/routers/drift.py api/schemas/drift_alert.py api/main.py tests/integration/test_drift_api.py
git commit -m "Week 5: drift detection — detector, signed webhooks, worker, alerts API"
```

---

## Phase 4 — Dashboard (Week 6) — "Linen Terminal"

Frontend rules for every task in this phase: TypeScript strict, no `any`; design tokens ONLY via CSS variables (below) — no raw colors in components; terracotta accent reserved for drift/attention; every interactive element has hover/focus-visible/disabled states; every list has loading (skeleton rows), empty (teaching copy), and error (inline retry) states; all animation inside `@media (prefers-reduced-motion: no-preference)`.

Verification for frontend tasks = `cd frontend && npx tsc --noEmit && npm run build` (must succeed with zero errors) + visual check in browser against seeded data.

### Task 16: Frontend bootstrap — Vite config, tokens, fonts, API client, app shell

**Files:**
- Modify (all currently 0-byte): `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/types/index.ts`, `frontend/src/components/Layout.tsx`, `frontend/src/components/Navbar.tsx`
- Create: `frontend/index.html`, `frontend/src/index.css`, `frontend/tailwind.config.ts`, `frontend/postcss.config.js`

- [ ] **Step 1: `frontend/package.json`**

```json
{
  "name": "llm-obs-dashboard",
  "private": true,
  "version": "0.6.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@fontsource/ibm-plex-mono": "^5.0.0",
    "@fontsource/ibm-plex-sans": "^5.0.0",
    "@fontsource/jersey-25": "^5.0.0",
    "@tanstack/react-query": "^5.51.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.24.0",
    "recharts": "^2.12.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.3.0"
  }
}
```

- [ ] **Step 2: Install** — `cd frontend && npm install` → Expected: lockfile created, no errors.

- [ ] **Step 3: `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "noEmit": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"]
}
```

- [ ] **Step 4: `frontend/vite.config.ts`**

```typescript
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    // Dev proxy: dashboard calls /api/*, Vite strips the prefix → FastAPI :8000.
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
```

- [ ] **Step 5: `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>llm-obs · dashboard</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: `frontend/src/index.css`** — tokens + base:

```css
@import "@fontsource/jersey-25";
@import "@fontsource/ibm-plex-sans/400.css";
@import "@fontsource/ibm-plex-sans/500.css";
@import "@fontsource/ibm-plex-sans/600.css";
@import "@fontsource/ibm-plex-mono/400.css";
@import "@fontsource/ibm-plex-mono/500.css";

@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  /* Linen Terminal — spec tokens (OKLCH) */
  --bg: oklch(0.955 0.015 78);
  --surface: oklch(0.925 0.018 76);
  --raise: oklch(0.885 0.022 74);
  --hairline: oklch(0.855 0.02 75);
  --rule: oklch(0.815 0.022 73);
  --ink: oklch(0.36 0.06 48);
  --ink-2: oklch(0.48 0.048 56);
  --faint: oklch(0.6 0.04 62);
  --accent: oklch(0.6 0.125 42);
  --accent-soft: oklch(0.6 0.125 42 / 0.12);
  --sage: oklch(0.52 0.085 135);
  --rust: oklch(0.55 0.15 30);
  --font-display: "Jersey 25", "IBM Plex Sans", sans-serif;
  --font-ui: "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
}

html { background: var(--bg); color: var(--ink); font-family: var(--font-ui); }

/* Focus visibility — AA keyboard nav */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }

/* Number columns align on tabular figures */
.tnum { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

/* Chart draw-in — states a data refresh, honors reduced motion */
@media (prefers-reduced-motion: no-preference) {
  .fade-up { animation: fadeUp 240ms cubic-bezier(0.22, 1, 0.36, 1) both; }
  @keyframes fadeUp { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
}
```

- [ ] **Step 7: `frontend/tailwind.config.ts`**

```typescript
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        raise: "var(--raise)",
        hairline: "var(--hairline)",
        rule: "var(--rule)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        faint: "var(--faint)",
        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        sage: "var(--sage)",
        rust: "var(--rust)",
      },
      fontFamily: {
        display: ["Jersey 25", "IBM Plex Sans", "sans-serif"],
        ui: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
```

`frontend/postcss.config.js`:

```javascript
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 8: `frontend/src/types/index.ts`** — mirror API schemas:

```typescript
export interface Paginated<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface LLMLog {
  id: string;
  application_id: string;
  model: string;
  provider: string;
  prompt: string;
  response: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  time_to_first_token_ms: number | null;
  status: "success" | "error" | "timeout";
  otel_trace_id: string | null;
  otel_span_id: string | null;
  tags: Record<string, unknown> | null;
  created_at: string;
}

export interface Metric {
  id: string;
  application_id: string;
  model: string;
  period_type: "hourly" | "daily";
  period_start: string;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
}

export interface MetricsSummary {
  window: "24h" | "7d" | "30d";
  total_requests: number;
  total_cost_usd: number;
  error_rate: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
  cost_prev_window_usd: number;
  open_drift_alerts: number;
}

export interface TestCase {
  id: string;
  suite_name: string;
  input_prompt: string;
  expected_output: string;
  eval_methods: Array<"exact_match" | "embedding_similarity" | "llm_judge">;
  similarity_threshold: number;
  created_at: string;
  updated_at: string;
}

export interface EvalRun {
  id: string;
  suite_name: string;
  commit_sha: string;
  triggered_by: string;
  total_cases: number;
  passed_cases: number;
  pass_rate: number | null;
  gate_threshold: number;
  gate_result: "pass" | "fail" | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface EvalResult {
  id: string;
  eval_run_id: string;
  test_case_id: string;
  exact_match_score: number | null;
  embedding_score: number | null;
  llm_judge_score: number | null;
  llm_judge_reasoning: string | null;
  passed: boolean;
  created_at: string;
}

export interface EvalRunDetail {
  run: EvalRun;
  results: EvalResult[];
}

export interface DriftAlert {
  id: string;
  application_id: string;
  drift_type: string;
  severity: "low" | "medium" | "high" | "critical";
  drift_score: number;
  baseline_stats: Record<string, unknown>;
  current_stats: Record<string, unknown>;
  status: "open" | "acknowledged" | "resolved";
  detected_at: string;
  resolved_at: string | null;
  created_at: string;
}
```

- [ ] **Step 9: `frontend/src/api/client.ts`**

```typescript
/**
 * Thin fetch wrapper. All requests go through /api (Vite dev proxy → :8000;
 * in docker the same prefix is nginx-routed). Throws ApiError on non-2xx so
 * TanStack Query lands in error state with a usable message.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api";

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    }
  }
  const resp = await fetch(url);
  if (!resp.ok) throw new ApiError(resp.status, `${resp.status} ${resp.statusText} — GET ${path}`);
  return resp.json() as Promise<T>;
}

export async function apiSend<T>(method: "POST" | "PATCH", path: string, body: unknown): Promise<T> {
  const resp = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new ApiError(resp.status, `${resp.status} ${resp.statusText} — ${method} ${path}`);
  return resp.json() as Promise<T>;
}
```

- [ ] **Step 10: API modules** — `frontend/src/api/logs.ts`, `metrics.ts`, `evals.ts`, `drift.ts`:

```typescript
// frontend/src/api/logs.ts
import { apiGet } from "./client";
import type { LLMLog, Paginated } from "@/types";

export interface LogFilters {
  application_id?: string;
  model?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export const fetchLogs = (f: LogFilters) => apiGet<Paginated<LLMLog>>("/logs", { page_size: 50, ...f });
export const fetchLog = (id: string) => apiGet<LLMLog>(`/logs/${id}`);
```

```typescript
// frontend/src/api/metrics.ts
import { apiGet } from "./client";
import type { Metric, MetricsSummary, Paginated } from "@/types";

export const fetchSummary = (window: "24h" | "7d" | "30d") =>
  apiGet<MetricsSummary>("/metrics/summary", { window });

export const fetchMetrics = (params: { period_type?: "hourly" | "daily"; application_id?: string; start?: string; page_size?: number }) =>
  apiGet<Paginated<Metric>>("/metrics", { page_size: 1000, ...params });
```

```typescript
// frontend/src/api/evals.ts
import { apiGet } from "./client";
import type { EvalRun, EvalRunDetail, Paginated } from "@/types";

export const fetchRuns = (page: number) => apiGet<Paginated<EvalRun>>("/evals/runs", { page, page_size: 50 });
export const fetchRunDetail = (id: string) => apiGet<EvalRunDetail>(`/evals/runs/${id}`);
```

```typescript
// frontend/src/api/drift.ts
import { apiGet, apiSend } from "./client";
import type { DriftAlert, Paginated } from "@/types";

export const fetchAlerts = (status?: string) =>
  apiGet<Paginated<DriftAlert>>("/drift/alerts", { status, page_size: 100 });

export const updateAlert = (id: string, status: "acknowledged" | "resolved") =>
  apiSend<DriftAlert>("PATCH", `/drift/alerts/${id}`, { status });
```

- [ ] **Step 11: Shell** — `frontend/src/main.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

`frontend/src/App.tsx`:

```tsx
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { DriftAlerts } from "./pages/DriftAlerts";
import { Evals } from "./pages/Evals";
import { Logs } from "./pages/Logs";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="logs" element={<Logs />} />
        <Route path="evals" element={<Evals />} />
        <Route path="drift" element={<DriftAlerts />} />
      </Route>
    </Routes>
  );
}
```

`frontend/src/components/Navbar.tsx` (sidebar — name kept for existing file):

```tsx
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchAlerts } from "@/api/drift";

const links = [
  { to: "/", label: "Overview" },
  { to: "/logs", label: "Logs" },
  { to: "/evals", label: "Evals" },
  { to: "/drift", label: "Drift" },
];

export function Navbar() {
  const { data } = useQuery({ queryKey: ["alerts", "open"], queryFn: () => fetchAlerts("open"), refetchInterval: 30_000 });
  const openCount = data?.total ?? 0;

  return (
    <nav className="flex h-full w-44 shrink-0 flex-col border-r border-rule bg-surface px-2 py-4">
      <div className="mb-6 flex items-center gap-2 px-2">
        <svg width="14" height="14" viewBox="0 0 12 12" aria-hidden>
          <rect x="1" y="6" width="2" height="5" fill="var(--accent)" />
          <rect x="5" y="3" width="2" height="8" fill="var(--ink-2)" />
          <rect x="9" y="1" width="2" height="10" fill="var(--ink-2)" />
        </svg>
        <span className="font-display text-xl leading-none">llm-obs</span>
      </div>
      {links.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            `flex items-center justify-between rounded px-2 py-1.5 text-sm transition-colors duration-150 ${
              isActive ? "bg-raise text-ink" : "text-ink-2 hover:bg-raise/60 hover:text-ink"
            }`
          }
        >
          <span>{label}</span>
          {label === "Drift" && openCount > 0 && (
            <span className="tnum flex items-center gap-1 text-xs text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
              {openCount}
            </span>
          )}
        </NavLink>
      ))}
      <div className="tnum mt-auto px-2 text-[10px] text-faint">v0.6.0</div>
    </nav>
  );
}
```

`frontend/src/components/Layout.tsx`:

```tsx
import { Outlet } from "react-router-dom";
import { Navbar } from "./Navbar";

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Navbar />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
```

Also create four MINIMAL placeholder pages so the build compiles (each replaced in Tasks 17–20). Example `frontend/src/pages/Dashboard.tsx` (repeat shape for Logs/Evals/DriftAlerts with their names):

```tsx
export function Dashboard() {
  return <div className="p-6 text-ink-2">Overview — built in Task 17.</div>;
}
```

- [ ] **Step 12: Verify** — `cd frontend && npx tsc --noEmit && npm run build` → zero errors. `npm run dev` → sidebar renders on linen bg, Jersey 25 brand visible.

- [ ] **Step 13: Commit**

```bash
git add frontend/
git commit -m "Week 6a: frontend bootstrap — linen-terminal tokens, fonts, router shell, API client"
```

### Task 17: Overview page

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`, `frontend/src/hooks/useMetrics.ts` (stub)
- Create: `frontend/src/components/ChartPanel.tsx`, `frontend/src/components/LedgerStrip.tsx`

- [ ] **Step 1: `frontend/src/hooks/useMetrics.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { fetchMetrics, fetchSummary } from "@/api/metrics";

export function useSummary(window: "24h" | "7d" | "30d") {
  return useQuery({
    queryKey: ["summary", window],
    queryFn: () => fetchSummary(window),
    refetchInterval: 30_000,
  });
}

export function useHourlyMetrics(sinceIso: string) {
  return useQuery({
    queryKey: ["metrics", "hourly", sinceIso],
    queryFn: () => fetchMetrics({ period_type: "hourly", start: sinceIso }),
    refetchInterval: 30_000,
  });
}
```

- [ ] **Step 2: `frontend/src/components/LedgerStrip.tsx`** — the signature metrics strip (NOT a card grid):

```tsx
import type { MetricsSummary } from "@/types";

function usd(v: number): string {
  return v.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function LedgerStrip({ s }: { s: MetricsSummary }) {
  const delta = s.cost_prev_window_usd > 0 ? (s.total_cost_usd - s.cost_prev_window_usd) / s.cost_prev_window_usd : null;
  return (
    <div className="flex items-stretch border-b border-rule px-6 py-4">
      <div className="pr-7">
        <div className="text-[11px] text-faint">Spend, {s.window}</div>
        <div className="font-display text-4xl leading-none tracking-tight">{usd(s.total_cost_usd)}</div>
        <div className="tnum mt-1 text-[11px] text-ink-2">
          {delta === null ? "no prior data" : `${delta >= 0 ? "+" : "−"}${Math.abs(delta * 100).toFixed(1)}% vs prior`}
        </div>
      </div>
      <div className="flex flex-col justify-center border-l border-rule px-7">
        <div className="mb-1 text-[11px] text-faint">Latency</div>
        <div className="tnum text-xs leading-relaxed text-ink-2">
          <div>p50 <span className="text-ink">{s.p50_latency_ms ?? "—"}ms</span></div>
          <div>p95 <span className="text-ink">{s.p95_latency_ms ?? "—"}ms</span></div>
          <div>p99 <span className="font-medium text-ink">{s.p99_latency_ms ?? "—"}ms</span></div>
        </div>
      </div>
      <div className="flex flex-col justify-center border-l border-rule px-7">
        <div className="mb-1 text-[11px] text-faint">Requests</div>
        <div className="tnum text-xl font-medium">{s.total_requests.toLocaleString()}</div>
        <div className="tnum mt-0.5 text-[11px] text-ink-2">err {(s.error_rate * 100).toFixed(1)}%</div>
      </div>
      <div className="flex flex-1 flex-col justify-center border-l border-rule px-7">
        <div className="mb-1 text-[11px] text-faint">Attention</div>
        {s.open_drift_alerts > 0 ? (
          <div className="flex items-center gap-2 text-accent">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
            <span className="tnum text-sm font-medium">{s.open_drift_alerts} open drift alert{s.open_drift_alerts > 1 ? "s" : ""}</span>
          </div>
        ) : (
          <div className="text-sm text-sage">all clear</div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: `frontend/src/components/ChartPanel.tsx`** — shared ruled panel + Recharts theming:

```tsx
import type { ReactNode } from "react";

export function ChartPanel({ title, unit, children, className = "" }: {
  title: string;
  unit?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border-b border-rule px-6 py-4 ${className}`}>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        {unit && <span className="tnum text-[10px] text-faint">{unit}</span>}
      </div>
      {children}
    </section>
  );
}

/** Shared Recharts props — tokens only, no library default colors. */
export const chartAxis = {
  stroke: "var(--faint)",
  fontSize: 10,
  fontFamily: "var(--font-mono)",
  tickLine: false,
  axisLine: { stroke: "var(--rule)" },
} as const;

export const chartTooltip = {
  contentStyle: {
    background: "var(--bg)",
    border: "1px solid var(--rule)",
    borderRadius: 4,
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    color: "var(--ink)",
  },
} as const;
```

- [ ] **Step 4: `frontend/src/pages/Dashboard.tsx`** — full page:

```tsx
import { useMemo, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { ChartPanel, chartAxis, chartTooltip } from "@/components/ChartPanel";
import { LedgerStrip } from "@/components/LedgerStrip";
import { useHourlyMetrics, useSummary } from "@/hooks/useMetrics";

type Win = "24h" | "7d" | "30d";
const WINDOW_HOURS: Record<Win, number> = { "24h": 24, "7d": 168, "30d": 720 };

export function Dashboard() {
  const [win, setWin] = useState<Win>("7d");
  const summary = useSummary(win);
  const since = useMemo(
    () => new Date(Date.now() - WINDOW_HOURS[win] * 3600_000).toISOString(),
    [win],
  );
  const metrics = useHourlyMetrics(since);

  const series = useMemo(() => {
    const byHour = new Map<string, { t: string; cost: number; p50: number | null; p95: number | null; p99: number | null; requests: number }>();
    for (const m of metrics.data?.items ?? []) {
      const key = m.period_start;
      const cur = byHour.get(key) ?? { t: key, cost: 0, p50: null, p95: null, p99: null, requests: 0 };
      cur.cost += Number(m.total_cost_usd);
      cur.requests += m.total_requests;
      cur.p50 = m.p50_latency_ms ?? cur.p50;
      cur.p95 = m.p95_latency_ms ?? cur.p95;
      cur.p99 = m.p99_latency_ms ?? cur.p99;
      byHour.set(key, cur);
    }
    return [...byHour.values()].sort((a, b) => a.t.localeCompare(b.t))
      .map((r) => ({ ...r, label: new Date(r.t).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" }) }));
  }, [metrics.data]);

  if (summary.isPending) {
    return <div className="space-y-3 p-6">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded bg-raise" />)}</div>;
  }
  if (summary.isError) {
    return (
      <div className="p-6 text-sm text-rust">
        Could not load metrics — is the API running?{" "}
        <button className="underline hover:text-ink" onClick={() => summary.refetch()}>Retry</button>
      </div>
    );
  }

  return (
    <div className="fade-up">
      <header className="flex items-center justify-between border-b border-rule px-6 py-3.5">
        <div>
          <h1 className="font-display text-2xl leading-none">Overview</h1>
          <p className="tnum mt-0.5 text-[11px] text-faint">all applications · refreshes every 30s</p>
        </div>
        <div className="flex overflow-hidden rounded border border-hairline text-xs" role="tablist" aria-label="Time window">
          {(["24h", "7d", "30d"] as const).map((w) => (
            <button
              key={w}
              role="tab"
              aria-selected={win === w}
              onClick={() => setWin(w)}
              className={`px-3 py-1 transition-colors duration-150 ${win === w ? "bg-raise text-ink" : "text-ink-2 hover:text-ink"}`}
            >
              {w}
            </button>
          ))}
        </div>
      </header>

      <LedgerStrip s={summary.data} />

      <ChartPanel title="Spend over time" unit="USD/hour">
        {series.length === 0 ? (
          <p className="py-8 text-center text-sm text-faint">No rollups yet — the metrics worker aggregates every 5 minutes. Seed demo data with <code className="tnum">python -m scripts.seed</code>.</p>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--hairline)" strokeDasharray="0" vertical={false} />
              <XAxis dataKey="label" {...chartAxis} minTickGap={48} />
              <YAxis {...chartAxis} />
              <Tooltip {...chartTooltip} />
              <Area dataKey="cost" stroke="var(--ink)" strokeWidth={1.5} fill="var(--accent-soft)" isAnimationActive={false} name="USD" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </ChartPanel>

      <ChartPanel title="Latency percentiles" unit="hourly · ms">
        {series.length === 0 ? (
          <p className="py-8 text-center text-sm text-faint">No latency data in this window.</p>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--hairline)" vertical={false} />
              <XAxis dataKey="label" {...chartAxis} minTickGap={48} />
              <YAxis {...chartAxis} />
              <Tooltip {...chartTooltip} />
              <Line dataKey="p50" stroke="var(--faint)" strokeWidth={1} dot={false} isAnimationActive={false} />
              <Line dataKey="p95" stroke="var(--ink-2)" strokeWidth={1} dot={false} isAnimationActive={false} />
              <Line dataKey="p99" stroke="var(--ink)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
        <div className="tnum mt-1 flex gap-4 text-[10px]">
          <span className="text-faint">━ p50</span>
          <span className="text-ink-2">━ p95</span>
          <span className="text-ink">━ p99</span>
        </div>
      </ChartPanel>
    </div>
  );
}
```

- [ ] **Step 5: Verify** — `npx tsc --noEmit && npm run build` clean; with API + seeded data running, Overview shows ledger strip + two charts; empty-DB shows teaching empty states.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "Week 6b: Overview — ledger strip, spend + latency charts, window switcher"
```

### Task 18: Logs page

**Files:**
- Modify: `frontend/src/pages/Logs.tsx`, `frontend/src/hooks/useLogs.ts`

- [ ] **Step 1: `frontend/src/hooks/useLogs.ts`**

```typescript
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchLogs, type LogFilters } from "@/api/logs";

export function useLogs(filters: LogFilters) {
  return useQuery({
    queryKey: ["logs", filters],
    queryFn: () => fetchLogs(filters),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData, // page flips don't blank the table
  });
}
```

- [ ] **Step 2: `frontend/src/pages/Logs.tsx`**

```tsx
import { useState } from "react";
import { useLogs } from "@/hooks/useLogs";
import type { LLMLog } from "@/types";

const inputCls =
  "rounded border border-hairline bg-bg px-2 py-1 text-xs text-ink placeholder:text-faint focus-visible:border-accent disabled:opacity-50";

function StatusMark({ s }: { s: LLMLog["status"] }) {
  const tone = s === "success" ? "text-sage" : "text-rust";
  return <span className={`tnum text-[11px] font-medium uppercase ${tone}`}>{s}</span>;
}

export function Logs() {
  const [app, setApp] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<LLMLog | null>(null);

  const q = useLogs({
    application_id: app || undefined,
    model: model || undefined,
    status: status || undefined,
    page,
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;

  return (
    <div className="fade-up">
      <header className="flex items-center justify-between border-b border-rule px-6 py-3.5">
        <div>
          <h1 className="font-display text-2xl leading-none">Logs</h1>
          <p className="tnum mt-0.5 text-[11px] text-faint">{q.data ? `${q.data.total.toLocaleString()} records · refreshes every 10s` : "loading"}</p>
        </div>
        <div className="flex gap-2">
          <input className={inputCls} placeholder="application" value={app} onChange={(e) => { setApp(e.target.value); setPage(1); }} />
          <input className={inputCls} placeholder="model" value={model} onChange={(e) => { setModel(e.target.value); setPage(1); }} />
          <select className={inputCls} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="status filter">
            <option value="">any status</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="timeout">timeout</option>
          </select>
        </div>
      </header>

      {q.isPending && (
        <div className="space-y-px p-6">{Array.from({ length: 8 }, (_, i) => <div key={i} className="h-8 animate-pulse bg-raise" />)}</div>
      )}
      {q.isError && (
        <div className="p-6 text-sm text-rust">
          Failed to load logs. <button className="underline hover:text-ink" onClick={() => q.refetch()}>Retry</button>
        </div>
      )}
      {q.data && q.data.items.length === 0 && (
        <p className="p-10 text-center text-sm text-faint">
          No logs match. Send one with <code className="tnum">POST /logs</code> or run <code className="tnum">python -m scripts.seed</code>.
        </p>
      )}

      {q.data && q.data.items.length > 0 && (
        <>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-rule text-[10px] uppercase tracking-wide text-faint">
                <th className="px-6 py-2 font-medium">time</th>
                <th className="py-2 font-medium">application</th>
                <th className="py-2 font-medium">model</th>
                <th className="py-2 text-right font-medium">latency</th>
                <th className="py-2 text-right font-medium">cost</th>
                <th className="px-6 py-2 text-right font-medium">status</th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((log) => (
                <tr
                  key={log.id}
                  onClick={() => setSelected(log)}
                  className="cursor-pointer border-b border-hairline transition-colors duration-150 hover:bg-raise/50"
                >
                  <td className="tnum px-6 py-2 text-ink-2">{new Date(log.created_at).toLocaleString()}</td>
                  <td className="py-2">{log.application_id}</td>
                  <td className="tnum py-2 text-ink-2">{log.model}</td>
                  <td className="tnum py-2 text-right">{log.latency_ms != null ? `${log.latency_ms}ms` : "—"}</td>
                  <td className="tnum py-2 text-right">{log.cost_usd != null ? `$${Number(log.cost_usd).toFixed(4)}` : "—"}</td>
                  <td className="px-6 py-2 text-right"><StatusMark s={log.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="tnum flex items-center justify-between px-6 py-3 text-xs text-ink-2">
            <span>page {q.data.page} / {pages}</span>
            <div className="flex gap-1">
              <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>prev</button>
              <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>next</button>
            </div>
          </div>
        </>
      )}

      {selected && (
        <aside className="fixed inset-y-0 right-0 z-10 w-[480px] overflow-y-auto border-l border-rule bg-bg p-6 shadow-xl" role="dialog" aria-label="Log detail">
          <div className="mb-4 flex items-start justify-between">
            <div>
              <h2 className="font-display text-xl">{selected.model}</h2>
              <p className="tnum text-[11px] text-faint">{selected.id}</p>
            </div>
            <button className="rounded border border-hairline px-2 py-1 text-xs hover:bg-raise" onClick={() => setSelected(null)}>close</button>
          </div>
          <dl className="tnum grid grid-cols-2 gap-x-4 gap-y-2 border-b border-rule pb-4 text-xs">
            <dt className="text-faint">application</dt><dd>{selected.application_id}</dd>
            <dt className="text-faint">provider</dt><dd>{selected.provider}</dd>
            <dt className="text-faint">status</dt><dd><StatusMark s={selected.status} /></dd>
            <dt className="text-faint">latency</dt><dd>{selected.latency_ms ?? "—"}ms</dd>
            <dt className="text-faint">tokens</dt><dd>{selected.total_tokens ?? "—"}</dd>
            <dt className="text-faint">cost</dt><dd>{selected.cost_usd != null ? `$${Number(selected.cost_usd).toFixed(6)}` : "—"}</dd>
            <dt className="text-faint">trace</dt><dd className="break-all">{selected.otel_trace_id ?? "—"}</dd>
            <dt className="text-faint">span</dt><dd>{selected.otel_span_id ?? "—"}</dd>
          </dl>
          <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-faint">prompt</h3>
          <pre className="tnum whitespace-pre-wrap rounded border border-hairline bg-surface p-3 text-xs">{selected.prompt}</pre>
          <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-faint">response</h3>
          <pre className="tnum whitespace-pre-wrap rounded border border-hairline bg-surface p-3 text-xs">{selected.response ?? "(no response — call failed)"}</pre>
        </aside>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify** — build clean; filters narrow the table; drawer opens/closes; pagination works against seeded data.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "Week 6c: Logs — filterable ruled table, detail drawer, pagination"
```

### Task 19: Evals page

**Files:**
- Modify: `frontend/src/pages/Evals.tsx`
- Create: `frontend/src/hooks/useEvals.ts` (there is no stub for this hook — create it; useDrift.ts stub is used in Task 20)

- [ ] **Step 1: `frontend/src/hooks/useEvals.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { fetchRunDetail, fetchRuns } from "@/api/evals";

export function useEvalRuns(page: number) {
  return useQuery({
    queryKey: ["eval-runs", page],
    queryFn: () => fetchRuns(page),
    refetchInterval: 30_000,
  });
}

export function useEvalRunDetail(id: string | null) {
  return useQuery({
    queryKey: ["eval-run", id],
    queryFn: () => fetchRunDetail(id as string),
    enabled: id !== null,
  });
}
```

- [ ] **Step 2: `frontend/src/pages/Evals.tsx`**

```tsx
import { useState } from "react";
import { useEvalRunDetail, useEvalRuns } from "@/hooks/useEvals";
import type { EvalResult } from "@/types";

function GateBadge({ result }: { result: "pass" | "fail" | null }) {
  if (result === null) return <span className="tnum text-[11px] text-faint">pending</span>;
  const tone = result === "pass" ? "text-sage" : "text-rust";
  return <span className={`tnum text-[11px] font-medium uppercase ${tone}`}>{result}</span>;
}

function Score({ v }: { v: number | null }) {
  return <span className="tnum">{v === null ? "—" : Number(v).toFixed(2)}</span>;
}

function ResultRow({ r }: { r: EvalResult }) {
  const [open, setOpen] = useState(false);
  const hasReasoning = r.llm_judge_reasoning !== null && r.llm_judge_reasoning !== "";
  return (
    <>
      <tr
        className={`border-b border-hairline ${hasReasoning ? "cursor-pointer hover:bg-raise/50" : ""} transition-colors duration-150`}
        onClick={() => hasReasoning && setOpen((o) => !o)}
      >
        <td className="tnum px-6 py-2 text-ink-2">{r.test_case_id.slice(0, 8)}</td>
        <td className="py-2 text-right"><Score v={r.exact_match_score} /></td>
        <td className="py-2 text-right"><Score v={r.embedding_score} /></td>
        <td className="py-2 text-right"><Score v={r.llm_judge_score} /></td>
        <td className={`tnum px-6 py-2 text-right text-[11px] font-medium uppercase ${r.passed ? "text-sage" : "text-rust"}`}>
          {r.passed ? "pass" : "fail"}
        </td>
      </tr>
      {open && hasReasoning && (
        <tr className="border-b border-hairline bg-surface">
          <td colSpan={5} className="px-6 py-2 text-xs italic text-ink-2">judge: {r.llm_judge_reasoning}</td>
        </tr>
      )}
    </>
  );
}

export function Evals() {
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const runs = useEvalRuns(page);
  const detail = useEvalRunDetail(selectedId);
  const pages = runs.data ? Math.max(1, Math.ceil(runs.data.total / runs.data.page_size)) : 1;

  return (
    <div className="fade-up">
      <header className="border-b border-rule px-6 py-3.5">
        <h1 className="font-display text-2xl leading-none">Evals</h1>
        <p className="tnum mt-0.5 text-[11px] text-faint">
          {runs.data ? `${runs.data.total} runs · gate threshold blocks CI on fail` : "loading"}
        </p>
      </header>

      {runs.isPending && (
        <div className="space-y-px p-6">{Array.from({ length: 6 }, (_, i) => <div key={i} className="h-8 animate-pulse bg-raise" />)}</div>
      )}
      {runs.isError && (
        <div className="p-6 text-sm text-rust">
          Failed to load runs. <button className="underline hover:text-ink" onClick={() => runs.refetch()}>Retry</button>
        </div>
      )}
      {runs.data && runs.data.items.length === 0 && (
        <p className="p-10 text-center text-sm text-faint">
          No eval runs yet. Trigger one: <code className="tnum">python -m eval.runner --suite core --commit-sha demo</code>
        </p>
      )}

      {runs.data && runs.data.items.length > 0 && (
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-rule text-[10px] uppercase tracking-wide text-faint">
              <th className="px-6 py-2 font-medium">when</th>
              <th className="py-2 font-medium">suite</th>
              <th className="py-2 font-medium">commit</th>
              <th className="py-2 text-right font-medium">passed</th>
              <th className="py-2 text-right font-medium">rate</th>
              <th className="px-6 py-2 text-right font-medium">gate</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.items.map((run) => (
              <tr
                key={run.id}
                onClick={() => setSelectedId(run.id === selectedId ? null : run.id)}
                className={`cursor-pointer border-b border-hairline transition-colors duration-150 hover:bg-raise/50 ${selectedId === run.id ? "bg-raise/60" : ""}`}
              >
                <td className="tnum px-6 py-2 text-ink-2">{new Date(run.created_at).toLocaleString()}</td>
                <td className="py-2">{run.suite_name}</td>
                <td className="tnum py-2 text-ink-2">{run.commit_sha.slice(0, 10)}</td>
                <td className="tnum py-2 text-right">{run.passed_cases}/{run.total_cases}</td>
                <td className="tnum py-2 text-right">{run.pass_rate !== null ? `${(Number(run.pass_rate) * 100).toFixed(1)}%` : "—"}</td>
                <td className="px-6 py-2 text-right"><GateBadge result={run.gate_result} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {runs.data && pages > 1 && (
        <div className="tnum flex items-center justify-between px-6 py-3 text-xs text-ink-2">
          <span>page {page} / {pages}</span>
          <div className="flex gap-1">
            <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>prev</button>
            <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>next</button>
          </div>
        </div>
      )}

      {selectedId && detail.data && (
        <section className="border-t-2 border-rule">
          <div className="flex items-baseline justify-between px-6 py-3">
            <h2 className="text-sm font-semibold">Run detail — {detail.data.run.suite_name} @ {detail.data.run.commit_sha.slice(0, 10)}</h2>
            <span className="tnum text-[11px] text-faint">
              threshold {Number(detail.data.run.gate_threshold).toFixed(2)} · {detail.data.results.length} cases · click a row for judge reasoning
            </span>
          </div>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-rule text-[10px] uppercase tracking-wide text-faint">
                <th className="px-6 py-2 font-medium">case</th>
                <th className="py-2 text-right font-medium">exact</th>
                <th className="py-2 text-right font-medium">embed</th>
                <th className="py-2 text-right font-medium">judge</th>
                <th className="px-6 py-2 text-right font-medium">verdict</th>
              </tr>
            </thead>
            <tbody>
              {detail.data.results.map((r) => <ResultRow key={r.id} r={r} />)}
            </tbody>
          </table>
        </section>
      )}
      {selectedId && detail.isPending && <div className="h-24 animate-pulse bg-raise" />}
    </div>
  );
}
```

- [ ] **Step 3: Verify** — build clean; run list renders, clicking a run expands detail, judge reasoning rows toggle.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "Week 6d: Evals — runs ledger, gate badges, per-case detail with judge reasoning"
```

### Task 20: Drift page + frontend polish pass

**Files:**
- Modify: `frontend/src/pages/DriftAlerts.tsx`, `frontend/src/hooks/useDrift.ts`

- [ ] **Step 1: `frontend/src/hooks/useDrift.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAlerts, updateAlert } from "@/api/drift";
import type { DriftAlert, Paginated } from "@/types";

export function useDriftAlerts(status?: string) {
  return useQuery({
    queryKey: ["drift-alerts", status ?? "all"],
    queryFn: () => fetchAlerts(status),
    refetchInterval: 30_000,
  });
}

export function useUpdateAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: "acknowledged" | "resolved" }) => updateAlert(id, status),
    // Optimistic: flip status locally, roll back on error
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: ["drift-alerts"] });
      const snapshots = qc.getQueriesData<Paginated<DriftAlert>>({ queryKey: ["drift-alerts"] });
      for (const [key, data] of snapshots) {
        if (!data) continue;
        qc.setQueryData(key, {
          ...data,
          items: data.items.map((a) => (a.id === id ? { ...a, status } : a)),
        });
      }
      return { snapshots };
    },
    onError: (_err, _vars, ctx) => {
      for (const [key, data] of ctx?.snapshots ?? []) qc.setQueryData(key, data);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["drift-alerts"] });
      void qc.invalidateQueries({ queryKey: ["alerts", "open"] }); // sidebar count
    },
  });
}
```

- [ ] **Step 2: `frontend/src/pages/DriftAlerts.tsx`**

```tsx
import { useState } from "react";
import { useDriftAlerts, useUpdateAlert } from "@/hooks/useDrift";
import type { DriftAlert } from "@/types";

const SEVERITY_TONE: Record<DriftAlert["severity"], string> = {
  low: "text-ink-2",
  medium: "text-accent",
  high: "text-accent",
  critical: "text-rust",
};

function StatRow({ label, stats }: { label: string; stats: Record<string, unknown> }) {
  return (
    <div className="tnum text-[11px] text-ink-2">
      <span className="text-faint">{label}:</span>{" "}
      {Object.entries(stats).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" · ") || "—"}
    </div>
  );
}

export function DriftAlerts() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const q = useDriftAlerts(statusFilter || undefined);
  const mutation = useUpdateAlert();

  return (
    <div className="fade-up">
      <header className="flex items-center justify-between border-b border-rule px-6 py-3.5">
        <div>
          <h1 className="font-display text-2xl leading-none">Drift</h1>
          <p className="tnum mt-0.5 text-[11px] text-faint">
            prompt-distribution shifts vs 7-day baseline · detector runs hourly
          </p>
        </div>
        <div className="flex overflow-hidden rounded border border-hairline text-xs" role="tablist" aria-label="Status filter">
          {["", "open", "acknowledged", "resolved"].map((s) => (
            <button
              key={s || "all"}
              role="tab"
              aria-selected={statusFilter === s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1 transition-colors duration-150 ${statusFilter === s ? "bg-raise text-ink" : "text-ink-2 hover:text-ink"}`}
            >
              {s || "all"}
            </button>
          ))}
        </div>
      </header>

      {q.isPending && (
        <div className="space-y-3 p-6">{[0, 1].map((i) => <div key={i} className="h-24 animate-pulse rounded bg-raise" />)}</div>
      )}
      {q.isError && (
        <div className="p-6 text-sm text-rust">
          Failed to load alerts. <button className="underline hover:text-ink" onClick={() => q.refetch()}>Retry</button>
        </div>
      )}
      {q.data && q.data.items.length === 0 && (
        <p className="p-10 text-center text-sm text-faint">
          No {statusFilter || ""} drift alerts — input distribution is stable. The detector compares each app&apos;s last 24h of prompt embeddings against its 7-day baseline.
        </p>
      )}

      {q.data?.items.map((alert) => (
        <article key={alert.id} className="border-b border-rule px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                {alert.status === "open" && <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />}
                <span className={`tnum text-[11px] font-semibold uppercase ${SEVERITY_TONE[alert.severity]}`}>{alert.severity}</span>
                <span className="text-sm font-semibold">{alert.application_id}</span>
                <span className="tnum text-[11px] text-faint">score {Number(alert.drift_score).toFixed(4)}</span>
              </div>
              <p className="tnum mt-1 text-[11px] text-faint">
                {alert.drift_type} · detected {new Date(alert.detected_at).toLocaleString()}
                {alert.resolved_at && ` · resolved ${new Date(alert.resolved_at).toLocaleString()}`}
              </p>
              <div className="mt-2 space-y-0.5">
                <StatRow label="baseline" stats={alert.baseline_stats} />
                <StatRow label="current" stats={alert.current_stats} />
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              {alert.status === "open" && (
                <button
                  className="rounded border border-hairline px-3 py-1 text-xs hover:bg-raise disabled:opacity-40"
                  disabled={mutation.isPending}
                  onClick={() => mutation.mutate({ id: alert.id, status: "acknowledged" })}
                >
                  acknowledge
                </button>
              )}
              {alert.status !== "resolved" && (
                <button
                  className="rounded border border-hairline px-3 py-1 text-xs text-sage hover:bg-raise disabled:opacity-40"
                  disabled={mutation.isPending}
                  onClick={() => mutation.mutate({ id: alert.id, status: "resolved" })}
                >
                  resolve
                </button>
              )}
              {alert.status === "resolved" && <span className="tnum text-[11px] uppercase text-sage">resolved</span>}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Polish checklist (verify each in browser, fix violations)**

- Focus-visible ring appears on every button/input/row via keyboard Tab
- Accent (terracotta) appears ONLY on: drift severity marks, open-alert dots, sidebar drift count, window-switcher focus, spend area fill — nowhere decorative
- Empty/loading/error states on all 4 pages
- `prefers-reduced-motion: reduce` (macOS: System Settings → Accessibility → Display → Reduce motion) kills fade-ups
- Body text pairs pass AA: `--ink` and `--ink-2` on `--bg` and `--surface` (check with browser devtools contrast checker; adjust L values down if any pair < 4.5:1)
- No horizontal scroll at 1024px width

- [ ] **Step 4: Verify** — `npx tsc --noEmit && npm run build` clean; all four pages against seeded data.

- [ ] **Step 5: Commit — Week 6 boundary**

```bash
git add frontend/src
git commit -m "Week 6: dashboard complete — drift page, optimistic updates, a11y polish"
```

---

## Phase 5 — Observability (Week 7)

### Task 21: Prometheus metrics endpoint + custom counters

**Files:**
- Create: `api/observability.py`
- Modify: `api/main.py` (instrumentator hookup), `infra/prometheus/prometheus.yml` (verify scrape target)
- Modify: `api/services/log_service.py` (increment counters), `eval/engine.py` (run counter), `monitor/drift_detector.py` (alert counter)
- Test: `tests/integration/test_observability.py` (new)

- [ ] **Step 1: Failing test** — `tests/integration/test_observability.py`:

```python
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
```

- [ ] **Step 2: Verify fail** — 404 on `/prometheus-metrics`.

- [ ] **Step 3: `api/observability.py`**

```python
"""
Prometheus custom metrics — one registry-backed module, imported anywhere.

prometheus_client metrics are process-global singletons; defining them here
once avoids duplicate-registration errors on app factory re-use (tests call
create_app() repeatedly, so instrumentation must be idempotent).
"""

from __future__ import annotations

from prometheus_client import Counter

llm_logs_ingested_total = Counter(
    "llm_logs_ingested_total", "LLM call logs ingested", ["application_id", "model", "status"]
)
llm_cost_usd_total = Counter(
    "llm_cost_usd_total", "Cumulative logged LLM spend (USD)", ["application_id", "model"]
)
eval_runs_total = Counter(
    "eval_runs_total", "Eval runs completed", ["suite_name", "gate_result"]
)
drift_alerts_total = Counter(
    "drift_alerts_total", "Drift alerts created", ["application_id", "severity"]
)
```

- [ ] **Step 4: Wire instrumentator in `api/main.py`** — inside `create_app()` after routers:

```python
    # Prometheus: /prometheus-metrics (not /metrics — that's the rollup API)
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(excluded_handlers=["/prometheus-metrics", "/health"]).instrument(app).expose(
        app, endpoint="/prometheus-metrics", include_in_schema=False
    )
```

If tests raise `Duplicated timeseries` on repeated create_app(): guard with a module flag or pass `registry` — preferred fix is `try/except ValueError` around `.instrument(app)` with a comment, keeping test runs green.

- [ ] **Step 5: Increment counters at the three sites**

`api/services/log_service.py` — in `create_log` after commit:

```python
    from api.observability import llm_cost_usd_total, llm_logs_ingested_total

    llm_logs_ingested_total.labels(log.application_id, log.model, log.status).inc()
    if log.cost_usd is not None:
        llm_cost_usd_total.labels(log.application_id, log.model).inc(float(log.cost_usd))
```

`eval/engine.py` — after `await session.commit()` in `run_eval`:

```python
    from api.observability import eval_runs_total

    eval_runs_total.labels(suite_name, run.gate_result).inc()
```

`monitor/drift_detector.py` — after `await session.refresh(alert)`:

```python
    from api.observability import drift_alerts_total

    drift_alerts_total.labels(application_id, severity).inc()
```

(Local imports keep eval/ + monitor/ importable without prometheus_client in exotic contexts and avoid cycles. prometheus_client has no FastAPI dependency — the standalone rule is intact.)

- [ ] **Step 6: Verify `infra/prometheus/prometheus.yml`** targets `api:8000` with `metrics_path: /prometheus-metrics`; if the stub file is empty, write:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: llm-obs-api
    metrics_path: /prometheus-metrics
    static_configs:
      - targets: ["api:8000"]
```

- [ ] **Step 7: Verify pass** — `pytest tests/integration/test_observability.py -v` → PASS.

- [ ] **Step 8: Commit**

```bash
git add api/observability.py api/main.py api/services/log_service.py eval/engine.py monitor/drift_detector.py infra/prometheus/prometheus.yml tests/integration/test_observability.py
git commit -m "Week 7a: Prometheus — /prometheus-metrics endpoint, domain counters"
```

### Task 22: OTEL tracing + Grafana dashboard

**Files:**
- Create: `api/tracing.py`
- Modify: `api/main.py` (call setup), `infra/grafana/dashboards/llm_observability.json` (0-byte stub), verify `infra/grafana/datasources/prometheus.yml`

- [ ] **Step 1: `api/tracing.py`**

```python
"""
OpenTelemetry setup — no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set.

Free default: without an endpoint no exporter is registered, zero overhead,
no collector container required. Set the env var to any OTLP gRPC endpoint
(Jaeger, Tempo, honeycomb...) and traces flow with no code change.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from api.config import get_settings

logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        logger.info("OTEL endpoint not set — tracing disabled (free default)")
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from api.dependencies import engine

    provider = TracerProvider(resource=Resource.create({"service.name": settings.app_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    logger.info("OTEL tracing → %s", settings.otel_exporter_otlp_endpoint)
```

In `create_app()` after instrumentator: `from api.tracing import setup_tracing` + `setup_tracing(app)`.

- [ ] **Step 2: `infra/grafana/dashboards/llm_observability.json`** — provisioned dashboard, panels over the Prometheus datasource:

```json
{
  "title": "LLM Observability — API",
  "uid": "llm-obs-api",
  "timezone": "browser",
  "refresh": "30s",
  "time": { "from": "now-6h", "to": "now" },
  "panels": [
    {
      "id": 1, "type": "timeseries", "title": "Request rate (req/s)",
      "gridPos": { "x": 0, "y": 0, "w": 12, "h": 8 },
      "targets": [{ "expr": "sum(rate(http_requests_total{handler!~\"/prometheus-metrics|/health\"}[5m]))" }]
    },
    {
      "id": 2, "type": "timeseries", "title": "API p95 latency (s)",
      "gridPos": { "x": 12, "y": 0, "w": 12, "h": 8 },
      "targets": [{ "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))" }]
    },
    {
      "id": 3, "type": "timeseries", "title": "Logs ingested /min by status",
      "gridPos": { "x": 0, "y": 8, "w": 12, "h": 8 },
      "targets": [{ "expr": "sum(rate(llm_logs_ingested_total[5m])) by (status) * 60" }]
    },
    {
      "id": 4, "type": "timeseries", "title": "Logged LLM spend rate (USD/h)",
      "gridPos": { "x": 12, "y": 8, "w": 12, "h": 8 },
      "targets": [{ "expr": "sum(rate(llm_cost_usd_total[1h])) by (model) * 3600" }]
    },
    {
      "id": 5, "type": "stat", "title": "Eval gate results (24h)",
      "gridPos": { "x": 0, "y": 16, "w": 12, "h": 6 },
      "targets": [{ "expr": "sum(increase(eval_runs_total[24h])) by (gate_result)" }]
    },
    {
      "id": 6, "type": "stat", "title": "Drift alerts (24h) by severity",
      "gridPos": { "x": 12, "y": 16, "w": 12, "h": 6 },
      "targets": [{ "expr": "sum(increase(drift_alerts_total[24h])) by (severity)" }]
    }
  ],
  "schemaVersion": 39
}
```

If `infra/grafana/datasources/prometheus.yml` is empty, write:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

Also ensure a dashboard provider file exists (`infra/grafana/dashboards/provider.yml`):

```yaml
apiVersion: 1
providers:
  - name: llm-obs
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

(Check docker-compose.yml mounts these paths into the grafana container — Week 1 already declared the service; align volume paths with whatever it mounts.)

- [ ] **Step 3: Verify** — `docker compose up -d prometheus grafana api` → Grafana :3000 shows the dashboard with live request-rate data after hitting the API a few times; `pytest tests/ -v` still green (tracing no-op in tests).

- [ ] **Step 4: Commit — Week 7 boundary**

```bash
git add api/tracing.py api/main.py infra/grafana/ infra/prometheus/
git commit -m "Week 7: OTEL tracing (opt-in endpoint) + Grafana dashboard provisioning"
```

---

## Phase 6 — Seed, CI, Ship (Week 8)

### Task 23: Seed script

**Files:**
- Create: `scripts/__init__.py`, `scripts/seed.py`

- [ ] **Step 1: `scripts/seed.py`** — full implementation:

```python
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
  One open high drift alert (via the real detector)

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
from datetime import datetime, timedelta

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
    now = datetime.utcnow()
    texts: list[str] = []
    slots: list[tuple[str, datetime]] = []

    for day in range(7, 0, -1):
        for app in APPS:
            n = rng.randint(120, 170)
            for _ in range(n):
                ts = now - timedelta(days=day) + timedelta(seconds=rng.randint(0, 86_399))
                drifting = app == "chatbot-prod" and day <= 2
                pool = DRIFT_PROMPTS if (drifting and rng.random() < 0.8) else BASE_PROMPTS
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

        now = datetime.utcnow()
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
    now = datetime.utcnow()
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
```

Create empty `scripts/__init__.py`.

- [ ] **Step 2: Verify end-to-end**

Run: `docker compose up -d postgres redis && alembic upgrade head && python -m scripts.seed --reset`
Expected: "Seed complete"; then with API + frontend running, all four dashboard pages show live data and Drift shows one open high alert for chatbot-prod.

- [ ] **Step 3: Commit**

```bash
git add scripts/
git commit -m "Week 8a: demo seed — 3k logs w/ real embeddings, drift event, eval history"
```

### Task 24: CI workflows

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/workflows/eval-gate.yml` (0-byte stubs)

- [ ] **Step 1: `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg15
        env:
          POSTGRES_USER: llm_obs
          POSTGRES_PASSWORD: llm_obs_password
          POSTGRES_DB: llm_obs
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U llm_obs" --health-interval 5s
          --health-timeout 5s --health-retries 10
      redis:
        image: redis:7
        ports: ["6379:6379"]
    env:
      DATABASE_URL: postgresql+asyncpg://llm_obs:llm_obs_password@localhost:5432/llm_obs
      TEST_DATABASE_URL: postgresql+asyncpg://llm_obs:llm_obs_password@localhost:5432/llm_obs_test
      REDIS_URL: redis://localhost:6379
      JUDGE_PROVIDER: mock
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Cache fastembed model
        uses: actions/cache@v4
        with:
          path: ~/.cache/fastembed
          key: fastembed-bge-small-en-v1.5
      - run: pip install -e ".[dev]" ruff
      - run: ruff check .
      - run: pytest tests/unit -v
      - run: pytest tests/integration -v

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run: { working-directory: frontend }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run build
```

- [ ] **Step 2: `.github/workflows/eval-gate.yml`**

```yaml
name: Eval Gate

on:
  pull_request:

jobs:
  eval-gate:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg15
        env:
          POSTGRES_USER: llm_obs
          POSTGRES_PASSWORD: llm_obs_password
          POSTGRES_DB: llm_obs
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U llm_obs" --health-interval 5s
          --health-timeout 5s --health-retries 10
    env:
      DATABASE_URL: postgresql+asyncpg://llm_obs:llm_obs_password@localhost:5432/llm_obs
      JUDGE_PROVIDER: mock        # $0 — deterministic judge in CI
      EVAL_GATE_THRESHOLD: "0.8"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Cache fastembed model
        uses: actions/cache@v4
        with:
          path: ~/.cache/fastembed
          key: fastembed-bge-small-en-v1.5
      - run: pip install -e .
      - run: alembic upgrade head
      - name: Seed eval suite
        run: |
          python - <<'EOF'
          import asyncio
          from api.dependencies import async_session_maker, engine
          from api.models.test_case import TestCase

          PROMPTS = [
              "How do I reset my password?",
              "What is the refund policy?",
              "How do I export my data?",
              "Where do I find my API keys?",
              "How do I add a team member?",
          ]

          async def main() -> None:
              async with async_session_maker() as s:
                  s.add_all([
                      TestCase(
                          suite_name="core",
                          input_prompt=p,
                          expected_output=f"Expected answer for: {p}",
                          eval_methods=["exact_match", "embedding_similarity"],
                          similarity_threshold=0.8,
                      ) for p in PROMPTS
                  ])
                  await s.commit()
              await engine.dispose()

          asyncio.run(main())
          EOF
      - name: Run eval gate
        run: python -m eval.runner --suite core --commit-sha "$GITHUB_SHA" --triggered-by github_actions
```

- [ ] **Step 2b: Local YAML sanity** — `python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('yaml ok')"` → `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/
git commit -m "Week 8b: CI — lint+tests+build pipeline, eval gate blocks PRs under threshold"
```

### Task 25: README + finish

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write README** with these sections (real content, no placeholders):

1. **Title + one-liner** — "Self-hostable LLM evaluation & observability platform. $0 to run."
2. **Badges** — CI + Eval Gate workflow badges (`https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg` — fill owner/repo from `git remote get-url origin`; if no remote, omit badges).
3. **Screenshots** — capture Overview, Logs, Evals, Drift from the seeded dashboard (`docs/img/*.png`, referenced in README).
4. **Architecture** — mermaid diagram:

```mermaid
graph LR
  SDK[Your app] -->|POST /logs| API[FastAPI]
  API --> PG[(Postgres + pgvector)]
  API -->|enqueue| RQ[(Redis / RQ)]
  RQ --> EMB[embed worker\nfastembed 384d]
  EMB --> PG
  MW[metrics worker] --> PG
  DW[drift worker] --> PG
  DW -->|HMAC webhook| HOOK[Your endpoint]
  CI[GitHub Actions\neval gate] -->|python -m eval.runner| PG
  DASH[React dashboard] -->|/api| API
  PROM[Prometheus] -->|/prometheus-metrics| API
  GRAF[Grafana] --> PROM
```

5. **Quickstart**:

```bash
git clone <repo> && cd llm-observability
cp .env.example .env
docker compose up -d
alembic upgrade head
python -m scripts.seed          # demo data, ~2 min (local embeddings)
uvicorn api.main:app --reload   # API :8000
cd frontend && npm install && npm run dev   # dashboard :5173
```

6. **Features** — the four core features, one paragraph each, mirroring CLAUDE.md.
7. **Zero-cost design** — table: what's free and why; how to opt into the real Claude judge.
8. **Eval gate** — how eval-gate.yml blocks PRs; how to plug a real `generate_fn` target.
9. **Design system** — one paragraph: linen terminal, Jersey 25 + IBM Plex, WCAG AA.
10. **Stack** — table from CLAUDE.md.

- [ ] **Step 2: Full-suite final verification**

```bash
pytest tests/ -v && cd frontend && npm run build && cd ..
docker compose up -d && alembic upgrade head && python -m scripts.seed --reset
```

Expected: all green; dashboard fully alive at :5173.

- [ ] **Step 3: Commit — Week 8 boundary / project complete**

```bash
git add README.md docs/img/
git commit -m "Week 8: README — architecture, quickstart, zero-cost design, screenshots"
```

---

## Self-Review Notes (already applied)

- Spec coverage: every spec section maps to a task (evals→4-10, metrics→11-12, drift→13-15, dashboard→16-20, observability→21-22, ship→23-25, config/deps→1, migration→2, tests→3+each).
- Prometheus `/metrics` collision with rollup API resolved: scrape endpoint is `/prometheus-metrics` (noted in Tasks 12 + 21).
- Type consistency: `PaginatedResponse` fields (`total/page/page_size/items`) match frontend `Paginated<T>`; `EvalRunDetail {run, results}` matches `useEvalRunDetail` consumer; severity/status literals identical across schema + TS types.
- Zero-cost invariant: only Task 6 touches the Anthropic SDK, and only behind `JUDGE_PROVIDER=anthropic` + key; CI pins `JUDGE_PROVIDER: mock`.

