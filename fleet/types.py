"""Shared dataclasses passed between ingestion, scoring and persistence."""
from __future__ import annotations

from dataclasses import dataclass

# A last_model_load_error this recent blocks a switch to that same model.
LOAD_ERROR_BLOCK_SECONDS = 120


@dataclass(frozen=True)
class CapacitySample:
    model: str
    active_requests: int
    warm_providers: int
    pressure: float  # active_requests / max(1, warm_providers)


@dataclass(frozen=True)
class Slot:
    model: str
    kv_backend: str | None = None  # e.g. "paged"
    mtp_enabled: bool | None = None  # multi-token prediction compiled in
    mtp_active: bool | None = None
    mtp_inactive_reason: str | None = None


@dataclass(frozen=True)
class DaemonState:
    current_model: str | None
    warm_models: tuple[str, ...]
    inference_active: bool
    pid: int
    started_at: float
    fresh: bool  # written_at within Config.daemon_freshness_seconds of "now"
    advertised_models: tuple[str, ...] = ()  # offered to the coordinator; a superset of warm_models
    requests_served: int = 0  # this daemon session's counter; resets on restart
    trust_level: str | None = None  # coordinator-granted: hardware | self_signed | ...; only "hardware" is routable
    trust_reason: str | None = None  # e.g. "continuity", "awaiting MDM verification"
    # Mac widget metrics (~/.darkbloom-widget/metrics.db, latest sample); None when no widget runs there.
    thermal_state: str | None = None  # macOS thermal state name, e.g. "nominal"
    memory_pressure: float | None = None  # 0-1
    cpu_usage: float | None = None  # 0-1
    fan_rpm: float | None = None
    peak_temperature_c: float | None = None
    # GPU memory from the daemon's own capacity section; gpu_active_gb falls back
    # to the widget's gpuActiveGb when the daemon does not report one.
    gpu_active_gb: float | None = None
    gpu_cache_gb: float | None = None
    total_memory_gb: float | None = None
    slots: tuple[Slot, ...] = ()  # one entry per model the daemon keeps resident
    # Last failed model load from daemon-state.json; each field is None when
    # the object is missing, malformed, or that value is non-finite.
    last_model_load_error_model: str | None = None
    last_model_load_error_message: str | None = None
    last_model_load_error_at: float | None = None  # absolute unix timestamp
    # Local-cache ids from `darkbloom models list --all --json`. None = unknown
    # this tick; () = verified empty. Presence of an id means on disk.
    installed_models: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Payout:
    rowid: int
    model: str
    completion_tokens: int
    micro_usd: int
    created_at: float
    provider_hash: str | None = None  # provider session; identifies the serving host (see attribution.py)


@dataclass(frozen=True)
class Decision:
    target: str | None
    reason: str
    action: str  # KEEP | SWITCH | SWITCH_WHEN_IDLE | WOULD_SWITCH | WAIT | BLOCKED
    models: tuple[str, ...] = ()  # exact launch set; empty means target only


@dataclass(frozen=True)
class Guardrails:
    relative_margin: float
    absolute_margin: float
    switch_cost_seconds: float
    decision_horizon_seconds: float
    min_dwell_seconds: float


@dataclass(frozen=True)
class Outcome:
    mode: str  # live | observe
    executed: bool
    error: str | None
