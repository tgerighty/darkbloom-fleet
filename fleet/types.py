"""Shared dataclasses passed between ingestion, scoring and persistence."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapacitySample:
    model: str
    active_requests: int
    warm_providers: int
    pressure: float  # active_requests / max(1, warm_providers)


@dataclass(frozen=True)
class DaemonState:
    current_model: str | None
    warm_models: tuple[str, ...]
    inference_active: bool
    pid: int
    started_at: float
    fresh: bool  # written_at within Config.daemon_freshness_seconds of "now"


@dataclass(frozen=True)
class Payout:
    rowid: int
    model: str
    completion_tokens: int
    micro_usd: int
    created_at: float


@dataclass(frozen=True)
class Decision:
    target: str | None
    reason: str
    action: str  # KEEP | SWITCH | SWITCH_WHEN_IDLE | WOULD_SWITCH | WAIT | BLOCKED


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
