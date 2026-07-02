# Weeks 3–8: Platform Completion — Design

**Date:** 2026-07-02
**Status:** Approved pending user review
**Scope:** Everything after Week 2 — eval engine, metrics aggregation, drift detection, dashboard, observability, CI gate, seed, README.

## Constraints (non-negotiable)

1. **$0 total cost.** No paid API calls anywhere in the default path: demo, tests, CI, seed. LLM-judge scorer ships as working code but defaults to mock mode; real Anthropic calls only if the user sets `ANTHROPIC_API_KEY` later. Embeddings are local (fastembed). Hosting is local docker compose only. Fonts self-hosted.
2. All CLAUDE.md hard rules apply (async DB, models≠schemas, standalone eval/monitor, get_settings, type hints, Alembic, logging, thin routers).
3. Build order (user chose): backend batch (wk 3–5) → dashboard (wk 6) → observability (wk 7) → CI + ship (wk 8). TDD throughout; tests green + commit at each week boundary.

## Decisions Log

| Decision | Choice |
|---|---|
| LLM judge | Claude via `anthropic` SDK; `JUDGE_PROVIDER=mock` default (deterministic heuristic), `anthropic` when key set |
| Embeddings | fastembed `BAAI/bge-small-en-v1.5`, 384-dim, ONNX, local, free |
| Schema change | `llm_logs.prompt_embedding vector(1536) → vector(384)` via Alembic |
| Demo data | Rich seed script: ~3k logs / 7 days / 3 apps / 4 models, injected drift, eval runs |
| Deploy | Local-only + README (no paid hosting) |
| Design | "Linen terminal": warm linen bg, coffee ink, terracotta accent, Jersey 25 display + IBM Plex Sans/Mono, editorial ledger layout |
| 3D | None. Subtle state-driven motion only |

## 1. Eval Engine (wk 3)

### Scorers — `eval/scorers/` (pure, no FastAPI, no DB)

- `exact_match.py` — `score(expected: str, actual: str) -> float`: normalize (strip, lower, collapse whitespace) → 1.0/0.0.
- `embedding_similarity.py` — `EmbeddingScorer` class holding a lazy singleton fastembed model; `score(expected, actual) -> float` = cosine similarity of embeddings, clamped 0–1. Same model reused by drift detection and log-embedding worker.
- `llm_judge.py` — `JudgeScorer` with provider strategy:
  - `mock` (default): deterministic heuristic (token-overlap Jaccard mapped to 0–1 + fixed reasoning string). Free, repeatable tests.
  - `anthropic`: `claude-haiku-4-5` (config: `JUDGE_MODEL`), rubric prompt → strict JSON `{score, reasoning}`, retry ×3 exponential backoff, 30s timeout. Never selected unless `ANTHROPIC_API_KEY` set AND `JUDGE_PROVIDER=anthropic`.

### Engine — `eval/engine.py`

`run_eval(session, suite_name, commit_sha, triggered_by, gate_threshold) -> EvalRunResult`:
1. Load test_cases for suite (raise `ValueError` if none).
2. Per case: run each method in `case.eval_methods`; case passes iff ALL its methods pass their thresholds (exact = 1.0; embedding ≥ `case.similarity_threshold`; judge ≥ 0.7).
3. Candidate outputs: the eval target is a pluggable async `generate_fn(prompt) -> str`; default `EchoTarget` (returns expected output for demo/CI determinism — documented clearly as demo target) with interface ready for real app integration.
4. Single transaction: insert `eval_runs` + all `eval_results`; compute `pass_rate`, `gate_result = pass_rate >= gate_threshold`.

### Runner — `eval/runner.py` (CI entry)

`python -m eval.runner --suite core --commit-sha $SHA [--threshold 0.8] [--triggered-by ci]` → prints summary table (case, methods, scores, pass/fail) → exit 0/1 by gate result. Own asyncpg engine from `DATABASE_URL` (no FastAPI app).

### API

- `POST /test-cases`, `GET /test-cases?suite_name=` — CRUD (create + list; update/delete YAGNI).
- `POST /evals/run {suite_name}` — enqueue RQ job → `workers/eval_worker.py` runs engine. Returns `{job_id, status: "queued"}`.
- `GET /evals/runs?suite_name=&limit=` — list runs.
- `GET /evals/runs/{id}` — run + nested per-case results.
- Routers thin → `eval_service.py`.

## 2. Metrics Aggregation (wk 4)

### Aggregator — `monitor/metrics_aggregator.py`

