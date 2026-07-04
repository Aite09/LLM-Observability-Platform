"""
Webhook dispatch — POSTs drift alerts to the configured URL.

Security: body signed with HMAC-SHA256 (X-Signature: sha256=<hex>).
Receivers verify with their copy of WEBHOOK_SECRET — prevents spoofed alerts.

Failure policy: 3 attempts, exponential backoff, then give up and log.
Never raises to the caller — a dead webhook must not break drift detection.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging

import httpx

from api.config import get_settings

logger = logging.getLogger(__name__)


def sign_payload(body: bytes, secret: str) -> str:
    """HMAC-SHA256 signature header value: sha256=<hexdigest>."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def dispatch_drift_alert(alert_data: dict) -> bool:
    """POST alert JSON to DRIFT_WEBHOOK_URL. True on 2xx, False otherwise/skip."""
    settings = get_settings()
    if not settings.drift_webhook_url:
        logger.debug("No DRIFT_WEBHOOK_URL configured — webhook skipped")
        return False

    body = json.dumps(alert_data, default=str).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": sign_payload(body, settings.webhook_secret),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(settings.drift_webhook_url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    logger.info("Webhook delivered: %s → %d", settings.drift_webhook_url, resp.status_code)
                    return True
                logger.warning("Webhook non-2xx (%d), attempt %d", resp.status_code, attempt + 1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Webhook attempt %d failed: %s", attempt + 1, exc)
            await asyncio.sleep(2**attempt)

    logger.error("Webhook delivery failed after 3 attempts: %s", settings.drift_webhook_url)
    return False
