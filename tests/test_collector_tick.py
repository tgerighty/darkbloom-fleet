"""run_tick and its helpers with every external call stubbed: no SSH, no
database, no network."""
import dataclasses
from types import SimpleNamespace

import pytest

from fleet import collector
from fleet.types import CapacitySample, DaemonState, Decision

DAEMON = DaemonState("a", ("a",), False, 1, 100.0, True)


def _cfg(**overrides) -> SimpleNamespace:
    base = {"host_id": "h", "base_url": "https://x", "pricing_url": "https://x/p", "models": ("a", "b"),
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
    monkeypatch.setattr(collector.routability, "measured_switch_cost", lambda pool, host: None)
    result = collector._decide(_cfg(), None, {"a": 1.0, "b": 1.05}, DAEMON, 10_000.0)
    assert result.action == "KEEP" and anchors == [100.0]


def _capture_guardrails(monkeypatch):
    seen = []
    monkeypatch.setattr(collector.decision_mod, "decide",
                        lambda *args: seen.append(args[-1]) or Decision("a", "r", "KEEP"))
    return seen


def test_decide_swaps_the_measured_switch_cost_in(monkeypatch):
    monkeypatch.setattr(collector.db, "dwell_anchor", lambda pool, host, started: started)
    monkeypatch.setattr(collector.routability, "measured_switch_cost", lambda pool, host: (312.0, 7))
    seen = _capture_guardrails(monkeypatch)
    collector._decide(_cfg(), None, {"a": 1.0}, DAEMON, 10_000.0)
    assert seen[0].switch_cost_seconds == 312.0


def test_decide_falls_back_to_the_configured_switch_cost(monkeypatch):
    monkeypatch.setattr(collector.db, "dwell_anchor", lambda pool, host, started: started)
    monkeypatch.setattr(collector.routability, "measured_switch_cost", lambda pool, host: None)
    seen = _capture_guardrails(monkeypatch)
    collector._decide(_cfg(switch_cost_seconds=240.0), None, {"a": 1.0}, DAEMON, 10_000.0)
    assert seen[0].switch_cost_seconds == 240.0


@pytest.mark.parametrize("daemon", [None, DaemonState("a", ("a",), False, 1, 100.0, False)])
def test_decide_waits_without_a_fresh_daemon_read(daemon):
    assert collector._decide(_cfg(), None, {"a": 1.0, "b": 9.0}, daemon, 10_000.0).action == "WAIT"


def _would_switch(monkeypatch):
    monkeypatch.setattr(collector.db, "dwell_anchor", lambda pool, host, started: 0.0)
    monkeypatch.setattr(collector.routability, "measured_switch_cost", lambda pool, host: None)
    return {"a": 1.0, "b": 2.0}


@pytest.mark.parametrize("live", [False, True])
def test_thermal_gate_is_the_same_in_observe_and_live(monkeypatch, live):
    ema = _would_switch(monkeypatch)
    daemon = DaemonState("a", ("a",), False, 1, 100.0, True, thermal_state="critical")
    result = collector._decide(_cfg(live_execution=live), None, ema, daemon, 10_000.0)
    assert result.action == "BLOCKED" and "critical" in result.reason


def test_trust_and_load_error_gates_run_in_the_shared_decide_path(monkeypatch):
    ema = _would_switch(monkeypatch)
    attest = DaemonState("a", ("a",), False, 1, 100.0, True, trust_level="self_signed")
    keep = collector._decide(_cfg(), None, ema, attest, 10_000.0)
    assert keep.action == "KEEP" and keep.target == "a"
    recent = DaemonState("a", ("a",), False, 1, 100.0, True, trust_level="hardware",
                         last_model_load_error_model="b", last_model_load_error_at=9_990.0)
    blocked = collector._decide(_cfg(), None, ema, recent, 10_000.0)
    assert blocked.action == "BLOCKED" and blocked.target == "b"


@pytest.mark.parametrize(("action", "live"), [("KEEP", True), ("SWITCH", False), ("BLOCKED", True)])
def test_maybe_execute_does_nothing_unless_a_live_switch_is_due(action, live):
    assert collector._maybe_execute(_cfg(live_execution=live), None, Decision("b", "r", action), 0.0) == (False, None)


def test_maybe_execute_aborts_when_the_provider_is_busy_again(monkeypatch):
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DaemonState("a", ("a",), True, 1, 0.0, True))
    executed, error = collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0)
    assert executed is False and "aborted" in error


def _live_daemon(**fields) -> DaemonState:
    return dataclasses.replace(DAEMON, trust_level="hardware", **fields)


