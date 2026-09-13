from types import SimpleNamespace

from fleet import attribution, queries
from fleet.queries import _serving_shares, _window_shares


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


def test_a_future_snapshot_does_not_count_time_after_now():
    shares = _serving_shares([_snap(1000, "a"), _snap(2000, "a")], since=1000, now=1500)
    assert shares == {"a": 100.0, "idle": 0.0}


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


def test_window_shares_include_the_model_serving_when_the_window_opened():
    snaps = [_snap(900.0, "a"), _snap(1100.0, "b")]
    assert _window_shares(snaps, 200.0, 1200.0) == {"a": 50.0, "b": 50.0, "idle": 0.0}


def test_lifetime_window_starts_at_the_first_snapshot():
    assert _window_shares([_snap(1000.0, "a")], None, 1200.0) == {"a": 100.0, "idle": 0.0}
    assert _window_shares([], None, 1200.0) == {}


def test_window_shares_drop_future_snapshots():
    snaps = [_snap(1000.0, "a"), _snap(2000.0, "b")]
    assert _window_shares(snaps, 600.0, 1500.0) == {"a": 83.3, "idle": 16.7}
    assert _window_shares(snaps, None, 1500.0) == {"a": 100.0, "idle": 0.0}


def test_window_shares_treat_unfresh_snapshots_as_idle():
    snaps = [_snap(0.0, "a", fresh=False), _snap(60.0, "a", fresh=False), _snap(120.0, "a", fresh=False)]
    assert _window_shares(snaps, 180.0, 180.0) == {"idle": 100.0}


def test_named_windows_share_one_history_and_one_now():
    now = 5_000.0
    snaps = [_snap(1_300.0, "a"), _snap(1_700.0, "b")]
    windows = {name: _window_shares(snaps, seconds, now) for name, seconds in queries.SERVING_WINDOWS.items()}
    # 1h opens at 1400: a is already serving and holds to 1700 (gap 400s).
    # Counting from 1300 would be 11.1%; dropping the before-row is all idle.
    assert windows["1h"] == {"a": 8.3, "idle": 91.7}
    assert windows["lifetime"] == {"a": 10.8, "idle": 89.2}
    assert windows["24h"]["idle"] == 99.5


def test_a_gap_inside_a_named_window_counts_as_idle():
    snaps = [_snap(3_000.0, "a"), _snap(3_700.0, "a")]
    assert _window_shares(snaps, 3_600.0, 4_000.0) == {"a": 8.3, "idle": 91.7}


def test_serving_percentages_reads_bounded_history_and_a_lifetime_aggregate(fake_pool):
    snaps = [_snap(900.0, "a"), _snap(1100.0, "b")]
    lifetime = [{"since": 900.0, "model": "a", "seconds": 200.0},
                {"since": 900.0, "model": "b", "seconds": 100.0}]
    pool = fake_pool(snaps, lifetime)
    result = queries.serving_percentages(pool, "h", 1200.0)
    assert set(result) == set(queries.SERVING_WINDOWS)
    assert result["lifetime"] == {"a": 66.7, "b": 33.3, "idle": 0.0}
    assert len(pool.calls) == 2
    bounded_sql, bounded_params = pool.calls[0]
    life_sql, life_params = pool.calls[1]
    assert "UNION ALL" in bounded_sql and "LIMIT 1" in bounded_sql and "left_boundary" in bounded_sql
    assert "LEAD(" in life_sql
    assert bounded_params == ("h", 1200.0 - 30 * queries.DAY_SECONDS, 1200.0, "h", 1200.0 - 30 * queries.DAY_SECONDS)
    assert life_params == ("h", 1200.0, 1200.0, 1200.0, 1200.0)
    assert result["1h"] == _window_shares(snaps, 3600, 1200.0)


def test_serving_percentages_lifetime_idle_when_the_aggregate_has_no_model_seconds(fake_pool):
    pool = fake_pool([], [{"since": 900.0, "model": None, "seconds": None}])
    result = queries.serving_percentages(pool, "h", 1200.0)
    assert result["lifetime"] == {"idle": 100.0}


def test_serving_percentages_lifetime_empty_when_the_aggregate_has_no_since(fake_pool):
    # Empty snaps: MIN(observed_at) is NULL, LEFT JOIN still yields one bounds row.
    pool = fake_pool([], [{"since": None, "model": None, "seconds": None}])
    assert queries.serving_percentages(pool, "h", 1200.0)["lifetime"] == {}


