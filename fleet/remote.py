"""SSH-based ingestion from the managed host. Read-only except execute_switch
and the fast-switch watcher controls; all of those are gated by
Config.live_execution except remove_fast_switch_target, the observe-mode
stale-target cleanup. No hostnames or credentials live here — the SSH target
and key path come from Config, which reads them from the environment.
"""
from __future__ import annotations

import json
import math
import shlex
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Config
from .types import DaemonState, Payout, Slot

DAEMON_STATE_PATH = "~/.darkbloom/daemon-state.json"
# Same binary the fast-switch watcher invokes as Path.home() / ".darkbloom" /
# "bin" / "darkbloom". Bare `darkbloom` is not on non-interactive SSH PATH.
DARKBLOOM_BIN = "~/.darkbloom/bin/darkbloom"
EARNINGS_DB_PATH = "~/.darkbloom-widget/earnings-observation.sqlite3"
WIDGET_METRICS_DB_PATH = "~/.darkbloom-widget/metrics.db"
MANAGER_STATE_PATH = "~/.local/share/benbuschmann-darkbloom-manager/state.json"
MANAGER_OBSERVER_DB_PATH = "~/.darkbloom-widget/manager-observer/decisions.sqlite3"
_WIDGET_LATEST_SQL = "select json from samples order by timestamp desc limit 1"
# Printed between the two documents so one SSH round trip can carry both; the
# daemon doc is JSON, so a distinctive marker line can never occur inside it.
_DOC_SEPARATOR = "___fleet-docs___"
_STATE_COMMAND = (
    f"cat {DAEMON_STATE_PATH} && printf '\\n{_DOC_SEPARATOR}\\n' && "
    f"(sqlite3 {WIDGET_METRICS_DB_PATH} '{_WIDGET_LATEST_SQL}' || true) && "
    f"printf '\\n{_DOC_SEPARATOR}\\n' && (cat {MANAGER_STATE_PATH} || true) && "
    f"printf '\\n{_DOC_SEPARATOR}\\n' && "
    "(launchctl print gui/$(id -u)/dev.darkbloom.warm-manager-live 2>/dev/null | "
    "awk '$1 == \"state\" && $3 == \"running\" {print 1; exit}' || true) && "
    f"printf '\\n{_DOC_SEPARATOR}\\n' && "
    f"(test -f {MANAGER_OBSERVER_DB_PATH} && "
    "sqlite3 \"file:$HOME/.darkbloom-widget/manager-observer/decisions.sqlite3?mode=ro\" "
    "'select json from decisions order by t desc limit 1' || true)"
)
# Separate from _STATE_COMMAND: a slow or failed inventory read must not
# stall or fail the daemon snapshot that freshness is judged from.
_INVENTORY_COMMAND = f"{DARKBLOOM_BIN} models list --all --json"
_MAX_INSTALLED_MODELS = 256
_MAX_MODEL_ID_LENGTH = 256

FAST_SWITCH_WATCHER_ASSET = Path(__file__).parent / "remote_assets" / "fast_switch_watcher.py"
FAST_SWITCH_REMOTE_DIR = "~/.darkbloom-widget"
FAST_SWITCH_SCRIPT_PATH = f"{FAST_SWITCH_REMOTE_DIR}/fast_switch_watcher.py"
FAST_SWITCH_STATE_PATH = f"{FAST_SWITCH_REMOTE_DIR}/fleet-target.json"
COLD_BOOT_SECONDS = 300
REMOTE_WARMUP_SECONDS = 600
REMOTE_POLL_SECONDS = COLD_BOOT_SECONDS + REMOTE_WARMUP_SECONDS + 60

_LOCAL_WARMUP_SNIPPET = """
import json, os, subprocess, time, urllib.request
from urllib.parse import urlparse
cli = os.path.expanduser("~/.darkbloom/bin/darkbloom")
models = {models}
deadline = time.monotonic() + {warmup_seconds}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None
for _ in range(24):
    try:
        if time.monotonic() >= deadline:
            raise RuntimeError("local warm-up timed out")
        local = json.loads(subprocess.check_output([cli, "local", "--json"]))
        if urlparse(local["base_url"]).hostname not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("local endpoint is not loopback")
        for model in models:
            body = json.dumps({{"model": model, "messages": [{{"role": "user", "content": "Reply OK."}}], "max_tokens": 1}}).encode()
            request = urllib.request.Request(local["base_url"] + "/chat/completions", body, {{
                "Authorization": "Bearer " + local["api_key"], "Content-Type": "application/json"}})
            remaining = max(1, deadline - time.monotonic())
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=min(120, remaining)) as response:
                response.read()
        state = json.load(open(os.path.expanduser("~/.darkbloom/daemon-state.json")))
        trust = state.get("trust") if isinstance(state.get("trust"), dict) else {{}}
        if (set(state.get("warm_models") or ()) == set(models)
                and trust.get("trust_level") == "hardware" and time.time() - float(state.get("written_at") or 0) <= 90):
            break
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    except (KeyError, OSError, subprocess.SubprocessError, TypeError, ValueError):
        time.sleep(5)
else:
    raise SystemExit("local endpoint did not pass warm-up and daemon checks")
"""

