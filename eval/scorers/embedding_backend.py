"""
Shared local embedding backend — fastembed (ONNX, no torch, no API, $0).

One lazy singleton per process. Used by:
  - eval/scorers/embedding_similarity.py (scoring)
  - monitor/drift_detector.py (via stored embeddings)
  - workers/log_worker.py (embedding generation on ingest)

Why lazy? Model load reads ~66MB from disk (first run: downloads).
Workers that never embed (metrics_worker) shouldn't pay that cost.
No FastAPI imports — this module is part of the standalone eval package.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
from fastembed import TextEmbedding

from api.config import get_settings

logger = logging.getLogger(__name__)

_model: TextEmbedding | None = None
_lock = threading.Lock()


def _get_model() -> TextEmbedding:
    """Lazy, thread-safe singleton. Double-checked locking: fast path no lock."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                settings = get_settings()
                logger.info("Loading embedding model %s", settings.embedding_model)
                _model = TextEmbedding(model_name=settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts → (len(texts), 384) float32 array.

    fastembed returns a generator of arrays; stack once for vector math.
    """
    model = _get_model()
    return np.stack(list(model.embed(texts)))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two 1-D vectors, safe against zero vectors."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)
