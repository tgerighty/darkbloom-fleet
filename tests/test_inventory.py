"""Read-only on-disk inventory: JSON parse, eligibility, and tick behaviour."""
import json
import logging

from fleet import collector, remote
from fleet.types import CapacitySample, DaemonState, Decision
from tests.test_collector_tick import _boom, _live_daemon

DAEMON = DaemonState("a", ("a",), False, 1, 100.0, True)


def _cfg():
    from tests.test_collector_tick import _cfg as make_cfg
    return make_cfg()


def test_parse_keeps_non_empty_string_ids_in_first_seen_order():
    raw = (
        '{"cacheDirectory": "/x", "filteredByConfig": true, "models": ['
        '{"id": "a", "size_bytes": 1}, {"id": "b"}, {"id": "a"}]}'
    )
    assert remote._parse_installed_model_ids(raw) == ("a", "b")


def test_parse_treats_a_malformed_item_as_unknown():
    raw = '{"models": [{"id": "a"}, {"id": ""}, {"id": "b"}]}'
    assert remote._parse_installed_model_ids(raw) is None
    assert remote._parse_installed_model_ids('{"models": [{"id": "a"}, "skip"]}') is None
    assert remote._parse_installed_model_ids('{"models": [{"name": "x"}]}') is None


def test_parse_treats_an_oversize_id_or_list_as_unknown():
    too_long = "m" * (remote._MAX_MODEL_ID_LENGTH + 1)
    assert remote._parse_installed_model_ids('{"models": [{"id": "' + too_long + '"}]}') is None
    too_many = [{"id": f"m{i}"} for i in range(remote._MAX_INSTALLED_MODELS + 1)]
    assert remote._parse_installed_model_ids(json.dumps({"models": too_many})) is None
    limit = [{"id": f"m{i}"} for i in range(remote._MAX_INSTALLED_MODELS)]
    assert remote._parse_installed_model_ids(json.dumps({"models": limit})) == tuple(
        f"m{i}" for i in range(remote._MAX_INSTALLED_MODELS))


def test_parse_treats_malformed_json_or_shape_as_unknown():
    for raw in ("", "not json", "null", "[]", '{"models": null}', '{"models": {}}',
                '{"cacheDirectory": "/x"}'):
        assert remote._parse_installed_model_ids(raw) is None


def test_parse_empty_models_list_is_authoritative_empty():
    assert remote._parse_installed_model_ids('{"models": []}') == ()


def test_eligible_models_intersect_the_allow_list_and_never_enrol_disk_only():
    assert collector._eligible_models(("a", "b"), None) == frozenset({"a", "b"})
    assert collector._eligible_models(("a", "b"), ()) == frozenset()
    assert collector._eligible_models(("a", "b"), ("b", "disk-only")) == frozenset({"b"})
    assert collector._eligible_models(("a", "b"), ("disk-only",)) == frozenset()


def _stub_tick(monkeypatch, stored, *, installed, samples=None, prices=None, ema_prev=None):
    samples = samples if samples is not None else {
        "a": CapacitySample("a", 2, 1, 2.0), "b": CapacitySample("b", 1, 1, 1.0),
    }
    prices = prices if prices is not None else {"a": 0.1, "b": 0.1}
    ema_prev = ema_prev if ema_prev is not None else {"a": 0.1, "b": 9.0}

    def save_ema(pool, host, ema, now):
        stored["ema"] = ema

    def load_ema(pool, host):
        stored["loaded"] = True
        return ema_prev, 50.0

    def act(cfg, pool, result, current, now, payout=None):
        stored["act"] = (current, result)

    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: DAEMON)
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: installed)
    monkeypatch.setattr(collector.db, "insert_daemon_snapshot",
                        lambda pool, host, now, daemon: stored.__setitem__("snapshot", daemon))
    monkeypatch.setattr(collector.db, "update_snapshot_installed_models",
                        lambda pool, host, now, ids: stored.__setitem__("installed_update", ids))
    monkeypatch.setattr(collector.db, "delete_ineligible_ema",
                        lambda pool, host, eligible: stored.__setitem__("deleted_ema", frozenset(eligible)))
    monkeypatch.setattr(collector, "_probe_self_route", lambda *args: None)
    monkeypatch.setattr(collector, "_ingest_earnings", lambda *args: None)
    monkeypatch.setattr(collector, "_fetch_scores", lambda cfg: (samples, prices))
    monkeypatch.setattr(collector.db, "load_ema", load_ema)
    monkeypatch.setattr(collector.db, "save_ema", save_ema)
    monkeypatch.setattr(collector.db, "insert_demand_samples", lambda *args: stored.setdefault("samples", True))
    monkeypatch.setattr(collector, "_decide", lambda cfg, pool, ema, daemon, now: Decision("a", "keep", "KEEP"))
    monkeypatch.setattr(collector, "_record_and_act", act)


def test_unknown_inventory_falls_back_to_the_configured_allow_list(monkeypatch):
    stored = {}
    _stub_tick(monkeypatch, stored, installed=None)
    collector.run_tick(_cfg(), None)
    assert stored["snapshot"].installed_models is None
    assert "installed_update" not in stored
    assert stored["loaded"] is True and "ema" in stored
    assert stored["act"][1].action == "KEEP"


