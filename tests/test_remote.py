"""The FLEET_LIVE_EXECUTION guards raise before touching subprocess/SSH; the
other tests swap subprocess.run or _run_ssh, so none of this needs a network."""
import dataclasses
import subprocess

import pytest

from fleet import remote
from fleet.config import Config
from fleet.types import DaemonState, Payout, Slot


def _state_output(daemon_json: str, widget_json: str = "") -> str:
    """What _STATE_COMMAND's single SSH round trip prints: the daemon doc, the
    separator, then the widget's latest sample row (empty when absent)."""
    return daemon_json + f"\n{remote._DOC_SEPARATOR}\n" + widget_json


def _cfg(live_execution: bool) -> Config:
    return Config(
        ssh_target="host", ssh_key_path=None, remote_python="python3", host_label="host-1",
        host_id="host-1", host_spec="unknown", database_url="postgres://x", poll_interval_seconds=60.0,
        models=("a", "b"), weights={}, ema_tau_minutes=20.0, relative_margin=0.25,
        absolute_margin=0.01, switch_cost_seconds=300.0, decision_horizon_seconds=3600.0,
        min_dwell_seconds=1800.0, daemon_freshness_seconds=90.0, restart_backoff_seconds=30.0,
        live_execution=live_execution, base_url="https://x", pricing_url="https://x", dashboard_port=8080,
        api_key=__name__,
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
    _capture(monkeypatch, _state_output('{"current_model": "a", "warm_models": ["a", ""], "inference_active": 1, '
                                        '"pid": "42", "started_at": 5, "written_at": 1000}'))
    assert remote.fetch_daemon_state(_cfg(False), now=1050.0) == DaemonState("a", ("a",), True, 42, 5.0, True)
    assert remote.fetch_daemon_state(_cfg(False), now=2000.0).fresh is False
    assert remote.fetch_daemon_state(_cfg(False), now=900.0).fresh is False  # future-dated state is not fresh


def test_fetch_daemon_state_reads_advertised_models_and_the_request_counter(monkeypatch):
    _capture(monkeypatch, _state_output('{"current_model": "a", "warm_models": ["a"], "advertised_models": ["a", "b"], '
                                        '"stats": {"requests_served": 7}, "written_at": 1000, '
                                        '"trust": {"trust_level": "self_signed", "reason": "awaiting MDM verification"}}'))
    state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
    assert state.advertised_models == ("a", "b") and state.requests_served == 7
    assert (state.trust_level, state.trust_reason) == ("self_signed", "awaiting MDM verification")


DAEMON_WITH_CAPACITY = ('{"current_model": "a", "warm_models": ["a"], "written_at": 1000, '
                        '"capacity": {"gpu_memory_active_gb": 14.8, "gpu_memory_cache_gb": 1.2, "total_memory_gb": 64}, '
                        '"slots": [{"model": "a", "kv_backend": "paged", "mtp_enabled": true, "mtp_active": true}, '
                        '{"model": "b", "kv_backend": "naive", "mtp_active": false, "mtp_inactive_reason": "no mtp head"}]}')
WIDGET_SAMPLE = ('{"thermalState": "nominal", "memoryPressure": 0.41, "cpuUsage": 0.12, "fanRPM": 1780.0, '
                 '"gpuActiveGb": 15.0, "peakTemperatureC": 62.5, "timestamp": 1005}')


def test_fetch_daemon_state_reads_the_widget_row_and_capacity_in_one_round_trip(monkeypatch):
    commands = _capture(monkeypatch, _state_output(DAEMON_WITH_CAPACITY, WIDGET_SAMPLE))
    state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
    assert (state.thermal_state, state.memory_pressure, state.cpu_usage) == ("nominal", 0.41, 0.12)
    assert (state.fan_rpm, state.peak_temperature_c) == (1780.0, 62.5)
    assert (state.gpu_active_gb, state.gpu_cache_gb, state.total_memory_gb) == (14.8, 1.2, 64)
    assert state.slots == (Slot("a", "paged", True, True, None),
                           Slot("b", "naive", None, False, "no mtp head"))
    # One command carries both reads, and a missing widget DB must not fail it.
    assert commands == [remote._STATE_COMMAND]
    assert "sqlite3" in commands[0] and "|| true" in commands[0]


def test_a_missing_or_malformed_widget_row_degrades_to_none_fields(monkeypatch):
    for widget in ("", "not json at all", "[1, 2, 3]", '{"cpuUsage": "busy", "memoryPressure": null}',
                   '{"thermalState": "fair"}'):
        _capture(monkeypatch, _state_output(DAEMON_WITH_CAPACITY, widget))
        state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
        assert (state.gpu_active_gb, state.gpu_cache_gb, state.total_memory_gb) == (14.8, 1.2, 64)
        if widget == '{"thermalState": "fair"}':
            assert state.thermal_state == "fair"
        else:
            assert (state.thermal_state, state.memory_pressure, state.cpu_usage,
                    state.fan_rpm, state.peak_temperature_c) == (None,) * 5


def test_the_widget_gpu_figure_stands_in_when_capacity_is_absent(monkeypatch):
    daemon = '{"current_model": "a", "warm_models": ["a"], "written_at": 1000, "capacity": {}}'
    _capture(monkeypatch, _state_output(daemon, WIDGET_SAMPLE))
    state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
    assert state.gpu_active_gb == 15.0 and state.gpu_cache_gb is None and state.total_memory_gb is None


def test_malformed_capacity_and_slots_leave_the_read_intact(monkeypatch):
    daemon = ('{"current_model": "a", "warm_models": ["a"], "written_at": 1000, "capacity": "big", '
              '"slots": [{"no_model": true}, "junk", {"model": "b", "mtp_active": "yes"}]}')
    _capture(monkeypatch, _state_output(daemon, WIDGET_SAMPLE + "\n"))
    state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
    assert (state.gpu_active_gb, state.gpu_cache_gb, state.total_memory_gb) == (15.0, None, None)
    assert state.slots == (Slot("b", None, None, None, None),)


def test_fetch_new_payouts_reads_rows_after_the_given_rowid(monkeypatch):
    commands = _capture(monkeypatch, '[[8, "a", null, 30, 1.5, "session-1"]]')
    assert remote.fetch_new_payouts(_cfg(False), since_rowid=7) == [Payout(8, "a", 0, 30, 1.5, "session-1")]
    assert "(7,)" in commands[0]


def test_empty_provider_hash_is_stored_as_null(monkeypatch):
    _capture(monkeypatch, '[[8, "a", null, 30, 1.5, ""]]')
    assert remote.fetch_new_payouts(_cfg(False), since_rowid=7)[0].provider_hash is None


def test_live_switch_and_target_clearing_run_the_expected_commands(monkeypatch):
    commands = _capture(monkeypatch, "0")
    monkeypatch.setattr(remote, "_submit_api_warmup", lambda cfg, model: None)
    remote.execute_switch(_cfg(True), "gpt-oss-20b")
    remote.clear_fast_switch_target(_cfg(True))
    assert len(commands) == 3
    assert "$HOME/.darkbloom/bin/darkbloom stop" in commands[0]
    assert "sleep 300" in commands[0]
    assert "nohup /bin/sh" in commands[0] and "fleet-cold-boot.status" in commands[1]
    assert "$HOME/.darkbloom/bin/darkbloom start --model gpt-oss-20b --idle-timeout 0 --local-endpoint" in commands[0]
    assert 'models = ["gpt-oss-20b"]' in commands[0]
    assert commands[2] == f"rm -f {remote.FAST_SWITCH_STATE_PATH}"


def test_live_switch_requires_a_consumer_key_for_the_api_check(monkeypatch):
    _capture(monkeypatch)
    with pytest.raises(RuntimeError, match="consumer API key"):
        remote.execute_switch(dataclasses.replace(_cfg(True), api_key=None), "a")


def test_api_warmup_is_self_routed(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"{}"

    def open_request(request, timeout):
        seen.update(url=request.full_url, headers=dict(request.header_items()), body=request.data, timeout=timeout)
        return Response()

    class Opener:
        open = staticmethod(open_request)

    monkeypatch.setattr(remote.urllib.request, "build_opener",
                        lambda handler: seen.setdefault("handler", handler) and Opener())
    remote._submit_api_warmup(_cfg(True), "a")
    assert seen["url"] == "https://x/v1/chat/completions"
    assert seen["headers"]["X-darkbloom-route"] == "self"
    assert seen["headers"]["Authorization"] == "Bearer " + __name__
    assert b'"model": "a"' in seen["body"]
    assert isinstance(seen["handler"], remote._NoRedirect)


def test_api_warmup_retries_transient_failure(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"{}"

    class Opener:
        def open(self, request, timeout):
            attempts.append(request)
            if len(attempts) == 1:
                raise OSError("not ready")
            return Response()

    monkeypatch.setattr(remote.urllib.request, "build_opener", lambda handler: Opener())
    monkeypatch.setattr(remote.time, "sleep", lambda seconds: None)
    remote._submit_api_warmup(_cfg(True), "a")
    assert len(attempts) == 2


def test_api_warmup_refuses_a_non_https_base_url():
    with pytest.raises(RuntimeError, match="non-HTTPS"):
        remote._submit_api_warmup(dataclasses.replace(_cfg(True), base_url="http://x"), "a")


def test_live_switch_quotes_the_model(monkeypatch):
    commands = _capture(monkeypatch, "0")
    monkeypatch.setattr(remote, "_submit_api_warmup", lambda cfg, model: None)
    remote.execute_switch(_cfg(True), "gpt oss; rm")
    assert "$HOME/.darkbloom/bin/darkbloom start --model 'gpt oss; rm'" in commands[0]
    assert 'models = ["gpt oss; rm"]' in commands[0]
    assert "models list" not in remote._STATE_COMMAND


def test_live_switch_starts_and_checks_each_requested_model(monkeypatch):
    commands = _capture(monkeypatch, "0")
    checked = []
    monkeypatch.setattr(remote, "_submit_api_warmup", lambda cfg, model: checked.append(model))
    remote.execute_switch(_cfg(True), ("qwen", "oss"))
    assert "start --model qwen --model oss" in commands[0]
    assert 'models = ["qwen", "oss"]' in commands[0]
    assert checked == ["qwen", "oss"]


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
    assert '"daemon_freshness_seconds": 90.0' in commands[0]


def test_inventory_fetch_is_a_separate_all_json_list_command(monkeypatch):
    commands = _capture(
        monkeypatch,
        '{"cacheDirectory": "/x", "filteredByConfig": false, "models": [{"id": "a"}, {"id": "a"}]}',
    )
    assert remote.fetch_installed_models(_cfg(False)) == ("a",)
    assert commands == [remote._INVENTORY_COMMAND]
    assert remote._INVENTORY_COMMAND == f"{remote.DARKBLOOM_BIN} models list --all --json"
    assert "models list" not in remote._STATE_COMMAND


def test_model_memory_uses_cli_estimates(monkeypatch):
    _capture(monkeypatch, '{"models": [{"id": "a", "estimated_memory_gb": 13.5}]}')
    assert remote.fetch_model_memory(_cfg(False)) == {"a": 13.5}


def test_inventory_fetch_rejects_malformed_json(monkeypatch):
    _capture(monkeypatch, "not json")
    with pytest.raises(RuntimeError, match="malformed"):
        remote.fetch_installed_models(_cfg(False))


def test_non_finite_widget_values_are_dropped():
    from fleet.remote import _optional_float
    assert _optional_float({"x": float("nan")}, "x") is None
    assert _optional_float({"x": float("inf")}, "x") is None
    assert _optional_float({"x": "0.5"}, "x") == 0.5


def test_fetch_daemon_state_reads_last_model_load_error(monkeypatch):
    _capture(monkeypatch, _state_output(
        '{"current_model": "a", "warm_models": ["a"], "written_at": 1000, '
        '"last_model_load_error": {"model": "b", "message": "oom", "at": 990}}'))
    state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
    assert (state.last_model_load_error_model, state.last_model_load_error_message,
            state.last_model_load_error_at) == ("b", "oom", 990.0)


def test_malformed_last_model_load_error_degrades_to_nulls_and_keeps_the_read(monkeypatch):
    prefix = '{"current_model": "a", "warm_models": ["a"], "written_at": 1000, "last_model_load_error": '
    cases = {
        '"oops"}': (None, None, None),
        "[]}": (None, None, None),
        "1}": (None, None, None),
        '{"model": "", "message": "", "at": null}}': (None, None, None),
        '{"model": "b", "message": "x", "at": "nan"}}': ("b", "x", None),
        '{"model": "b", "message": "x", "at": "inf"}}': ("b", "x", None),
        '{"at": "nope"}}': (None, None, None),
    }
    for blob, expected in cases.items():
        _capture(monkeypatch, _state_output(prefix + blob))
        state = remote.fetch_daemon_state(_cfg(False), now=1010.0)
        assert state.current_model == "a"
        assert (state.last_model_load_error_model, state.last_model_load_error_message,
                state.last_model_load_error_at) == expected
