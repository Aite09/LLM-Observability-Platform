# LLM Observability Platform — Claude Instructions

## What This Project Is

Production-grade LLM Evaluation & Observability Platform. Self-hostable. 4 core features:
1. **CI/CD Eval Gate** — blocks deploys when LLM pass rate < threshold
2. **Production LLM Logger** — logs every LLM call (prompt, response, tokens, cost, latency, OTEL IDs)
3. **Input Drift Detection** — pgvector cosine similarity, fires webhook on drift
4. **React Dashboard** — cost, latency p50/p95/p99, error rates, eval pass rates, drift alerts

Portfolio project targeting AI/MLOps engineering roles. Every decision = production-grade.

---

## Tech Stack (Do Not Deviate)

| Layer | Tech |
|-------|------|
| Backend | Python 3.11, FastAPI, fully async |
| DB driver | asyncpg, SQLAlchemy 2.0 async |
| Databases | PostgreSQL 15 + pgvector, Redis 7 |
| Evals | LLM-as-judge (GPT-4o or Claude), embedding cosine similarity, exact match |
| Observability | OpenTelemetry, Prometheus, Grafana |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Recharts, TanStack Query |
| Config | Pydantic v2 + pydantic-settings |
| Migrations | Alembic only |
| Infra | Docker Compose (local), Railway or Fly.io (prod) |
| CI/CD | GitHub Actions |

---

## Project Structure

```
llm-observability/
├── api/                    # FastAPI backend
│   ├── main.py             # App factory, router registration, lifespan
│   ├── config.py           # Pydantic settings — single source of truth
│   ├── dependencies.py     # FastAPI Depends() — DB sessions, settings
│   ├── models/             # SQLAlchemy ORM models (DB layer only)
│   ├── schemas/            # Pydantic schemas (API contract only)
│   ├── routers/            # Route handlers — NO business logic here
│   ├── services/           # Business logic called by routers
│   └── migrations/         # Alembic env + versions
├── eval/                   # Eval engine — zero FastAPI imports
│   ├── engine.py           # Orchestrates a full eval run
│   ├── runner.py           # CLI entry point for CI/CD gate
│   └── scorers/            # exact_match, embedding_similarity, llm_judge
├── monitor/                # Drift detection + metrics — zero FastAPI imports
│   ├── drift_detector.py   # pgvector cosine similarity drift detection
│   ├── metrics_aggregator.py  # hourly/daily rollup aggregation
│   └── webhooks.py         # webhook dispatch on drift/alerts
├── workers/                # Redis background job workers
├── frontend/               # React 18 dashboard
├── infra/                  # Docker, Prometheus, Grafana configs
├── tests/
│   ├── unit/               # Pure logic — no DB, no HTTP
│   └── integration/        # Real DB + HTTP via TestClient
└── .github/workflows/      # ci.yml, eval-gate.yml
```

---

## Database Schema (6 Tables)

All: UUID PKs, TIMESTAMPTZ timestamps.

### `llm_logs`
```
id, application_id, model, provider, prompt, response,
prompt_tokens, completion_tokens, total_tokens,
cost_usd NUMERIC(10,6), latency_ms INT, time_to_first_token_ms INT,
status TEXT CHECK IN ('success','error','timeout'),
otel_trace_id TEXT, otel_span_id TEXT,
tags JSONB, prompt_embedding vector(1536),
created_at TIMESTAMPTZ
```

### `test_cases`
```
id, suite_name, input_prompt, expected_output,
eval_methods TEXT[], similarity_threshold NUMERIC(4,3),
created_at, updated_at
```

### `eval_runs`
```
id, suite_name, commit_sha, triggered_by,
total_cases INT, passed_cases INT, pass_rate NUMERIC(5,4),
gate_threshold NUMERIC(5,4), gate_result TEXT CHECK IN ('pass','fail'),
started_at, completed_at, created_at
```

### `eval_results`
```
id, eval_run_id → eval_runs, test_case_id → test_cases,
exact_match_score NUMERIC(4,3), embedding_score NUMERIC(4,3),
llm_judge_score NUMERIC(4,3), llm_judge_reasoning TEXT,
passed BOOL, created_at
```

### `drift_alerts`
```
id, application_id, drift_type, severity CHECK IN ('low','medium','high','critical'),
drift_score NUMERIC(6,4), baseline_stats JSONB, current_stats JSONB,
status TEXT CHECK IN ('open','acknowledged','resolved'),
detected_at, resolved_at, created_at
```

### `metrics`
```
id, application_id, model,
period_type TEXT CHECK IN ('hourly','daily'),
period_start TIMESTAMPTZ,
total_requests INT, successful_requests INT, failed_requests INT,
total_tokens BIGINT, total_cost_usd NUMERIC(12,6),
avg_latency_ms NUMERIC(8,2), p50_latency_ms INT, p95_latency_ms INT, p99_latency_ms INT,
created_at, updated_at
UNIQUE(application_id, model, period_type, period_start)
```

