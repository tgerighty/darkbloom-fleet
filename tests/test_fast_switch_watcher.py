"""fast_switch_watcher.py is a standalone stdlib script deployed to the
remote host, not part of the fleet package - loaded here by file path so its
pure logic (the lock, target-state parsing, failure backoff, the idle-gap
wait) can be unit tested without SSH or a real darkbloom host."""
import fcntl
import importlib.util
import os
import time
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "fleet" / "remote_assets" / "fast_switch_watcher.py"
IDLE_ON_A = {"current_model": "a", "inference_active": False}
BUSY_ON_A = {"current_model": "a", "inference_active": True}


def _load_module():
    spec = importlib.util.spec_from_file_location("fast_switch_watcher", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(module, "FAILED_AT_FILE", tmp_path / "failed-at")
    monkeypatch.setattr(module, "TARGET_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(module, "LOG", tmp_path / "fast_switch.log")
    monkeypatch.setattr(module, "POLL_SECONDS", 0.01)
    return module


def test_acquire_lock_writes_our_pid(watcher):
    fd = watcher.acquire_lock_or_exit()
    try:
        assert watcher.LOCK_FILE.read_text() == str(os.getpid())
    finally:
        os.close(fd)


def test_acquire_lock_ignores_a_pid_left_behind_by_a_dead_watcher(watcher):
    watcher.LOCK_FILE.write_text("999999999")
    fd = watcher.acquire_lock_or_exit()
    os.close(fd)
    assert watcher.LOCK_FILE.read_text() == str(os.getpid())


def test_acquire_lock_exits_while_another_watcher_holds_it(watcher):
    holder = os.open(watcher.LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        with pytest.raises(SystemExit) as exc:
            watcher.acquire_lock_or_exit()
        assert exc.value.code == 0
    finally:
        os.close(holder)


def test_acquire_lock_refuses_a_symlinked_lock_path(watcher, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("")
    watcher.LOCK_FILE.symlink_to(elsewhere)
    with pytest.raises(SystemExit) as exc:
        watcher.acquire_lock_or_exit()
    assert exc.value.code not in (0, None)


def test_read_target_state_rejects_a_target_outside_the_valid_set(watcher):
    watcher.TARGET_STATE_PATH.write_text('{"target": "evil-model", "valid_targets": ["a", "b"], "max_seconds": 10}')
    target, valid, max_seconds = watcher.read_target_state()
    assert target is None and valid == ("a", "b") and max_seconds == 10.0


def test_read_target_state_accepts_a_valid_target(watcher):
    watcher.TARGET_STATE_PATH.write_text('{"target": "b", "valid_targets": ["a", "b"], "max_seconds": 10}')
    target, _valid, _max_seconds = watcher.read_target_state()
    assert target == "b"


def test_read_target_state_defaults_when_the_file_is_missing(watcher):
    target, valid, max_seconds = watcher.read_target_state()
    assert target is None and valid == () and max_seconds == watcher.DEFAULT_MAX_SECONDS


def test_failure_backoff_holds_until_the_configured_backoff_passes(watcher):
    watcher.TARGET_STATE_PATH.write_text('{"restart_backoff_seconds": 30}')
    watcher.FAILED_AT_FILE.write_text(str(time.time() - 10))
    assert watcher.in_failure_backoff(time.time()) is True
    assert watcher.in_failure_backoff(time.time() + 25) is False


def test_failure_backoff_is_off_without_a_recorded_failure(watcher):
    watcher.TARGET_STATE_PATH.write_text('{"restart_backoff_seconds": 30}')
    assert watcher.in_failure_backoff(time.time()) is False


def test_an_idle_gap_that_survives_the_recheck_returns_the_target(watcher, monkeypatch):
    watcher.TARGET_STATE_PATH.write_text('{"target": "b", "valid_targets": ["a", "b"]}')
    monkeypatch.setattr(watcher, "read_daemon_state", lambda: IDLE_ON_A)
    assert watcher._wait_for_idle_gap(time.time() + 5) == "b"


def test_a_request_starting_during_the_recheck_stops_the_switch(watcher, monkeypatch):
    watcher.TARGET_STATE_PATH.write_text('{"target": "b", "valid_targets": ["a", "b"]}')
    states = iter([IDLE_ON_A])
    monkeypatch.setattr(watcher, "read_daemon_state", lambda: next(states, BUSY_ON_A))
    assert watcher._wait_for_idle_gap(time.time() + 0.3) is None


def test_verification_rides_out_a_half_written_state_file(watcher, monkeypatch):
    reads = iter([ValueError("half-written"), {"current_model": "b"}])

    def fake_read():
        item = next(reads)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(watcher, "read_daemon_state", fake_read)
    monkeypatch.setattr(watcher.time, "sleep", lambda _seconds: None)
    assert watcher._verify("b") is True
