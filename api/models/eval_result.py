"""
EvalResult — one row per test case per eval run.

Stores all three scorer outputs for every test case so you can:
  - See exactly which cases failed and why
  - Compare scorer agreement (LLM judge vs embedding similarity)
  - Debug regressions by diffing two eval runs
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EvalResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "eval_results"

    # FK to the run this result belongs to
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # FK to the specific test case that was evaluated
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Scorer outputs — NULL if that scorer wasn't in test_case.eval_methods
    exact_match_score: Mapped[float | None] = mapped_column(Numeric(4, 3))   # 0.0 or 1.0
    embedding_score: Mapped[float | None] = mapped_column(Numeric(4, 3))     # 0.0–1.0
    llm_judge_score: Mapped[float | None] = mapped_column(Numeric(4, 3))     # 0.0–1.0

    # LLM judge's one-sentence explanation of its score
    llm_judge_reasoning: Mapped[str | None] = mapped_column(Text)

    # Final verdict: True if the case passed all required scorers
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Relationships (lazy load, no back_populates needed — read-only navigation)
    eval_run: Mapped["EvalRun"] = relationship(lazy="select", foreign_keys=[eval_run_id])
    test_case: Mapped["TestCase"] = relationship(lazy="select", foreign_keys=[test_case_id])

    def __repr__(self) -> str:
        return (
            f"<EvalResult id={self.id} run={self.eval_run_id} "
            f"case={self.test_case_id} passed={self.passed}>"
        )
