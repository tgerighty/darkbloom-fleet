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
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

from . import queries
from .config import Config
from .scheduler import run_forever

STATIC_DIR = Path(__file__).parent / "static"
# The page's JS and the API ship in the same image: a browser that keeps a
# cached module across a deploy renders the new API's data with the old code
# (NaN% rows after the hourly-gaps change). no-cache keeps the ETag round trip
# but makes it mandatory on every load.
NO_CACHE = {"Cache-Control": "no-cache"}


class RevalidatedStaticFiles(StaticFiles):
    """Only file responses need the header: StaticFiles' 404/405 errors carry
    no Last-Modified, so browsers never cache them heuristically."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response


def create_app(configs: tuple[Config, ...], pool: ConnectionPool) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        tasks = [asyncio.create_task(run_forever(cfg, pool, stop)) for cfg in configs]
        try:
            yield
        finally:
            stop.set()
            # Let a tick already in its thread finish: main() closes the pool next.
            await asyncio.gather(*tasks)

    app = FastAPI(title="darkbloom-fleet", lifespan=lifespan)
    # The page's JS lives next to the HTML it belongs with; mounting the whole
    # static dir keeps that pairing without a per-file route each time it grows.
    app.mount("/static", RevalidatedStaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html", headers=NO_CACHE)

    # response_model=None: the rows are plain dicts; FastAPI must not build a
    # validation model from the annotation.
    @app.get("/api/status", response_model=None)
    async def status() -> dict[str, list[queries.Row]]:
        # Attribution and the self-route view are account-wide: query once,
        # then every host row reads the same mapping.
        try:
            attributed, self_route = await asyncio.to_thread(queries.shared_status_data, pool)
        except Exception as exc:
            return {"hosts": [_error_host(cfg, exc) for cfg in configs]}
        statuses = await asyncio.gather(
            *(asyncio.to_thread(_status_row, cfg, pool, attributed, self_route) for cfg in configs)
        )
        return {"hosts": list(statuses)}

    return app


def _error_host(cfg: Config, exc: BaseException) -> queries.Row:
    return {
        "host": {"label": getattr(cfg, "host_label", "host"), "spec": getattr(cfg, "host_spec", "")},
        "mode": "LIVE" if getattr(cfg, "live_execution", False) else "OBSERVE",
        "current_model": None,
        "inference_active": None,
        "as_of": None,
        "demand": [],
        "recent_decisions": [],
        "recent_earnings": [],
        "serving": {},
        "card": None,
        "routability": None,
        "hourly_jobs": None,
        "unattributed_recent": 0,
        "error": f"{type(exc).__name__}: {exc}",
    }


def _status_row(cfg: Config, pool: ConnectionPool, attributed: dict[str, str],
                self_route: tuple[float | None, dict[str, int]]) -> queries.Row:
    try:
        return queries.build_status(cfg, pool, attributed, self_route)
    except Exception as exc:
        return _error_host(cfg, exc)
