"""
Shared local embedding backend — fastembed (ONNX, no torch, no API, $0).

One lazy singleton per process. Used by:
  - eval/scorers/embedding_similarity.py (scoring)
  - monitor/drift_detector.py (via stored embeddings)
  - workers/log_worker.py (embedding generation on ingest)

Why lazy? Model load reads ~66MB from disk (first run: downloads).
Workers that never embed (metrics_worker) shouldn't pay that cost.

Config: reads EMBEDDING_MODEL from the environment directly — no api.config
import, so eval/ stays standalone and embedding never requires DATABASE_URL.
"""

from __future__ import annotations

import logging
import os
import threading

import numpy as np
from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

_model: TextEmbedding | None = None
_lock = threading.Lock()


def _get_model() -> TextEmbedding:
    """Lazy, thread-safe singleton. Double-checked locking: fast path no lock."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                model_name = os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
                logger.info("Loading embedding model %s", model_name)
                _model = TextEmbedding(model_name=model_name)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts → (len(texts), 384) float32 array.

    fastembed returns a generator of arrays; stack once for vector math.
    """
    if not texts:
        raise ValueError("texts must be non-empty")
    model = _get_model()
    return np.stack(list(model.embed(texts)))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two 1-D vectors, safe against zero vectors."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)
