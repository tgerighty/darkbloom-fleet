"""Read-only ingestion parses provider data over SSH; the
other tests swap subprocess.run or _run_ssh, so none of this needs a network."""
import dataclasses
import subprocess

import pytest

from fleet import remote
from fleet.config import Config
from fleet.types import DaemonState, Payout, Slot


def _state_output(daemon_json: str, widget_json: str = "", manager_json: str = "", manager_pid: str = "") -> str:
    """Build the four-field SSH response, including optional manager state and the running marker."""
    return (daemon_json + f"\n{remote._DOC_SEPARATOR}\n" + widget_json +
            f"\n{remote._DOC_SEPARATOR}\n" + manager_json +
            f"\n{remote._DOC_SEPARATOR}\n" + manager_pid)


def _cfg() -> Config:
    return Config(
        ssh_target="host", ssh_key_path=None, remote_python="python3", host_label="host-1",
        host_id="host-1", host_spec="unknown", database_url="postgres://x", poll_interval_seconds=60.0,
        models=("a", "b"), weights={}, ema_tau_minutes=20.0, switch_cost_seconds=300.0, daemon_freshness_seconds=90.0, base_url="https://x", pricing_url="https://x", dashboard_port=8080,
        api_key=__name__,
    )


def _capture(monkeypatch, reply=""):
    commands = []
    monkeypatch.setattr(remote, "_run_ssh", lambda cfg, command, timeout: commands.append(command) or reply)
    return commands


