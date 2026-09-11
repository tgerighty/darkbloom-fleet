"""Environment-driven configuration. No secrets or real hostnames live here
or anywhere else in this repo — see README "Security". Every value that
identifies a real host or credential comes from the environment or a
mounted secret at deploy time.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Guardrail defaults below are the values validated in the darkbloom-manager
# project's 2026-09-11 backtest (54.5h of real earnings-ledger data). See
# CONFIG.md for the full rationale and numbers.
DEFAULT_MODELS = ("qwen3.5-35b-a3b", "gemma-4-26b-qat-4bit", "gpt-oss-20b")
DEFAULT_WEIGHTS = {
    "qwen3.5-35b-a3b": 1.25,
    "qwen3.6-35b-a3b-vl-mtp-mxfp8": 1.20,
    "gemma-4-26b-qat-4bit": 1.05,
    "gpt-oss-20b": 1.00,
}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class Config:
    ssh_target: str
    ssh_key_path: str | None
    remote_python: str
    host_label: str
    host_spec: str
    database_url: str
    poll_interval_seconds: float
    models: tuple[str, ...]
    weights: dict[str, float]
    ema_tau_minutes: float
    relative_margin: float
    absolute_margin: float
    switch_cost_seconds: float
    decision_horizon_seconds: float
    min_dwell_seconds: float
    daemon_freshness_seconds: float
    restart_backoff_seconds: float
    live_execution: bool
    base_url: str
    pricing_url: str
    dashboard_port: int


def load_configs() -> tuple[Config, ...]:
    # Hosts are DARKBLOOM_HOST_1_*, _2_*, ... until the first missing SSH_TARGET.
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required (postgres connection string)")

    shared = dict(
        database_url=database_url,
        poll_interval_seconds=_float_env("POLL_INTERVAL_SECONDS", 60.0),
        weights=dict(DEFAULT_WEIGHTS),
        ema_tau_minutes=_float_env("FLEET_EMA_TAU_MINUTES", 20.0),
        relative_margin=_float_env("FLEET_RELATIVE_MARGIN", 0.25),
        absolute_margin=_float_env("FLEET_ABSOLUTE_MARGIN", 0.01),
        switch_cost_seconds=_float_env("FLEET_SWITCH_COST_SECONDS", 300.0),
        decision_horizon_seconds=_float_env("FLEET_DECISION_HORIZON_SECONDS", 3600.0),
        min_dwell_seconds=_float_env("FLEET_MIN_DWELL_SECONDS", 1800.0),
        daemon_freshness_seconds=_float_env("FLEET_DAEMON_FRESHNESS_SECONDS", 90.0),
        restart_backoff_seconds=_float_env("FLEET_RESTART_BACKOFF_SECONDS", 30.0),
        base_url=os.environ.get("DARKBLOOM_BASE_URL", "https://api.darkbloom.dev"),
        pricing_url=os.environ.get("DARKBLOOM_PRICING_URL", "https://api.darkbloom.dev/v1/pricing"),
        dashboard_port=int(os.environ.get("FLEET_DASHBOARD_PORT", "8080")),
    )
    default_live = _bool_env("FLEET_LIVE_EXECUTION", False)

    configs: list[Config] = []
    n = 1
    while True:
        prefix = f"DARKBLOOM_HOST_{n}_"
        ssh_target = os.environ.get(prefix + "SSH_TARGET")
        if not ssh_target:
            break
        models_raw = os.environ.get(prefix + "MODELS")
        models = tuple(m.strip() for m in models_raw.split(",") if m.strip()) if models_raw else DEFAULT_MODELS
        configs.append(Config(
            ssh_target=ssh_target,
            ssh_key_path=os.environ.get(prefix + "SSH_KEY_PATH") or None,
            remote_python=os.environ.get(prefix + "REMOTE_PYTHON", "python3"),
            host_label=os.environ.get(prefix + "LABEL", ssh_target),
            host_spec=os.environ.get(prefix + "SPEC", "unknown"),
            models=models,
            live_execution=_bool_env(prefix + "LIVE_EXECUTION", default_live),
            **shared,
        ))
        n += 1
    if not configs:
        raise RuntimeError(
            "At least one host is required: set DARKBLOOM_HOST_1_SSH_TARGET "
            "(an SSH host/alias, e.g. from ~/.ssh/config), plus _LABEL/_SPEC/_MODELS as needed"
        )
    return tuple(configs)