def _status_responses(daemon, demand, decisions, card_totals=None, hourly=None):
    """Canned rows in the order build_status queries them: daemon, demand,
    last-served, measured switch cost, earnings x2, bounded serving plus lifetime,
    decisions, earnings rows, unattributed recent hashes, the card's session
    payout totals, the hourly jobs buckets."""
    return [daemon, demand, [], [{"median": None, "n": 0}],
            [{"total": 2_500_000}], [{"total": 500_000}], [], [], decisions,
            [{"created_at": 9_000.0, "model": "a", "completion_tokens": 30, "micro_usd": 12}],
            [{"provider_hash": None}, {"provider_hash": "no-votes"}],
            card_totals or [{"tokens": 4_000, "requests": 2}],
            hourly or []]


def test_build_status_assembles_every_panel(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    daemon = {"current_model": "a", "fresh": True, "inference_active": False, "observed_at": 9_990.0}
    hourly = [{"hour": 7_200.0, "portion": 0, "model": "a", "n": 2}]
    attributed = {"s1": "m3", "s2": "other"}
    self_route = (None, {})
    pool = fake_pool(*_status_responses([daemon], [{"model": "a", "ema_score": 0.2}], [{"action": "KEEP"}],
                                        hourly=hourly))
    status = queries.build_status(
        SimpleNamespace(host_label="M3 label", host_id="m3", host_spec="M3 Max", live_execution=False,
                        switch_cost_seconds=300.0, daemon_freshness_seconds=90.0), pool, attributed, self_route)
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
    assert all("self_route_samples" not in sql for sql, _ in pool.calls)
    assert all("next_served >" not in sql for sql, _ in pool.calls)
    bounded_sql = [sql for sql, _ in pool.calls if "left_boundary" in sql]
    lifetime_sql = [sql for sql, _ in pool.calls if "LEAD(" in sql]
    assert len(bounded_sql) == 1 and len(lifetime_sql) == 1


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
                                                  switch_cost_seconds=300.0, daemon_freshness_seconds=90.0),
                                  pool, {}, (None, {}))
    assert status["current_model"] is None and status["mode"] == "LIVE"
    assert status["serving"]["1h"] == {"idle": 100.0} and status["demand"] == []
    assert status["card"]["status"]["state"] == "OFF" and status["card"]["kpis"]["tokens"] == 4_000


def test_shared_status_data_is_attribution_plus_self_route(fake_pool):
    pool = fake_pool(
        [{"payout_rowid": 1, "provider_hash": "s1", "host": "m3"}],
        [{"t": 100.0}],
        [{"model": "a", "routable_providers": 1}],
    )
    attributed, self_route = queries.shared_status_data(pool)
    assert attributed == {"s1": "m3"}
    assert self_route == (100.0, {"a": 1})
    assert len(pool.calls) == 3


def _host_cfg(hid):
    return SimpleNamespace(
        host_label=hid, host_id=hid, host_spec="?", live_execution=False, switch_cost_seconds=300.0,
        daemon_freshness_seconds=90.0)


def test_two_hosts_run_account_wide_sql_once(fake_pool, monkeypatch):
    _clock(monkeypatch, 10_000.0)
    host_block = _status_responses([], [], [])
    pool = fake_pool(
        [],
        [{"t": 1.0}],
        [{"model": "a", "routable_providers": 1}],
        *host_block,
        *host_block,
    )
    attributed, self_route = queries.shared_status_data(pool)
    queries.build_status(_host_cfg("m3"), pool, attributed, self_route)
    queries.build_status(_host_cfg("m1"), pool, attributed, self_route)
    vote_sql = [sql for sql, _ in pool.calls if "next_served >" in sql]
    route_sql = [sql for sql, _ in pool.calls if "self_route_samples" in sql]
    bounded_sql = [sql for sql, _ in pool.calls if "left_boundary" in sql]
    lifetime_sql = [sql for sql, _ in pool.calls if "LEAD(" in sql]
    assert len(vote_sql) == 1
    assert len(route_sql) == 2
    assert len(bounded_sql) == 2 and len(lifetime_sql) == 2
