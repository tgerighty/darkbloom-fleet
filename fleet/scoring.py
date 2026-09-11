"""Revenue-score formula, forked from darkbloom-manager's warm_model_manager.py.

score(model) = pressure * output_$/M_tokens * preference_weight

This is the exact formula `revenue_scores()` uses in the source project;
only the input plumbing (this service pulls pressure and price itself
instead of reading them from a local darkbloom CLI) has changed.
"""
from __future__ import annotations

from .types import CapacitySample


def pressure_from_capacity(row: dict) -> CapacitySample | None:
    """Parse one row of the public /v1/models/capacity response."""
    model = str(row.get("id") or row.get("model_id") or "")
    if not model:
        return None
    active = max(0, int(row.get("active_requests", row.get("in_progress", 0)) or 0))
    warm = max(0, int(row.get("warm_providers", row.get("loaded", 0)) or 0))
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
