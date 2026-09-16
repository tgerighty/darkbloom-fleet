"""Read-only SSH ingestion of provider, manager, inventory, and earnings data."""
from __future__ import annotations

import json
import math
import shlex
import subprocess
import time
from .config import Config
from .types import DaemonState, Payout, Slot

DAEMON_STATE_PATH = "~/.darkbloom/daemon-state.json"
# Bare `darkbloom` is not on the non-interactive SSH PATH.
DARKBLOOM_BIN = "~/.darkbloom/bin/darkbloom"
EARNINGS_DB_PATH = "~/.darkbloom-widget/earnings-observation.sqlite3"
WIDGET_METRICS_DB_PATH = "~/.darkbloom-widget/metrics.db"
MANAGER_STATE_PATH = "~/.local/share/benbuschmann-darkbloom-manager/state.json"
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
    "awk '$1 == \"state\" && $3 == \"running\" {print 1; exit}' || true)"
)
# Separate from _STATE_COMMAND: a slow or failed inventory read must not
# stall or fail the daemon snapshot that freshness is judged from.
_INVENTORY_COMMAND = f"{DARKBLOOM_BIN} models list --all --json"
_MAX_INSTALLED_MODELS = 256
_MAX_MODEL_ID_LENGTH = 256

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
    daemon_raw, widget_raw, manager_raw, manager_pid = _split_documents(raw)
    payload = json.loads(daemon_raw)
    widget = _widget_metrics(widget_raw)
    current_time = time.time() if now is None else now
    written_at = float(payload.get("written_at") or 0)
    trust = _section(payload, "trust")
    gpu_active, gpu_cache, gpu_total = _capacity_gbs(payload)
    load_error = _model_load_error(payload)
    return DaemonState(
        attestation_public_key=_text(payload.get("attestation_public_key")),
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
        manager=_manager_report(manager_raw, manager_pid, current_time, cfg.daemon_freshness_seconds * 2),
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


def _split_documents(raw: str) -> tuple[str, str, str, str]:
    """Daemon, widget, manager state, and live-manager PID from one SSH read."""
    docs = raw.split(f"\n{_DOC_SEPARATOR}\n", 3)
    return tuple((docs + ["", "", "", ""])[:4])


def _manager_report(raw: str, pid: str, now: float, freshness_seconds: float) -> dict[str, object]:
    running = pid.strip().isdigit()
    try:
        state = json.loads(raw)
    except ValueError:
        state = None
    if not isinstance(state, dict):
        return {"running": running, "mode": "LIVE" if running else "OFF"}
    as_of = _optional_float(state, "last_decision_at")
    return {
        "running": running, "mode": "LIVE" if running else "OFF",
        "fresh": as_of is not None and abs(now - as_of) <= freshness_seconds,
        "version": _text(state.get("manager_version")),
        "as_of": as_of,
        "current_model": _text(state.get("current_model")),
        "target_model": _text(state.get("last_decision_target")),
        "reason": _text(state.get("last_decision_reason")),
        "challenger_model": _text(state.get("live_challenger_model")),
        "streak": _optional_integer(state.get("live_challenger_streak")),
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