---

## Hard Rules — Always Follow

### 1. All DB ops are async
```python
# CORRECT
async def get_log(session: AsyncSession, log_id: UUID) -> LLMLog | None:
    result = await session.execute(select(LLMLog).where(LLMLog.id == log_id))
    return result.scalar_one_or_none()

# WRONG — never do this
session.execute(...)  # sync call
```

### 2. Models ≠ Schemas — never merge them
- `api/models/` = SQLAlchemy ORM classes (map to DB tables)
- `api/schemas/` = Pydantic classes (API request/response contracts)
- No model inherits from BaseModel. No schema has Column().

### 3. eval/ and monitor/ are standalone
```python
# WRONG — in eval/ or monitor/
from fastapi import HTTPException  # forbidden

# CORRECT — raise plain Python exceptions
raise ValueError("Suite not found")
```

### 4. Config via get_settings() only
```python
# CORRECT
from api.config import get_settings
settings = get_settings()

# WRONG
DATABASE_URL = "postgresql://..."  # never hardcode
```

### 5. Type hints on every function
```python
# CORRECT
async def create_log(session: AsyncSession, data: LLMLogCreate) -> LLMLog:

# WRONG
async def create_log(session, data):
```

### 6. Alembic for all schema changes
```bash
# add a column? run this, never touch Base.metadata.create_all()
alembic revision --autogenerate -m "add column X to table Y"
alembic upgrade head
```

### 7. No print() — use logging
```python
import logging
logger = logging.getLogger(__name__)
logger.info("Log ingested: %s", log_id)
```

### 8. Routes call services — no logic in handlers
```python
# CORRECT router
@router.post("/logs", response_model=LLMLogResponse)
async def ingest_log(
    payload: LLMLogCreate,
    session: AsyncSession = Depends(get_db),
) -> LLMLogResponse:
    return await log_service.create_log(session, payload)

# WRONG — business logic in router
@router.post("/logs")
async def ingest_log(payload: LLMLogCreate, session=Depends(get_db)):
    log = LLMLog(**payload.model_dump())  # logic belongs in service
    session.add(log)
    await session.commit()
```

### 9. Read files before editing
Never assume file contents. Always Read first.

### 10. Ask before adding dependencies
State: what package, why needed, no existing alternative.

---

## Development Workflow

### Local Setup
```bash
docker compose up -d          # starts postgres, pgvector, redis
alembic upgrade head          # apply migrations
uvicorn api.main:app --reload # run API
```

### Running Tests
```bash
pytest tests/unit/            # fast, no DB
pytest tests/integration/     # needs running postgres+redis
```

### Adding a Migration
```bash
# after editing api/models/
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

### Env Vars (see .env.example)
All config from environment. Never hardcode. Key vars:
- `DATABASE_URL` — asyncpg format: `postgresql+asyncpg://user:pass@host:5432/db`
- `REDIS_URL` — `redis://localhost:6379`
- `OPENAI_API_KEY` — for embedding + LLM judge
- `EVAL_GATE_THRESHOLD` — default `0.8`
- `DRIFT_WEBHOOK_URL` — fires on drift detection

---

## 8-Week Roadmap

| Week | Deliverable |
|------|-------------|
| 1 | docker-compose, DB schema, FastAPI skeleton, health checks, Alembic, SQLAlchemy models |
| 2 | POST /logs ingestion, GET /logs filtering, Pydantic schemas, Redis queue |
| 3 | Eval runner, scorers (exact_match, embedding_similarity, llm_judge), eval API |
| 4 | Metrics aggregation worker, GET /metrics endpoint |
| 5 | Drift detector (pgvector cosine similarity), alerting webhooks |
| 6 | React dashboard — logs, evals, drift pages, Recharts charts |
| 7 | Prometheus /metrics, Grafana dashboards, OpenTelemetry tracing |
| 8 | eval-gate.yml GitHub Action, README, demo |

---

## Key Patterns Reference

### Async DB session (dependencies.py)
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
```

### Upsert pattern (metrics)
```python
await session.execute(
    insert(Metric)
    .values(**data)
    .on_conflict_do_update(
        index_elements=["application_id", "model", "period_type", "period_start"],
        set_={...},
    )
)
```

### pgvector cosine similarity
```python
from pgvector.sqlalchemy import Vector
# in query:
.order_by(LLMLog.prompt_embedding.cosine_distance(query_embedding))
```

### Redis job enqueue (workers)
```python
from rq import Queue
import redis

q = Queue(connection=redis.from_url(settings.redis_url))
q.enqueue(some_worker_fn, arg1, arg2)
```
