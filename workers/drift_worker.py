"""
Drift worker — periodic detection across all active applications.

Loop daemon (same shape as metrics_worker). Each tick: distinct app ids
seen in the last baseline+1 days → detect per app → webhook on new alerts.

Run: python -m workers.drift_worker
"""

from __future__ import annotations

import asyncio
import logging
import random
import signal
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from api.config import get_settings
from api.dependencies import async_session_maker
from api.models.llm_log import LLMLog
from monitor.drift_detector import detect_drift_for_app
from monitor.webhooks import dispatch_drift_alert

logger = logging.getLogger(__name__)


async def run_once() -> None:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=settings.drift_baseline_days + 1)

    async with async_session_maker() as session:
        app_ids = (
            await session.execute(
                select(LLMLog.application_id).where(LLMLog.created_at >= cutoff).distinct()
            )
        ).scalars().all()

        for app_id in app_ids:
            try:
                alert = await detect_drift_for_app(session, app_id)
            except Exception as exc:  # noqa: BLE001 — one bad app never stops the sweep
                logger.error("drift detection failed for %s: %s", app_id, exc)
                continue
            if alert is not None:
                await dispatch_drift_alert({
                    "id": str(alert.id),
                    "application_id": alert.application_id,
                    "drift_type": alert.drift_type,
                    "severity": alert.severity,
                    "drift_score": float(alert.drift_score),
                    "detected_at": alert.detected_at.isoformat(),
                    "baseline_stats": alert.baseline_stats,
                    "current_stats": alert.current_stats,
                })


async def main() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("drift_worker started; interval=%ds", settings.drift_check_interval_seconds)
    while not stop.is_set():
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001
            logger.error("drift tick failed: %s", exc)
        delay = settings.drift_check_interval_seconds * random.uniform(0.9, 1.1)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
    logger.info("drift_worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    asyncio.run(main())
