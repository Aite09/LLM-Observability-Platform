"""Unit tests for webhook dispatch — httpx mocked, no network."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from monitor.webhooks import dispatch_drift_alert, sign_payload


class TestSigning:
    def test_hmac_sha256_hex(self) -> None:
        body = b'{"a":1}'
        sig = sign_payload(body, "secret")
        expected = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        assert sig == expected


class TestDispatch:
    @pytest.fixture
    def alert_payload(self) -> dict:
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "application_id": "app-1",
            "severity": "high",
            "drift_score": 0.41,
        }

    async def test_posts_with_signature(self, alert_payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DRIFT_WEBHOOK_URL", "https://example.test/hook")
        monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")
        from api.config import get_settings
        get_settings.cache_clear()

        sent = {}

        async def fake_post(self, url, content=None, headers=None):  # noqa: ANN001
            sent["url"], sent["content"], sent["headers"] = url, content, headers
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with patch("httpx.AsyncClient.post", new=fake_post):
            ok = await dispatch_drift_alert(alert_payload)

        assert ok is True
        assert sent["url"] == "https://example.test/hook"
        body = sent["content"]
        assert json.loads(body)["severity"] == "high"
        assert sent["headers"]["X-Signature"] == sign_payload(body, "s3cr3t")
        get_settings.cache_clear()

    async def test_no_url_configured_skips(self, alert_payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DRIFT_WEBHOOK_URL", raising=False)
        from api.config import get_settings
        get_settings.cache_clear()
        ok = await dispatch_drift_alert(alert_payload)
        assert ok is False
        get_settings.cache_clear()

    async def test_retries_then_gives_up(self, alert_payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DRIFT_WEBHOOK_URL", "https://example.test/hook")
        from api.config import get_settings
        get_settings.cache_clear()

        calls = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("httpx.AsyncClient.post", new=calls), patch("asyncio.sleep", new=AsyncMock()):
            ok = await dispatch_drift_alert(alert_payload)

        assert ok is False
        assert calls.await_count == 3
        get_settings.cache_clear()
