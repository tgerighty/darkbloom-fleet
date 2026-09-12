import asyncio
from types import SimpleNamespace

from fleet import scheduler


def _run_one_tick(monkeypatch, tick_body):
    calls = []

    async def scenario():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def fake_tick(cfg, pool):
            calls.append(pool)
            loop.call_soon_threadsafe(stop.set)
            tick_body()

        monkeypatch.setattr(scheduler, "run_tick", fake_tick)
        await asyncio.wait_for(scheduler.run_forever(SimpleNamespace(poll_interval_seconds=60.0), "pool", stop), timeout=5)

    asyncio.run(scenario())
    return calls


def test_run_forever_finishes_the_tick_in_flight_then_stops(monkeypatch):
    assert _run_one_tick(monkeypatch, lambda: None) == ["pool"]


def test_a_failing_tick_is_logged_and_does_not_escape(monkeypatch, caplog):
    def boom():
        raise RuntimeError("boom")

    assert _run_one_tick(monkeypatch, boom) == ["pool"]
    assert "ingestion tick failed" in caplog.text
