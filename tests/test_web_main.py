import asyncio
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import Mount
from fastapi.staticfiles import StaticFiles

from fleet import main, web


def _route(app, path):
    return next(route for route in app.router.routes if getattr(route, "path", None) == path)


def test_index_serves_the_dashboard_and_must_be_revalidated():
    app = web.create_app((), pool=None)
    response = asyncio.run(_route(app, "/").endpoint())
    assert str(response.path).endswith("dashboard.html")
    assert response.headers["cache-control"] == "no-cache"


def test_the_static_dir_is_mounted_for_the_page_module():
    app = web.create_app((), pool=None)
    mount = _route(app, "/static")
    assert isinstance(mount, Mount) and isinstance(mount.app, web.RevalidatedStaticFiles)
    assert isinstance(mount.app, StaticFiles)
    assert Path(mount.app.directory) == web.STATIC_DIR


def test_static_modules_must_be_revalidated_on_every_load():
    # A cached hourly.js against a newer API rendered NaN% rows on the phone.
    app = web.create_app((), pool=None)
    path = web.STATIC_DIR / "hourly.js"
    scope = {"type": "http", "method": "GET", "headers": []}
    response = _route(app, "/static").app.file_response(path, os.stat(path), scope)
    assert response.headers["cache-control"] == "no-cache"


def _patch_status(monkeypatch, build, shared=None, extras=None):
    monkeypatch.setattr(web.queries, "shared_status_data", shared or (lambda pool: ({}, (None, {}), 0)))
    monkeypatch.setattr(web.queries, "unconfigured_host_ids",
                        (lambda pool, configured: list(extras or [])))
    monkeypatch.setattr(web.queries, "build_status", build)


def test_status_returns_one_entry_per_host(monkeypatch):
    _patch_status(monkeypatch, lambda cfg, pool, attributed, self_route, unattributed: {"label": cfg.host_label})
    app = web.create_app((SimpleNamespace(host_label="m3"), SimpleNamespace(host_label="m1")), pool=None)
    assert asyncio.run(_route(app, "/api/status").endpoint()) == {"hosts": [{"label": "m3"}, {"label": "m1"}]}


def test_status_computes_account_wide_data_once_and_passes_it_to_each_host(monkeypatch):
    attributed = {"s1": "m3"}
    self_route = (100.0, {"a": 1})
    unattributed = 2
    shared_calls = []
    seen = []

    def shared(pool):
        shared_calls.append(pool)
        return attributed, self_route, unattributed

    def build(cfg, pool, got_attr, got_route, got_unattributed):
        seen.append((cfg.host_label, got_attr, got_route, got_unattributed))
        return {"label": cfg.host_label}

    _patch_status(monkeypatch, build, shared)
    app = web.create_app((SimpleNamespace(host_label="m3"), SimpleNamespace(host_label="m1")), pool="P")
    assert asyncio.run(_route(app, "/api/status").endpoint()) == {"hosts": [{"label": "m3"}, {"label": "m1"}]}
    assert shared_calls == ["P"]
    assert {row[0] for row in seen} == {"m3", "m1"}
    assert all(row[1] is attributed and row[2] is self_route for row in seen)
    assert all(row[3] == unattributed for row in seen)
    assert len(seen) == 2


def test_status_keeps_a_host_when_the_other_build_fails(monkeypatch, caplog):
    def build(cfg, pool, attributed, self_route, unattributed):
        if cfg.host_label == "m1":
            raise RuntimeError("boom")
        return {"host": {"label": cfg.host_label}, "mode": "OBSERVE"}

    _patch_status(monkeypatch, build)
    app = web.create_app(
        (SimpleNamespace(host_label="m3", host_spec="M3", live_execution=False),
         SimpleNamespace(host_label="m1", host_spec="M1", live_execution=False)),
        pool=None,
    )
    body = asyncio.run(_route(app, "/api/status").endpoint())
    assert body["hosts"][0] == {"host": {"label": "m3"}, "mode": "OBSERVE"}
    err = body["hosts"][1]
    assert err["host"] == {"label": "m1", "spec": "M1"}
    assert err["demand"] == [] and err["recent_earnings"] == []
    assert err["error"] == "status unavailable"
    assert "boom" not in str(err)
    assert "boom" in caplog.text


def test_status_keeps_host_rows_when_shared_data_fails(monkeypatch, caplog):
    def shared(pool):
        raise RuntimeError("votes down")

    _patch_status(monkeypatch, lambda cfg, pool, attributed, self_route, unattributed: {"label": cfg.host_label}, shared)
    app = web.create_app(
        (SimpleNamespace(host_label="m3", host_spec="M3", live_execution=False),
         SimpleNamespace(host_label="m1", host_spec="M1", live_execution=False)),
        pool=None,
    )
    body = asyncio.run(_route(app, "/api/status").endpoint())
    assert all(row["error"] == "status unavailable" for row in body["hosts"])
    assert [row["host"]["label"] for row in body["hosts"]] == ["m3", "m1"]
    assert "votes down" in caplog.text


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


