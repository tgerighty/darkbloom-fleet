"""Payout-backed shadow check for the demand model's proposed warm set."""
from __future__ import annotations

from .types import Decision

_MIN_EVIDENCE_SECONDS = 3600.0


def _models(decision: Decision) -> tuple[str, ...]:
    return tuple(sorted(decision.models or ((decision.target,) if decision.target else ())))


def _supported_rate(rates: dict[tuple[str, ...], tuple[float, float]],
                    models: tuple[str, ...]) -> float | None:
    evidence = rates.get(models)
    if evidence is None or evidence[1] < _MIN_EVIDENCE_SECONDS:
        return None
    return evidence[0]


def decide(current: tuple[str, ...], demand: Decision,
           rates: dict[tuple[str, ...], tuple[float, float]], switch_cost_seconds: float,
           horizon_seconds: float, confirmed_seconds: float) -> Decision:
    proposed = _models(demand)
    current = tuple(sorted(current))
    if demand.action not in {"SWITCH", "SWITCH_WHEN_IDLE"}:
        return Decision(current[0] if current else demand.target, "demand model does not propose a switch", "KEEP", current)
    if not proposed:
        return Decision(current[0] if current else demand.target, "demand model does not propose a switch", "KEEP", current)
    current_rate = _supported_rate(rates, current)
    proposed_rate = _supported_rate(rates, proposed)
    if current_rate is None:
        return Decision(current[0] if current else None, "insufficient payout evidence for current or proposed models", "KEEP", current)
    if proposed_rate is None:
        return Decision(current[0] if current else None, "insufficient payout evidence for current or proposed models", "KEEP", current)

    gain = (proposed_rate - current_rate) * horizon_seconds / 3600.0
    switch_loss = current_rate * switch_cost_seconds / 3600.0
    if gain <= 2 * switch_loss:
        return Decision(current[0] if current else None,
                        f"forecast gain ${gain:.4f} does not cover 2x switch loss ${switch_loss:.4f}",
                        "KEEP", current)
    if confirmed_seconds < 300:
        return Decision(demand.target,
                        f"payout switch confirming ({confirmed_seconds:.0f}/300s)",
                        "KEEP", proposed)
    return Decision(demand.target, f"forecast ${proposed_rate:.4f}/h vs ${current_rate:.4f}/h; "
                    f"gain ${gain:.4f} covers 2x switch loss ${switch_loss:.4f}",
                    demand.action, proposed)
