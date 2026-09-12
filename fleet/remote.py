"""SSH-based ingestion from the managed host. Read-only except execute_switch
and the fast-switch watcher controls, all gated by Config.live_execution and
never called from the default observe-mode collector path. No hostnames or
credentials live here — the SSH target and key path come from Config, which
reads them from the environment.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path

from .config import Config
from .types import DaemonState, Payout

DAEMON_STATE_PATH = "~/.darkbloom/daemon-state.json"
EARNINGS_DB_PATH = "~/.darkbloom-widget/earnings-observation.sqlite3"

FAST_SWITCH_WATCHER_ASSET = Path(__file__).parent / "remote_assets" / "fast_switch_watcher.py"
FAST_SWITCH_REMOTE_DIR = "~/.darkbloom-widget"
FAST_SWITCH_SCRIPT_PATH = f"{FAST_SWITCH_REMOTE_DIR}/fast_switch_watcher.py"
FAST_SWITCH_STATE_PATH = f"{FAST_SWITCH_REMOTE_DIR}/fleet-target.json"

_PAYOUTS_SNIPPET = """
import json, sqlite3
from pathlib import Path
db = sqlite3.connect((Path.home() / {db_path!r}).expanduser().as_uri() + "?mode=ro", uri=True)
rows = db.execute(
    "SELECT rowid, model, completion_tokens, micro_usd, created_at FROM payouts "
    "WHERE rowid > ? AND model != 'base_reward' ORDER BY rowid", ({since_rowid},)
).fetchall()
print(json.dumps(rows))
"""


def _run_ssh(cfg: Config, remote_command: str, timeout: float) -> str:
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    if cfg.ssh_config_path:
        command += ["-F", cfg.ssh_config_path]
    if cfg.ssh_key_path:
        command += ["-i", cfg.ssh_key_path]
    command += [cfg.ssh_target, remote_command]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"ssh command failed: {detail}")
    return result.stdout


def fetch_daemon_state(cfg: Config, now: float | None = None) -> DaemonState:
    """Read the provider's own daemon-state.json. Raises on any failure —
    the caller decides how to degrade; this never fabricates a state."""
    raw = _run_ssh(cfg, f"cat {DAEMON_STATE_PATH}", timeout=15)
    payload = json.loads(raw)
    current_time = time.time() if now is None else now
    written_at = float(payload.get("written_at") or 0)
    return DaemonState(
        current_model=str(payload["current_model"]) if payload.get("current_model") else None,
        warm_models=_model_ids(payload, "warm_models"),
        inference_active=bool(payload.get("inference_active")),
        pid=int(payload.get("pid") or 0),
        started_at=float(payload.get("started_at") or 0),
        fresh=written_at > 0 and 0 <= current_time - written_at <= cfg.daemon_freshness_seconds,
        advertised_models=_model_ids(payload, "advertised_models"),
        requests_served=int((payload.get("stats") or {}).get("requests_served") or 0),
        trust_level=_text((payload.get("trust") or {}).get("trust_level")),
        trust_reason=_text((payload.get("trust") or {}).get("reason")),
    )


def _text(value: object) -> str | None:
    return str(value) if value else None


def _model_ids(payload: dict[str, object], key: str) -> tuple[str, ...]:
    values = payload.get(key)
    return tuple(str(m) for m in values if m) if isinstance(values, list) else ()


def fetch_new_payouts(cfg: Config, since_rowid: int) -> list[Payout]:
    """Ground-truth $/model/hour, read-only, from the real payouts ledger."""
    script = _PAYOUTS_SNIPPET.format(db_path=EARNINGS_DB_PATH.removeprefix("~/"), since_rowid=int(since_rowid))
    remote_command = f"{shlex.quote(cfg.remote_python)} - <<'PY'\n{script}\nPY"
    raw = _run_ssh(cfg, remote_command, timeout=20)
    rows = json.loads(raw)
    return [Payout(rowid=r[0], model=r[1], completion_tokens=r[2] or 0, micro_usd=r[3] or 0, created_at=r[4]) for r in rows]


def execute_switch(cfg: Config, target_model: str) -> None:
    """Live mode only. Caller must have already confirmed idle + dwell +
    backoff; this makes no safety checks of its own — see collector.py."""
    if not cfg.live_execution:
        raise RuntimeError("refusing to execute a switch: FLEET_LIVE_EXECUTION is not enabled")
    command = f"darkbloom start --model {shlex.quote(target_model)} --idle-timeout 0"
    _run_ssh(cfg, command, timeout=300)


def clear_fast_switch_target(cfg: Config) -> None:
    """Live mode only. Removes the watcher's target, so a watcher still running
    from an earlier tick can never act on a decision that no longer stands."""
    if not cfg.live_execution:
        raise RuntimeError("refusing to change the watcher target: FLEET_LIVE_EXECUTION is not enabled")
    _run_ssh(cfg, f"rm -f {FAST_SWITCH_STATE_PATH}", timeout=15)


def launch_fast_switch_watcher(cfg: Config, target: str, max_seconds: float) -> None:
    """Live mode only. Deploys fast_switch_watcher.py to the remote host and
    launches it in the background (idempotent - safe to call every tick: the
    watcher holds an exclusive lock, so a call while one is already running
    just re-deploys the script/state and exits without a second poller). The
    watcher re-reads its target from the state file written here each time
    rather than a fixed argument, so it self-corrects if the recommendation
    changes mid-wait. See collector.py and README for why this exists."""
    if not cfg.live_execution:
        raise RuntimeError("refusing to launch the fast-poll watcher: FLEET_LIVE_EXECUTION is not enabled")
    script = FAST_SWITCH_WATCHER_ASSET.read_text()
    state = json.dumps({
        "target": target,
        "valid_targets": list(cfg.models),
        "max_seconds": max_seconds,
        "restart_backoff_seconds": cfg.restart_backoff_seconds,
        "written_at": time.time(),
    })
    script_tmp = f"{FAST_SWITCH_SCRIPT_PATH}.tmp"
    state_tmp = f"{FAST_SWITCH_STATE_PATH}.tmp"
    # set -e and rename-into-place: a failed write can never launch a stale
    # script or leave a stale target behind.
    remote_command = (
        "set -e\n"
        f"mkdir -p {FAST_SWITCH_REMOTE_DIR}\n"
        f"cat > {script_tmp} <<'PY'\n{script}\nPY\n"
        f"cat > {state_tmp} <<'JSON'\n{state}\nJSON\n"
        f"mv -f {script_tmp} {FAST_SWITCH_SCRIPT_PATH}\n"
        f"mv -f {state_tmp} {FAST_SWITCH_STATE_PATH}\n"
        f"nohup {shlex.quote(cfg.remote_python)} {FAST_SWITCH_SCRIPT_PATH} </dev/null >/dev/null 2>&1 &"
    )
    _run_ssh(cfg, remote_command, timeout=20)
