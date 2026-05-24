"""
Import all models here so Alembic's autogenerate can discover them.

When env.py does `import api.models`, Python executes this file,
which imports every model class. Each import registers the model's
table with Base.metadata. Alembic then compares Base.metadata vs
the actual DB schema to generate migration diffs.

If you add a new model file, add it here — or autogenerate will
produce empty migration files (confusing but not an error).
"""

from api.models.drift_alert import DriftAlert
from api.models.eval_result import EvalResult
from api.models.eval_run import EvalRun
from api.models.llm_log import LLMLog
from api.models.metric import Metric
from api.models.test_case import TestCase

__all__ = [
    "LLMLog",
    "TestCase",
    "EvalRun",
    "EvalResult",
    "DriftAlert",
    "Metric",
]