def test_status_shares_hourly_letters_and_colour_order_across_hosts(monkeypatch):
    def build(cfg, *_args):
        models = ['gpt-oss-20b', 'nvidia-nemotron-3.5-lightning'] if cfg.host_label == 'm1' else [
            'gemma-4-26b-qat', 'gpt-oss-20b']
        return {'hourly_jobs': {'legend': [{'model': m, 'letter': '?'} for m in models],
                                'rows': [{'jobs': len(models), 'portions': models}]}}
    _patch_status(monkeypatch, build)
    app = web.create_app((SimpleNamespace(host_label='m3'), SimpleNamespace(host_label='m1')), object())
    hosts = asyncio.run(_route(app, '/api/status').endpoint())['hosts']
    expected = [{'model': 'gemma-4-26b-qat', 'letter': 'G'},
                {'model': 'gpt-oss-20b', 'letter': 'O'},
                {'model': 'nvidia-nemotron-3.5-lightning', 'letter': 'N'}]
    assert hosts[0]['hourly_jobs']['legend'] == hosts[1]['hourly_jobs']['legend'] == expected
    assert hosts[0]['hourly_jobs']['rows'][0]['portions'] == ['gemma-4-26b-qat', 'gpt-oss-20b']
    assert hosts[1]['hourly_jobs']['rows'][0]['portions'] == ['gpt-oss-20b', 'nvidia-nemotron-3.5-lightning']


def test_status_appends_discovered_hosts_after_configured(monkeypatch):
    seen = []

    def build(cfg, pool, attributed, self_route, unattributed):
        seen.append(cfg.host_id)
        return {"host": {"label": cfg.host_label, "spec": cfg.host_spec}}

    _patch_status(monkeypatch, build, extras=["m4-128-1"])
    app = web.create_app(
        (SimpleNamespace(host_id="m3-48-1", host_label="m3-48-1", host_spec="M3",
                         daemon_freshness_seconds=90, switch_cost_seconds=300),),
        pool=None,
    )
    body = asyncio.run(_route(app, "/api/status").endpoint())
    # gather preserves display order even when build threads finish out of order
    assert [row["host"]["label"] for row in body["hosts"]] == ["m3-48-1", "m4-128-1"]
    assert body["hosts"][1]["host"]["spec"] == "discovered"
    assert set(seen) == {"m3-48-1", "m4-128-1"}


def test_status_bounds_host_row_concurrency_to_pool_max_size(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def build(cfg, *_args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"label": cfg.host_label}

    _patch_status(monkeypatch, build)
    configs = tuple(SimpleNamespace(host_label=f"m{n}") for n in range(8))
    pool = SimpleNamespace(max_size=3)
    app = web.create_app(configs, pool=pool)
    t0 = time.perf_counter()
    body = asyncio.run(_route(app, "/api/status").endpoint())
    elapsed = time.perf_counter() - t0
    assert [row["label"] for row in body["hosts"]] == [f"m{n}" for n in range(8)]
    assert peak == 3
    # sequential ~8*0.05=0.40s; three-wide ~ceil(8/3)*0.05 ~= 0.15s (+slack)
    assert elapsed < 0.30, elapsed


def test_status_falls_back_to_four_when_pool_has_no_max_size(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def build(cfg, *_args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"label": cfg.host_label}

    _patch_status(monkeypatch, build)
    configs = tuple(SimpleNamespace(host_label=f"m{n}") for n in range(6))
    app = web.create_app(configs, pool=None)
    assert len(asyncio.run(_route(app, "/api/status").endpoint())["hosts"]) == 6
    assert peak == 4


def test_status_skips_uuid_discovery_full_rows_and_exposes_count(monkeypatch):
    """UUID provider_ids must not multiply per-host build_status / DB work."""
    seen = []
    builds = {"n": 0}

    def build(cfg, pool, attributed, self_route, unattributed):
        builds["n"] += 1
        seen.append(cfg.host_id)
        return {"host": {"label": cfg.host_label, "spec": cfg.host_spec}}

    uuids = [f"00000000-0000-4000-8000-{n:012d}" for n in range(1, 33)]
    _patch_status(monkeypatch, build, extras=[*uuids, "m4-128-1"])
    app = web.create_app(
        (SimpleNamespace(host_id="m3-48-1", host_label="m3-48-1", host_spec="M3",
                         daemon_freshness_seconds=90, switch_cost_seconds=300),
         SimpleNamespace(host_id="M1-64-1", host_label="M1-64-1", host_spec="M1",
                         daemon_freshness_seconds=90, switch_cost_seconds=300)),
        pool=None,
    )
    body = asyncio.run(_route(app, "/api/status").endpoint())
    labels = [row["host"]["label"] for row in body["hosts"]]
    assert labels == ["m3-48-1", "M1-64-1", "m4-128-1"]
    assert body["hosts"][2]["host"]["spec"] == "discovered"
    assert set(seen) == {"m3-48-1", "M1-64-1", "m4-128-1"}
    assert builds["n"] == 3  # not 2 + 32 + 1
    assert body["discovered_unlinked"] == 32
    assert not any(web._is_provider_uuid(label) for label in labels)


def test_status_omits_discovered_unlinked_when_no_uuid_extras(monkeypatch):
    _patch_status(
        monkeypatch,
        lambda cfg, *_a: {"host": {"label": cfg.host_label}},
        extras=["m4-128-1"],
    )
    app = web.create_app(
        (SimpleNamespace(host_id="m3-48-1", host_label="m3-48-1", host_spec="M3",
                         daemon_freshness_seconds=90, switch_cost_seconds=300),),
        pool=None,
    )
    body = asyncio.run(_route(app, "/api/status").endpoint())
    assert "discovered_unlinked" not in body
    assert [row["host"]["label"] for row in body["hosts"]] == ["m3-48-1", "m4-128-1"]


def test_is_provider_uuid_accepts_rfc4122_only():
    assert web._is_provider_uuid("00000000-0000-4000-8000-000000000004")
    assert not web._is_provider_uuid("m4-128-1")
    assert not web._is_provider_uuid("legacy-mac")
    assert not web._is_provider_uuid("")
