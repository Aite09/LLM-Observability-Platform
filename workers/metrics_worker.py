"""
Metrics worker — loop daemon aggregating logs into rollups.

Not an RQ job: aggregation is periodic, not event-driven. A plain asyncio
loop with SIGTERM-aware shutdown keeps operational surface minimal
(no scheduler dependency).

Run: python -m workers.metrics_worker
"""

from __future__ import annotations

import asyncio
import logging
import random
import signal
from datetime import datetime, timedelta, timezone

from api.config import get_settings
from api.dependencies import async_session_maker
from monitor.metrics_aggregator import aggregate_window

logger = logging.getLogger(__name__)


async def run_once() -> None:
    """One aggregation tick: current + previous hour (hourly), today (daily)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    hour = now.replace(minute=0, second=0, microsecond=0)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_maker() as session:
        await aggregate_window(session, "hourly", hour - timedelta(hours=1), hour + timedelta(hours=1))
        await aggregate_window(session, "daily", day, day + timedelta(days=1))


async def main() -> None:
    settings = get_settings()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("metrics_worker started; interval=%ds", settings.metrics_interval_seconds)
    while not stop.is_set():
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001 — worker never dies from one tick
            logger.error("metrics tick failed: %s", exc)
        # jitter ±10% avoids thundering-herd with drift worker on shared DB
        delay = settings.metrics_interval_seconds * random.uniform(0.9, 1.1)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
    logger.info("metrics_worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    asyncio.run(main())
