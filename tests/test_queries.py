from types import SimpleNamespace

from fleet import attribution, queries
from fleet.queries import _serving_shares


def _snap(t: float, model: str | None, *, active: bool = True, fresh: bool = True) -> dict:
    return {"observed_at": t, "current_model": model, "inference_active": active, "fresh": fresh}


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


def test_snapshots_with_fresh_false_do_not_count_as_serving():
    snaps = [_snap(0, "a", fresh=False), _snap(60, "a", fresh=False), _snap(120, "a", fresh=False)]
    assert _serving_shares(snaps, since=0, now=180) == {"idle": 100.0}


def test_a_stale_snapshot_does_not_hold_inference_active():
    shares = _serving_shares(
        [_snap(0, "a"), _snap(60, "a", fresh=False), _snap(120, "a")], since=0, now=180)
    assert shares == {"a": 66.7, "idle": 33.3}


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


def test_serving_percentage_treats_unfresh_snapshots_as_idle(fake_pool, monkeypatch):
    _clock(monkeypatch, 180.0)
    pool = fake_pool([_snap(0.0, "a", fresh=False)], [_snap(60.0, "a", fresh=False), _snap(120.0, "a", fresh=False)])
    assert queries.serving_percentage(pool, "h", 180.0) == {"idle": 100.0}
    assert all("fresh" in sql for sql, _params in pool.calls)


def _status_responses(daemon, demand, decisions, votes=(), card_totals=None, hourly=None):
    """Canned rows in the order build_status queries them: daemon, demand,
    attribution votes, the routability panel (self-route probe, last-served,
    measured switch cost), earnings x2, four fixed windows (before + rows
    each), lifetime's first snapshot, decisions, earnings rows, unattributed
    recent hashes, the card's session payout totals, the hourly jobs buckets."""
    return [daemon, demand, list(votes), [{"t": None}], [], [{"median": None, "n": 0}],
            [{"total": 2_500_000}], [{"total": 500_000}], *([[], []] * 4), [{"t": None}], decisions,
            [{"created_at": 9_000.0, "model": "a", "completion_tokens": 30, "micro_usd": 12}],
            [{"provider_hash": None}, {"provider_hash": "no-votes"}],
            card_totals or [{"tokens": 4_000, "requests": 2}],
            hourly or []]


