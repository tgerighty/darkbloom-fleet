import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import Mount
from fastapi.staticfiles import StaticFiles

from fleet import main, web


def _route(app, path):
    return next(route for route in app.router.routes if getattr(route, "path", None) == path)


def test_index_serves_the_dashboard():
    app = web.create_app((), pool=None)
    response = asyncio.run(_route(app, "/").endpoint())
    assert str(response.path).endswith("dashboard.html")


def test_the_static_dir_is_mounted_for_the_page_module():
    app = web.create_app((), pool=None)
    mount = _route(app, "/static")
    assert isinstance(mount, Mount) and isinstance(mount.app, StaticFiles)
    assert Path(mount.app.directory) == web.STATIC_DIR


def test_status_returns_one_entry_per_host(monkeypatch):
    monkeypatch.setattr(web.queries, "build_status", lambda cfg, pool: {"label": cfg.host_label})
    app = web.create_app((SimpleNamespace(host_label="m3"), SimpleNamespace(host_label="m1")), pool=None)
    assert asyncio.run(_route(app, "/api/status").endpoint()) == {"hosts": [{"label": "m3"}, {"label": "m1"}]}


def test_lifespan_runs_one_loop_per_host_and_waits_for_them_on_shutdown(monkeypatch):
    finished = []

    async def fake_run_forever(cfg, pool, stop):
        await stop.wait()
        finished.append(cfg)

    monkeypatch.setattr(web, "run_forever", fake_run_forever)
    app = web.create_app(("a", "b"), pool=None)

    async def scenario():
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert sorted(finished) == ["a", "b"]


def test_lifespan_stops_the_loops_even_when_the_app_shuts_down_via_an_exception(monkeypatch):
    finished = []

    async def fake_run_forever(cfg, pool, stop):
        await stop.wait()
        finished.append(cfg)

    monkeypatch.setattr(web, "run_forever", fake_run_forever)
    app = web.create_app(("a",), pool=None)

    async def scenario():
        with pytest.raises(RuntimeError, match="boom"):
            async with app.router.lifespan_context(app):
                raise RuntimeError("boom")

    asyncio.run(scenario())
    assert finished == ["a"]


def _run_main(monkeypatch):
    calls = []
    configs = (SimpleNamespace(database_url="postgresql://x", live_execution=False, host_label="m3", dashboard_port=8080),
               SimpleNamespace(database_url="postgresql://x", live_execution=True, host_label="m1", dashboard_port=8080))
    monkeypatch.setattr(main, "load_configs", lambda: configs)
    monkeypatch.setattr(main.db, "get_pool", lambda url: calls.append(("pool", url)) or SimpleNamespace(close=lambda: calls.append("close")))
    monkeypatch.setattr(main.db, "init_schema", lambda pool: calls.append("schema"))
    monkeypatch.setattr(main, "create_app", lambda cfgs, pool: calls.append(("app", len(cfgs))) or "app")
    monkeypatch.setattr(main.uvicorn, "run", lambda app, host, port: calls.append(("run", app, host, port)))
    main.main()
    return calls


def test_main_serves_every_host_from_one_pool_and_closes_it(monkeypatch):
    monkeypatch.delenv("FLEET_BIND_HOST", raising=False)
    assert _run_main(monkeypatch) == [("pool", "postgresql://x"), "schema", ("app", 2), ("run", "app", "127.0.0.1", 8080), "close"]


def test_main_binds_where_fleet_bind_host_says(monkeypatch):
    monkeypatch.setenv("FLEET_BIND_HOST", "0.0.0.0")
    assert ("run", "app", "0.0.0.0", 8080) in _run_main(monkeypatch)
