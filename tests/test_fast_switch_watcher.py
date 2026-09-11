"""fast_switch_watcher.py is a standalone stdlib script deployed to the
remote host, not part of the fleet package - loaded here by file path so its
pure logic (the PID-file lock, target-state parsing) can be unit tested
without SSH or a real darkbloom host."""
import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "fleet" / "remote_assets" / "fast_switch_watcher.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fast_switch_watcher", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / "lock")
    return module


def test_acquire_lock_creates_a_pid_file_when_none_exists(watcher):
    watcher.acquire_lock_or_exit()
    assert watcher.LOCK_FILE.read_text() == str(os.getpid())


def test_acquire_lock_takes_over_a_stale_lock(watcher):
    watcher.LOCK_FILE.write_text("999999999")  # pid extremely unlikely to be alive
    watcher.acquire_lock_or_exit()
    assert watcher.LOCK_FILE.read_text() == str(os.getpid())


def test_acquire_lock_takes_over_an_unreadable_lock(watcher):
    watcher.LOCK_FILE.write_text("not-a-pid")
    watcher.acquire_lock_or_exit()
    assert watcher.LOCK_FILE.read_text() == str(os.getpid())


def test_acquire_lock_exits_when_another_instance_is_alive(watcher):
    watcher.LOCK_FILE.write_text(str(os.getpid()))  # our own pid is definitely alive
    with pytest.raises(SystemExit) as exc:
        watcher.acquire_lock_or_exit()
    assert exc.value.code == 0


def test_read_target_state_rejects_a_target_outside_the_valid_set(watcher, tmp_path):
    watcher.TARGET_STATE_PATH = tmp_path / "state.json"
    watcher.TARGET_STATE_PATH.write_text('{"target": "evil-model", "valid_targets": ["a", "b"], "max_seconds": 10}')
    target, valid, max_seconds = watcher.read_target_state()
    assert target is None and valid == ("a", "b") and max_seconds == 10.0


def test_read_target_state_accepts_a_valid_target(watcher, tmp_path):
    watcher.TARGET_STATE_PATH = tmp_path / "state.json"
    watcher.TARGET_STATE_PATH.write_text('{"target": "b", "valid_targets": ["a", "b"], "max_seconds": 10}')
    target, _valid, _max_seconds = watcher.read_target_state()
    assert target == "b"


def test_read_target_state_defaults_when_the_file_is_missing(watcher, tmp_path):
    watcher.TARGET_STATE_PATH = tmp_path / "missing.json"
    target, valid, max_seconds = watcher.read_target_state()
    assert target is None and valid == () and max_seconds == watcher.DEFAULT_MAX_SECONDS