def test_build_status_assembles_every_panel(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    daemon = {"current_model": "a", "fresh": True, "inference_active": False, "observed_at": 9_990.0}
    votes = [{"payout_rowid": 1, "provider_hash": "s1", "host": "m3"},
             {"payout_rowid": 2, "provider_hash": "s1", "host": "m3"},
             {"payout_rowid": 3, "provider_hash": "s2", "host": "other"}]
    hourly = [{"hour": 7_200.0, "portion": 0, "model": "a", "n": 2}]
    pool = fake_pool(*_status_responses([daemon], [{"model": "a", "ema_score": 0.2}], [{"action": "KEEP"}], votes,
                                        hourly=hourly))
    status = queries.build_status(
        SimpleNamespace(host_label="M3 label", host_id="m3", host_spec="M3 Max", live_execution=False,
                        switch_cost_seconds=300.0), pool)
    assert status["host"] == {"label": "M3 label", "spec": "M3 Max"} and status["mode"] == "OBSERVE"
    assert status["current_model"] == "a" and status["daemon_fresh"] is True
    assert status["earnings_usd_24h"] == 2.5 and status["earnings_usd_1h"] == 0.5
    assert set(status["serving"]) == {"1h", "7h", "24h", "30d", "lifetime"}
    assert status["serving"]["24h"] == {"idle": 100.0} and status["serving"]["lifetime"] == {}
    assert status["recent_decisions"] == [{"action": "KEEP"}]
    hourly_jobs = status["hourly_jobs"]
    assert hourly_jobs["legend"] == [{"letter": "A", "model": "a"}]
    assert len(hourly_jobs["rows"]) == 24
    assert hourly_jobs["rows"][0]["jobs"] == 2
    assert hourly_jobs["rows"][0]["portions"][0] == "a"
    assert hourly_jobs["rows"][1]["portions"] == [None] * 40
    assert status["recent_earnings"] == [{"created_at": 9_000.0, "model": "a", "completion_tokens": 30, "micro_usd": 12}]
    assert status["unattributed_recent"] == 2
    assert status["card"]["status"]["state"] == "ATTESTING"  # no trust level on the snapshot
    assert status["card"]["last_model_load_error"] is None
    assert status["card"]["kpis"]["tokens"] == 4_000 and status["card"]["kpis"]["token_requests"] == 2
    # Hash ownership, not ingest host; current totals stop at now.
    earnings_calls = [params for sql, params in pool.calls if "sum(micro_usd)" in sql]
    assert earnings_calls == [(10_000.0 - 86_400, 10_000.0, ["s1"]), (10_000.0 - 3_600, 10_000.0, ["s1"])]
    assert status["routability"] == {"self_route_as_of": None, "trust_level": None, "trust_reason": None,
                                     "last_served_at": None, "models": [], "session": None,
                                     "switch_cost": {"configured_seconds": 300.0, "measured_seconds": None,
                                                     "measured_sessions": 0}}


def _assert_unique_hash_owned_sql(sql: str) -> None:
    assert "DISTINCT ON (payout_rowid)" in sql
    assert "host = %s" not in sql
    assert "created_at <= %s" in sql
    assert "provider_hash = ANY(%s)" in sql


def test_earnings_follow_hash_ownership_and_unique_payouts(fake_pool):
    pool = fake_pool([{"total": 1_000_000}], [])
    assert queries.earnings_usd(pool, 0.0, 100.0, ["s1"]) == 1.0
    assert queries.recent_earnings(pool, 100.0, ["s1"]) == []
    sum_sql, sum_params = pool.calls[0]
    recent_sql, recent_params = pool.calls[1]
    _assert_unique_hash_owned_sql(sum_sql)
    _assert_unique_hash_owned_sql(recent_sql)
    assert sum_params == (0.0, 100.0, ["s1"])
    assert recent_params == (100.0, ["s1"], 50)


def test_recent_and_unattributed_share_unique_ledger_rows(fake_pool):
    pool = fake_pool(
        [{"created_at": 9.0, "model": "a", "completion_tokens": 1, "micro_usd": 2}],
        [{"provider_hash": None}, {"provider_hash": "s1"}],
    )
    rows = queries.recent_earnings(pool, 10.0, ["s1"])
    unattributed = attribution.unattributed_recent(pool, {"s1": "mac1"}, now=10.0)
    assert rows == [{"created_at": 9.0, "model": "a", "completion_tokens": 1, "micro_usd": 2}]
    assert unattributed == 1
    recent_sql, recent_params = pool.calls[0]
    unattr_sql, unattr_params = pool.calls[1]
    assert "DISTINCT ON (payout_rowid)" in recent_sql and "DISTINCT ON (payout_rowid)" in unattr_sql
    assert "host = %s" not in recent_sql and "host = %s" not in unattr_sql
    assert recent_params == (10.0, ["s1"], 50)
    assert unattr_params == (10.0, 50)


def test_build_status_without_any_daemon_snapshot(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    pool = fake_pool(*_status_responses([], [], []))
    status = queries.build_status(SimpleNamespace(host_label="m1", host_id="m1", host_spec="?", live_execution=True,
                                                  switch_cost_seconds=300.0), pool)
    assert status["current_model"] is None and status["mode"] == "LIVE"
    assert status["serving"]["1h"] == {"idle": 100.0} and status["demand"] == []
    assert status["card"]["status"]["state"] == "OFF" and status["card"]["kpis"]["tokens"] == 4_000
