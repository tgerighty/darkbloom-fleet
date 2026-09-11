"""_maybe_launch_fast_poll is pure aside from the remote watcher controls,
which are stubbed out here - no SSH, no database needed."""
from types import SimpleNamespace

import pytest

from fleet import collector
from fleet.types import Decision


def _cfg(live_execution: bool) -> SimpleNamespace:
    return SimpleNamespace(live_execution=live_execution, poll_interval_seconds=60.0)


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
