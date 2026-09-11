import pytest

from fleet import demand


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


def test_a_capacity_payload_of_the_wrong_shape_yields_no_samples(monkeypatch):
    monkeypatch.setattr(demand, "_get_json", lambda url: "oops")
    assert demand.fetch_capacity("https://x") == {}
