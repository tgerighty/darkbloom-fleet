"""SSH-based ingestion from the managed host. Read-only except execute_switch,
which is gated by Config.live_execution and is never called from the default
observe-mode collector path. No hostnames or credentials live here — the SSH
target and key path come from Config, which reads them from the environment.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import time

from .config import Config
from .types import DaemonState, Payout

DAEMON_STATE_PATH = "~/.darkbloom/daemon-state.json"
EARNINGS_DB_PATH = "~/.darkbloom-widget/earnings-observation.sqlite3"

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
    warm = tuple(str(m) for m in (payload.get("warm_models") or []) if m)
    return DaemonState(
        current_model=str(payload["current_model"]) if payload.get("current_model") else None,
        warm_models=warm,
        inference_active=bool(payload.get("inference_active")),
        pid=int(payload.get("pid") or 0),
        started_at=float(payload.get("started_at") or 0),
        fresh=written_at > 0 and current_time - written_at <= cfg.daemon_freshness_seconds,
    )


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
