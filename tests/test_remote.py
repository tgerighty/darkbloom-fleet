"""Only the FLEET_LIVE_EXECUTION guard is tested here: both functions raise
before ever touching subprocess/SSH, so this needs no network and no mocking."""
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
