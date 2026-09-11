"""Entrypoint: init the schema, then serve the dashboard + run ingestion in
the same process (the scheduler runs as a background asyncio task started by
web.py's lifespan hook).
"""
from __future__ import annotations

import logging

import uvicorn

from . import db
from .config import load_configs
from .web import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    configs = load_configs()
    pool = db.get_pool(configs[0].database_url)
    db.init_schema(pool)
    log = logging.getLogger("fleet.main")
    for cfg in configs:
        mode = "LIVE — switches will be executed" if cfg.live_execution else "OBSERVE — dry-run only, no switches will be executed"
        log.info("starting in %s mode for host %r", mode, cfg.host_label)
    app = create_app(configs, pool)
    try:
        uvicorn.run(app, host="0.0.0.0", port=configs[0].dashboard_port)
    finally:
        pool.close()


if __name__ == "__main__":
    main()
