from fleet import routability


def test_no_probe_yet(fake_pool):
    assert routability.latest_self_route(fake_pool([{"t": None}])) == (None, {})


def test_the_latest_probe_gives_counts_by_model(fake_pool):
    pool = fake_pool([{"t": 100.0}], [{"model": "a", "routable_providers": 1}, {"model": "b", "routable_providers": 0}])
    assert routability.latest_self_route(pool) == (100.0, {"a": 1, "b": 0})


def test_session_timing_in_minutes_from_the_daemon_start(fake_pool):
    pool = fake_pool([{"t": 1300.0}], [{"t": 1900.0}])
    assert routability.session_timing(pool, "h", 1000.0) == {
        "started_at": 1000.0, "any_host_routable_after_min": 5.0, "first_request_after_min": 15.0,
    }


def test_session_timing_before_anything_happened(fake_pool):
    timing = routability.session_timing(fake_pool([{"t": None}], []), "h", 1000.0)
    assert timing["any_host_routable_after_min"] is None and timing["first_request_after_min"] is None


def test_last_served_per_model(fake_pool):
    pool = fake_pool([{"model": "a", "t": 500.0}, {"model": "b", "t": 900.0}])
    assert routability.last_served(pool, "h") == {"a": 500.0, "b": 900.0}


def test_measured_switch_cost_is_the_median_over_serving_sessions(fake_pool):
    assert routability.measured_switch_cost(fake_pool([{"median": 312.4, "n": 7}]), "h") == (312.4, 7)


def test_measured_switch_cost_waits_for_three_serving_sessions(fake_pool):
    assert routability.measured_switch_cost(fake_pool([{"median": 240.0, "n": 2}]), "h") is None


def test_the_panel_merges_the_host_view_with_the_account_view(fake_pool):
    pool = fake_pool([{"t": 100.0}],
                     [{"model": "gemma-4-26b", "routable_providers": 1}, {"model": "gpt-oss-20b", "routable_providers": 3},
                      {"model": "other-model", "routable_providers": 2}],
                     [{"model": "gpt-oss-20b", "t": 90.0}, {"model": "old-model", "t": 20.0}],
                     [{"median": 312.4, "n": 7}], [{"t": 130.0}], [{"t": None}])
    daemon = {"advertised_models": ["gpt-oss-20b", "gemma-4-26b-qat-4bit"], "warm_models": ["gpt-oss-20b", "z-warm-only"],
              "started_at": 70.0, "trust_level": "self_signed", "trust_reason": "awaiting MDM verification"}
    panel = routability.routability_panel(pool, "h", daemon, 300.0)
    assert panel["self_route_as_of"] == 100.0 and panel["last_served_at"] == 90.0
    assert (panel["trust_level"], panel["trust_reason"]) == ("self_signed", "awaiting MDM verification")
    # The coordinator's short id (gemma-4-26b) folds into our advertised
    # gemma-4-26b-qat-4bit row; an id matching nothing keeps its own row.
    assert panel["models"] == [
        {"model": "gemma-4-26b-qat-4bit", "advertised": True, "warm": False, "routable_providers": 1, "last_served_at": None},
        {"model": "gpt-oss-20b", "advertised": True, "warm": True, "routable_providers": 3, "last_served_at": 90.0},
        {"model": "old-model", "advertised": False, "warm": False, "routable_providers": 0, "last_served_at": 20.0},
        {"model": "other-model", "advertised": False, "warm": False, "routable_providers": 2, "last_served_at": None},
        {"model": "z-warm-only", "advertised": False, "warm": True, "routable_providers": 0, "last_served_at": None},
    ]
    assert panel["session"] == {"started_at": 70.0, "any_host_routable_after_min": 1.0, "first_request_after_min": None}
    assert panel["switch_cost"] == {"configured_seconds": 300.0, "measured_seconds": 312.4, "measured_sessions": 7}


def test_the_panel_without_a_daemon_snapshot(fake_pool):
    panel = routability.routability_panel(fake_pool([{"t": None}], [], [{"median": None, "n": 0}]), "h", None, 300.0)
    assert panel == {"self_route_as_of": None, "trust_level": None, "trust_reason": None, "last_served_at": None,
                     "models": [], "session": None,
                     "switch_cost": {"configured_seconds": 300.0, "measured_seconds": None, "measured_sessions": 0}}