`aggregate(session, period_type, window_start, window_end)`: single GROUP BY query over `llm_logs` (`application_id, model, date_trunc(period)`) computing counts, success/fail, tokens, cost, avg + `percentile_cont` p50/p95/p99 latency → upsert into `metrics` (`on_conflict_do_update` on the unique index). Idempotent; re-aggregates only the current + previous period each tick (no full scans).

### Worker — `workers/metrics_worker.py` (new file)

Async loop daemon: every `METRICS_INTERVAL_SECONDS` (default 300) run hourly aggregation; daily aggregation on hour boundary. Jitter ±10%, graceful SIGTERM shutdown, errors logged not fatal.

### API

- `GET /metrics?application_id=&model=&period_type=&from=&to=` → rollup rows.
- `GET /metrics/summary?window=24h|7d|30d` → dashboard KPIs: total cost, request count, error rate, p50/p95/p99 (aggregated across rollups), cost delta vs prior window.

## 3. Drift Detection (wk 5)

### Detector — `monitor/drift_detector.py`

Per application_id:
- Baseline: prompt embeddings, window −8d…−1d (min 50, else skip + log).
- Current: last 24h (min 20, else skip).
- `drift_score = cosine_distance(centroid_baseline, centroid_current)` plus spread ratio (`avg pairwise distance current / baseline`) reported in stats.
- Severity: ≥0.15 low, ≥0.25 medium, ≥0.35 high, ≥0.50 critical; below → no alert.
- Dedup: skip insert if an `open` alert exists for same app + same-or-higher severity.
- `baseline_stats` / `current_stats` JSONB: window bounds, counts, centroid norms, spread.

### Webhooks — `monitor/webhooks.py`

`dispatch_drift_alert(alert) -> bool`: async httpx POST to `DRIFT_WEBHOOK_URL` (skip silently if unset), body = alert JSON, header `X-Signature: sha256=HMAC(body, WEBHOOK_SECRET)`. Retry ×3 exponential backoff. Failures logged, never raised to detector.

### Worker — `workers/drift_worker.py`

Loop daemon, every `DRIFT_CHECK_INTERVAL_SECONDS` (default 3600), iterate distinct application_ids from recent logs.

### API

- `GET /drift/alerts?status=&severity=&limit=`
- `PATCH /drift/alerts/{id} {status}` — `acknowledged`/`resolved` (resolved sets `resolved_at`). Router → `drift_service.py`.

## 4. Dashboard (wk 6) — "Linen Terminal"

### Design tokens (CSS vars, OKLCH)

- bg `oklch(0.955 0.015 78)` linen · sidebar `oklch(0.925 0.018 76)` · hairline `oklch(0.855 0.02 75)` · rule-strong `oklch(0.815 0.022 73)`
- ink `oklch(0.36 0.06 48)` coffee · secondary `oklch(0.48 0.048 56)` · faint `oklch(0.60 0.04 62)`
- accent terracotta `oklch(0.60 0.125 42)` (attention only) · sage `oklch(0.52 0.085 135)` pass/success · rust `oklch(0.55 0.15 30)` errors
- Type: Jersey 25 (headings, hero numbers, nav brand) / IBM Plex Sans (UI, body) / IBM Plex Mono (data, timestamps, ledgers). All via @fontsource — self-hosted, no CDN.
- WCAG AA: body text pairs verified ≥4.5:1; `prefers-reduced-motion` honored on every animation; severity always text+color.

### Layout language

Editorial ledger: full-bleed ruled sections (1px hairlines), no floating card grids, no side-stripe accents, asymmetric splits (62/38), metrics ledger strip with deliberate hierarchy (spend dominant), drift annotations drawn on charts, activity as ruled ledger rows with exact mono timestamps. Accent appears only where attention is required.

### Pages

1. **Overview** — metrics ledger strip (spend hero, latency stack, requests, attention slot) · daily spend chart with drift annotation · latency percentiles chart · share-by-model ledger · activity ledger. Auto-refresh 30s (TanStack Query `refetchInterval`).
2. **Logs** — filter bar (app, model, status, date range) · ruled table, server-side pagination 50/page (no virtualization dependency) · row → detail drawer (prompt/response, tokens, cost, latency, OTEL trace/span ids, tags) · auto-refresh 10s.
3. **Evals** — runs ledger (suite, sha short, pass rate, gate badge sage/rust) · run detail: per-case table w/ per-method scores, judge reasoning expandable row.
4. **Drift** — alerts grouped by status; severity chip (text+color), score, windows, stats table; acknowledge/resolve actions (optimistic updates).

### Frontend architecture

