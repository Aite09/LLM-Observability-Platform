"""
Metric — pre-aggregated hourly/daily rollup per (application, model).

Why pre-aggregate?
  Dashboard queries like "show cost over last 7 days" would otherwise
  scan millions of rows in llm_logs. Aggregating to one row per hour
  per app/model means the dashboard reads at most ~168 rows (7d × 24h).

The UNIQUE constraint on (application_id, model, period_type, period_start)
makes upserts safe — re-running the aggregation worker for the same hour
updates the row rather than inserting a duplicate.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Metric(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "metrics"

    __table_args__ = (
        # Enables ON CONFLICT DO UPDATE (upsert) in the aggregation worker
        UniqueConstraint(
            "application_id", "model", "period_type", "period_start",
            name="uq_metrics_app_model_period",
        ),
    )

    application_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # "hourly" or "daily"
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # Start of the aggregation window (truncated to hour or day)
    # e.g. 2024-01-15 14:00:00+00 for hourly, 2024-01-15 00:00:00+00 for daily
    period_start: Mapped[datetime] = mapped_column(nullable=False)

    # Request counts
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    successful_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Token + cost totals
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    total_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")

    # Latency percentiles (ms) — NULL if no requests with latency data in window
    avg_latency_ms: Mapped[float | None] = mapped_column(Numeric(8, 2))
    p50_latency_ms: Mapped[int | None] = mapped_column(Integer)
    p95_latency_ms: Mapped[int | None] = mapped_column(Integer)
    p99_latency_ms: Mapped[int | None] = mapped_column(Integer)

    # updated_at: set by the DB on every UPDATE (safe re-runs show last aggregation time)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Metric app={self.application_id} model={self.model} "
            f"period={self.period_type} start={self.period_start}>"
        )
