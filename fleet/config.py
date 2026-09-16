"""Environment-driven configuration. No secrets or real hostnames live here
or anywhere else in this repo — see README "Security". Every value that
identifies a real host or credential comes from the environment or a
mounted secret at deploy time.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from psycopg.conninfo import make_conninfo

# Demand score defaults retained for logged measurements.
DEFAULT_MODELS = ("qwen3.5-35b-a3b", "gemma-4-26b-qat-4bit", "gpt-oss-20b")
DEFAULT_WEIGHTS = {
    "qwen3.5-35b-a3b": 1.25,
    "qwen3.6-35b-a3b-vl-mtp-mxfp8": 1.20,
    "gemma-4-26b-qat-4bit": 1.05,
    "gpt-oss-20b": 1.00,
}
SECRETS_DIRECTORY = Path("/run/secrets")
_SECRET_FILENAMES = {
    "DATABASE_PASSWORD_FILE": "darkbloom_fleet_db_password",
    "DARKBLOOM_API_KEY_FILE": "darkbloom_fleet_api_key",
}


def _float_env(name: str, default: float, *, positive: bool = False) -> float:
    raw = os.environ.get(name)
    try:
        value = float(raw) if raw else default
    except ValueError:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        need = "> 0" if positive else ">= 0"
        raise RuntimeError(f"{name} must be a finite number {need}, got {raw!r}")
    return value


@dataclass(frozen=True)
class Config:
    ssh_target: str
    ssh_key_path: str | None
    remote_python: str
    host_label: str
    host_id: str
    host_spec: str
    database_url: str
    poll_interval_seconds: float
    models: tuple[str, ...]
    weights: dict[str, float]
    ema_tau_minutes: float
    switch_cost_seconds: float
    daemon_freshness_seconds: float
    base_url: str
    pricing_url: str
    dashboard_port: int
    ssh_config_path: str | None = None
    api_key: str | None = None  # consumer key for the self-route routability probe
    probe_self_route: bool = False  # the probe is account-wide, so only one host runs it


def _secret_file(name: str) -> str | None:
    filename = os.environ.get(name)
    if not filename:
        return None
    expected = _SECRET_FILENAMES[name]
    if filename != expected:
        raise RuntimeError(f"{name} must be {expected!r}")
    path = SECRETS_DIRECTORY / expected
    return path.read_text().strip() or None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required (postgres connection string)")
    password = _secret_file("DATABASE_PASSWORD_FILE")
    if password:
        url = make_conninfo(url, password=password)
    return url


def _require_unique(configs: list[Config], field: str, what: str) -> None:
    values = [getattr(c, field) for c in configs]
    if len(set(values)) != len(values):
        raise RuntimeError(f"{what} must be unique: {values}")


def _host_config(n: int, ssh_target: str, shared: dict[str, object]) -> Config:
    prefix = f"DARKBLOOM_HOST_{n}_"
    models_raw = os.environ.get(prefix + "MODELS")
    models = tuple(m.strip() for m in models_raw.split(",") if m.strip()) if models_raw else DEFAULT_MODELS
    return Config(
        ssh_target=ssh_target,
        ssh_key_path=os.environ.get(prefix + "SSH_KEY_PATH") or None,
        remote_python=os.environ.get(prefix + "REMOTE_PYTHON", "python3"),
        host_label=os.environ.get(prefix + "LABEL", ssh_target),
        host_id=os.environ.get(prefix + "ID") or ssh_target,
        host_spec=os.environ.get(prefix + "SPEC", "unknown"),
        models=models,
        probe_self_route=n == 1,
        **shared,
    )


def load_configs() -> tuple[Config, ...]:
    # Hosts are DARKBLOOM_HOST_1_*, _2_*, ... until the first missing SSH_TARGET.
    shared = {
        "database_url": _database_url(),
        "ssh_config_path": os.environ.get("DARKBLOOM_SSH_CONFIG") or None,
        "api_key": _secret_file("DARKBLOOM_API_KEY_FILE"),
        "poll_interval_seconds": _float_env("POLL_INTERVAL_SECONDS", 60.0, positive=True),
        "weights": dict(DEFAULT_WEIGHTS),
        "ema_tau_minutes": _float_env("FLEET_EMA_TAU_MINUTES", 20.0, positive=True),
        "switch_cost_seconds": _float_env("FLEET_SWITCH_COST_SECONDS", 300.0),
        "daemon_freshness_seconds": _float_env("FLEET_DAEMON_FRESHNESS_SECONDS", 90.0),
        "base_url": os.environ.get("DARKBLOOM_BASE_URL", "https://api.darkbloom.dev"),
        "pricing_url": os.environ.get("DARKBLOOM_PRICING_URL", "https://api.darkbloom.dev/v1/pricing"),
        "dashboard_port": int(os.environ.get("FLEET_DASHBOARD_PORT", "8080")),
    }
    configs: list[Config] = []
    n = 1
    while ssh_target := os.environ.get(f"DARKBLOOM_HOST_{n}_SSH_TARGET"):
        configs.append(_host_config(n, ssh_target, shared))
        n += 1
    if not configs:
        raise RuntimeError(
            "At least one host is required: set DARKBLOOM_HOST_1_SSH_TARGET "
            "(an SSH host/alias, e.g. from ~/.ssh/config), plus _LABEL/_SPEC/_MODELS as needed"
        )
    _require_unique(configs, "host_id", "host ids are the database identity and")
    _require_unique(configs, "host_label", "host labels (display only)")
    return tuple(configs)
