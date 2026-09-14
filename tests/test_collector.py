"""The collector's decision plumbing, with the remote watcher controls and
database calls stubbed out - no SSH, no database needed."""
import logging
from types import SimpleNamespace

import pytest

from fleet import collector
from fleet.types import Decision


def _cfg(live_execution: bool) -> SimpleNamespace:
    return SimpleNamespace(live_execution=live_execution, poll_interval_seconds=60.0, host_id="h",
                           restart_backoff_seconds=30.0)


def _boom(*_args, **_kwargs):
    raise RuntimeError("down")


@pytest.fixture
def remote_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(collector.remote, "launch_fast_switch_watcher",
                        lambda cfg, target, max_seconds: calls.append(("launch", target, max_seconds)))
    monkeypatch.setattr(collector.remote, "clear_fast_switch_target", lambda cfg: calls.append(("clear",)))
    monkeypatch.setattr(collector.remote, "remove_fast_switch_target", lambda cfg: calls.append(("remove",)))
    return calls


def test_busy_switch_waits_for_a_full_checked_cold_boot_on_a_later_tick(remote_calls):
    decision = Decision("gemma-4-26b-qat-4bit", "clears margin but waiting for idle", "SWITCH_WHEN_IDLE")
    collector._maybe_launch_fast_poll(_cfg(live_execution=True), decision)
    assert remote_calls == [("clear",)]


def test_every_live_decision_clears_the_watcher_target(remote_calls):
    for action in ("KEEP", "SWITCH", "WAIT"):
        collector._maybe_launch_fast_poll(_cfg(live_execution=True), Decision("b", "reason", action))
    assert remote_calls == [("clear",), ("clear",), ("clear",)]


def test_observe_mode_never_launches_but_still_clears_a_stale_target(remote_calls):
    for action in ("SWITCH_WHEN_IDLE", "KEEP", "SWITCH", "WAIT"):
        collector._maybe_launch_fast_poll(_cfg(live_execution=False), Decision("b", "reason", action))
    assert remote_calls == [("remove",)] * 4


def test_observe_mode_logs_the_watcher_it_would_have_launched(monkeypatch, caplog, remote_calls):
    monkeypatch.setattr(collector.remote, "remove_fast_switch_target", _boom)
    with caplog.at_level(logging.INFO, logger="fleet.collector"):
        collector._maybe_launch_fast_poll(_cfg(live_execution=False), Decision("b", "waiting for idle", "SWITCH_WHEN_IDLE"))
    assert "observe mode: would launch fast-poll watcher for target b" in caplog.text


def test_a_failing_stale_target_removal_in_observe_mode_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(collector.remote, "remove_fast_switch_target", _boom)
    collector._maybe_launch_fast_poll(_cfg(live_execution=False), Decision("b", "reason", "KEEP"))
    assert "fast-poll watcher control failed" in caplog.text


def test_a_switch_within_the_restart_backoff_is_deferred_not_failed(monkeypatch, remote_calls):
    events = []
    monkeypatch.setattr(collector.db, "last_failed_switch_at", lambda pool, host: 90.0)
    monkeypatch.setattr(collector.db, "insert_decision",
                        lambda pool, host, now, current, result, outcome, payout: events.append(("insert", result, outcome)) or 7)
    monkeypatch.setattr(collector.db, "record_outcome", lambda pool, decision_id, outcome: events.append(("update",)))
    monkeypatch.setattr(collector, "_maybe_execute",
                        lambda cfg, pool, result, now: events.append(("execute", result.action)) or (False, None))
    collector._record_and_act(_cfg(live_execution=True), None, Decision("b", "clears margin", "SWITCH"), "a", 100.0)
    (_insert, result, outcome), (_execute, action) = events
    assert result.action == "BLOCKED" and "backoff" in result.reason
    assert outcome.error is None and outcome.executed is False  # NULL error: the backoff must not extend itself
    assert action == "BLOCKED"  # no switch was attempted
    assert remote_calls == [("clear",)]


def test_the_decision_is_stored_before_a_live_switch_and_updated_after(monkeypatch, remote_calls):
    events = []
    monkeypatch.setattr(collector.db, "last_failed_switch_at", lambda pool, host: 0.0)
    monkeypatch.setattr(collector.db, "insert_decision",
                        lambda pool, host, now, current, result, outcome, payout: events.append(("insert", outcome.executed)) or 7)
    monkeypatch.setattr(collector, "_maybe_execute", lambda cfg, pool, result, now: events.append(("execute",)) or (True, None))
    monkeypatch.setattr(collector.db, "record_outcome",
                        lambda pool, decision_id, outcome: events.append(("update", decision_id, outcome.executed)))
    collector._record_and_act(_cfg(live_execution=True), None, Decision("b", "clears margin", "SWITCH"), "a", 0.0)
    assert events == [("insert", False), ("execute",), ("update", 7, True)]


def test_nothing_is_updated_when_no_switch_was_attempted(monkeypatch, remote_calls):
    events = []
    monkeypatch.setattr(collector.db, "insert_decision", lambda *args: events.append("insert") or 1)
    monkeypatch.setattr(collector, "_maybe_execute", lambda *args: (False, None))
    monkeypatch.setattr(collector.db, "record_outcome", lambda *args: events.append("update"))
    collector._record_and_act(_cfg(live_execution=False), None, Decision("a", "keep", "KEEP"), "a", 0.0)
    assert events == ["insert"]
