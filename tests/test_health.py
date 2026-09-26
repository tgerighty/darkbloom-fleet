from fleet import health

NOW = 10_000.0
HOST = "h"


def _daemon(**fields):
    base = {"fresh": True, "trust_level": "hardware", "inference_active": False, "started_at": NOW - 600,
            "requests_served": 4, "advertised_models": ["a"], "warm_models": ["a"], "observed_at": NOW - 10}
    base.update(fields)
    return base


def _check(pool, daemon):
    return health.host_health(pool, HOST, daemon, NOW)


def _snap(t, warm=("a",), active=False, served=1):
    return {"observed_at": t, "warm_models": list(warm), "inference_active": active, "requests_served": served}


def _flips(n):
    return [_snap(NOW - 600 + 60 * i, warm=(f"m{i}",)) for i in range(n + 1)]


def test_fresh_and_serving_is_healthy(fake_pool):
    got = _check(fake_pool([]), _daemon())
    assert got == {"state": health.HEALTHY, "since": NOW - 10,
                   "detail": "The daemon is fresh and no fault is detected."}


def test_fresh_snapshot_at_configured_age_limit_is_healthy(fake_pool):
    got = _check(fake_pool([]), _daemon(observed_at=NOW - 90))
    assert got["state"] == health.HEALTHY


def test_stale_one_minute_is_stale(fake_pool):
    got = _check(fake_pool([{"last_fresh": NOW - 60, "first_seen": NOW - 1000}], []), _daemon(fresh=False))
    assert got["state"] == health.STALE and got["since"] == NOW - 60


def test_stale_three_minutes_is_daemon_down(fake_pool):
    got = _check(fake_pool([{"last_fresh": NOW - 180, "first_seen": NOW - 1000}]), _daemon(fresh=False))
    assert got["state"] == health.DAEMON_DOWN and got["since"] == NOW - 180


def test_old_snapshot_marked_fresh_is_daemon_down(fake_pool):
    got = _check(fake_pool([{"last_fresh": NOW - 180, "first_seen": NOW - 1000}]),
                 _daemon(observed_at=NOW - 180))
    assert got["state"] == health.DAEMON_DOWN and got["since"] == NOW - 180


def test_dead_session(fake_pool):
    started = NOW - 31 * 60
    pool = fake_pool([{"n": 2, "other_served": True}])
    got = _check(pool, _daemon(started_at=started, requests_served=0))
    assert got["state"] == health.DEAD_SESSION and got["since"] == started
    assert "31 minutes old" in got["detail"]
    assert pool.calls[0][1] == (HOST, started, ["a"], HOST, started)


def test_zero_demand_is_healthy(fake_pool):
    got = _check(fake_pool([{"n": 0, "other_served": True}], []),
                 _daemon(started_at=NOW - 31 * 60, requests_served=0))
    assert got["state"] == health.HEALTHY


def test_seven_warm_flips_is_thrash(fake_pool):
    rows = _flips(7)
    got = _check(fake_pool(rows), _daemon())
    assert got["state"] == health.THRASH and got["since"] == rows[7]["observed_at"]
    assert "changed 7 times" in got["detail"]


def test_frozen_inference_is_thrash(fake_pool):
    rows = [_snap(NOW - 360, active=True, served=2), _snap(NOW - 60, active=True, served=2)]
    got = _check(fake_pool(rows), _daemon())
    assert got["state"] == health.THRASH and got["since"] == NOW - 360


def test_no_daemon_snapshot_is_stale(fake_pool):
    got = _check(fake_pool(), None)
    assert got == {"state": health.STALE, "since": NOW, "detail": "No daemon snapshot is available."}


def test_never_fresh_uses_first_seen(fake_pool):
    down = _check(fake_pool([{"last_fresh": None, "first_seen": NOW - 180}]), _daemon(fresh=False))
    assert down["state"] == health.DAEMON_DOWN and down["since"] == NOW - 180
    brief = _check(fake_pool([{"last_fresh": None, "first_seen": NOW - 60}], []), _daemon(fresh=False))
    assert brief["state"] == health.STALE and brief["since"] == NOW - 60


def test_empty_stale_row_is_stale(fake_pool):
    got = _check(fake_pool([], []), _daemon(fresh=False))
    assert got["state"] == health.STALE and got["since"] == NOW


def test_dead_session_skips_without_hardware_age_or_models(fake_pool):
    started = NOW - 31 * 60
    snaps = [_daemon(trust_level="self_signed", started_at=started, requests_served=0),
             _daemon(started_at=0, requests_served=0),
             _daemon(started_at=started, requests_served=0, advertised_models=[]),
             _daemon(started_at=NOW - health.SESSION_AGE, requests_served=0),
             _daemon(started_at=started, requests_served=1)]
    for snap in snaps:
        assert _check(fake_pool([]), snap)["state"] == health.HEALTHY


def test_other_host_idle_is_healthy(fake_pool):
    got = _check(fake_pool([{"n": 3, "other_served": False}], []),
                 _daemon(started_at=NOW - 31 * 60, requests_served=0))
    assert got["state"] == health.HEALTHY


def test_missing_dead_signal_row_is_healthy(fake_pool):
    got = _check(fake_pool([], []), _daemon(started_at=NOW - 31 * 60, requests_served=0))
    assert got["state"] == health.HEALTHY


def test_six_warm_flips_is_healthy(fake_pool):
    assert _check(fake_pool(_flips(6)), _daemon())["state"] == health.HEALTHY


def test_thrash_beats_brief_stale(fake_pool):
    got = _check(fake_pool([{"last_fresh": NOW - 60, "first_seen": 1.0}], _flips(7)), _daemon(fresh=False))
    assert got["state"] == health.THRASH


def test_a_completed_frozen_streak_is_thrash(fake_pool):
    rows = [_snap(NOW - 400, active=True, served=2), _snap(NOW - 50, active=True, served=2),
            _snap(NOW - 10, active=False, served=2)]
    assert _check(fake_pool(rows), _daemon())["state"] == health.THRASH


def test_a_rising_counter_is_not_thrash(fake_pool):
    rows = [_snap(NOW - 360, active=True, served=1), _snap(NOW - 60, active=True, served=2)]
    assert _check(fake_pool(rows), _daemon())["state"] == health.HEALTHY


def test_idle_breaks_a_frozen_streak(fake_pool):
    rows = [_snap(NOW - 360, active=True, served=1), _snap(NOW - 240, active=False, served=1),
            _snap(NOW - 10, active=True, served=1)]
    assert _check(fake_pool(rows), _daemon())["state"] == health.HEALTHY


def test_stable_warm_set_and_missing_fields_are_healthy(fake_pool):
    rows = [_snap(NOW - 120), _snap(NOW - 60),
            {"observed_at": NOW - 10, "warm_models": None, "inference_active": False}]
    daemon = _daemon()
    del daemon["observed_at"]
    got = _check(fake_pool(rows), daemon)
    assert got["state"] == health.HEALTHY and got["since"] == NOW
