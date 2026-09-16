"""Revenue-score formula, forked from darkbloom-manager's warm_model_manager.py.

score(model) = pressure * output_$/M_tokens * preference_weight

This is the exact formula `revenue_scores()` uses in the source project;
only the input plumbing (this service pulls pressure and price itself
instead of reading them from a local darkbloom CLI) has changed.
"""
from __future__ import annotations

import math

from .types import CapacitySample


def pressure_from_capacity(row: object) -> CapacitySample | None:
    """Parse one row of the public /v1/models/capacity response. A malformed
    row is skipped rather than failing the whole feed."""
    if not isinstance(row, dict):
        return None
    model = str(row.get("id") or row.get("model_id") or "")
    if not model:
        return None
    try:
        active = max(0, int(row.get("active_requests", row.get("in_progress", 0)) or 0))
        warm = max(0, int(row.get("warm_providers", row.get("loaded", 0)) or 0))
    except (TypeError, ValueError):
        return None
    return CapacitySample(model=model, active_requests=active, warm_providers=warm,
                           pressure=active / max(1, warm))


def compute_scores(
    samples: dict[str, CapacitySample],
    prices: dict[str, float],
    weights: dict[str, float],
) -> dict[str, float]:
    """score = pressure * output $/M tokens * preference; models missing a
    price are excluded, matching the source project's `revenue_scores()`."""
    return {
        model: sample.pressure * prices[model] * weights.get(model, 1.0)
        for model, sample in samples.items()
        if model in prices
    }


def update_ema(ema: dict[str, float], scores: dict[str, float], dt_seconds: float, tau_minutes: float) -> dict[str, float]:
    """Exponential moving average of each model's score. dt_seconds since the
    last update; alpha follows the standard tau-based EMA formula."""
    alpha = 1 - math.exp(-dt_seconds / (tau_minutes * 60))
    updated = dict(ema)
    for model, score in scores.items():
        updated[model] = score if model not in updated else updated[model] + alpha * (score - updated[model])
    return updated