_PAYOUTS_SNIPPET = """
import json, sqlite3
from pathlib import Path
db = sqlite3.connect((Path.home() / {db_path!r}).expanduser().as_uri() + "?mode=ro", uri=True)
rows = db.execute(
    "SELECT rowid, model, completion_tokens, micro_usd, created_at, provider_hash FROM payouts "
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
    """Read the provider's own daemon-state.json plus the latest Mac widget
    metrics sample in one SSH round trip. Raises only when the daemon doc
    itself is unreadable — a missing or malformed widget row degrades to None
    fields. The caller decides how to degrade; this never fabricates a state."""
    raw = _run_ssh(cfg, _STATE_COMMAND, timeout=15)
    daemon_raw, widget_raw, manager_raw, manager_pid, observer_raw = _split_documents(raw)
    payload = json.loads(daemon_raw)
    widget = _widget_metrics(widget_raw)
    current_time = time.time() if now is None else now
    written_at = float(payload.get("written_at") or 0)
    trust = _section(payload, "trust")
    gpu_active, gpu_cache, gpu_total = _capacity_gbs(payload)
    load_error = _model_load_error(payload)
    return DaemonState(
        current_model=_text(payload.get("current_model")),
        warm_models=_model_ids(payload, "warm_models"),
        inference_active=bool(payload.get("inference_active")),
        pid=int(payload.get("pid") or 0),
        started_at=float(payload.get("started_at") or 0),
        # abs(): a Mac clock slightly ahead of ours must not read as stale forever.
        fresh=written_at > 0 and abs(current_time - written_at) <= cfg.daemon_freshness_seconds,
        advertised_models=_model_ids(payload, "advertised_models"),
        requests_served=int(_section(payload, "stats").get("requests_served") or 0),
        trust_level=_text(trust.get("trust_level")),
        trust_reason=_text(trust.get("reason")),
        thermal_state=_text(widget.get("thermalState")),
        memory_pressure=_optional_float(widget, "memoryPressure"),
        cpu_usage=_optional_float(widget, "cpuUsage"),
        fan_rpm=_optional_float(widget, "fanRPM"),
        peak_temperature_c=_optional_float(widget, "peakTemperatureC"),
        gpu_active_gb=gpu_active if gpu_active is not None else _optional_float(widget, "gpuActiveGb"),
        gpu_cache_gb=gpu_cache,
        total_memory_gb=gpu_total,
        slots=_slots(payload),
        last_model_load_error_model=load_error[0],
        last_model_load_error_message=load_error[1],
        last_model_load_error_at=load_error[2],
        manager=_manager_report(manager_raw, manager_pid),
        manager_observer=_manager_observer_report(observer_raw),
    )


def fetch_installed_models(cfg: Config) -> tuple[str, ...]:
    """Read-only local-cache ids. Observation only — not gated by live
    execution. Raises on SSH failure or malformed JSON/shape; an empty
    tuple is a verified empty cache. Presence of an id means on disk."""
    raw = _run_ssh(cfg, _INVENTORY_COMMAND, timeout=20)
    ids = _parse_installed_model_ids(raw)
    if ids is None:
        raise RuntimeError("installed-model inventory is malformed")
    return ids


def fetch_model_memory(cfg: Config) -> dict[str, float]:
    """Estimated resident GB from the installed-model inventory."""
    raw = _run_ssh(cfg, _INVENTORY_COMMAND, timeout=20)
    try:
        models = json.loads(raw)["models"]
        memory = {str(item["id"]): float(item["estimated_memory_gb"]) for item in models}
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("installed-model memory inventory is malformed") from None
    if not memory or any(not math.isfinite(value) or value <= 0 for value in memory.values()):
        raise RuntimeError("installed-model memory inventory is malformed")
    return memory


def _installed_model_id(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id or len(model_id) > _MAX_MODEL_ID_LENGTH:
        return None
    return model_id


def _parse_installed_model_ids(raw: str) -> tuple[str, ...] | None:
    """Non-empty string models[].id values, first-seen order. None = unknown
    (malformed item, oversize id/list, or unreadable JSON/shape). An empty
    list is verified empty, not unknown."""
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    models = payload.get("models")
    if not isinstance(models, list) or len(models) > _MAX_INSTALLED_MODELS:
        return None
    ids: list[str] = []
    for item in models:
        model_id = _installed_model_id(item)
        if model_id is None:
            return None
        ids.append(model_id)
    return tuple(dict.fromkeys(ids))


def _split_documents(raw: str) -> tuple[str, str, str, str, str]:
    """Daemon, widget, live manager state/PID, and legacy observer report."""
    docs = raw.split(f"\n{_DOC_SEPARATOR}\n", 4)
    return tuple((docs + ["", "", "", "", ""])[:5])


def _manager_report(raw: str, pid: str) -> dict[str, object]:
    running = pid.strip().isdigit()
    try:
        state = json.loads(raw)
    except ValueError:
        state = None
    if not isinstance(state, dict):
        return {"running": running, "mode": "LIVE" if running else "OFF"}
    return {
        "running": running, "mode": "LIVE" if running else "OFF",
        "version": _text(state.get("manager_version")),
        "as_of": _optional_float(state, "last_decision_at"),
        "current_model": _text(state.get("current_model")),
        "target_model": _text(state.get("last_decision_target")),
        "reason": _text(state.get("last_decision_reason")),
        "challenger_model": _text(state.get("live_challenger_model")),
        "streak": _optional_integer(state.get("live_challenger_streak")),
    }


def _manager_observer_report(raw: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    state = _section(payload, "manager_state")
    provenance = _section(payload, "provenance")
    errors = _section(payload, "errors")
    return {
        "mode": "OBSERVE", "version": _text(provenance.get("manager_version")),
        "as_of": _optional_float(payload, "t"),
        "current_model": _text(state.get("current_model")),
        "target_model": _text(state.get("last_decision_target")),
        "reason": _text(state.get("last_decision_reason")),
        "error": ", ".join(sorted(str(key) for key in errors)) or None,
    }


def _optional_integer(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _widget_metrics(raw: str) -> dict[str, object]:
    """The widget's latest sample row, or {} when the DB is absent (empty
    output), empty-table, or holds anything but a JSON object."""
    raw = raw.strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _optional_float(payload: dict[str, object], key: str) -> float | None:
    """A finite float, or None: NaN/inf would poison the gauges and the
    Postgres columns just as silently as a missing key."""
    value = payload.get(key)
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _capacity_gbs(payload: dict[str, object]) -> tuple[float | None, float | None, float | None]:
    """(active, cache, total) GB from the daemon's capacity section; a missing
    or malformed section leaves all three None rather than failing the read."""
    capacity = _section(payload, "capacity")
    return (_optional_float(capacity, "gpu_memory_active_gb"),
            _optional_float(capacity, "gpu_memory_cache_gb"),
            _optional_float(capacity, "total_memory_gb"))


def _optional_bool(payload: dict[str, object], key: str) -> bool | None:
    value = payload.get(key)
    return bool(value) if isinstance(value, bool) else None


def _slots(payload: dict[str, object]) -> tuple[Slot, ...]:
    values = payload.get("slots")
    if not isinstance(values, list):
        return ()
    slots = []
    for item in values:
        if isinstance(item, dict) and item.get("model"):
            slots.append(Slot(
                model=str(item["model"]),
                kv_backend=_text(item.get("kv_backend")),
                mtp_enabled=_optional_bool(item, "mtp_enabled"),
                mtp_active=_optional_bool(item, "mtp_active"),
                mtp_inactive_reason=_text(item.get("mtp_inactive_reason")),
            ))
    return tuple(slots)


def _model_load_error(payload: dict[str, object]) -> tuple[str | None, str | None, float | None]:
    """(model, message, at) from daemon-state.json. A missing, non-object, or
    non-finite value becomes None and never fails the rest of the read."""
    raw = payload.get("last_model_load_error")
    if not isinstance(raw, dict):
        return None, None, None
    return _text(raw.get("model")), _text(raw.get("message")), _optional_float(raw, "at")


def _section(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


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
    return [Payout(rowid=r[0], model=r[1], completion_tokens=r[2] or 0, micro_usd=r[3] or 0,
                   created_at=r[4], provider_hash=r[5] or None) for r in rows]


def _checked_models(cfg: Config, target_models: str | tuple[str, ...]) -> tuple[str, ...]:
    if not cfg.live_execution:
        raise RuntimeError("refusing to execute a switch: FLEET_LIVE_EXECUTION is not enabled")
    if not cfg.api_key:
        raise RuntimeError("refusing to switch without a consumer API key for verification")
    requested = (target_models,) if isinstance(target_models, str) else target_models
    models = tuple(dict.fromkeys(requested))
    if not models:
        raise RuntimeError("refusing to switch without a target model")
    return models


def _cold_boot_launch(cfg: Config, models: tuple[str, ...]) -> tuple[str, str]:
    model_args = " ".join(f"--model {shlex.quote(model)}" for model in models)
    warmup = _LOCAL_WARMUP_SNIPPET.format(
        models=json.dumps(models), warmup_seconds=REMOTE_WARMUP_SECONDS)
    operation = (
        "set -e\n"
        "$HOME/.darkbloom/bin/darkbloom stop\n"
        f"sleep {COLD_BOOT_SECONDS}\n"
        f"$HOME/.darkbloom/bin/darkbloom start {model_args} --idle-timeout 0 --local-endpoint\n"
        f"{shlex.quote(cfg.remote_python)} - <<'PY'\n{warmup}\nPY"
    )
    script = f"{FAST_SWITCH_REMOTE_DIR}/fleet-cold-boot.sh"
    status = f"{FAST_SWITCH_REMOTE_DIR}/fleet-cold-boot.status"
    pid_file = f"{FAST_SWITCH_REMOTE_DIR}/fleet-cold-boot.pid"
    launch = (
        "set -e\n"
        f"mkdir -p {FAST_SWITCH_REMOTE_DIR}\n"
        f"rm -f {status}\n"
        f"cat > {script}.tmp <<'SH'\n"
        "#!/bin/sh\n"
        f"status={status}\n"
        f"pid_file={pid_file}\n"
        "finish() { code=$?; rm -f \"$pid_file\"; printf '%s\\n' \"$code\" > \"$status.tmp\"; mv -f \"$status.tmp\" \"$status\"; }\n"
        "trap finish EXIT\n"
        f"{operation}\nSH\n"
        f"mv -f {script}.tmp {script}\n"
        f"nohup /bin/sh {script} </dev/null >{FAST_SWITCH_REMOTE_DIR}/fleet-cold-boot.log 2>&1 & "
        f"echo $! > {pid_file}"
    )
    _run_ssh(cfg, launch, timeout=20)
    return status, pid_file


def _check_cold_boot_result(result: str) -> bool:
    if not result:
        return False
    if result != "0":
        raise RuntimeError(f"remote cold boot failed with exit {result}")
    return True


def _wait_for_cold_boot(cfg: Config, status: str, pid_file: str) -> None:
    deadline = time.monotonic() + REMOTE_POLL_SECONDS
    while time.monotonic() < deadline:
        try:
            result = _run_ssh(cfg, f"test -f {status} && cat {status} || true", timeout=20).strip()
        except RuntimeError:
            time.sleep(5)
            continue
        if _check_cold_boot_result(result):
            break
        time.sleep(5)
    else:
        _run_ssh(
            cfg,
            f"pid=$(cat {pid_file} 2>/dev/null || true); "
            "case \"$pid\" in ''|*[!0-9]*) exit 0;; esac; kill \"$pid\" 2>/dev/null || true",
            timeout=20,
        )
        raise TimeoutError("remote cold boot did not finish")


def execute_switch(cfg: Config, target_models: str | tuple[str, ...]) -> None:
    """Run one checked, detached cold boot after the caller's safety gates."""
    models = _checked_models(cfg, target_models)
    clear_fast_switch_target(cfg)
    status, pid_file = _cold_boot_launch(cfg, models)
    _wait_for_cold_boot(cfg, status, pid_file)
    for model in models:
        _submit_api_warmup(cfg, model)


