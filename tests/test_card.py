from fleet import card

FRESHNESS = 90.0


def _card(pool, daemon, last=None, hashes=None, now=1_000.0):
    return card.build_card(pool, "h", daemon, last, hashes or [], now, FRESHNESS)


def _daemon(**fields):
    base = {"fresh": True, "trust_level": "hardware", "inference_active": False, "started_at": 100.0}
    base.update(fields)
    return base


def test_off_without_a_snapshot(fake_pool):
    built = _card(fake_pool([{"tokens": 0, "requests": 0}]), None)
    assert built["status"]["state"] == "OFF" and built["status"]["tone"] == "red"
    assert built["loaded"] == [] and built["catalog"] == [] and built["slots"] == []
    assert built["kpis"]["started_at"] is None and built["kpis"]["tokens"] == 0


def test_stale_beats_trust_and_traffic(fake_pool):
    built = _card(fake_pool([{"tokens": 0, "requests": 0}]),
                  _daemon(fresh=False, inference_active=True))
    assert (built["status"]["state"], built["status"]["tone"]) == ("STALE", "red")


def test_earning_with_hardware_trust_and_traffic_now(fake_pool):
    built = _card(fake_pool([{"tokens": 0, "requests": 0}]), _daemon(inference_active=True))
    assert (built["status"]["state"], built["status"]["tone"]) == ("EARNING", "green")
    assert built["status"]["detail"] == "Full routing priority — no action needed."


def test_earning_from_a_request_within_the_last_ten_minutes(fake_pool):
    built = _card(fake_pool([{"tokens": 0, "requests": 0}]), _daemon(), last=9_400.0, now=10_000.0)
    assert built["status"]["state"] == "EARNING" and built["kpis"]["last_served_at"] == 9_400.0
    older = _card(fake_pool([{"tokens": 0, "requests": 0}]), _daemon(), last=8_999.0, now=10_000.0)
    assert older["status"]["state"] == "TRUSTED"  # just past the 10-minute window


def test_attesting_when_trust_is_not_hardware(fake_pool):
    built = _card(fake_pool([{"tokens": 0, "requests": 0}]),
                  _daemon(trust_level="self_signed", trust_reason="awaiting MDM verification"))
    assert (built["status"]["state"], built["status"]["tone"]) == ("ATTESTING", "amber")
    assert "hardware trust" in built["status"]["detail"]


def test_gpu_peak_counts_the_cache_on_top_of_active(fake_pool):
    built = _card(fake_pool([{"tokens": 0, "requests": 0}]),
                  _daemon(gpu_active_gb=14.8, gpu_cache_gb=1.2, total_memory_gb=64.0))
    assert built["gpu"] == {"active_gb": 14.8, "cache_gb": 1.2, "total_gb": 64.0, "peak_gb": 16.0}
    empty = _card(fake_pool([{"tokens": 0, "requests": 0}]), _daemon())
    assert empty["gpu"] == {"active_gb": None, "cache_gb": None, "total_gb": None, "peak_gb": None}


def test_loaded_marks_only_the_current_model_while_serving(fake_pool):
    quiet = _card(fake_pool([{"tokens": 0, "requests": 0}]),
                  _daemon(warm_models=["a", "b"], current_model="a"))
    assert quiet["loaded"] == [{"model": "a", "active": False}, {"model": "b", "active": False}]
    busy = _card(fake_pool([{"tokens": 0, "requests": 0}]),
                 _daemon(warm_models=["a", "b"], current_model="a", inference_active=True))
    assert busy["loaded"] == [{"model": "a", "active": True}, {"model": "b", "active": False}]


def test_the_card_assembles_resources_kpis_and_slots(fake_pool):
    slots = [{"model": "a", "kv_backend": "paged", "mtp_enabled": True, "mtp_active": True, "mtp_inactive_reason": None}]
    snapshot = _daemon(warm_models=["a"], current_model="a", advertised_models=["a", "b"],
                       requests_served=12, thermal_state="nominal", memory_pressure=0.41, cpu_usage=0.12,
                       slots=slots)
    built = _card(fake_pool([{"tokens": 4_000, "requests": 7}]), snapshot, last=9_950.0, hashes=["s1"], now=10_000.0)
    assert built["resources"] == {"thermal_state": "nominal", "memory_pressure": 0.41, "cpu_usage": 0.12}
    assert built["catalog"] == ["a", "b"] and built["slots"] == slots
    assert built["kpis"] == {"requests": 12, "tokens": 4_000, "token_requests": 7,
                             "started_at": 100.0, "last_served_at": 9_950.0}
    assert built["last_model_load_error"] is None


def test_the_card_surfaces_a_recent_load_error(fake_pool):
    snapshot = _daemon(last_model_load_error_model="b", last_model_load_error_message="oom",
                       last_model_load_error_at=9_950.0)
    built = _card(fake_pool([{"tokens": 0, "requests": 0}]), snapshot, now=10_000.0)
    assert built["last_model_load_error"] == {
        "model": "b", "message": "oom", "at": 9_950.0, "recent": True,
    }
    old = _card(fake_pool([{"tokens": 0, "requests": 0}]),
                _daemon(last_model_load_error_model="b", last_model_load_error_message="oom",
                        last_model_load_error_at=9_000.0), now=10_000.0)
    assert old["last_model_load_error"]["recent"] is False
    assert old["last_model_load_error"]["at"] == 9_000.0


def test_session_totals_filters_by_window_and_attributed_sessions(fake_pool):
    pool = fake_pool([{"tokens": 4_000, "requests": 7}])
    assert card.session_totals(pool, 100.0, 1_000.0, ["s1"]) == {"tokens": 4_000, "requests": 7}
    sql, params = pool.calls[0]
    assert "DISTINCT ON (payout_rowid)" in sql
    assert "host = %s" not in sql
    assert "created_at <= %s" in sql
    assert params == (100.0, 1_000.0, ["s1"])


def test_an_aged_fresh_snapshot_is_stale(fake_pool):
    pool = fake_pool([{"tokens": 0, "requests": 0}])
    aged = card.build_card(pool, "h", _daemon(fresh=True, observed_at=1_000.0, inference_active=True),
                           None, [], 1_000.0 + FRESHNESS + 0.001, FRESHNESS)
    assert aged["status"]["state"] == "STALE"
    current = _card(fake_pool([{"tokens": 0, "requests": 0}]),
                    _daemon(fresh=True, observed_at=1_000.0, inference_active=True), now=1_000.0 + FRESHNESS)
    assert current["status"]["state"] == "EARNING"
