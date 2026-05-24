"""
EvalRun — one row per CI/CD eval trigger.

When GitHub Actions runs eval-gate.yml, it creates one EvalRun.
The EvalRun tracks aggregate results: how many cases passed, the overall
pass_rate, and whether the gate passed or failed.

gate_result drives the CI exit code:
  "pass" → exit 0 → deploy proceeds
  "fail" → exit 1 → deploy blocked
"""

from datetime import datetime

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EvalRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "eval_runs"

    # Which test suite was evaluated (matches TestCase.suite_name)
    suite_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Git commit that triggered this eval — links result to exact code version
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)

    # What triggered the run: "github_actions" | "manual" | "api"
    triggered_by: Mapped[str] = mapped_column(String(100), nullable=False, server_default="api")

    # Aggregate counts
    total_cases: Mapped[int] = mapped_column(nullable=False, server_default="0")
    passed_cases: Mapped[int] = mapped_column(nullable=False, server_default="0")

    # pass_rate = passed_cases / total_cases, stored for fast dashboard queries
    pass_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))  # e.g. 0.8750

    # The threshold that was active at eval time (may change over time)
    gate_threshold: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)

    # "pass" or "fail" — determined by pass_rate >= gate_threshold
    gate_result: Mapped[str | None] = mapped_column(String(10))

    # Timing
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    def __repr__(self) -> str:
        return (
            f"<EvalRun id={self.id} suite={self.suite_name} "
            f"pass_rate={self.pass_rate} gate={self.gate_result}>"
        )
