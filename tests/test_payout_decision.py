from fleet.payout_decision import decide
from fleet.types import Decision


def test_payout_forecast_switches_only_when_gain_covers_twice_the_outage():
    demand = Decision("b", "demand ranks b first", "SWITCH", ("b",))
    rates = {("a",): (1.0, 7200.0), ("b",): (2.0, 7200.0)}

    result = decide(("a",), demand, rates, switch_cost_seconds=300.0, horizon_seconds=3600.0,
                    confirmed_seconds=300)

    assert result.action == "SWITCH"
    assert result.target == "b"
    assert "forecast" in result.reason


def test_payout_forecast_keeps_when_evidence_is_missing_or_gain_is_too_small():
    demand = Decision("b", "demand ranks b first", "SWITCH", ("b",))

    missing = decide(("a",), demand, {("a",): (1.0, 7200.0)}, 300.0, 3600.0, 300)
    narrow = decide(("a",), demand, {("a",): (1.0, 7200.0), ("b",): (1.1, 7200.0)}, 300.0, 3600.0, 300)

    assert missing.action == "KEEP" and "evidence" in missing.reason
    assert narrow.action == "KEEP" and "switch loss" in narrow.reason
    assert "$0.1667" in narrow.reason


def test_payout_forecast_uses_exact_dual_model_rates():
    demand = Decision("b", "demand ranks pair first", "SWITCH", ("b", "c"))
    rates = {("a",): (1.0, 7200.0), ("b", "c"): (1.9, 7200.0)}

    result = decide(("a",), demand, rates, 300.0, 3600.0, 300)

    assert result.action == "SWITCH" and result.models == ("b", "c")


def test_payout_forecast_requires_five_elapsed_minutes_of_confirmation():
    demand = Decision("b", "demand ranks b first", "SWITCH", ("b",))
    rates = {("a",): (1.0, 7200.0), ("b",): (2.0, 7200.0)}

    result = decide(("a",), demand, rates, 300.0, 3600.0, 299)

    assert result.action == "KEEP" and result.models == ("b",) and "299/300s" in result.reason


def test_payout_forecast_keeps_without_a_demand_switch_target():
    rates = {("a",): (1.0, 7200.0)}

    assert decide(("a",), Decision("a", "keep", "KEEP"), rates, 300, 3600, 300).action == "KEEP"
    assert decide(("a",), Decision(None, "wait", "SWITCH"), rates, 300, 3600, 300).action == "KEEP"
