from types import SimpleNamespace

from fleet import queries
from fleet.queries import _serving_shares


def _snap(t: float, model: str | None, *, active: bool = True) -> dict:
    return {"observed_at": t, "current_model": model, "inference_active": active}


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


def test_a_warm_but_idle_model_counts_as_idle():
    shares = _serving_shares([_snap(0, "a", active=False), _snap(300, "a")], since=0, now=400)
    assert shares == {"a": 25.0, "idle": 75.0}


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


def _status_responses(daemon, demand, decisions, votes=()):
    """Canned rows in the order build_status queries them: daemon, demand,
    attribution votes, earnings x2, four fixed windows (before + rows each),
    lifetime's first snapshot, decisions, earnings rows, unattributed recent
    hashes, self-route probe, last-served."""
    return [daemon, demand, list(votes), [{"total": 2_500_000}], [{"total": 500_000}],
            *([[], []] * 4), [{"t": None}], decisions,
            [{"created_at": 9_000.0, "model": "a", "completion_tokens": 30, "micro_usd": 12}],
            [{"provider_hash": None}, {"provider_hash": "no-votes"}], [{"t": None}], []]


def test_build_status_assembles_every_panel(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    daemon = {"current_model": "a", "fresh": True, "inference_active": False, "observed_at": 9_990.0}
    votes = [{"provider_hash": "s1", "host": "m3", "votes": 2}, {"provider_hash": "s2", "host": "other", "votes": 9}]
    pool = fake_pool(*_status_responses([daemon], [{"model": "a", "ema_score": 0.2}], [{"action": "KEEP"}], votes))
    status = queries.build_status(SimpleNamespace(host_label="m3", host_spec="M3 Max", live_execution=False), pool)
    assert status["host"] == {"label": "m3", "spec": "M3 Max"} and status["mode"] == "OBSERVE"
    assert status["current_model"] == "a" and status["daemon_fresh"] is True
    assert status["earnings_usd_24h"] == 2.5 and status["earnings_usd_1h"] == 0.5
    assert set(status["serving"]) == {"1h", "7h", "24h", "30d", "lifetime"}
    assert status["serving"]["24h"] == {"idle": 100.0} and status["serving"]["lifetime"] == {}
    assert status["recent_decisions"] == [{"action": "KEEP"}]
    assert status["recent_earnings"] == [{"created_at": 9_000.0, "model": "a", "completion_tokens": 30, "micro_usd": 12}]
    assert status["unattributed_recent"] == 2
    # Only this host's provider sessions count as its money.
    earnings_calls = [params for sql, params in pool.calls if "sum(micro_usd)" in sql]
    assert earnings_calls == [("m3", 10_000.0 - 86_400, ["s1"]), ("m3", 10_000.0 - 3_600, ["s1"])]
    assert status["routability"] == {"self_route_as_of": None, "trust_level": None, "trust_reason": None,
                                     "last_served_at": None, "models": [], "session": None}


def test_earnings_queries_pass_the_attribution_filter_through(fake_pool):
    pool = fake_pool([{"total": 1_000_000}], [])
    assert queries.earnings_usd(pool, "h", 0.0, ["s1"]) == 1.0
    assert queries.recent_earnings(pool, "h", ["s1"]) == []
    assert [params for _sql, params in pool.calls] == [("h", 0.0, ["s1"]), ("h", ["s1"], 50)]


def test_build_status_without_any_daemon_snapshot(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    pool = fake_pool(*_status_responses([], [], []))
    status = queries.build_status(SimpleNamespace(host_label="m1", host_spec="?", live_execution=True), pool)
    assert status["current_model"] is None and status["mode"] == "LIVE"
    assert status["serving"]["1h"] == {"idle": 100.0} and status["demand"] == []
