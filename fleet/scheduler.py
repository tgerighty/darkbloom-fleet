"""Self-scheduling ingestion loop. A plain asyncio loop is all a fixed-interval
poll needs — no APScheduler dependency for something `while True: sleep()`
already does.
"""
from __future__ import annotations

import asyncio
import logging
import time

from psycopg_pool import ConnectionPool

from .collector import run_tick
from .config import Config

log = logging.getLogger("fleet.scheduler")


async def run_forever(cfg: Config, pool: ConnectionPool) -> None:
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(run_tick, cfg, pool)
        except Exception:  # noqa: BLE001 - one bad tick must not kill the service
            log.exception("ingestion tick failed")
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(0.0, cfg.poll_interval_seconds - elapsed))
