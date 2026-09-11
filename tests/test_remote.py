"""The FLEET_LIVE_EXECUTION guards raise before touching subprocess/SSH; the
command-line tests swap subprocess.run or _run_ssh, so none of this needs a
network."""
import dataclasses
import subprocess

import pytest

from fleet import remote
from fleet.config import Config


def _cfg(live_execution: bool) -> Config:
    return Config(
        ssh_target="host", ssh_key_path=None, remote_python="python3", host_label="host-1",
        host_spec="unknown", database_url="postgres://x", poll_interval_seconds=60.0,
        models=("a", "b"), weights={}, ema_tau_minutes=20.0, relative_margin=0.25,
        absolute_margin=0.01, switch_cost_seconds=300.0, decision_horizon_seconds=3600.0,
        min_dwell_seconds=1800.0, daemon_freshness_seconds=90.0, restart_backoff_seconds=30.0,
        live_execution=live_execution, base_url="https://x", pricing_url="https://x", dashboard_port=8080,
    )


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


def test_watcher_deploy_fails_fast_and_installs_both_files_before_launching(monkeypatch):
    commands = []
    monkeypatch.setattr(remote, "_run_ssh", lambda cfg, command, timeout: commands.append(command) or "")

    remote.launch_fast_switch_watcher(_cfg(live_execution=True), "a", max_seconds=55.0)

    lines = commands[0].splitlines()
    launch = next(i for i, line in enumerate(lines) if line.startswith("nohup "))
    moves = [i for i, line in enumerate(lines) if line.startswith("mv -f ")]
    assert lines[0] == "set -e"
    assert len(moves) == 2 and max(moves) < launch
