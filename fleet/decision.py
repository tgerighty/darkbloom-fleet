"""Switch decision: EMA-smoothed scores + the source project's margins/dwell.

A SWITCH_WHEN_IDLE result means the challenger already clears every gate
except idle. The collector waits for a fresh idle tick before it starts the
checked cold boot.

Forked from darkbloom-manager's warm_model_manager.py (score formula, switch-
cost discount, relative/absolute margins) with the "N consecutive passing
checks" switch gate replaced by a 20-minute EMA of each candidate's score —
the improvement validated in that project's analysis/dry_run_switcher.py
against 54.5h of real earnings-ledger data (same revenue, 3-5x fewer
switches: 48 -> 3-16). See CONFIG.md for the full numbers. This module ports
`update_ema()` and `candidate_decision()` from that script almost verbatim.
"""
from __future__ import annotations

import math
from itertools import combinations

from .types import LOAD_ERROR_BLOCK_SECONDS, DaemonState, Decision, Guardrails

_SWITCH_ACTIONS = frozenset({"SWITCH", "SWITCH_WHEN_IDLE"})
_HOT_THERMAL = frozenset({"serious", "critical"})
HARDWARE_TRUST = "hardware"


def update_ema(ema: dict[str, float], scores: dict[str, float], dt_seconds: float, tau_minutes: float) -> dict[str, float]:
    """Exponential moving average of each model's score. dt_seconds since the
    last update; alpha follows the standard tau-based EMA formula."""
    alpha = 1 - math.exp(-dt_seconds / (tau_minutes * 60))
    updated = dict(ema)
    for model, score in scores.items():
        updated[model] = score if model not in updated else updated[model] + alpha * (score - updated[model])
    return updated


def _unscored_current(
    ema: dict[str, float],
    current_model: str | None,
    last_switch_at: float,
    now: float,
    inference_active: bool,
    guardrails: Guardrails,
) -> Decision:
    """No eligible current model: move to the best-scored one, but only
    through the same dwell and idle gates as any other switch."""
    best = max(ema, key=ema.get)
    if now - last_switch_at < guardrails.min_dwell_seconds:
        remaining = guardrails.min_dwell_seconds - (now - last_switch_at)
        return Decision(current_model, f"no eligible current model; minimum dwell has {remaining:.0f}s left", "KEEP")
    if inference_active:
        return Decision(best, f"no eligible current model; highest smoothed score {ema[best]:.3f}; waiting for idle", "SWITCH_WHEN_IDLE")
    return Decision(best, f"no eligible current model; highest smoothed score {ema[best]:.3f}", "SWITCH")


def decide(
    ema: dict[str, float],
    current_model: str | None,
    last_switch_at: float,
    now: float,
    inference_active: bool,
    guardrails: Guardrails,
) -> Decision:
    """Same switch-cost discount and margins as warm_model_manager's
    choose_scored_target(), applied to the EMA instead of a raw pressure
    average + consecutive-check counter."""
    if not ema:
        return Decision(current_model, "no scored models yet", "WAIT")
    if current_model not in ema:
        return _unscored_current(ema, current_model, last_switch_at, now, inference_active, guardrails)

    horizon = guardrails.decision_horizon_seconds
    discount = max(0.0, (horizon - guardrails.switch_cost_seconds) / horizon)
    adjusted = {m: (v if m == current_model else v * discount) for m, v in ema.items()}
    challenger = max(adjusted, key=adjusted.get)
    if challenger == current_model:
        return Decision(current_model, f"current model ranks first after switch cost ({ema[current_model]:.3f})", "KEEP")

    current_score = ema[current_model]
    challenger_score = adjusted[challenger]
    need = max(current_score * (1 + guardrails.relative_margin), current_score + guardrails.absolute_margin)
    if challenger_score < need:
        return Decision(
            current_model,
            f"{challenger} below margin ({challenger_score:.3f} vs current {current_score:.3f}; need >= {need:.3f})",
            "KEEP",
        )
    if now - last_switch_at < guardrails.min_dwell_seconds:
        remaining = guardrails.min_dwell_seconds - (now - last_switch_at)
        return Decision(current_model, f"{challenger} clears margin but minimum dwell has {remaining:.0f}s left", "KEEP")
    if inference_active:
        return Decision(
            challenger,
            f"{challenger} clears margin but provider is serving a request; waiting for idle",
            "SWITCH_WHEN_IDLE",
        )
    return Decision(
        challenger,
        f"{challenger} clears margin on smoothed score ({challenger_score:.3f} vs {current_score:.3f})",
        "SWITCH",
    )


