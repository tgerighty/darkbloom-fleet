import asyncio
from types import SimpleNamespace

from fleet import scheduler


def test_run_forever_finishes_the_tick_in_flight_then_stops(monkeypatch):
    calls = []

    async def scenario():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def fake_tick(cfg, pool):
            calls.append(pool)
            loop.call_soon_threadsafe(stop.set)

        monkeypatch.setattr(scheduler, "run_tick", fake_tick)
        cfg = SimpleNamespace(poll_interval_seconds=60.0)
        await asyncio.wait_for(scheduler.run_forever(cfg, "pool", stop), timeout=5)

    asyncio.run(scenario())
    assert calls == ["pool"]
