"""Self-scheduling ingestion loop. A plain asyncio loop is all a fixed-interval
poll needs — no APScheduler dependency for something `while True: sleep()`
already does.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from psycopg_pool import ConnectionPool

from .collector import run_tick
from .config import Config

log = logging.getLogger("fleet.scheduler")


async def run_forever(cfg: Config, pool: ConnectionPool, stop: asyncio.Event) -> None:
    """Tick until `stop` is set. A tick already running in its thread always
    finishes first, so the caller may close the pool once this returns."""
    while not stop.is_set():
        started = time.monotonic()
        try:
            await asyncio.to_thread(run_tick, cfg, pool)
        except Exception:
            log.exception("ingestion tick failed")
        elapsed = time.monotonic() - started
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, cfg.poll_interval_seconds - elapsed))