def test_maybe_execute_reports_success_and_failure(monkeypatch, caplog):
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: _live_daemon())
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("a", "b"))
    monkeypatch.setattr(collector.remote, "execute_switch", lambda cfg, target: None)
    assert collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0) == (True, None)
    monkeypatch.setattr(collector.remote, "execute_switch", _boom)
    assert collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0) == (False, "switch failed")
    assert "down" in caplog.text


def test_maybe_execute_reapplies_host_gates_on_the_fresh_read(monkeypatch):
    hot = _live_daemon(thermal_state="critical")
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: hot)
    monkeypatch.setattr(collector.remote, "execute_switch", _boom)
    executed, error = collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0)
    assert executed is False and "aborted" in error and "safety gate" in error
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    executed, error = collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0)
    assert executed is False and "safety gate" in error


def test_unknown_inventory_on_the_tick_keeps_current_instead_of_switching(monkeypatch):
    ema = _would_switch(monkeypatch)
    daemon = _live_daemon(installed_models=None)
    result = collector._decide(_cfg(), None, ema, daemon, 10_000.0)
    assert result.action == "KEEP" and result.target == "a"
    assert "inventory unknown" in result.reason


def test_a_failing_watcher_launch_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(collector.remote, "launch_fast_switch_watcher", _boom)
    collector._maybe_launch_fast_poll(_cfg(), Decision("b", "r", "SWITCH_WHEN_IDLE"))
    assert "fast-poll watcher control failed" in caplog.text


def test_run_tick_feeds_one_pass_through_every_stage(monkeypatch):
    calls = []

    def record(name):
        return lambda *args, **kwargs: calls.append(name)

    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: None)
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot", record("snapshot"))
    monkeypatch.setattr(collector.db, "update_snapshot_installed_models", record("installed"))
    monkeypatch.setattr(collector.db, "delete_ineligible_ema", record("delete_ema"))
    monkeypatch.setattr(collector, "_probe_self_route", record("probe"))
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: ({"a": CapacitySample("a", 2, 1, 2.0)}, {"a": 0.1}))
    monkeypatch.setattr(collector.db, "load_ema", lambda pool, host: ({"a": 0.1}, 50.0))
    monkeypatch.setattr(collector.db, "save_ema", record("save_ema"))
    monkeypatch.setattr(collector.db, "insert_demand_samples", record("samples"))
    monkeypatch.setattr(collector, "_ingest_earnings", record("earnings"))
    monkeypatch.setattr(collector, "_decide", lambda cfg, pool, ema, daemon, now: Decision("a", "keep", "KEEP"))
    monkeypatch.setattr(collector, "_record_and_act", lambda cfg, pool, result, current, now: calls.append(("act", current)))
    collector.run_tick(_cfg(), None)
    assert calls == ["snapshot", "probe", "earnings", "delete_ema", "save_ema", "samples", ("act", "a")]


def test_run_tick_keys_rows_by_host_id_and_drops_retired_models_from_the_restored_ema(monkeypatch):
    stored = {}

    def fake_load_ema(pool, host):
        stored["load_host"] = host
        return {"a": 0.1, "gone": 9.0}, 50.0

    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: None)
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot", lambda *args: None)
    monkeypatch.setattr(collector.db, "update_snapshot_installed_models", lambda *args: None)
    monkeypatch.setattr(collector.db, "delete_ineligible_ema", lambda *args: None)
    monkeypatch.setattr(collector, "_probe_self_route", lambda *args: None)
    monkeypatch.setattr(collector, "_ingest_earnings", lambda *args: None)
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: ({"a": CapacitySample("a", 2, 1, 2.0)}, {"a": 0.1}))
    monkeypatch.setattr(collector.db, "load_ema", fake_load_ema)
    monkeypatch.setattr(collector.db, "save_ema", lambda pool, host, ema, now: stored.setdefault("ema", ema))
    monkeypatch.setattr(collector.db, "insert_demand_samples", lambda *args: None)
    monkeypatch.setattr(collector, "_decide", lambda cfg, pool, ema, daemon, now: Decision("a", "keep", "KEEP"))
    monkeypatch.setattr(collector, "_record_and_act", lambda *args: None)
    collector.run_tick(_cfg(host_label="pretty-label"), None)
    assert stored["load_host"] == "h"  # the id, not the display label, keys the row
    assert "gone" not in stored["ema"] and "a" in stored["ema"]