def test_authoritative_empty_inventory_waits_without_advancing_ema(monkeypatch):
    stored = {}
    _stub_tick(monkeypatch, stored, installed=())
    collector.run_tick(_cfg(), None)
    assert stored["snapshot"].installed_models is None
    assert stored["installed_update"] == ()
    assert stored["deleted_ema"] == frozenset()
    assert "loaded" not in stored and "ema" not in stored and "samples" not in stored
    assert stored["act"] == ("a", Decision(None, "no eligible installed models", "WAIT"))


def test_configured_models_absent_from_disk_wait_without_enroling_disk_only(monkeypatch):
    stored = {}
    _stub_tick(monkeypatch, stored, installed=("disk-only",))
    collector.run_tick(_cfg(), None)
    assert "loaded" not in stored and "ema" not in stored
    assert stored["act"][1] == Decision(None, "no eligible installed models", "WAIT")
    assert stored["installed_update"] == ("disk-only",)


def test_scoring_uses_the_configured_on_disk_intersection(monkeypatch):
    stored = {}
    seen = {}

    def decide(cfg, pool, ema, daemon, now):
        seen["ema"] = ema
        return Decision("a", "keep", "KEEP")

    _stub_tick(monkeypatch, stored, installed=("a", "disk-only"))
    monkeypatch.setattr(collector, "_decide", decide)
    collector.run_tick(_cfg(), None)
    assert stored["installed_update"] == ("a", "disk-only")
    assert "a" in seen["ema"] and "b" not in seen["ema"] and "disk-only" not in seen["ema"]


def test_a_model_missing_from_disk_is_dropped_from_the_active_ema(monkeypatch):
    stored = {}
    seen = {}

    def decide(cfg, pool, ema, daemon, now):
        seen["ema"] = ema
        return Decision("a", "keep", "KEEP")

    _stub_tick(monkeypatch, stored, installed=("a",), ema_prev={"a": 0.1, "b": 9.0, "gone": 8.0})
    monkeypatch.setattr(collector, "_decide", decide)
    collector.run_tick(_cfg(), None)
    assert seen["ema"].keys() == {"a"}
    assert stored["ema"].keys() == {"a"}


def test_maybe_execute_aborts_when_fresh_inventory_is_unknown(monkeypatch):
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: _live_daemon())
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: None)
    monkeypatch.setattr(collector.remote, "execute_switch", _boom)
    executed, error = collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0)
    assert executed is False and error is not None and "inventory" in error


def test_maybe_execute_aborts_when_the_fresh_target_is_not_installed(monkeypatch):
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: _live_daemon())
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("a",))
    monkeypatch.setattr(collector.remote, "execute_switch", _boom)
    executed, error = collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0)
    assert executed is False and error is not None and "inventory" in error


def test_maybe_execute_aborts_when_the_switch_target_is_absent(monkeypatch):
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: _live_daemon())
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("a", "b"))
    monkeypatch.setattr(collector.remote, "execute_switch", _boom)
    executed, error = collector._maybe_execute(_cfg(), None, Decision(None, "r", "SWITCH"), 100.0)
    assert executed is False and error is not None and "inventory" in error


def test_maybe_execute_starts_when_fresh_inventory_contains_the_target(monkeypatch):
    monkeypatch.setattr(collector, "_fetch_daemon", lambda cfg, now: _live_daemon())
    monkeypatch.setattr(collector, "_fetch_installed", lambda cfg: ("a", "b"))
    monkeypatch.setattr(collector.remote, "execute_switch", lambda cfg, target: None)
    assert collector._maybe_execute(_cfg(), None, Decision("b", "r", "SWITCH"), 100.0) == (True, None)


def test_a_failing_inventory_read_is_logged_and_unknown(monkeypatch, caplog):
    def boom(_cfg):
        raise RuntimeError("down")

    monkeypatch.setattr(collector.remote, "fetch_installed_models", boom)
    with caplog.at_level(logging.WARNING, logger="fleet.collector"):
        assert collector._fetch_installed(_cfg()) is None
    assert "installed-model inventory unknown" in caplog.text


def test_a_failing_memory_inventory_read_is_logged_and_unknown(monkeypatch, caplog):
    monkeypatch.setattr(collector.remote, "fetch_model_memory", _boom)
    assert collector._fetch_model_memory(_cfg()) is None
    assert "memory inventory unknown" in caplog.text


def test_a_64gb_host_waits_when_memory_inventory_is_unknown(monkeypatch):
    monkeypatch.setattr(collector.db, "dwell_anchor", lambda pool, host, started: 0.0)
    monkeypatch.setattr(collector.routability, "measured_switch_cost", lambda pool, host: None)
    monkeypatch.setattr(collector, "_fetch_model_memory", lambda cfg: None)
    result = collector._decide(_cfg(), None, {"a": 1, "b": 2},
                               _live_daemon(total_memory_gb=64), 10_000.0)
    assert result.action == "WAIT" and "memory inventory" in result.reason
