"""
LLMLog — one row per LLM API call.

Key design decisions:
  - prompt_embedding vector(1536): stores the OpenAI text-embedding-3-small
    embedding of the prompt. Used by the drift detector (pgvector cosine
    similarity) to compare production query distribution vs baseline.
  - tags JSONB: arbitrary caller-supplied metadata. JSONB not JSON because
    JSONB is stored binary, indexed, supports containment queries (@>).
  - Composite index on (application_id, created_at): covers the most common
    query pattern "logs for app X in time range Y-Z".
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LLMLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "llm_logs"

    # Which application/service made this call
    application_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # LLM identifiers
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # The actual call content
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text)

    # Token economics
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))

    # Latency
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer)

    # Outcome: success | error | timeout
    # CHECK constraint added in Alembic migration for DB-level enforcement
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # OpenTelemetry — link this row to a distributed trace
    otel_trace_id: Mapped[str | None] = mapped_column(String(32))
    otel_span_id: Mapped[str | None] = mapped_column(String(16))

    # Arbitrary caller metadata
    tags: Mapped[dict | None] = mapped_column(JSONB)

    # 1536-dim embedding of the prompt (text-embedding-3-small).
    # NULL until the background worker generates and stores it.
    prompt_embedding: Mapped[list | None] = mapped_column(Vector(1536))

    __table_args__ = (
        # Covers: WHERE application_id = ? AND created_at BETWEEN ? AND ?
        Index("ix_llm_logs_app_created", "application_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMLog id={self.id} app={self.application_id} "
            f"model={self.model} status={self.status}>"
        )