Existing scaffold: Vite + React 18 + TS strict + Tailwind + Recharts + TanStack Query + `frontend/src/api/client.ts` fetch wrapper. Tokens as CSS variables consumed by Tailwind config. Recharts styled to token palette (no default colors). Empty states teach ("No drift alerts — detector runs hourly"); loading = skeleton rows; errors = inline retry. Component vocabulary consistent: one button style, one chip style, one table style.

## 5. Observability (wk 7)

- **Prometheus**: `prometheus-fastapi-instrumentator` on the app → `/metrics`. Custom metrics: `llm_logs_ingested_total`, `llm_cost_usd_total` (counter), `eval_runs_total{gate_result}`, `drift_alerts_total{severity}`. Scrape config in `infra/prometheus/prometheus.yml` (api:8000).
- **OTEL**: `opentelemetry-instrumentation-fastapi` + `-sqlalchemy`; OTLP HTTP exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` set, else no-op. No collector container ships in docker compose — tracing is wired and documented, endpoint is user-supplied.
- **Grafana**: provisioned Prometheus datasource (exists) + `llm_observability.json` dashboard: request rate, error %, p95 API latency, ingested logs/min, RQ queue depth (exposed as `rq_queue_depth` gauge from the API's Prometheus registry — no extra exporter container), cost counter rate.

## 6. CI Gate + Ship (wk 8)

- **`ci.yml`**: push/PR → ruff → pytest unit → pytest integration (services: postgres w/ pgvector image, redis) → frontend `tsc --noEmit` + `vite build`. All free (GitHub Actions public repo).
- **`eval-gate.yml`**: PR → postgres service → `alembic upgrade head` → seed eval suite (`scripts/seed_eval_cases.py`, part of seed module) → `python -m eval.runner --suite core --commit-sha $GITHUB_SHA --threshold $EVAL_GATE_THRESHOLD` → exit code gates merge. Judge = mock provider in CI (free, deterministic).
- **`scripts/seed.py`**: idempotent (`--reset`), ~3k logs over 7 days (3 apps, 4 models, lognormal latency, per-model token/cost distributions, 6% error/timeout), embeddings computed locally via fastembed, topic-shift injected on day 6 for one app (drives real drift alert), 3 eval runs with results (2 pass, 1 fail), one open high drift alert. Runtime target < 2 min on laptop.
- **README**: hero screenshot, mermaid architecture diagram, feature list, quickstart (`docker compose up -d && alembic upgrade head && python -m scripts.seed && open dashboard`), eval-gate explanation + badge, design-system note, roadmap.

## Config additions (`api/config.py` + `.env.example`)

`ANTHROPIC_API_KEY=""` (optional), `JUDGE_PROVIDER=mock`, `JUDGE_MODEL=claude-haiku-4-5`, `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `METRICS_INTERVAL_SECONDS=300`, `DRIFT_CHECK_INTERVAL_SECONDS=3600`, `DRIFT_BASELINE_DAYS=7`, `DRIFT_MIN_BASELINE=50`, `DRIFT_MIN_CURRENT=20`, `WEBHOOK_SECRET=""`, `OTEL_EXPORTER_OTLP_ENDPOINT=""`.

## New dependencies

Python: `anthropic` (SDK free; zero calls in mock mode), `fastembed`, `prometheus-fastapi-instrumentator`, `opentelemetry-distro`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`, `opentelemetry-exporter-otlp`.
Frontend: `@fontsource/jersey-25`, `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`.

## Testing strategy

- **Unit** (no DB): scorers (exact normalization table-driven; embedding cosine math w/ tiny fixture vectors — model mocked; judge mock provider determinism + anthropic provider w/ mocked client), drift math (centroid/severity/dedup logic w/ injected vectors), aggregator SQL builders, webhook signing.
- **Integration** (real postgres+redis): eval run end-to-end w/ echo target + mock judge; metrics aggregation over seeded logs incl. percentile correctness; drift detector over seeded embeddings fires alert + dedup; all new API endpoints (status codes, filters, pagination, PATCH transitions); runner exit codes.
- **Frontend**: `tsc` strict + build as CI gate (component tests YAGNI for portfolio scope).

## Error handling principles

Workers never die from job errors (log + continue). Scorer failure → per-case error captured, case fails, run completes. Webhook failure → logged, alert still persists. API: 404 unknown ids, 422 validation (FastAPI default); duplicate test cases allowed (no unique constraint — YAGNI). Judge provider `anthropic` without key → clear config error at startup, not mid-run.

## Migration plan

One Alembic revision: alter `prompt_embedding` to `vector(384)` (drop+recreate column — existing dev data has no real embeddings), recreate ivfflat index if present.