def test_run_tick_waits_and_leaves_the_ema_untouched_when_no_model_is_scored(monkeypatch):
    calls = []

    def record(name):
        return lambda *args, **kwargs: calls.append(name)

    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: None)
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot", record("snapshot"))
    monkeypatch.setattr(collector.db, "update_snapshot_installed_models", record("installed"))
    monkeypatch.setattr(collector.db, "delete_ineligible_ema", record("delete_ema"))
    monkeypatch.setattr(collector, "_probe_self_route", record("probe"))
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: ({}, {}))
    monkeypatch.setattr(collector.db, "load_ema", record("load_ema"))
    monkeypatch.setattr(collector.db, "save_ema", record("save_ema"))
    monkeypatch.setattr(collector.db, "insert_demand_samples", record("samples"))
    monkeypatch.setattr(collector, "_ingest_earnings", record("earnings"))
    monkeypatch.setattr(collector, "_record_and_act", lambda cfg, pool, result, current, now: calls.append(("act", current, result)))
    collector.run_tick(_cfg(), None)
    assert calls == ["snapshot", "probe", "earnings", "delete_ema",
                     ("act", "a", Decision(None, "demand feeds unavailable", "WAIT"))]


def test_run_tick_skips_inventory_when_the_daemon_read_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: None)
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: calls.append("inventory") or ("a",))
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot", lambda *args: calls.append("snapshot"))
    monkeypatch.setattr(collector.db, "update_snapshot_installed_models", lambda *args: calls.append("update"))
    monkeypatch.setattr(collector.db, "delete_ineligible_ema", lambda *args: None)
    monkeypatch.setattr(collector, "_probe_self_route", lambda *args: None)
    monkeypatch.setattr(collector, "_ingest_earnings", lambda *args: None)
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: ({}, {}))
    monkeypatch.setattr(collector, "_record_and_act", lambda *args: calls.append("act"))
    collector.run_tick(_cfg(), None)
    assert calls == ["act"]


def test_run_tick_inserts_the_daemon_before_inventory_then_updates_it(monkeypatch):
    calls = []

    def fetch_installed(cfg):
        calls.append("inventory")
        return ("a",)

    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector, "_fetch_installed", fetch_installed)
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot",
                        lambda pool, host, now, daemon: calls.append(("snapshot", daemon.installed_models)))
    monkeypatch.setattr(collector.db, "update_snapshot_installed_models",
                        lambda pool, host, now, installed: calls.append(("update", installed)))
    monkeypatch.setattr(collector.db, "delete_ineligible_ema", lambda *args: None)
    monkeypatch.setattr(collector, "_probe_self_route", lambda *args: None)
    monkeypatch.setattr(collector, "_ingest_earnings", lambda *args: None)
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: ({}, {}))
    monkeypatch.setattr(collector, "_record_and_act", lambda *args: None)
    collector.run_tick(_cfg(), None)
    assert calls[:3] == [("snapshot", None), "inventory", ("update", ("a",))]


def test_stale_ema_cannot_win_after_a_model_disappears_and_returns(monkeypatch):
    store = {"a": 0.9, "b": 0.3}
    saved = []

    def load_ema(pool, host):
        return dict(store), 50.0

    def save_ema(pool, host, ema, now):
        store.clear()
        store.update(ema)
        saved.append(dict(ema))

    def delete_ineligible(pool, host, eligible):
        for model in list(store):
            if model not in eligible:
                del store[model]

    samples = {"a": CapacitySample("a", 1, 1, 1.0), "b": CapacitySample("b", 1, 1, 1.0)}
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot", lambda *args: None)
    monkeypatch.setattr(collector.db, "update_snapshot_installed_models", lambda *args: None)
    monkeypatch.setattr(collector.db, "delete_ineligible_ema", delete_ineligible)
    monkeypatch.setattr(collector, "_probe_self_route", lambda *args: None)
    monkeypatch.setattr(collector, "_ingest_earnings", lambda *args: None)
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: (samples, {"a": 0.1, "b": 0.1}))
    monkeypatch.setattr(collector.db, "load_ema", load_ema)
    monkeypatch.setattr(collector.db, "save_ema", save_ema)
    monkeypatch.setattr(collector.db, "insert_demand_samples", lambda *args: None)
    monkeypatch.setattr(collector, "_decide", lambda cfg, pool, ema, daemon, now: Decision("b", "keep", "KEEP"))
    monkeypatch.setattr(collector, "_record_and_act", lambda *args: None)
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("b",))
    collector.run_tick(_cfg(), None)
    assert "a" not in store and "b" in store
    gone_score = store["b"]
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("a", "b"))
    collector.run_tick(_cfg(), None)
    assert saved[-1]["a"] == pytest.approx(0.1)
    assert gone_score != pytest.approx(0.9)
