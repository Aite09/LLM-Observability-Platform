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
