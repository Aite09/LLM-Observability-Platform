"""Unit tests for eval scorers — pure logic, no DB, no network."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from eval.scorers.exact_match import score as exact_score
from eval.scorers.embedding_similarity import score as embedding_score
from eval.scorers.llm_judge import JudgeResult, judge


class TestExactMatch:
    @pytest.mark.parametrize(
        ("expected", "actual", "want"),
        [
            ("Paris", "Paris", 1.0),
            ("Paris", "paris", 1.0),            # case-insensitive
            ("  Paris ", "Paris", 1.0),          # strip
            ("New  York", "new york", 1.0),      # whitespace collapse
            ("Paris", "London", 0.0),
            ("Paris", "", 0.0),
            ("", "", 1.0),                        # both empty = match
        ],
    )
    def test_normalized_comparison(self, expected: str, actual: str, want: float) -> None:
        assert exact_score(expected, actual) == want


class TestEmbeddingSimilarity:
    def test_identical_texts_near_one(self) -> None:
        s = embedding_score("The capital of France is Paris", "The capital of France is Paris")
        assert s == pytest.approx(1.0, abs=1e-3)

    def test_paraphrase_above_unrelated(self) -> None:
        para = embedding_score("The cat sat on the mat", "A cat is sitting on a mat")
        unrel = embedding_score("The cat sat on the mat", "Revenue grew 40% quarter over quarter")
        assert para > unrel

    def test_clamped_to_unit_interval(self) -> None:
        s = embedding_score("alpha", "omega")
        assert 0.0 <= s <= 1.0


class TestLLMJudgeMock:
    async def test_identical_scores_high(self) -> None:
        r = await judge("Paris is the capital", "Paris is the capital", provider="mock")
        assert isinstance(r, JudgeResult)
        assert r.score == pytest.approx(1.0)
        assert "mock" in r.reasoning.lower()

    async def test_disjoint_scores_low(self) -> None:
        r = await judge("Paris is the capital", "bananas grow on trees", provider="mock")
        assert r.score < 0.3

    async def test_deterministic(self) -> None:
        a = await judge("some expected", "some actual output", provider="mock")
        b = await judge("some expected", "some actual output", provider="mock")
        assert a.score == b.score


class TestLLMJudgeAnthropic:
    async def test_parses_json_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_msg = MagicMock()
        fake_msg.content = [MagicMock(text='{"score": 0.9, "reasoning": "matches key facts"}')]
        fake_client = MagicMock()
        fake_client.messages.create = AsyncMock(return_value=fake_msg)
        monkeypatch.setattr("eval.scorers.llm_judge._get_anthropic_client", lambda: fake_client)

        r = await judge("expected", "actual", provider="anthropic")
        assert r.score == pytest.approx(0.9)
        assert r.reasoning == "matches key facts"

    async def test_malformed_json_returns_zero_with_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_msg = MagicMock()
        fake_msg.content = [MagicMock(text="not json at all")]
        fake_client = MagicMock()
        fake_client.messages.create = AsyncMock(return_value=fake_msg)
        monkeypatch.setattr("eval.scorers.llm_judge._get_anthropic_client", lambda: fake_client)

        r = await judge("expected", "actual", provider="anthropic")
        assert r.score == 0.0
        assert "parse" in r.reasoning.lower()
