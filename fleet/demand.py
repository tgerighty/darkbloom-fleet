"""Public darkbloom endpoints: network-wide demand and output-token pricing.
Same call pattern as darkbloom-manager's demand_report.py (--live mode) and
warm_model_manager.py's fetch_output_prices() — stdlib only, no SSH needed.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from .scoring import pressure_from_capacity
from .types import CapacitySample

USER_AGENT = "darkbloom-fleet/0.1"


def _get_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def fetch_capacity(base_url: str) -> dict[str, CapacitySample]:
    payload = _get_json(f"{base_url.rstrip('/')}/v1/models/capacity")
    rows = payload if isinstance(payload, list) else payload.get("data", payload.get("models", []))
    samples: dict[str, CapacitySample] = {}
    for row in rows:
        sample = pressure_from_capacity(row)
        if sample:
            samples[sample.model] = sample
    return samples


def fetch_output_prices(pricing_url: str) -> tuple[dict[str, float], float]:
    """Output USD per token, per model, plus the fallback price for models
    with no explicit row. Mirrors warm_model_manager.fetch_output_prices()."""
    payload = _get_json(pricing_url)
    fallback = max(0, int(payload.get("fallback_output_price") or 0)) / 1_000_000
    prices: dict[str, float] = {}
    for row in payload.get("prices") or []:
        if isinstance(row, dict) and row.get("model"):
            prices[str(row["model"])] = max(0, int(row.get("output_price") or 0)) / 1_000_000
    return prices, fallback


def resolve_prices(models: tuple[str, ...], prices: dict[str, float], fallback: float) -> dict[str, float]:
    """Apply the fallback price to any configured model without its own row."""
    return {m: prices.get(m, fallback) for m in models if prices.get(m, fallback) > 0}
