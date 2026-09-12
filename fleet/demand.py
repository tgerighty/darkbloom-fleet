"""Public darkbloom endpoints: network-wide demand and output-token pricing.
Same call pattern as darkbloom-manager's demand_report.py (--live mode) and
warm_model_manager.py's fetch_output_prices() — stdlib only, no SSH needed.
"""
from __future__ import annotations

import json
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .scoring import pressure_from_capacity
from .types import CapacitySample

USER_AGENT = "darkbloom-fleet/0.1"
Json = dict[str, object] | list[object]


class _NoRedirect(HTTPRedirectHandler):
    """An authenticated request must never follow a redirect: the bearer
    token would be replayed to whatever origin the redirect names."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _get_json(url: str, headers: dict[str, str] | None = None) -> Json:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})})
    opener = build_opener(_NoRedirect()).open if headers else urlopen
    with opener(request, timeout=20) as response:
        return json.load(response)


def _routable_count(row: object) -> tuple[str, int] | None:
    """(model id, routable providers) from one self-route listing row."""
    if not isinstance(row, dict) or not row.get("id"):
        return None
    meta = row.get("metadata")
    routable = meta.get("routable_providers") if isinstance(meta, dict) else 0
    try:
        return str(row["id"]), int(routable or 0)
    except (TypeError, ValueError):
        return None


def fetch_self_route(base_url: str, api_key: str) -> dict[str, int]:
    """Models the coordinator will route to on OUR machines right now, with how
    many of our providers it counts as routable for each. The self-route view
    lists what is advertised and passes the routing gates, not what is warm,
    so an empty result means every owned machine is in the post-restart
    penalty box (darkbloom-manager/analysis/switch-penalty)."""
    headers = {"Authorization": f"Bearer {api_key}", "X-Darkbloom-Route": "self"}
    payload = _get_json(f"{base_url.rstrip('/')}/v1/models", headers)
    rows = payload.get("data") if isinstance(payload, dict) else None
    return {c[0]: c[1] for row in (rows if isinstance(rows, list) else []) if (c := _routable_count(row))}


def fetch_capacity(base_url: str) -> dict[str, CapacitySample]:
    payload = _get_json(f"{base_url.rstrip('/')}/v1/models/capacity")
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("models", []))
    rows = payload if isinstance(payload, list) else []
    samples: dict[str, CapacitySample] = {}
    for row in rows:
        sample = pressure_from_capacity(row)
        if sample:
            samples[sample.model] = sample
    return samples


def _price_per_token(row: object) -> tuple[str, float] | None:
    """(model, USD per output token) from one pricing row; None if malformed."""
    if not isinstance(row, dict) or not row.get("model"):
        return None
    try:
        return str(row["model"]), max(0, int(row.get("output_price") or 0)) / 1_000_000
    except (TypeError, ValueError):
        return None


def fetch_output_prices(pricing_url: str) -> tuple[dict[str, float], float]:
    """Output USD per token, per model, plus the fallback price for models
    with no explicit row. Mirrors warm_model_manager.fetch_output_prices()."""
    payload = _get_json(pricing_url)
    if not isinstance(payload, dict):
        raise TypeError("pricing payload is not a JSON object")
    fallback = max(0, int(payload.get("fallback_output_price") or 0)) / 1_000_000
    rows = payload.get("prices") or []
    return {p[0]: p[1] for row in rows if (p := _price_per_token(row))}, fallback


def resolve_prices(models: tuple[str, ...], prices: dict[str, float], fallback: float) -> dict[str, float]:
    """Apply the fallback price to any configured model without its own row."""
    return {m: prices.get(m, fallback) for m in models if prices.get(m, fallback) > 0}
