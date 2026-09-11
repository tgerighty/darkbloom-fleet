"""The collector's decision plumbing, with the remote watcher controls and
database calls stubbed out - no SSH, no database needed."""
from types import SimpleNamespace

import pytest

from fleet import collector
from fleet.types import Decision


def _cfg(live_execution: bool) -> SimpleNamespace:
    return SimpleNamespace(live_execution=live_execution, poll_interval_seconds=60.0, host_label="h")


@pytest.fixture
def remote_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(collector.remote, "launch_fast_switch_watcher",
                        lambda cfg, target, max_seconds: calls.append(("launch", target, max_seconds)))
    monkeypatch.setattr(collector.remote, "clear_fast_switch_target", lambda cfg: calls.append(("clear",)))
    return calls


def test_launches_the_watcher_when_busy_and_a_different_target_clears_margin(remote_calls):
    decision = Decision("gemma-4-26b-qat-4bit", "clears margin but waiting for idle", "SWITCH_WHEN_IDLE")
    collector._maybe_launch_fast_poll(_cfg(live_execution=True), decision)
    assert remote_calls == [("launch", "gemma-4-26b-qat-4bit", 55.0)]


def test_every_other_live_decision_clears_the_watcher_target(remote_calls):
    for action in ("KEEP", "SWITCH", "WAIT"):
        collector._maybe_launch_fast_poll(_cfg(live_execution=True), Decision("b", "reason", action))
    assert remote_calls == [("clear",), ("clear",), ("clear",)]


def test_observe_mode_never_touches_the_watcher(remote_calls):
    for action in ("SWITCH_WHEN_IDLE", "KEEP", "SWITCH", "WAIT"):
        collector._maybe_launch_fast_poll(_cfg(live_execution=False), Decision("b", "reason", action))
    assert remote_calls == []


def test_the_decision_is_stored_before_a_live_switch_and_updated_after(monkeypatch, remote_calls):
    events = []
    monkeypatch.setattr(collector.db, "insert_decision",
                        lambda pool, host, now, current, result, outcome: events.append(("insert", outcome.executed)) or 7)
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
