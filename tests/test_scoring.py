from fleet.scoring import compute_scores, pressure_from_capacity
from fleet.types import CapacitySample


def test_pressure_from_capacity_computes_ratio():
    sample = pressure_from_capacity({"id": "gemma-4-26b-qat-4bit", "active_requests": 6, "warm_providers": 3})
    assert sample == CapacitySample(model="gemma-4-26b-qat-4bit", active_requests=6, warm_providers=3, pressure=2.0)


def test_pressure_from_capacity_floors_warm_at_one():
    sample = pressure_from_capacity({"id": "m", "active_requests": 5, "warm_providers": 0})
    assert sample.pressure == 5.0  # divide by max(1, warm), never by zero


def test_pressure_from_capacity_skips_rows_without_an_id():
    assert pressure_from_capacity({"active_requests": 1, "warm_providers": 1}) is None


def test_pressure_from_capacity_skips_rows_with_non_numeric_counts():
    assert pressure_from_capacity({"id": "m", "active_requests": "many", "warm_providers": 1}) is None


def test_pressure_from_capacity_skips_rows_that_are_not_objects():
    assert pressure_from_capacity("gpt-oss-20b") is None


def test_compute_scores_matches_pressure_times_price_times_weight():
    samples = {
        "qwen3.5-35b-a3b": CapacitySample("qwen3.5-35b-a3b", 4, 2, 2.0),
        "gpt-oss-20b": CapacitySample("gpt-oss-20b", 1, 1, 1.0),
    }
    prices = {"qwen3.5-35b-a3b": 0.5, "gpt-oss-20b": 0.5}
    weights = {"qwen3.5-35b-a3b": 1.25, "gpt-oss-20b": 1.0}
    scores = compute_scores(samples, prices, weights)
    assert scores == {"qwen3.5-35b-a3b": 2.0 * 0.5 * 1.25, "gpt-oss-20b": 1.0 * 0.5 * 1.0}


def test_compute_scores_excludes_models_with_no_price():
    samples = {"m": CapacitySample("m", 1, 1, 1.0)}
    assert compute_scores(samples, {}, {}) == {}