def test_run_ssh_uses_the_configured_ssh_config_file(monkeypatch):
    seen = {}

    def fake_run(command, **_kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    cfg = dataclasses.replace(_cfg(), ssh_config_path="/run/secrets/ssh_config")

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
        remote._run_ssh(dataclasses.replace(_cfg(), ssh_key_path="/keys/id"), "true", timeout=1)
    assert seen["command"][seen["command"].index("-i") + 1] == "/keys/id"


def test_fetch_daemon_state_parses_and_judges_freshness(monkeypatch):
    _capture(monkeypatch, _state_output('{"current_model": "a", "warm_models": ["a", ""], "inference_active": 1, '
                                        '"pid": "42", "started_at": 5, "written_at": 1000}'))
    assert remote.fetch_daemon_state(_cfg(), now=1050.0) == DaemonState(
        "a", ("a",), True, 42, 5.0, True, manager={"running": False, "mode": "OFF"})
    assert remote.fetch_daemon_state(_cfg(), now=2000.0).fresh is False
    assert remote.fetch_daemon_state(_cfg(), now=900.0).fresh is False  # future-dated state is not fresh


def test_fetch_daemon_state_reads_advertised_models_and_the_request_counter(monkeypatch):
    _capture(monkeypatch, _state_output('{"current_model": "a", "warm_models": ["a"], "advertised_models": ["a", "b"], '
                                        '"stats": {"requests_served": 7}, "written_at": 1000, '
                                        '"trust": {"trust_level": "self_signed", "reason": "awaiting MDM verification"}}'))
    state = remote.fetch_daemon_state(_cfg(), now=1010.0)
    assert state.advertised_models == ("a", "b") and state.requests_served == 7
    assert (state.trust_level, state.trust_reason) == ("self_signed", "awaiting MDM verification")


def test_fetch_daemon_state_reads_the_live_manager_report(monkeypatch):
    manager = ('{"manager_version":"0.1.7","last_decision_at":1005,'
               '"current_model":"gemma","last_decision_target":"qwen",'
               '"last_decision_reason":"3 checks required","live_challenger_model":"qwen",'
               '"live_challenger_streak":2}')
    _capture(monkeypatch, _state_output('{"written_at":1000}', "", manager, "321"))
    state = remote.fetch_daemon_state(_cfg(), now=1010.0)
    assert state.manager == {"running": True, "mode": "LIVE", "fresh": True,
                             "version": "0.1.7", "as_of": 1005.0,
                             "current_model": "gemma", "target_model": "qwen",
                             "reason": "3 checks required", "challenger_model": "qwen", "streak": 2, "score_snapshot": None, "earnings_shadow": None}


def test_missing_or_malformed_manager_state_is_reported_as_not_running(monkeypatch):
    for raw in ("", "nope", "[]"):
        _capture(monkeypatch, _state_output('{"written_at":1000}', "", raw, ""))
        assert remote.fetch_daemon_state(_cfg(), now=1010.0).manager == {"running": False, "mode": "OFF"}
    _capture(monkeypatch, _state_output('{"written_at":1000}', "", '{"live_challenger_streak":"bad"}', "1"))
    assert remote.fetch_daemon_state(_cfg(), now=1010.0).manager["streak"] == 0


DAEMON_WITH_CAPACITY = ('{"current_model": "a", "warm_models": ["a"], "written_at": 1000, '
                        '"capacity": {"gpu_memory_active_gb": 14.8, "gpu_memory_cache_gb": 1.2, "total_memory_gb": 64}, '
                        '"slots": [{"model": "a", "kv_backend": "paged", "mtp_enabled": true, "mtp_active": true}, '
                        '{"model": "b", "kv_backend": "naive", "mtp_active": false, "mtp_inactive_reason": "no mtp head"}]}')
WIDGET_SAMPLE = ('{"thermalState": "nominal", "memoryPressure": 0.41, "cpuUsage": 0.12, "fanRPM": 1780.0, '
                 '"gpuActiveGb": 15.0, "peakTemperatureC": 62.5, "timestamp": 1005}')


def test_fetch_daemon_state_reads_the_widget_row_and_capacity_in_one_round_trip(monkeypatch):
    commands = _capture(monkeypatch, _state_output(DAEMON_WITH_CAPACITY, WIDGET_SAMPLE))
    state = remote.fetch_daemon_state(_cfg(), now=1010.0)
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
        state = remote.fetch_daemon_state(_cfg(), now=1010.0)
        assert (state.gpu_active_gb, state.gpu_cache_gb, state.total_memory_gb) == (14.8, 1.2, 64)
        if widget == '{"thermalState": "fair"}':
            assert state.thermal_state == "fair"
        else:
            assert (state.thermal_state, state.memory_pressure, state.cpu_usage,
                    state.fan_rpm, state.peak_temperature_c) == (None,) * 5


def test_the_widget_gpu_figure_stands_in_when_capacity_is_absent(monkeypatch):
    daemon = '{"current_model": "a", "warm_models": ["a"], "written_at": 1000, "capacity": {}}'
    _capture(monkeypatch, _state_output(daemon, WIDGET_SAMPLE))
    state = remote.fetch_daemon_state(_cfg(), now=1010.0)
    assert state.gpu_active_gb == 15.0 and state.gpu_cache_gb is None and state.total_memory_gb is None


def test_malformed_capacity_and_slots_leave_the_read_intact(monkeypatch):
    daemon = ('{"current_model": "a", "warm_models": ["a"], "written_at": 1000, "capacity": "big", '
              '"slots": [{"no_model": true}, "junk", {"model": "b", "mtp_active": "yes"}]}')
    _capture(monkeypatch, _state_output(daemon, WIDGET_SAMPLE + "\n"))
    state = remote.fetch_daemon_state(_cfg(), now=1010.0)
    assert (state.gpu_active_gb, state.gpu_cache_gb, state.total_memory_gb) == (15.0, None, None)
    assert state.slots == (Slot("b", None, None, None, None),)


def test_fetch_new_payouts_reads_rows_after_the_given_rowid(monkeypatch):
    commands = _capture(monkeypatch, '[[8, "a", null, 30, 1.5, "session-1"]]')
    assert remote.fetch_new_payouts(_cfg(), since_rowid=7) == [Payout(8, "a", 0, 30, 1.5, "session-1")]
    assert f"(7, {remote.PAYOUT_BATCH_SIZE})" in commands[0]


def test_empty_provider_hash_is_stored_as_null(monkeypatch):
    _capture(monkeypatch, '[[8, "a", null, 30, 1.5, ""]]')
    assert remote.fetch_new_payouts(_cfg(), since_rowid=7)[0].provider_hash is None


def test_inventory_fetch_is_a_separate_all_json_list_command(monkeypatch):
    commands = _capture(
        monkeypatch,
        '{"cacheDirectory": "/x", "filteredByConfig": false, "models": [{"id": "a"}, {"id": "a"}]}',
    )
    assert remote.fetch_installed_models(_cfg()) == ("a",)
    assert commands == [remote._INVENTORY_COMMAND]
    assert remote._INVENTORY_COMMAND == f"{remote.DARKBLOOM_BIN} models list --all --json"
    assert "models list" not in remote._STATE_COMMAND


def test_inventory_fetch_rejects_malformed_json(monkeypatch):
    _capture(monkeypatch, "not json")
    with pytest.raises(RuntimeError, match="malformed"):
        remote.fetch_installed_models(_cfg())


def test_non_finite_widget_values_are_dropped():
    from fleet.remote import _optional_float
    assert _optional_float({"x": float("nan")}, "x") is None
    assert _optional_float({"x": float("inf")}, "x") is None
    assert _optional_float({"x": "0.5"}, "x") == 0.5


def test_overflowing_optional_values_do_not_discard_a_daemon_read(monkeypatch):
    _capture(monkeypatch, _state_output('{"current_model": "a", "warm_models": ["a"], "written_at": 1000}',
                                        '{"cpuUsage": 1e400}', '{"live_challenger_streak": 1e400}'))
    state = remote.fetch_daemon_state(_cfg(), now=1010.0)
    assert state.current_model == "a" and state.cpu_usage is None
    assert state.manager["streak"] == 0


def test_fetch_daemon_state_reads_last_model_load_error(monkeypatch):
    _capture(monkeypatch, _state_output(
        '{"current_model": "a", "warm_models": ["a"], "written_at": 1000, '
        '"last_model_load_error": {"model": "b", "message": "oom", "at": 990}}'))
    state = remote.fetch_daemon_state(_cfg(), now=1010.0)
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
        state = remote.fetch_daemon_state(_cfg(), now=1010.0)
        assert state.current_model == "a"
        assert (state.last_model_load_error_model, state.last_model_load_error_message,
                state.last_model_load_error_at) == expected


def test_ledger_ingestion_includes_base_rewards(tmp_path, capsys):
    import json
    import sqlite3

    ledger = tmp_path / "earnings.sqlite3"
    with sqlite3.connect(ledger) as conn:
        conn.execute("CREATE TABLE payouts (id INTEGER PRIMARY KEY, model TEXT, completion_tokens INTEGER, "
                     "micro_usd INTEGER, created_at REAL, provider_hash TEXT)")
        conn.executemany("INSERT INTO payouts VALUES (?,?,?,?,?,?)", [
            (1, "base_reward", 0, 2000, 10.0, "m1"),
            (2, "nemotron", 100, 30, 11.0, "m1"),
            (3, "base_reward", 0, 1800, 12.0, "m3"),
            (4, "nemotron", 10, 50, 13.0, "m1"),
        ])
    exec(remote._PAYOUTS_SNIPPET.format(db_path=str(ledger), since_rowid=0, batch_size=2))
    rows = json.loads(capsys.readouterr().out)
    assert [row[0] for row in rows] == [1, 2]
    assert sum(row[3] for row in rows if row[5] == "m1") == 2030
    exec(remote._PAYOUTS_SNIPPET.format(db_path=str(ledger), since_rowid=2, batch_size=2))
    assert [row[0] for row in json.loads(capsys.readouterr().out)] == [3, 4]


def test_manager_report_preserves_score_snapshot():
    import json
    snapshot = {"observed_at": 1000, "models": {"oss": {"eligible": True, "score": .104}}}
    report = remote._manager_report(json.dumps({"last_score_snapshot": snapshot}), "321", 1001, 180)
    assert report["score_snapshot"] == snapshot
