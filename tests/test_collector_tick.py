"""run_tick and its helpers with every external call stubbed: no SSH, no
database, no network."""
import dataclasses
from types import SimpleNamespace

import pytest

from fleet import collector
from fleet.types import CapacitySample, DaemonState

DAEMON = DaemonState("a", ("a",), False, 1, 100.0, True)


def _cfg(**overrides) -> SimpleNamespace:
    base = {"host_id": "h", "base_url": "https://x", "pricing_url": "https://x/p", "models": ("a", "b"),
            "weights": {}, "ema_tau_minutes": 20.0, "poll_interval_seconds": 60.0, "relative_margin": 0.25,
            "absolute_margin": 0.01, "switch_cost_seconds": 300.0, "decision_horizon_seconds": 3600.0,
            "min_dwell_seconds": 1800.0, "live_execution": True, "restart_backoff_seconds": 30.0,
            "probe_self_route": False, "api_key": None, "dual_model_min_gb": 64.0}
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


def _live_daemon(**fields) -> DaemonState:
    return dataclasses.replace(DAEMON, trust_level="hardware", **fields)


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
    monkeypatch.setattr(collector, "_ingest_provider_identity", record("identity"))
    collector.run_tick(_cfg(live_execution=True), None)
    assert calls == ["snapshot", "probe", "earnings", "identity", "delete_ema", "save_ema", "samples"]


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
    collector.run_tick(_cfg(), None)
    assert calls == ["snapshot", "probe", "earnings", "delete_ema"]


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
    collector.run_tick(_cfg(), None)
    assert calls == []


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
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("b",))
    collector.run_tick(_cfg(), None)
    assert "a" not in store and "b" in store
    gone_score = store["b"]
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("a", "b"))
    collector.run_tick(_cfg(), None)
    assert saved[-1]["a"] == pytest.approx(0.1)
    assert gone_score != pytest.approx(0.9)