def _submit_api_warmup(cfg: Config, target_model: str) -> None:
    if urllib.parse.urlsplit(cfg.base_url).scheme != "https":
        raise RuntimeError("refusing to send the consumer API key over a non-HTTPS URL")
    body = json.dumps({
        "model": target_model,
        "messages": [{"role": "user", "content": "Reply OK."}],
        "max_tokens": 1,
    }).encode()
    request = urllib.request.Request(
        cfg.base_url.rstrip("/") + "/v1/chat/completions", body,
        {"Authorization": "Bearer " + str(cfg.api_key), "Content-Type": "application/json",
         "X-Darkbloom-Route": "self"},
    )
    opener = urllib.request.build_opener(_NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=120) as response:
                response.read()
            return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(10)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def clear_fast_switch_target(cfg: Config) -> None:
    """Live mode only. Removes the watcher's target, so a watcher still running
    from an earlier tick can never act on a decision that no longer stands."""
    if not cfg.live_execution:
        raise RuntimeError("refusing to change the watcher target: FLEET_LIVE_EXECUTION is not enabled")
    _run_ssh(cfg, f"rm -f {FAST_SWITCH_STATE_PATH}", timeout=15)


def remove_fast_switch_target(cfg: Config) -> None:
    """Unguarded counterpart to clear_fast_switch_target: the same plain rm -f,
    allowed in observe mode so a target written by an earlier live tick is not
    left behind for a still-running watcher to act on."""
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
        "daemon_freshness_seconds": cfg.daemon_freshness_seconds,
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
