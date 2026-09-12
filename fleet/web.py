"""Dashboard: one static HTML/JS page plus the JSON API it polls. No
templating engine — the page is static and fetches /api/status itself.
One scheduler task runs per configured host, all against the same pool —
see config.load_configs for why the rest of the app stays single-host-shaped.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from psycopg_pool import ConnectionPool

from . import queries
from .config import Config
from .scheduler import run_forever

STATIC_DIR = Path(__file__).parent / "static"


def create_app(configs: tuple[Config, ...], pool: ConnectionPool) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        tasks = [asyncio.create_task(run_forever(cfg, pool, stop)) for cfg in configs]
        yield
        stop.set()
        # Let a tick already in its thread finish: main() closes the pool next.
        await asyncio.gather(*tasks)

    app = FastAPI(title="darkbloom-fleet", lifespan=lifespan)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html")

    # response_model=None: the rows are plain dicts; FastAPI must not build a
    # validation model from the annotation.
    @app.get("/api/status", response_model=None)
    async def status() -> dict[str, list[queries.Row]]:
        statuses = await asyncio.gather(*(asyncio.to_thread(queries.build_status, cfg, pool) for cfg in configs))
        return {"hosts": list(statuses)}

    return app
