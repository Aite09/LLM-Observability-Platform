"""
Embedding-similarity scorer — cosine similarity of local embeddings.

Uses the shared fastembed backend (384-dim bge-small). Raw cosine for
bge-normalized vectors lands in [-1, 1]; we clamp to [0, 1] because
scores below 0 carry no ranking meaning for eval pass/fail.
"""

from __future__ import annotations

from eval.scorers.embedding_backend import cosine_similarity, embed_texts


def score(expected: str, actual: str) -> float:
    """Cosine similarity of expected vs actual, clamped to [0, 1]."""
    vecs = embed_texts([expected, actual])
    raw = cosine_similarity(vecs[0], vecs[1])
    return max(0.0, min(1.0, raw))
