"""Embedding backend — lazy singleton around fastembed.

Unit tests use the real model (small, local, free). First call downloads
~66MB to ~/.cache — CI caches this. Offline first run fails at download.
"""

import numpy as np
import pytest

from eval.scorers.embedding_backend import embed_texts, cosine_similarity


def test_embed_returns_384_dim_unit_vectors() -> None:
    vecs = embed_texts(["hello world", "goodbye world"])
    assert vecs.shape == (2, 384)
    # bge models emit L2-normalized vectors → norms ≈ 1
    np.testing.assert_allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-3)


def test_cosine_similarity_bounds() -> None:
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    c = np.array([-1.0, 0.0, 0.0])
    assert cosine_similarity(a, b) == pytest.approx(1.0)
    assert cosine_similarity(a, c) == pytest.approx(-1.0)


def test_similar_texts_score_higher_than_different() -> None:
    vecs = embed_texts([
        "The cat sat on the mat",
        "A cat is sitting on a mat",
        "Quarterly revenue grew 40 percent",
    ])
    sim_close = cosine_similarity(vecs[0], vecs[1])
    sim_far = cosine_similarity(vecs[0], vecs[2])
    assert sim_close > sim_far
    assert sim_close > 0.8
