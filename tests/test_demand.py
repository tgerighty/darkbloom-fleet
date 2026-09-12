import io
import json

import pytest

from fleet import demand
from fleet.types import CapacitySample


def test_get_json_sends_the_user_agent_and_parses_the_body(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(ua=request.get_header("User-agent"), timeout=timeout)
        return io.BytesIO(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(demand, "urlopen", fake_urlopen)
    assert demand._get_json("https://x") == {"ok": True}
    assert seen == {"ua": demand.USER_AGENT, "timeout": 20}


def test_fetch_capacity_reads_the_data_list(monkeypatch):
    payload = {"data": [{"id": "m", "active_requests": 4, "warm_providers": 2}, {"no_id": True}]}
    monkeypatch.setattr(demand, "_get_json", lambda url: payload)
    assert demand.fetch_capacity("https://x/") == {"m": CapacitySample("m", 4, 2, 2.0)}


def test_a_capacity_payload_of_the_wrong_shape_yields_no_samples(monkeypatch):
    monkeypatch.setattr(demand, "_get_json", lambda url: "oops")
    assert demand.fetch_capacity("https://x") == {}


def test_a_pricing_payload_that_is_not_an_object_is_rejected(monkeypatch):
    monkeypatch.setattr(demand, "_get_json", lambda url: ["not", "an", "object"])
    with pytest.raises(TypeError, match="not a JSON object"):
        demand.fetch_output_prices("https://x")


def test_malformed_price_rows_are_skipped(monkeypatch):
    payload = {"fallback_output_price": 200000,
               "prices": [{"model": "a", "output_price": 100000}, {"model": "b", "output_price": "lots"}, "junk"]}
    monkeypatch.setattr(demand, "_get_json", lambda url: payload)
    prices, fallback = demand.fetch_output_prices("https://x")
    assert prices == {"a": 0.1} and fallback == 0.2


def test_resolve_prices_fills_gaps_with_the_fallback_and_drops_free_models():
    assert demand.resolve_prices(("a", "b"), {"a": 0.1}, 0.2) == {"a": 0.1, "b": 0.2}
    assert demand.resolve_prices(("a", "b"), {"a": 0.1}, 0.0) == {"a": 0.1}
