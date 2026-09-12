"""The watcher's switch and main-loop paths, with darkbloom, the clock and the
daemon state all stubbed. Loaded by file path like test_fast_switch_watcher."""
import importlib.util
import json
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "fleet" / "remote_assets" / "fast_switch_watcher.py"


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fast_switch_watcher_run", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = {"LOCK_FILE": "lock", "FAILED_AT_FILE": "failed-at", "TARGET_STATE_PATH": "state.json",
             "LOG": "fast_switch.log", "DAEMON_STATE_PATH": "daemon-state.json"}
    for name, filename in paths.items():
        monkeypatch.setattr(module, name, tmp_path / filename)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return module


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["darkbloom"], returncode, stdout="", stderr=stderr)


def _target(watcher, **state) -> None:
    watcher.TARGET_STATE_PATH.write_text(json.dumps({"target": "b", "valid_targets": ["a", "b"], **state}))


def test_daemon_state_comes_from_the_state_file(watcher):
    watcher.DAEMON_STATE_PATH.write_text('{"current_model": "a"}')
    assert watcher.read_daemon_state() == {"current_model": "a"}
    watcher.DAEMON_STATE_PATH.unlink()
    assert watcher._daemon_state_or_none() is None


def test_run_start_invokes_darkbloom_for_the_target(watcher, monkeypatch):
    seen = {}

    def fake_run(args, **_kwargs):
        seen["args"] = args
        return _completed(0)

    monkeypatch.setattr(watcher.subprocess, "run", fake_run)
    assert watcher._run_start("b").returncode == 0
    assert seen["args"][1:4] == ["start", "--model", "b"]


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("darkbloom", 60), FileNotFoundError("darkbloom")])
def test_a_hung_or_missing_cli_is_a_failed_switch(watcher, monkeypatch, error):
    def fake_run(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(watcher.subprocess, "run", fake_run)
    assert watcher.execute_switch("b") is False
    assert "FAILED" in watcher.LOG.read_text()


def test_execute_switch_retries_once_after_a_launchd_bootstrap_race(watcher, monkeypatch):
    results = iter([_completed(1, "Bootstrap failed: 5: Input/output error"), _completed(0)])
    monkeypatch.setattr(watcher, "_run_start", lambda target: next(results))
    monkeypatch.setattr(watcher, "_verify", lambda target: True)
    assert watcher.execute_switch("b") is True


def test_execute_switch_reports_a_failed_start(watcher, monkeypatch):
    monkeypatch.setattr(watcher, "_run_start", lambda target: _completed(1, "no such model"))
    assert watcher.execute_switch("b") is False
    assert "FAILED" in watcher.LOG.read_text()


def test_verify_gives_up_when_the_model_never_appears(watcher, monkeypatch):
    monkeypatch.setattr(watcher, "read_daemon_state", lambda: {"current_model": "a"})
    assert watcher._verify("b") is False


def test_main_waits_out_the_failure_backoff(watcher, monkeypatch):
    _target(watcher, restart_backoff_seconds=60)
    watcher.FAILED_AT_FILE.write_text(str(time.time()))
    switched = []
    monkeypatch.setattr(watcher, "execute_switch", switched.append)
    watcher.main()
    assert switched == [] and "backoff" in watcher.LOG.read_text()


def test_main_logs_a_timeout_when_no_idle_gap_opens(watcher, monkeypatch):
    _target(watcher, max_seconds=0.05)
    monkeypatch.setattr(watcher, "read_daemon_state", lambda: {"current_model": "a", "inference_active": True})
    watcher.main()
    assert "timed out" in watcher.LOG.read_text()


def test_main_records_a_failed_switch_for_the_backoff(watcher, monkeypatch):
    _target(watcher, max_seconds=5)
    monkeypatch.setattr(watcher, "read_daemon_state", lambda: {"current_model": "a", "inference_active": False})
    monkeypatch.setattr(watcher, "execute_switch", lambda target: False)
    watcher.main()
    assert watcher.FAILED_AT_FILE.exists()
