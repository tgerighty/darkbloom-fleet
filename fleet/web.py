"""Dashboard: one static HTML/JS page plus the JSON API it polls. No
templating engine — the page is static and fetches /api/status itself.
One scheduler task runs per configured host, all against the same pool —
see config.load_configs for why the rest of the app stays single-host-shaped.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

from . import earnings_shadow, hourly, queries, watch
from .config import Config
from .scheduler import run_forever

log = logging.getLogger("fleet.web")
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
        tasks += [asyncio.create_task(watch.run_forever(cfg, pool, stop)) for cfg in configs]
        tasks += [asyncio.create_task(earnings_shadow.run_forever(cfg, pool, stop)) for cfg in configs]
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
    async def status() -> dict[str, object]:
        # Attribution and the self-route view are account-wide: query once,
        # then every host row reads the same mapping. Host cards are the
        # configured SSH collectors plus named discovered Macs (not UUIDs).
        try:
            attributed, self_route, unattributed = await asyncio.to_thread(queries.shared_status_data, pool)
            extras = await asyncio.to_thread(
                queries.unconfigured_host_ids, pool, _configured_host_ids(configs),
            )
        except Exception:
            log.exception("shared status data failed")
            return {"hosts": [_error_host(cfg) for cfg in configs]}
        # UUID discovery rows are account provider_ids, not fleet Macs. Full
        # build_status on each burned ~1.4s×32 after #34 still left ~45s wall.
        # Fan-out only configured + named discoveries; expose UUID count cheaply.
        uuid_extras, named_extras = [], []
        for host_id in extras:
            (uuid_extras if _is_provider_uuid(host_id) else named_extras).append(host_id)
        display = _display_configs(configs, named_extras)
        # Bound host-row fan-out to the pool: each build_status holds one
        # connection at a time; stampeding past max_size just queues in the
        # pool and adds no throughput. Order matches `display`.
        # ponytail: Semaphore(pool.max_size); raise if status holds >1 conn.
        limit = max(1, int(getattr(pool, "max_size", 4) or 4))
        gate = asyncio.Semaphore(limit)

        async def _bounded(cfg: object) -> queries.Row:
            async with gate:
                return await asyncio.to_thread(
                    _status_row, cfg, pool, attributed, self_route, unattributed,
                )

        statuses = await asyncio.gather(*(_bounded(cfg) for cfg in display))
        hourly.share_legends(statuses)
        body: dict[str, object] = {"hosts": list(statuses)}
        if uuid_extras:
            body["discovered_unlinked"] = len(uuid_extras)
        return body

    return app



def _is_provider_uuid(host_id: str) -> bool:
    """True for Darkbloom provider_id keys (RFC-4122 UUID strings)."""
    try:
        UUID(host_id)
    except ValueError:
        return False
    return True


def _configured_host_ids(configs: tuple[Config, ...]) -> set[str]:
    ids: set[str] = set()
    for cfg in configs:
        host_id = getattr(cfg, "host_id", None)
        if isinstance(host_id, str) and host_id:
            ids.add(host_id)
    return ids


def _display_configs(configs: tuple[Config, ...], extra_ids: list[str]) -> list[object]:
    """Configured hosts first (deploy order), then named discovered hosts.

    Callers must filter UUID provider_ids out of extra_ids — those are not Macs.
    Named discovered rows are display-only: build_status only reads
    host_id/label/spec and freshness/switch-cost knobs from configs[0].
    """
    from types import SimpleNamespace

    if not extra_ids:
        return list(configs)
    if not configs:
        return []
    template = configs[0]
    extras = [
        SimpleNamespace(
            host_id=host_id,
            host_label=host_id,
            host_spec="discovered",
            daemon_freshness_seconds=getattr(template, "daemon_freshness_seconds", 90.0),
            switch_cost_seconds=getattr(template, "switch_cost_seconds", 300.0),
        )
        for host_id in extra_ids
    ]
    return [*configs, *extras]



def _error_host(cfg: Config) -> queries.Row:
    return {
        "host": {"label": getattr(cfg, "host_label", "host"), "spec": getattr(cfg, "host_spec", "")},
        "mode": "MONITOR",
        "current_model": None,
        "inference_active": None,
        "as_of": None,
        "demand": [],
        "recent_earnings": [],
        "serving": {},
        "card": None,
        "routability": None,
        "hourly_jobs": None,
        "unattributed_recent": 0,
        "error": "status unavailable",
    }


def _status_row(cfg: Config, pool: ConnectionPool, attributed: dict[str, str],
                self_route: tuple[float | None, dict[str, int]], unattributed: int) -> queries.Row:
    try:
        return queries.build_status(cfg, pool, attributed, self_route, unattributed)
    except Exception:
        log.exception("host status failed: %s", getattr(cfg, "host_label", "host"))
        return _error_host(cfg)
