"""
TestCase — one row per test case in a golden dataset ("suite").

A suite is a named collection of test cases used for eval runs.
Example suite: "production-suite" with 50 prompt/expected-output pairs.

eval_methods TEXT[]: which scorers to apply. Values: "exact_match",
  "embedding_similarity", "llm_judge". A single test case can use
  multiple scorers — the eval engine runs all listed methods.

similarity_threshold: minimum cosine similarity score to consider
  the embedding_similarity scorer a "pass" for this test case.
  Stored per test case so different cases can have different thresholds.
"""

from datetime import datetime

from sqlalchemy import ARRAY, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TestCase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "test_cases"

    # Not a pytest test class — the name collides with pytest's collection heuristic.
    __test__ = False

    # Groups test cases into named suites (e.g. "production-v1", "summarization")
    suite_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # The prompt sent to the LLM during eval
    input_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # The reference output we compare against
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)

    # Which scorers to run: ["exact_match"], ["embedding_similarity", "llm_judge"], etc.
    eval_methods: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)

    # Cosine similarity threshold for embedding_similarity scorer (0.0–1.0)
    # Default 0.85: outputs must be ≥85% semantically similar to pass
    similarity_threshold: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        server_default="0.850",
    )

    # Track when test cases are updated (dataset versioning)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TestCase id={self.id} suite={self.suite_name}>"
