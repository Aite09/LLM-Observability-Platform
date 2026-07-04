"""Unit tests for drift math — injected vectors, no DB."""

import numpy as np

from monitor.drift_detector import compute_drift_score, severity_for


class TestDriftMath:
    def test_identical_distributions_score_zero(self) -> None:
        vecs = np.random.RandomState(7).normal(size=(50, 8))
        score = compute_drift_score(vecs, vecs)
        assert score < 0.01

    def test_shifted_distribution_scores_higher(self) -> None:
        rng = np.random.RandomState(7)
        baseline = rng.normal(loc=0.0, size=(60, 8))
        shifted = rng.normal(loc=3.0, size=(30, 8))
        assert compute_drift_score(baseline, shifted) > compute_drift_score(baseline, baseline)

    def test_severity_thresholds(self) -> None:
        assert severity_for(0.10) is None
        assert severity_for(0.15) == "low"
        assert severity_for(0.25) == "medium"
        assert severity_for(0.35) == "high"
        assert severity_for(0.50) == "critical"
