"""_maybe_launch_fast_poll is pure aside from the remote.launch_fast_switch_watcher
call, which is stubbed out here - no SSH, no database needed."""
from types import SimpleNamespace

from fleet import collector
from fleet.types import Decision


def _cfg(live_execution: bool) -> SimpleNamespace:
    return SimpleNamespace(live_execution=live_execution, poll_interval_seconds=60.0)


def test_launches_the_watcher_only_when_busy_and_a_different_target_clears_margin(monkeypatch):
    calls = []
    monkeypatch.setattr(collector.remote, "launch_fast_switch_watcher",
                         lambda cfg, target, max_seconds: calls.append((target, max_seconds)))
    decision = Decision("gemma-4-26b-qat-4bit", "clears margin but waiting for idle", "SWITCH_WHEN_IDLE")
    collector._maybe_launch_fast_poll(_cfg(live_execution=True), decision, now=0.0)
    assert calls == [("gemma-4-26b-qat-4bit", 55.0)]


def test_does_not_launch_for_keep_switch_or_wait_decisions(monkeypatch):
    calls = []
    monkeypatch.setattr(collector.remote, "launch_fast_switch_watcher", lambda *a, **k: calls.append(a))
    for action in ("KEEP", "SWITCH", "WAIT"):
        collector._maybe_launch_fast_poll(_cfg(live_execution=True), Decision("b", "reason", action), now=0.0)
    assert calls == []


def test_stays_a_no_op_end_to_end_when_live_execution_is_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(collector.remote, "launch_fast_switch_watcher", lambda *a, **k: calls.append(a))
    decision = Decision("b", "clears margin but waiting for idle", "SWITCH_WHEN_IDLE")
    collector._maybe_launch_fast_poll(_cfg(live_execution=False), decision, now=0.0)
    assert calls == []
