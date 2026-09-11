"""Dashboard: one static HTML/JS page plus the JSON API it polls. No
templating engine — the page is static and fetches /api/status itself.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from psycopg_pool import ConnectionPool

from . import queries
from .config import Config
from .scheduler import run_forever

STATIC_DIR = Path(__file__).parent / "static"


def create_app(cfg: Config, pool: ConnectionPool) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(run_forever(cfg, pool))
        yield
        task.cancel()

    app = FastAPI(title="darkbloom-fleet", lifespan=lifespan)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html")

    @app.get("/api/status")
    async def status() -> dict:
        return await asyncio.to_thread(queries.build_status, cfg, pool)

    return app
