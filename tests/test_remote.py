"""The FLEET_LIVE_EXECUTION guards raise before touching subprocess/SSH; the
other tests swap subprocess.run or _run_ssh, so none of this needs a network."""
import dataclasses
import subprocess

import pytest

from fleet import remote
from fleet.config import Config
from fleet.types import DaemonState, Payout


def _cfg(live_execution: bool) -> Config:
    return Config(
        ssh_target="host", ssh_key_path=None, remote_python="python3", host_label="host-1",
        host_id="host-1", host_spec="unknown", database_url="postgres://x", poll_interval_seconds=60.0,
        models=("a", "b"), weights={}, ema_tau_minutes=20.0, relative_margin=0.25,
        absolute_margin=0.01, switch_cost_seconds=300.0, decision_horizon_seconds=3600.0,
        min_dwell_seconds=1800.0, daemon_freshness_seconds=90.0, restart_backoff_seconds=30.0,
        live_execution=live_execution, base_url="https://x", pricing_url="https://x", dashboard_port=8080,
    )


def _capture(monkeypatch, reply=""):
    commands = []
    monkeypatch.setattr(remote, "_run_ssh", lambda cfg, command, timeout: commands.append(command) or reply)
    return commands


def test_execute_switch_refuses_without_live_execution():
    with pytest.raises(RuntimeError, match="FLEET_LIVE_EXECUTION"):
        remote.execute_switch(_cfg(live_execution=False), "a")


def test_launch_fast_switch_watcher_refuses_without_live_execution():
    with pytest.raises(RuntimeError, match="FLEET_LIVE_EXECUTION"):
        remote.launch_fast_switch_watcher(_cfg(live_execution=False), "a", max_seconds=55.0)


def test_clear_fast_switch_target_refuses_without_live_execution():
    with pytest.raises(RuntimeError, match="FLEET_LIVE_EXECUTION"):
        remote.clear_fast_switch_target(_cfg(live_execution=False))


def test_run_ssh_uses_the_configured_ssh_config_file(monkeypatch):
    seen = {}

    def fake_run(command, **_kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    cfg = dataclasses.replace(_cfg(live_execution=False), ssh_config_path="/run/secrets/ssh_config")

    assert remote._run_ssh(cfg, "true", timeout=1) == "ok"
    command = seen["command"]
    assert command[command.index("-F") + 1] == "/run/secrets/ssh_config"
    assert command[-2:] == ["host", "true"]


def test_run_ssh_passes_an_explicit_key_and_reports_failures(monkeypatch):
    seen = {}

    def fake_run(command, **_kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 255, stdout="", stderr="Permission denied")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="Permission denied"):
        remote._run_ssh(dataclasses.replace(_cfg(live_execution=False), ssh_key_path="/keys/id"), "true", timeout=1)
    assert seen["command"][seen["command"].index("-i") + 1] == "/keys/id"


def test_fetch_daemon_state_parses_and_judges_freshness(monkeypatch):
    _capture(monkeypatch, '{"current_model": "a", "warm_models": ["a", ""], "inference_active": 1, '
                          '"pid": "42", "started_at": 5, "written_at": 1000}')
    assert remote.fetch_daemon_state(_cfg(False), now=1050.0) == DaemonState("a", ("a",), True, 42, 5.0, True)
    assert remote.fetch_daemon_state(_cfg(False), now=2000.0).fresh is False
    assert remote.fetch_daemon_state(_cfg(False), now=900.0).fresh is False  # future-dated state is not fresh


def test_fetch_daemon_state_reads_advertised_models_and_the_request_counter(monkeypatch):
    _capture(monkeypatch, '{"current_model": "a", "warm_models": ["a"], "advertised_models": ["a", "b"], '
                          '"stats": {"requests_served": 7}, "written_at": 1000, '
                          '"trust": {"trust_level": "self_signed", "reason": "awaiting MDM verification"}}')
    state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
    assert state.advertised_models == ("a", "b") and state.requests_served == 7
    assert (state.trust_level, state.trust_reason) == ("self_signed", "awaiting MDM verification")


def test_fetch_new_payouts_reads_rows_after_the_given_rowid(monkeypatch):
    commands = _capture(monkeypatch, '[[8, "a", null, 30, 1.5, "session-1"]]')
    assert remote.fetch_new_payouts(_cfg(False), since_rowid=7) == [Payout(8, "a", 0, 30, 1.5, "session-1")]
    assert "(7,)" in commands[0]


def test_live_switch_and_target_clearing_run_the_expected_commands(monkeypatch):
    commands = _capture(monkeypatch)
    remote.execute_switch(_cfg(True), "gpt-oss-20b")
    remote.clear_fast_switch_target(_cfg(True))
    assert commands == ["darkbloom start --model gpt-oss-20b --idle-timeout 0", f"rm -f {remote.FAST_SWITCH_STATE_PATH}"]


def test_remove_fast_switch_target_needs_no_live_execution(monkeypatch):
    commands = _capture(monkeypatch)
    remote.remove_fast_switch_target(_cfg(live_execution=False))
    assert commands == [f"rm -f {remote.FAST_SWITCH_STATE_PATH}"]


def test_watcher_deploy_fails_fast_and_installs_both_files_before_launching(monkeypatch):
    commands = _capture(monkeypatch)
    remote.launch_fast_switch_watcher(_cfg(live_execution=True), "a", max_seconds=55.0)
    lines = commands[0].splitlines()
    launch = next(i for i, line in enumerate(lines) if line.startswith("nohup "))
    moves = [i for i, line in enumerate(lines) if line.startswith("mv -f ")]
    assert lines[0] == "set -e"
    assert len(moves) == 2 and max(moves) < launch