def decide_pair(
    ema: dict[str, float], warm_models: tuple[str, ...], last_switch_at: float,
    now: float, inference_active: bool, guardrails: Guardrails,
    model_memory_gb: dict[str, float], memory_limit_gb: float,
) -> Decision:
    """Rank a two-model resident set by its combined smoothed earnings score."""
    if len(ema) < 2:
        current = next((model for model in warm_models if model in ema), None)
        return decide(ema, current, last_switch_at, now, inference_active, guardrails)
    pairs = [pair for pair in combinations(ema, 2)
             if all(model in model_memory_gb for model in pair)
             and sum(model_memory_gb[model] for model in pair) <= memory_limit_gb]
    if not pairs:
        current = next((model for model in warm_models if model in ema), None)
        return decide(ema, current, last_switch_at, now, inference_active, guardrails)
    pair = max(pairs, key=lambda models: sum(ema[model] for model in models))
    pair = tuple(sorted(pair, key=ema.get, reverse=True))
    current = tuple(model for model in warm_models if model in ema)[:2]
    if set(pair).issubset(warm_models):
        return Decision(pair[0], f"best model pair is already warm: {', '.join(pair)}", "KEEP", pair)
    current_score = sum(ema[model] for model in current)
    discount = max(0.0, (guardrails.decision_horizon_seconds - guardrails.switch_cost_seconds)
                   / guardrails.decision_horizon_seconds)
    challenger_score = sum(ema[model] for model in pair) * discount
    need = max(current_score * (1 + guardrails.relative_margin), current_score + guardrails.absolute_margin)
    if challenger_score < need:
        target = current[0] if current else pair[0]
        return Decision(target, f"best pair below margin ({challenger_score:.3f} vs {current_score:.3f}; need >= {need:.3f})", "KEEP", current)
    if now - last_switch_at < guardrails.min_dwell_seconds:
        return Decision(current[0] if current else pair[0], "best pair clears margin but minimum dwell remains", "KEEP", current)
    target = next(model for model in pair if model not in warm_models)
    action = "SWITCH_WHEN_IDLE" if inference_active else "SWITCH"
    return Decision(target, f"best pair clears margin: {', '.join(pair)}", action, pair)


def _load_error_gate(result: Decision, daemon: DaemonState, now: float) -> Decision | None:
    """BLOCKED when the target matches a load error with no valid timestamp, a
    future timestamp, or one at most LOAD_ERROR_BLOCK_SECONDS in the past.
    None means this gate does not fire."""
    err_model = daemon.last_model_load_error_model
    err_at = daemon.last_model_load_error_at
    if not err_model or result.target != err_model:
        return None
    if err_at is None:
        return Decision(
            result.target,
            f"{result.reason}; blocked: {err_model} failed to load with no timestamp",
            "BLOCKED",
        )
    if err_at > now or (now - err_at) <= LOAD_ERROR_BLOCK_SECONDS:
        age = abs(now - err_at)
        return Decision(
            result.target,
            f"{result.reason}; blocked: {err_model} failed to load {age:.0f}s ago",
            "BLOCKED",
        )
    return None


def apply_host_gates(result: Decision, daemon: DaemonState, now: float) -> Decision:
    """Thermal, trust, and load-error gates. OBSERVE and LIVE share this path.
    Missing trust is not hardware: a switch-like decision becomes KEEP."""
    if result.action not in _SWITCH_ACTIONS:
        return result
    thermal = daemon.thermal_state
    if thermal in _HOT_THERMAL:
        return Decision(result.target, f"{result.reason}; blocked: thermal state is {thermal}", "BLOCKED")
    trust = daemon.trust_level
    if trust != HARDWARE_TRUST:
        label = "unknown" if trust is None else trust
        return Decision(
            daemon.current_model,
            f"{result.reason}; trust is {label}, not hardware; no restart during attestation",
            "KEEP",
        )
    for model in result.models or ((result.target,) if result.target else ()):
        blocked = _load_error_gate(Decision(model, result.reason, result.action), daemon, now)
        if blocked is not None:
            return blocked
    return result


def apply_warm_target_gate(result: Decision, daemon: DaemonState) -> Decision:
    """Do not cold-boot a host when it already serves the selected model."""
    wanted = result.models or ((result.target,) if result.target else ())
    if wanted and result.action in _SWITCH_ACTIONS and set(wanted).issubset(daemon.warm_models):
        return Decision(result.target, f"{result.reason}; target is already warm on this host", "KEEP")
    return result


def apply_inventory_gate(result: Decision, daemon: DaemonState) -> Decision:
    """Unknown inventory may still be scored, but must not SWITCH. A known
    target missing from installed ids is BLOCKED. Tick snapshot only."""
    if result.action not in _SWITCH_ACTIONS:
        return result
    installed = daemon.installed_models
    if installed is None:
        return Decision(
            daemon.current_model,
            f"{result.reason}; inventory unknown: keeping the current model",
            "KEEP",
        )
    missing = next((model for model in result.models or ((result.target,) if result.target else ())
                    if model not in installed), None)
    if missing is not None:
        return Decision(
            missing,
            f"{result.reason}; blocked: {missing} is not installed",
            "BLOCKED",
        )
    return result
