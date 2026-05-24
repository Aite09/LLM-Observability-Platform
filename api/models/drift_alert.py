"""
DriftAlert — one row per detected input distribution drift event.

Created by monitor/drift_detector.py when cosine distance between
recent prompt embeddings and the baseline centroid exceeds the threshold.

baseline_stats / current_stats are JSONB — flexible enough to store
whatever statistical summary the detector computes without schema changes.
"""

from datetime import datetime

from sqlalchemy import Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DriftAlert(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "drift_alerts"

    application_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # What kind of drift was detected
    # "embedding_distribution" = prompt vectors drifted from baseline centroid
    drift_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # How bad: low | medium | high | critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    # Numeric drift score (cosine distance from baseline, 0.0–1.0+)
    drift_score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)

    # Statistical summary of the baseline (centroid norm, sample count, etc.)
    baseline_stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Statistical summary of the current window
    current_stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Alert lifecycle: open → acknowledged → resolved
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")

    # When the drift was first detected
    detected_at: Mapped[datetime] = mapped_column(nullable=False)

    # Set when status transitions to "resolved"
    resolved_at: Mapped[datetime | None] = mapped_column()

    def __repr__(self) -> str:
        return (
            f"<DriftAlert id={self.id} app={self.application_id} "
            f"severity={self.severity} score={self.drift_score} status={self.status}>"
        )
