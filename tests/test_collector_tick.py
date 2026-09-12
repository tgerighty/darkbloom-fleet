"""run_tick and its helpers with every external call stubbed: no SSH, no
database, no network."""
from types import SimpleNamespace

import pytest

from fleet import collector
from fleet.types import CapacitySample, DaemonState, Decision

DAEMON = DaemonState("a", ("a",), False, 1, 100.0, True)


def _cfg(**overrides) -> SimpleNamespace:
    base = {"host_label": "h", "base_url": "https://x", "pricing_url": "https://x/p", "models": ("a", "b"),
            "weights": {}, "ema_tau_minutes": 20.0, "poll_interval_seconds": 60.0, "relative_margin": 0.25,
            "absolute_margin": 0.01, "switch_cost_seconds": 300.0, "decision_horizon_seconds": 3600.0,
            "min_dwell_seconds": 1800.0, "live_execution": True, "restart_backoff_seconds": 30.0,
            "probe_self_route": False, "api_key": None}
    base.update(overrides)
    return SimpleNamespace(**base)


def _boom(*_args, **_kwargs):
    raise RuntimeError("down")


def test_fetch_daemon_returns_the_state_or_none(monkeypatch):
    monkeypatch.setattr(collector.remote, "fetch_daemon_state", lambda cfg, now: DAEMON)
    assert collector._fetch_daemon(_cfg(), 0.0) == DAEMON
    monkeypatch.setattr(collector.remote, "fetch_daemon_state", _boom)
    assert collector._fetch_daemon(_cfg(), 0.0) is None


def test_fetch_scores_keeps_configured_models_and_survives_feed_failures(monkeypatch):
    samples = {"a": CapacitySample("a", 2, 1, 2.0), "zzz": CapacitySample("zzz", 1, 1, 1.0)}
    monkeypatch.setattr(collector.demand, "fetch_capacity", lambda url: samples)
    monkeypatch.setattr(collector.demand, "fetch_output_prices", lambda url: ({"a": 0.1}, 0.2))
    assert collector._fetch_scores(_cfg()) == ({"a": samples["a"]}, {"a": 0.1, "b": 0.2})
    monkeypatch.setattr(collector.demand, "fetch_capacity", _boom)
    monkeypatch.setattr(collector.demand, "fetch_output_prices", _boom)
    assert collector._fetch_scores(_cfg()) == ({}, {})


def test_ingest_earnings_stores_new_payouts_and_skips_an_unreachable_ledger(monkeypatch):
    stored = []
    monkeypatch.setattr(collector.db, "last_payout_rowid", lambda pool, host: 5)
    monkeypatch.setattr(collector.db, "insert_payouts", lambda pool, host, payouts, now: stored.append(payouts))
    monkeypatch.setattr(collector.remote, "fetch_new_payouts", lambda cfg, since: ["p6"])
    collector._ingest_earnings(_cfg(), None, 1.0)
    monkeypatch.setattr(collector.remote, "fetch_new_payouts", _boom)
    collector._ingest_earnings(_cfg(), None, 1.0)
    assert stored == [["p6"]]


def test_the_probe_runs_only_on_the_probing_host_with_a_key(monkeypatch):
    stored = []
    monkeypatch.setattr(collector.demand, "fetch_self_route", lambda url, key: {"gpt-oss-20b": 1})
    monkeypatch.setattr(collector.db, "insert_self_route_samples", lambda pool, now, counts: stored.append(counts))
    collector._probe_self_route(_cfg(api_key="k"), None, 1.0)
    collector._probe_self_route(_cfg(probe_self_route=True), None, 1.0)
    collector._probe_self_route(_cfg(probe_self_route=True, api_key="k"), None, 1.0)
    assert stored == [{"gpt-oss-20b": 1}]


def test_a_failed_probe_is_logged_not_stored(monkeypatch, caplog):
    monkeypatch.setattr(collector.demand, "fetch_self_route", _boom)
    monkeypatch.setattr(collector.db, "insert_self_route_samples", _boom)
    collector._probe_self_route(_cfg(probe_self_route=True, api_key="k"), None, 1.0)
    assert "self-route probe unavailable" in caplog.text


def test_decide_anchors_dwell_on_the_daemon_start(monkeypatch):
    anchors = []
    monkeypatch.setattr(collector.db, "dwell_anchor", lambda pool, host, started: anchors.append(started) or started)
    result = collector._decide(_cfg(), None, {"a": 1.0, "b": 1.05}, DAEMON, 10_000.0)
    assert result.action == "KEEP" and anchors == [100.0]


@pytest.mark.parametrize("daemon", [None, DaemonState("a", ("a",), False, 1, 100.0, False)])
def test_decide_waits_without_a_fresh_daemon_read(daemon):
    assert collector._decide(_cfg(), None, {"a": 1.0, "b": 9.0}, daemon, 10_000.0).action == "WAIT"


@pytest.mark.parametrize(("action", "live"), [("KEEP", True), ("SWITCH", False)])
def test_maybe_execute_does_nothing_unless_a_live_switch_is_due(action, live):
    assert collector._maybe_execute(_cfg(live_execution=live), None, Decision("b", "r", action), 0.0) == (False, None)


def test_maybe_execute_respects_the_restart_backoff(monkeypatch):
    monkeypatch.setattr(collector.db, "last_failed_switch_at", lambda pool, host: 90.0)
    executed, error = collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0)
    assert executed is False and "backoff" in error


def test_maybe_execute_aborts_when_the_provider_is_busy_again(monkeypatch):
    monkeypatch.setattr(collector.db, "last_failed_switch_at", lambda pool, host: 0.0)
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DaemonState("a", ("a",), True, 1, 0.0, True))
    executed, error = collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0)
    assert executed is False and "aborted" in error


def test_maybe_execute_reports_success_and_failure(monkeypatch):
    monkeypatch.setattr(collector.db, "last_failed_switch_at", lambda pool, host: 0.0)
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector.remote, "execute_switch", lambda cfg, target: None)
    assert collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0) == (True, None)
    monkeypatch.setattr(collector.remote, "execute_switch", _boom)
    assert collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0) == (False, "down")


def test_a_failing_watcher_launch_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(collector.remote, "launch_fast_switch_watcher", _boom)
    collector._maybe_launch_fast_poll(_cfg(), Decision("b", "r", "SWITCH_WHEN_IDLE"))
    assert "fast-poll watcher control failed" in caplog.text


def test_run_tick_feeds_one_pass_through_every_stage(monkeypatch):
    calls = []

    def record(name):
        return lambda *args, **kwargs: calls.append(name)

    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot", record("snapshot"))
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: ({"a": CapacitySample("a", 2, 1, 2.0)}, {"a": 0.1}))
    monkeypatch.setattr(collector.db, "load_ema", lambda pool, host: ({"a": 0.1}, 50.0))
    monkeypatch.setattr(collector.db, "save_ema", record("save_ema"))
    monkeypatch.setattr(collector.db, "insert_demand_samples", record("samples"))
    monkeypatch.setattr(collector, "_ingest_earnings", record("earnings"))
    monkeypatch.setattr(collector, "_decide", lambda cfg, pool, ema, daemon, now: Decision("a", "keep", "KEEP"))
    monkeypatch.setattr(collector, "_record_and_act", lambda cfg, pool, result, current, now: calls.append(("act", current)))
    collector.run_tick(_cfg(), None)
    assert calls == ["snapshot", "save_ema", "samples", "earnings", ("act", "a")]
