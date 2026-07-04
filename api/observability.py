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
