from types import SimpleNamespace

from fleet import queries
from fleet.queries import _serving_shares


def _snap(t: float, model: str | None) -> dict:
    return {"observed_at": t, "current_model": model}


def _clock(monkeypatch, now: float) -> None:
    monkeypatch.setattr(queries, "time", SimpleNamespace(time=lambda: now))


def test_a_snapshot_before_the_window_counts_from_the_window_start():
    shares = _serving_shares([_snap(900, "a"), _snap(1100, "b")], since=1000, now=1200)
    assert shares == {"a": 50.0, "b": 50.0, "idle": 0.0}


def test_the_last_snapshot_holds_until_now():
    assert _serving_shares([_snap(1000, "a")], since=1000, now=1300) == {"a": 100.0, "idle": 0.0}


def test_gaps_longer_than_ten_minutes_count_as_idle():
    shares = _serving_shares([_snap(0, "a"), _snap(60, "b"), _snap(2000, "a")], since=0, now=2060)
    assert shares == {"a": 5.8, "idle": 94.2}


def test_a_gap_of_exactly_ten_minutes_still_counts_as_serving():
    assert _serving_shares([_snap(0, "a"), _snap(600, "b")], since=0, now=660) == {"a": 90.9, "b": 9.1, "idle": 0.0}


def test_a_stale_final_snapshot_is_all_idle():
    assert _serving_shares([_snap(0, "a")], since=0, now=1000) == {"idle": 100.0}


def test_an_empty_window_has_no_shares():
    assert _serving_shares([], since=1000, now=1000) == {}


def test_latest_demand_table_orders_by_smoothed_score(fake_pool):
    pool = fake_pool([{"model": "a", "ema_score": 0.1}, {"model": "b", "ema_score": 0.3}, {"model": "c", "ema_score": None}])
    assert [row["model"] for row in queries.latest_demand_table(pool, "h")] == ["b", "a", "c"]


def test_serving_percentage_includes_the_model_serving_when_the_window_opened(fake_pool, monkeypatch):
    _clock(monkeypatch, 1200.0)
    pool = fake_pool([_snap(900.0, "a")], [_snap(1100.0, "b")])
    assert queries.serving_percentage(pool, "h", 200.0) == {"a": 50.0, "b": 50.0, "idle": 0.0}


def test_lifetime_serving_starts_at_the_first_snapshot(fake_pool, monkeypatch):
    _clock(monkeypatch, 1200.0)
    pool = fake_pool([{"t": 1000.0}], [], [_snap(1000.0, "a")])
    assert queries.serving_percentage(pool, "h", None) == {"a": 100.0, "idle": 0.0}
    assert queries.serving_percentage(fake_pool([{"t": None}]), "h", None) == {}


def _status_responses(daemon, demand, decisions):
    """Canned rows in the order build_status queries them: daemon, demand,
    earnings x2, four fixed windows (before + rows each), lifetime's first
    snapshot, decisions, self-route probe."""
    return [daemon, demand, [{"total": 2_500_000}], [{"total": 500_000}],
            *([[], []] * 4), [{"t": None}], decisions, [{"t": None}]]


def test_build_status_assembles_every_panel(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    daemon = {"current_model": "a", "fresh": True, "inference_active": False, "observed_at": 9_990.0}
    pool = fake_pool(*_status_responses([daemon], [{"model": "a", "ema_score": 0.2}], [{"action": "KEEP"}]))
    status = queries.build_status(SimpleNamespace(host_label="m3", host_spec="M3 Max", live_execution=False), pool)
    assert status["host"] == {"label": "m3", "spec": "M3 Max"} and status["mode"] == "OBSERVE"
    assert status["current_model"] == "a" and status["daemon_fresh"] is True
    assert status["earnings_usd_24h"] == 2.5 and status["earnings_usd_1h"] == 0.5
    assert set(status["serving"]) == {"1h", "7h", "24h", "30d", "lifetime"}
    assert status["serving"]["24h"] == {"idle": 100.0} and status["serving"]["lifetime"] == {}
    assert status["recent_decisions"] == [{"action": "KEEP"}]
    assert status["routability"] == {"self_route_as_of": None, "models": [], "session": None}


def test_build_status_without_any_daemon_snapshot(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    pool = fake_pool(*_status_responses([], [], []))
    status = queries.build_status(SimpleNamespace(host_label="m1", host_spec="?", live_execution=True), pool)
    assert status["current_model"] is None and status["mode"] == "LIVE"
    assert status["serving"]["1h"] == {"idle": 100.0} and status["demand"] == []
